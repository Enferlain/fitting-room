#!/bin/bash
# Reference: the same three answers from the tools (oracle runs only with dev-stack).
set -euo pipefail
cd /work/hermes-agora
python=/opt/venv/bin/python
"$python" - <<'PY'
import json, subprocess
def run(*cmd):
    return subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
def graph(*args):
    return json.loads(run("codebase-memory-mcp", "cli", "search_graph", "--project",
                          "work-hermes-agora", "--format", "json", *args))
ready = [i["id"] for i in json.loads(run("bd", "ready", "--json"))]
specs = [s["id"] for s in json.loads(run("openspec", "list", "--specs", "--json"))["specs"]]
cls = graph("--name-pattern", "^TransportStore$", "--label", "Class")["groups"][0]
methods = graph("--label", "Method", "--qn-pattern", r".*\.TransportStore\..*", "--limit", "200")
names = sorted({row[0] for g in methods["groups"] for row in g["rows"]})
report = {"bd_ready": ready, "openspec_specs": specs,
          "transport_store_file": cls["file"], "transport_store_methods": names}
open("toolkit-report.json", "w").write(json.dumps(report, indent=1))
PY
