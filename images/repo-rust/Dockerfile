# fitting-room repo image for a Rust workspace (CPU).
# Build context (images/build.sh, KIND=repo-rust): warm/ = git archive of a recent commit,
# used only to install the pinned toolchain and pre-build dependencies and test binaries.
ARG BASE=fr-base/cpu:1
FROM ${BASE}
ENV RUSTUP_HOME=/opt/rustup CARGO_HOME=/opt/cargo CARGO_TARGET_DIR=/opt/cargo-target \
    PATH=/opt/cargo/bin:/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin
COPY warm/ /opt/warm/
RUN set -eu; \
    channel=$(sed -n 's/^channel *= *"\(.*\)"/\1/p' /opt/warm/rust-toolchain.toml); \
    curl -fsSL https://sh.rustup.rs | sh -s -- -y --profile minimal \
        --default-toolchain "$channel" --component clippy,rustfmt; \
    cd /opt/warm && cargo fetch --locked && cargo test --workspace --locked --no-run; \
    rm -rf /opt/warm
