#!/bin/bash
# Pass iff the Pliron crate builds and its tests pass offline from the warmed seed, and the
# Python venv imports torch and xdsl.
mkdir -p /logs/verifier; reward=0; trap 'echo "$reward" > /logs/verifier/reward.txt' EXIT
cd /work/sd-scripts
cargo test --locked --offline --manifest-path docs_design/models-strategy-trainer/pliron_candidate/native/Cargo.toml 2>&1 | tail -5 \
  && "$VIRTUAL_ENV/bin/python" -c "import torch, xdsl; print('torch', torch.__version__, 'xdsl ok')" \
  && reward=1
exit 0
