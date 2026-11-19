#!/bin/bash
# Reference solution. Runs in the task container as the oracle agent.
set -euo pipefail
cd /work/REPO
# private: apply the episode's own change.
git apply --whitespace=nowarn /solution/fix.patch
# shareable: write the fixed files instead, for example
# cat > /work/REPO/tool.py <<'PY'
# ...
# PY
