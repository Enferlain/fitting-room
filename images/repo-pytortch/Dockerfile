# pytortch-backend-experiments: the repo runs in stage0/.venv, a free-threaded 3.14t venv
# that links an existing PyTorch install without Triton (stage0/isolate_python.py). On the
# host that install is sd-scripts' venv, so this image builds FROM the sd-scripts image
# (/opt/venv: torch 2.14.1+cu130, NVRTC and CUDA headers from torch's nvidia packages)
# and adds Rust plus a pre-built native target for the CubeCL compiler and bridge.
# Context (images/build.sh, KIND=repo-pytortch): warm/ = git archive of a recent commit.
ARG BASE=fr-repo/sd-scripts:latest
FROM ${BASE}
ARG RUST_VERSION=1.99.1
ENV RUSTUP_HOME=/opt/rustup CARGO_HOME=/opt/cargo \
    PATH=/opt/cargo/bin:/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin
RUN apt-get update && apt-get install -y --no-install-recommends python3 \
    && rm -rf /var/lib/apt/lists/* \
    && curl -fsSL https://sh.rustup.rs | sh -s -- -y --profile minimal \
        --default-toolchain "${RUST_VERSION}" --component clippy,rustfmt
# Build a recent commit at the path tasks use, so a task's build reuses unchanged crates.
# warm/ is bind-mounted and copied into place, so the 2 GB tree is not left in a layer.
RUN --mount=type=bind,source=warm,target=/opt/warm-src \
    set -eu; cp -a /opt/warm-src /work/pytortch-backend-experiments; \
    cd /work/pytortch-backend-experiments; \
    git init -q && git add -A && git commit -qm warm; \
    cubecl_torch/native/build.sh; \
    mkdir -p /opt/pt-warm; \
    mv cubecl_torch/native/target /opt/pt-warm/native-target; \
    [ -d cubecl_torch/native/bridge/target ] && mv cubecl_torch/native/bridge/target /opt/pt-warm/bridge-target || true; \
    cd / && rm -rf /work/pytortch-backend-experiments
# Task images: COPY the snapshot, then RUN fr-snapshot-init && fr-pytortch-setup
COPY fr-pytortch-setup /usr/local/bin/fr-pytortch-setup
# Last: shared helper scripts (cheap to rebuild).
COPY fr-snapshot-init /usr/local/bin/fr-snapshot-init
