# fitting-room shared base (CPU): OS tools, uv and Node only. Repo tools (bd, openspec,
# codebase-memory) are NOT here: nothing is enabled by default; the dev-stack toolkit
# layer (images/toolkits/dev-stack) adds them when a run asks for it.
# Repo images build FROM this; task images build FROM the repo image.
FROM debian:trixie-slim

ARG UV_VERSION=0.13.4
ARG NODE_VERSION=24.21.0

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    DO_NOT_TRACK=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_INSTALL_DIR=/opt/uv-python \
    UV_CACHE_DIR=/opt/uv-cache \
    MAKEFLAGS=-j8 CARGO_BUILD_JOBS=8 CMAKE_BUILD_PARALLEL_LEVEL=8 MAX_JOBS=8 \
    UV_CONCURRENT_BUILDS=2 UV_CONCURRENT_DOWNLOADS=8 \
    PATH=/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl git ripgrep jq less procps unzip xz-utils \
        build-essential pkg-config \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.13.4 /uv /uvx /usr/local/bin/

RUN curl -fsSL "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-x64.tar.xz" \
        | tar -xJ -C /usr/local --strip-components=1

# Sandbox git identity, so agents can commit.
RUN git config --system user.name agent && git config --system user.email agent@example.invalid \
    && git config --system init.defaultBranch main && git config --system safe.directory '*'

# fr-snapshot-init: run by task Dockerfiles after COPY repo/ (one fresh commit).
COPY fr-snapshot-init /usr/local/bin/fr-snapshot-init
