# Eth2 python hacks

This is a set of examples to toy with for anyone hacking on the pyspec and Eth2 tooling:
- `app.py` (requires rumor): sync the lighthouse testnet! (Config loading, transition logic, RPC is set up for you)
- `minimal_transition.py`: do a single fast-spec transition (Load/write states, isolate example to debug things with)
- `fast_spec.py`: a custom version of the `phase0/spec.py` from the eth2 specs repo. Completely optimized to pre-compute everything, and make the best use of remerkleable.

## Install

Some examples require [`rumor`](https://github.com/protolambda/rumor) for networking.
You can change the example to specify the executable path, e.g. `app.py` assumes you have it locally next to this repo: `cd ../rumor && go run .`
Or just `rumor` if you have it on your path.

Python dependencies:
- For local development: `dev_requirements.txt`, linking to pyrum and remerkleable local sources
- For regular users: `requirements.txt`: install pyrum and remerkleable from PyPi, and specs from git.

## License

MIT, see [`LICENSE`](./LICENSE) file.
