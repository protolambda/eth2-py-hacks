# from eth2spec.phase0 import spec
from eth2spec.config.config_util import prepare_config

from importlib import reload

import io
import os

import fast_spec
import canon_spec

# Apply lighthouse config to spec
prepare_config("./lighthouse", "config")
reload(fast_spec)
reload(canon_spec)

# Turn off sig verification
fast_spec.bls.bls_active = False

def load_fast_state(filepath: str) -> fast_spec.BeaconState:
    state_size = os.stat(filepath).st_size
    with io.open(filepath, 'br') as f:
        return fast_spec.BeaconState.deserialize(f, state_size)


def load_block(filepath: str) -> fast_spec.SignedBeaconBlock:
    block_size = os.stat(filepath).st_size
    with io.open(filepath, 'br') as f:
        return fast_spec.SignedBeaconBlock.deserialize(f, block_size)


print("loading inputs")
state = load_fast_state('fail_state_pre.ssz')
block = load_block('fail_block.ssz')

print(f"slot: {state.slot}  val count: {len(state.validators)}")

print("loading transition context")
epochs_ctx = fast_spec.EpochsContext()
epochs_ctx.load_state(state)

print("running transition")
fast_state = state.copy()
canon_state = canon_spec.BeaconState.view_from_backing(fast_state.get_backing())

print("fast transition...")
fast_spec.state_transition(epochs_ctx, fast_state, block, validate_result=False)
print(f"fast post state root: {fast_state.hash_tree_root().hex()}")

print("canon transition...")
canon_spec.state_transition(canon_state, block, validate_result=False)
print(f"fast post state root: {fast_state.hash_tree_root().hex()}")

print(f"expected block state root: {block.message.state_root.hex()}")

print("saving post state")
with io.open('fail_state_check_fast.ssz', 'bw') as f:
    fast_state.serialize(f)
with io.open('fail_state_check_canon.ssz', 'bw') as f:
    canon_state.serialize(f)

print("done")

