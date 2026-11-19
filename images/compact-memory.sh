#!/bin/sh
# Return WSL VM memory to Windows after a large build: drop the page cache and compact,
# so free memory forms the 2 MB blocks that autoMemoryReclaim can hand back.
exec docker run --rm --privileged alpine:3.20 sh -c \
    'sync; echo 1 > /proc/sys/vm/drop_caches; echo 1 > /proc/sys/vm/compact_memory'
