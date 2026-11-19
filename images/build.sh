#!/bin/sh
# Build a repo image: images/build.sh <repo> [commit]   (default commit: HEAD)
# For historical Python snapshots, set FR_IMAGE_PYTHON to a compatible Python version.
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
tag=$sha
if [ -n "${FR_IMAGE_PYTHON:-}" ]; then
    if [ "${KIND:-repo-python}" != repo-python ]; then
        echo "FR_IMAGE_PYTHON applies only to repo-python images" >&2
        exit 2
    fi
    case "$FR_IMAGE_PYTHON" in
        *[!0-9.t]*|[!0-9]*)
            echo "FR_IMAGE_PYTHON must be a version such as 3.13 or 3.14t" >&2
            exit 2 ;;
    esac
    PYTHON=$FR_IMAGE_PYTHON
    tag="$sha-py$PYTHON"
    ctx="$ctx-$tag"
    set -- -t "fr-repo/$repo:$tag"
else
    set -- -t "fr-repo/$repo:$tag" -t "fr-repo/$repo:latest"
fi
rm -rf "$ctx"; mkdir -p "$ctx/warm"
case "${KIND:-repo-python}" in
    repo-python)
        git -C "$src" show "$sha:pyproject.toml" > "$ctx/warm/pyproject.toml"
        git -C "$src" show "$sha:uv.lock" > "$ctx/warm/uv.lock" ;;
    *)  git -C "$src" archive "$sha" | tar -x -C "$ctx/warm" ;;
esac
# Shared helpers (images/common/) and the kind's own helper files go into the context.
cp -a "$here/common/." "$ctx/"
for f in "$here/${KIND:-repo-python}"/*; do
    [ "$(basename "$f")" = Dockerfile ] || cp -a "$f" "$ctx/"
done
docker build "$@" \
    --build-arg PYTHON="$PYTHON" ${BASE:+--build-arg BASE="$BASE"} \
    ${SYNC_ARGS+--build-arg SYNC_ARGS="$SYNC_ARGS"} \
    -f "$here/${KIND:-repo-python}/Dockerfile" "$ctx"
echo "built fr-repo/$repo:$tag"
