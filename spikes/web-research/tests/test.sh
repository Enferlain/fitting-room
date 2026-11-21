#!/usr/bin/env bash
set -euo pipefail

mkdir -p /logs/verifier
if printf '%s\n' Contact Expires https://www.rfc-editor.org/rfc/rfc9116.txt |
    cmp -s - /app/answer.txt; then
    printf '1\n' > /logs/verifier/reward.txt
else
    printf '0\n' > /logs/verifier/reward.txt
fi
