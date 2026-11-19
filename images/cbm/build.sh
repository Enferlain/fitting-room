#!/bin/sh
# Build fr-tool/cbm:<commit> from ~/Projects/codebase-memory-mcp at [commit] (default HEAD).
set -eu
src="${FR_REPOS_DIR:-$HOME/Projects}/codebase-memory-mcp"
here=$(cd "$(dirname "$0")" && pwd)
sha=$(git -C "$src" rev-parse --short=10 "${1:-HEAD}")
ctx="$here/../../work/images/cbm"
rm -rf "$ctx"; mkdir -p "$ctx/src"
git -C "$src" archive "$sha" | tar -x -C "$ctx/src"
cp "$here/Dockerfile" "$ctx/Dockerfile"
docker build -t "fr-tool/cbm:$sha" -t fr-tool/cbm:latest "$ctx"
echo "built fr-tool/cbm:$sha"
