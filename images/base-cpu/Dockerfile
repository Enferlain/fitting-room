# fitting-room shared base (CPU): the tools every repo's instructions expect.
# Repo images build FROM this; task images build FROM the repo image.
FROM debian:trixie-slim

ARG UV_VERSION=0.13.4
ARG NODE_VERSION=24.21.0
ARG OPENSPEC_VERSION=1.15.0
ARG BD_VERSION=1.3.2

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    DO_NOT_TRACK=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_INSTALL_DIR=/opt/uv-python \
    UV_CACHE_DIR=/opt/uv-cache \
    PATH=/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl git ripgrep jq less procps unzip xz-utils \
        build-essential pkg-config \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.13.4 /uv /uvx /usr/local/bin/

RUN curl -fsSL "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-x64.tar.xz" \
        | tar -xJ -C /usr/local --strip-components=1 \
    && npm install -g "@fission-ai/openspec@${OPENSPEC_VERSION}" \
    && npm cache clean --force

# bd release binary, checked against the release's checksums.txt.
RUN set -eu; cd /tmp; \
    base="https://github.com/gastownhall/beads/releases/download/v${BD_VERSION}"; \
    curl -fsSLO "$base/beads_${BD_VERSION}_linux_amd64.tar.gz"; \
    curl -fsSLO "$base/checksums.txt"; \
    grep " beads_${BD_VERSION}_linux_amd64.tar.gz\$" checksums.txt | sha256sum -c -; \
    tar -xzf "beads_${BD_VERSION}_linux_amd64.tar.gz"; \
    install -m 0755 "$(find . -maxdepth 2 -type f -name bd | head -1)" /usr/local/bin/bd; \
    rm -rf /tmp/*; \
    bd metrics off >/dev/null 2>&1 || true; \
    bd version

# Sandbox git identity, so agents can commit.
RUN git config --system user.name agent && git config --system user.email agent@example.invalid \
    && git config --system init.defaultBranch main && git config --system safe.directory '*'

# fr-snapshot-init: run by task Dockerfiles after COPY repo/ (one fresh commit, beads DB).
COPY fr-snapshot-init /usr/local/bin/fr-snapshot-init
