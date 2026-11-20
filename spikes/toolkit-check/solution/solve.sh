#!/bin/bash
# Reference: the same answers from the tools (oracle runs only with dev-stack).
set -euo pipefail
cd /work/hermes-agora
python="$VIRTUAL_ENV/bin/python"
"$python" - <<'PY'
import json, subprocess
def run(*cmd):
    return subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
ready = [i["id"] for i in json.loads(run("bd", "ready", "--json"))]
specs = [s["id"] for s in json.loads(run("openspec", "list", "--specs", "--json"))["specs"]]
report = {"bd_ready": ready, "openspec_specs": specs}
open("toolkit-report.json", "w").write(json.dumps(report, indent=1))
PY
