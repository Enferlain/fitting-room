#!/bin/sh
# dev-stack toolkit setup, run at image build after the snapshot commit (WORKDIR = repo).
# Puts the tools on PATH, initialises bd from the snapshot's issues and indexes the repo
# for codebase-memory, keeping the snapshot a single clean commit.
set -eu
for b in /opt/fr-toolkit/bin/*; do ln -sf "$b" /usr/local/bin/; done
bd metrics off >/dev/null 2>&1 || true
if [ -f .beads/issues.jsonl ]; then
    prefix=$(jq -r 'select(.id) | .id' .beads/issues.jsonl | head -1 | sed 's/-[^-]*$//')
    bd init --from-jsonl --non-interactive --skip-hooks --skip-agents --quiet \
        ${prefix:+--prefix "$prefix"} >/dev/null
    # bd init commits its ignore-file additions; fold them into the single init commit.
    git add -A
    root=$(git rev-list --max-parents=0 HEAD)
    git reset -q --soft "$root"
    git commit -q --amend -m init
fi
# Graph of the snapshot, so codebase-memory answers about this commit only.
codebase-memory-mcp cli index_repository --repo-path "$(pwd)" >/dev/null
git reflog expire --expire=now --all
git gc -q --prune=now
