#!/usr/bin/env bash
set -euo pipefail
base=$(cd -- "$(dirname -- "$0")" && pwd)
wheelhouse=${WHEELHOUSE:?Set WHEELHOUSE to the separately staged wheel directory}
python=${BENCH_PYTHON:-python3.12}
group=${1:?Provide the runtime group}
uv venv --python "$python" "$base/$group"
uv pip install --offline --no-index --find-links "$wheelhouse" --python "$base/$group/bin/python" \
  -r "$base/requirements-$group.txt"
