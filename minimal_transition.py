# from eth2spec.phase0 import spec
from eth2spec.config.config_util import prepare_config

from importlib import reload

import io
import os

import fast_spec
spec = fast_spec

# Apply lighthouse config to spec
prepare_config("./lighthouse", "config")
reload(fast_spec)

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
epochs_ctx = fast_spec.EpochsContext()
epochs_ctx.load_state(state)

print("running transition")
fast_spec.process_slots(epochs_ctx, state, block.message.slot)

print("saving post state")
with io.open('post.ssz', 'bw') as f:
    state.serialize(f)

print("done")

