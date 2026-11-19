# codebase-memory-mcp from the user's fork (upstream + local patches), built static.
# Context (images/cbm/build.sh): src/ = git archive of the fork at a pinned commit.
FROM debian:trixie-slim AS build
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential zlib1g-dev ca-certificates git pkg-config \
    && rm -rf /var/lib/apt/lists/*
ARG CBM_VERSION=0.12.1-fork.1
COPY src/ /src/
WORKDIR /src
RUN make -f Makefile.cbm -j8 STATIC=1 CFLAGS_EXTRA="-DCBM_VERSION=\\\"${CBM_VERSION}\\\"" cbm \
    && ./build/c/codebase-memory-mcp --version

FROM scratch
COPY --from=build /src/build/c/codebase-memory-mcp /codebase-memory-mcp
