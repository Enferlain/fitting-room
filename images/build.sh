#!/bin/sh
# Build a repo image: images/build.sh <repo> [commit]   (default commit: HEAD)
# Stages pyproject.toml + uv.lock from ~/Projects/<repo> at <commit> into
# work/images/<repo>/ (gitignored) and builds fr-repo/<repo>:<short-commit>.
set -eu
repo=${1:?repo}; commit=${2:-HEAD}
src="${FR_REPOS_DIR:-$HOME/Projects}/$repo"
here=$(cd "$(dirname "$0")" && pwd)
ctx="$here/../work/images/$repo"
sha=$(git -C "$src" rev-parse --short=10 "$commit")
# Per-repo settings: PYTHON (interpreter the repo's venv uses), KIND, optional BASE.
. "$here/repos/$repo.env"
rm -rf "$ctx"; mkdir -p "$ctx/warm"
case "${KIND:-repo-python}" in
    repo-python)
        git -C "$src" show "$sha:pyproject.toml" > "$ctx/warm/pyproject.toml"
        git -C "$src" show "$sha:uv.lock" > "$ctx/warm/uv.lock" ;;
    *)  git -C "$src" archive "$sha" | tar -x -C "$ctx/warm" ;;
esac
docker build -t "fr-repo/$repo:$sha" -t "fr-repo/$repo:latest" \
    --build-arg PYTHON="$PYTHON" ${BASE:+--build-arg BASE="$BASE"} \
    -f "$here/${KIND:-repo-python}/Dockerfile" "$ctx"
echo "built fr-repo/$repo:$sha"
