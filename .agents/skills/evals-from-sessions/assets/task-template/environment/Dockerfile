# fitting-room: start FROM the repo image (images/build.sh <repo>): toolchain, git, uv,
# node. bd, openspec and codebase-memory come only with the dev-stack toolkit layer.
FROM fr-repo/REPO:latest
WORKDIR /work/REPO
# private: repo/ is `git archive <parent-commit>`; shareable: a new starter repo.
COPY repo/ /work/REPO/
# One fresh commit (no history, tags, remotes, hooks or episode messages). fitting-room:
# fr-snapshot-init from the base image. Python repos that need the commit's own
# dependencies sync into the shared /opt/venv through the shared uv cache mount:
# RUN --mount=type=cache,id=fr-uv-cache,target=/opt/uv-cache,sharing=locked \
#     uv sync --frozen $FR_SYNC_ARGS && fr-snapshot-init
RUN fr-snapshot-init
