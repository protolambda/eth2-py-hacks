import io
import os

from eth2spec.config.config_util import prepare_config
# Apply lighthouse config to spec (instead of reloading spec, we can prepare the config before the spec is loaded)
prepare_config("./lighthouse", "config")

import fast_spec as spec

# Turn off sig verification
spec.bls.bls_active = False


def load_state(filepath: str) -> spec.BeaconState:
    state_size = os.stat(filepath).st_size
    with io.open(filepath, 'br') as f:
        return spec.BeaconState.deserialize(f, state_size)


def load_block(filepath: str) -> spec.SignedBeaconBlock:
    block_size = os.stat(filepath).st_size
    with io.open(filepath, 'br') as f:
        return spec.SignedBeaconBlock.deserialize(f, block_size)

print("loading inputs")
state = load_state('pre.ssz')
block = load_block('block.ssz')

print("loading transition context")
epochs_ctx = spec.EpochsContext()
epochs_ctx.load_state(state)

print("running transition")
# spec.process_slots(epochs_ctx, state, block.message.slot)
spec.state_transition(epochs_ctx, state, block)

print("saving post state")
with io.open('post.ssz', 'bw') as f:
    state.serialize(f)

print("done")

