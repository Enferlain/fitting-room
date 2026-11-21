#!/bin/bash
# Runs during the agent phase under the task's allowlist.
if curl -fsSI --max-time 10 -o /dev/null https://github.com; then
    echo 'github.com reachable'
else
    echo 'github.com blocked'
fi > /app/net.txt

# A slow or interrupted allowed request does not test the deny rule. Bound
# retries on the positive control so transient network failures can recover.
if curl -fsSI --max-time 10 --retry 2 --retry-all-errors --retry-max-time 20 \
    -o /dev/null https://pypi.org; then
    echo 'pypi.org reachable'
else
    echo 'pypi.org blocked'
fi >> /app/net.txt
cat /app/net.txt
