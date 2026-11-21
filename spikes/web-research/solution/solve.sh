#!/usr/bin/env bash
set -euo pipefail

source_url=https://www.rfc-editor.org/rfc/rfc9116.txt
source_file=$(mktemp)
trap 'rm -f "$source_file"' EXIT

curl --fail --silent --show-error --retry 2 --max-time 20 "$source_url" -o "$source_file"
for field in Contact Expires; do
    grep -Eq "Field Name:[[:space:]]+$field$" "$source_file"
done
printf '%s\n' Contact Expires "$source_url" > /app/answer.txt
