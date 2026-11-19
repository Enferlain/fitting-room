# fitting-room: start FROM the repo image (images/build.sh <repo>): toolchain, git, uv,
# node. bd, openspec and codebase-memory come only with the dev-stack toolkit layer.
FROM fr-repo/REPO:latest
WORKDIR /work/REPO
# private: repo/ is `git archive <parent-commit>`; shareable: a new starter repo.
COPY repo/ /work/REPO/
# One fresh commit (no history, tags, remotes, hooks or episode messages). fitting-room:
# fr-snapshot-init from the base image; append the repo's install step, e.g.
# RUN fr-snapshot-init && uv sync --frozen
RUN fr-snapshot-init
