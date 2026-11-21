#!/usr/bin/env bash
set -euo pipefail
base=$(cd -- "$(dirname -- "$0")" && pwd)
group=${1:?Provide the runtime group}
trial=$(realpath "${2:?Provide a trial directory}")
shift 2
py=/opt/codex/runtimes/codex-primary-runtime/dependencies/python
# The manifest-controlled runtime has no trial source installed in site-packages.
mounts=()
if [[ -d "$base/$group" ]]; then mounts+=(--ro-bind "$base/$group" /bench); fi
if [[ -d "$base/toolchain-$group" ]]; then mounts+=(--ro-bind "$base/toolchain-$group" /toolchain); fi
exec bwrap --unshare-user --unshare-pid --unshare-ipc --unshare-uts --die-with-parent --new-session \
  --clearenv --ro-bind /usr /usr --symlink usr/bin /bin --symlink usr/lib /lib \
  --symlink usr/lib64 /lib64 --ro-bind /etc/alternatives /etc/alternatives --ro-bind /etc/ld.so.cache /etc/ld.so.cache \
  --ro-bind "$py" "$py" --tmpfs "$py/lib/python3.12/site-packages" --ro-bind "$base/offline.py" /offline.py \
  --dev /dev --proc /proc --tmpfs /tmp --dir /tmp/home --bind "$trial" /trial \
  "${mounts[@]}" --chdir /trial --setenv HOME /tmp/home \
  --setenv PATH "/bench/bin:/toolchain/bin:$py/bin:/usr/bin" --setenv LANG C.UTF-8 \
  --setenv PYTHONPATH /trial --setenv PYTHONNOUSERSITE 1 \
  --setenv PYTHONDONTWRITEBYTECODE 1 --setenv UV_OFFLINE 1 --setenv CARGO_NET_OFFLINE true \
  --setenv OMP_NUM_THREADS 1 --setenv MKL_NUM_THREADS 1 \
  --setenv PYTHONHASHSEED 0 --setenv TZ UTC \
  "$py/bin/python3.12" -I /offline.py "$@"
