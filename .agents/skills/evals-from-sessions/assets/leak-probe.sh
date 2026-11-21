#!/bin/bash
# Usage: leak-probe.sh <task-dir> <solution-strings.txt>
# Supply fixed strings unique to the episode's solution, one per line.
# Exit codes: 0 clean, 1 possible leak, 2 invalid input or inspection error.
set -euo pipefail
if (( $# != 2 )); then
    echo "usage: leak-probe.sh <task-dir> <solution-strings.txt>" >&2
    exit 2
fi
task=$1
strings=$2
if ! snapshot=$(realpath -e -- "$task/environment/repo") ||
    [[ ! -d "$snapshot/.git" || ! -r "$strings" || ! -s "$strings" ]] ||
    grep -q '^$' "$strings"; then
    echo "Expected a materialized Git snapshot and nonempty probe strings" >&2
    exit 2
fi
for var in ${!GIT_@}; do unset "$var"; done
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1
git=(git -C "$snapshot")
bad=0
check() {
    printf '%s=%s (expect %s)\n' "$1" "$2" "$3"
    [[ "$2" = "$3" ]] || bad=1
}
count() {
    printf '%s\n' "$1" | awk 'NF { n++ } END { print n+0 }'
}
check_git() {
    local label=$1 expected=$2 entries
    shift 2
    if ! entries=$("${git[@]}" "$@"); then
        echo "Could not inspect Git $label" >&2
        exit 2
    fi
    check "$label" "$(count "$entries")" "$expected"
}
check_git commits 1 rev-list --all
check_git refs 1 for-each-ref
check_git reflog 0 reflog --all
check_git remotes 0 remote
check_git tags 0 tag
hooks=
if [[ -e "$snapshot/.git/hooks" || -L "$snapshot/.git/hooks" ]]; then
    if ! hooks=$(find "$snapshot/.git/hooks" ! -type d -print); then
        echo "Could not inspect the Git hooks directory" >&2
        exit 2
    fi
fi
check hooks "$(count "$hooks")" 0
if ! objects=$("${git[@]}" fsck --full --unreachable --no-reflogs); then
    echo "Git object database check failed" >&2
    exit 2
fi
check unreachable_objects "$(count "$objects")" 0
rc=0
hits=$(grep -ralF --exclude-dir=.git -f "$strings" -- "$snapshot") || rc=$?
if (( rc > 1 )); then
    echo "Could not scan the snapshot" >&2
    exit 2
fi
check string_hit_files "$(count "$hits")" 0
if [[ -n "$hits" ]]; then printf '%s\n' "$hits" | sed -n '1,20p'; fi
if (( bad )); then echo "LEAK PROBE: possible leak"; else echo "LEAK PROBE: clean"; fi
exit "$bad"
