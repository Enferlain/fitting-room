FROM fr-repo/hermes-agora:latest
WORKDIR /work/hermes-agora
COPY repo/ /work/hermes-agora/
RUN fr-snapshot-init && uv sync --frozen $FR_SYNC_ARGS
