import asyncio
import io
import os
import time
import traceback

from pyrum import Rumor

from remerkleable.complex import Container
from remerkleable.byte_arrays import Bytes32, Bytes4
from remerkleable.basic import uint64

from eth2spec.config.config_util import prepare_config

from importlib import reload

import csv

from remerkleable.tree import Node
import fast_spec

# Apply lighthouse config to spec
prepare_config("./lighthouse", "config")
reload(fast_spec)

# Instead of the real spec, use fast-spec as drop-in replacement.
# We can make the two compatible (share config and types) when testnets update to v0.11 (minimum pyspec package requirement)
spec = fast_spec

# Turn off sig verification
spec.bls.bls_active = False


class Goodbye(uint64):
    pass


class Status(Container):
    version: Bytes4
    finalized_root: Bytes32
    finalized_epoch: uint64
    head_root: Bytes32
    head_slot: uint64


class BlocksByRange(Container):
    head_block_root: Bytes32
    start_slot: uint64
    count: uint64
    step: uint64


bootnodes = [
    "enr:-Iu4QGuiaVXBEoi4kcLbsoPYX7GTK9ExOODTuqYBp9CyHN_PSDtnLMCIL91ydxUDRPZ-jem-o0WotK6JoZjPQWhTfEsTgmlkgnY0gmlwhDbOLfeJc2VjcDI1NmsxoQLVqNEoCVTC74VmUx25USyFe7lL0TgpXHaCX9CDy9H6boN0Y3CCIyiDdWRwgiMo",
    "enr:-Iu4QLNTiVhgyDyvCBnewNcn9Wb7fjPoKYD2NPe-jDZ3_TqaGFK8CcWr7ai7w9X8Im_ZjQYyeoBP_luLLBB4wy39gQ4JgmlkgnY0gmlwhCOhiGqJc2VjcDI1NmsxoQMrmBYg_yR_ZKZKoLiChvlpNqdwXwodXmgw_TRow7RVwYN0Y3CCIyiDdWRwgiMo",
    "enr:-Iu4QLpJhdfRFsuMrAsFQOSZTIW1PAf7Ndg0GB0tMByt2-n1bwVgLsnHOuujMg-YLns9g1Rw8rfcw1KCZjQrnUcUdekNgmlkgnY0gmlwhA01ZgSJc2VjcDI1NmsxoQPk2OMW7stSjbdcMgrKEdFOLsRkIuxgBFryA3tIJM0YxYN0Y3CCIyiDdWRwgiMo",
    "enr:-Iu4QBHuAmMN5ogZP_Mwh_bADnIOS2xqj8yyJI3EbxW66WKtO_JorshNQJ1NY8zo-u3G7HQvGW3zkV6_kRx5d0R19bETgmlkgnY0gmlwhDRCMUyJc2VjcDI1NmsxoQJZ8jY1HYauxirnJkVI32FoN7_7KrE05asCkZb7nj_b-YN0Y3CCIyiDdWRwgiMo",
]


def load_state(filepath: str) -> spec.BeaconState:
    state_size = os.stat(filepath).st_size
    with io.open(filepath, 'br') as f:
        return spec.BeaconState.deserialize(f, state_size)


async def lit_morty():
    rumor = Rumor()
    await rumor.start(cmd='cd ../rumor && go run .')

    state = load_state('lighthouse/genesis.ssz')

    morty = rumor.actor('morty')
    await morty.host.start().ok
    await morty.host.listen(tcp=9000).ok

    genesis_root = state.hash_tree_root()

    # Sync status
    morty_status = Status(
        version=spec.GENESIS_FORK_VERSION,
        finalized_root=genesis_root,
        finalized_epoch=0,
        head_root=genesis_root,
        head_epoch=0,
    )
    print("Morty status:")
    print(morty_status)
    print(morty_status.encode_bytes().hex())

    async def status_work():
        print("listening for status requests")
        status_listener = morty.rpc.status.listen(raw=True)
        # TODO; pyrum cancel() hook, to stop this
        async for req in status_listener.listen_req():
            if 'input_err' not in req:
                req_status = Status.decode_bytes(bytes.fromhex(req['data']))
                print(f"Got status request: {req_status}")

                resp = morty_status.encode_bytes().hex()
                await morty.rpc.status.resp.chunk.raw(req['req_id'], resp, done=True).ok
                print("replied back status")
            else:
                print(f"Got invalid status request: {req}")

        print("stopped listening for status requests")

    async def ask_status(peer_id: str) -> Status:
        boot_status_resp = await morty.rpc.status.req.raw(peer_id, morty_status.encode_bytes().hex(), raw=True).ok
        print("Got status response: ", boot_status_resp)
        assert boot_status_resp['chunk']['result_code'] == 0
        status = Status.decode_bytes(bytes.fromhex(boot_status_resp['chunk']['data']))
        return status

    async def sync_from_bootnode(state: spec.BeaconState):
        await asyncio.sleep(2)

        peer_id = await morty.peer.connect(bootnodes[0], "bootnode").peer_id()
        print(f"connected bootnode peer: {peer_id}")

        # boot_status = await ask_status(peer_id)
        # print("Bootnode status:", boot_status)

        print(await morty.peer.list('all').ok)

        # Play nice, don't hit them with another request right away, wait half a minute. (Age?!)
        # await asyncio.sleep(31)

        async def sync_step(stats_csv: csv.DictWriter, epochs_ctx: fast_spec.EpochsContext, state: fast_spec.BeaconState) -> spec.BeaconState:
            range_req = BlocksByRange(start_slot=state.slot + 1, count=10, step=1).encode_bytes().hex()
            print("range req:", range_req)
            blocks = []
            async for chunk in morty.rpc.blocks_by_range.req.raw(peer_id, range_req, max_chunks=10, raw=True).listen_chunk():
                print("got chunk: ", chunk)
                if chunk['result_code'] == 0:
                    block = spec.SignedBeaconBlock.decode_bytes(bytes.fromhex(chunk["data"]))
                    blocks.append(block)
                else:
                    print("failed to get block; msg: ", chunk["msg"])
                    break

            for b in blocks:
                print("processing block!")
                start_time = time.time()
                try:
                    transition_input_state = state.copy()
                    fast_spec.state_transition(epochs_ctx, transition_input_state, b)
                except Exception as e:
                    print("failed transition: ", e)
                    traceback.print_tb(e.__traceback__)
                    print("failing block: ", b)
                    with io.open('state_fail.ssz', 'bw') as f:
                        state.serialize(f)
                    with io.open('block_fail.ssz', 'bw') as f:
                        b.serialize(f)
                    import sys
                    sys.exit(1)

                end_time = time.time()
                elapsed_time = end_time - start_time
                print(f"slot: {state.slot} state root: {state.hash_tree_root().hex()}  processing speed: {1.0 / elapsed_time} blocks / second  ({elapsed_time * 1000.0} ms/block)")

                def subtree_size(n: Node) -> int:
                    if n.is_leaf():
                        return 1
                    return subtree_size(n.get_left()) + subtree_size(n.get_right())

                def analyze_diff(a: Node, b: Node) -> (int, int):
                    """Iterate over the changes of b, not common with a. Left-to-right order.
                     Returns (a,b) tuples that can't be diffed deeper."""
                    if a.root != b.root:
                        a_leaf = a.is_leaf()
                        b_leaf = b.is_leaf()
                        if a_leaf or b_leaf:
                            return subtree_size(a), subtree_size(b)
                        else:
                            a_l, b_l = analyze_diff(a.get_left(), b.get_left())
                            a_r, b_r = analyze_diff(a.get_right(), b.get_right())
                            return a_l + a_r + 1, b_l + b_r + 1
                    return 0, 0

                stats = {
                    'slot': b.message.slot,
                    'proposer': epochs_ctx.get_beacon_proposer(b.message.slot),
                    'process_time': elapsed_time,
                }
                for i, key in enumerate(spec.BeaconState.fields().keys()):
                    a = state.get(i).get_backing()
                    b = transition_input_state.get(i).get_backing()

                    removed_nodes, added_nodes = analyze_diff(a, b)
                    stats[f"added_nodes_{key}"] = added_nodes
                    stats[f"removed_nodes_{key}"] = removed_nodes

                stats_csv.writerow(stats)

                print(f"stats: {stats}")
                state = transition_input_state

            global morty_status
            morty_status = Status(
                version=spec.GENESIS_FORK_VERSION,
                finalized_root=state.finalized_checkpoint.root,
                finalized_epoch=state.finalized_checkpoint.epoch,
                head_root=state.latest_block_header.hash_tree_root(),
                head_epoch=state.slot,
            )

            return state

        async def sync_work(stats_csv: csv.DictWriter, state: spec.BeaconState):
            epochs_ctx = fast_spec.EpochsContext()
            epochs_ctx.load_state(state)

            snapshot_step = 200
            prev_snap_slot = state.slot
            while True:
                state = await sync_step(stats_csv, epochs_ctx, state)
                if state.slot > prev_snap_slot + snapshot_step:
                    with io.open('state_snapshot.ssz', 'bw') as f:
                        state.serialize(f)
                    prev_snap_slot = state.slot
                if state.slot > 4000:
                    break  # synced enough (TODO: use bootnode status instead)

        with open(r'sync_stats.csv', 'a', newline='') as csvfile:
            fieldnames = ['slot', 'proposer', 'process_time']
            for key in spec.BeaconState.fields().keys():
                fieldnames.append(f"added_nodes_{key}")
                fieldnames.append(f"removed_nodes_{key}")
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            await sync_work(writer, state)

        print("Saying goobye")
        ok_bye_bye = Goodbye(1)  # A.k.a "Client shut down"
        await morty.rpc.goodbye.req.raw(peer_id, ok_bye_bye.encode_bytes().hex(), raw=True).ok

        print("disconnecting")
        await morty.peer.disconnect(peer_id).ok
        print("disconnected")

    asyncio.Task(status_work())

    await sync_from_bootnode(state)

    # Close the Rumor process
    await rumor.stop()


asyncio.run(lit_morty())
