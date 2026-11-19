# dev-stack toolkit payload: bd, openspec, codebase-memory-mcp and a setup script, all
# under /opt/fr-toolkit. Not a runnable image: a run that enables the toolkit adds
#   COPY --from=fr-toolkit/dev-stack:<tag> /opt/fr-toolkit /opt/fr-toolkit
#   RUN /opt/fr-toolkit/setup.sh
# on top of the task image (Node comes from the base image).
ARG CBM_IMAGE=fr-tool/cbm:latest
FROM ${CBM_IMAGE} AS cbm

FROM fr-base/cpu:1 AS build
ARG OPENSPEC_VERSION=1.15.0
ARG BD_VERSION=1.3.2
RUN set -eu; mkdir -p /opt/fr-toolkit/bin; cd /tmp; \
    base="https://github.com/gastownhall/beads/releases/download/v${BD_VERSION}"; \
    curl -fsSLO "$base/beads_${BD_VERSION}_linux_amd64.tar.gz"; \
    curl -fsSLO "$base/checksums.txt"; \
    grep " beads_${BD_VERSION}_linux_amd64.tar.gz\$" checksums.txt | sha256sum -c -; \
    tar -xzf "beads_${BD_VERSION}_linux_amd64.tar.gz"; \
    install -m 0755 "$(find . -maxdepth 2 -type f -name bd | head -1)" /opt/fr-toolkit/bin/bd; \
    npm install -g --prefix /opt/fr-toolkit/openspec "@fission-ai/openspec@${OPENSPEC_VERSION}"; \
    ln -s ../openspec/bin/openspec /opt/fr-toolkit/bin/openspec; \
    npm cache clean --force
COPY --from=cbm /codebase-memory-mcp /opt/fr-toolkit/bin/codebase-memory-mcp
COPY setup.sh /opt/fr-toolkit/setup.sh

FROM scratch
COPY --from=build /opt/fr-toolkit /opt/fr-toolkit
