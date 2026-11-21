#!/bin/bash
if body=$(curl -fsS --max-time 10 http://host.containers.internal:18080/ping); then
    printf 'host %s\n' "$body"
else
    echo 'host blocked'
fi > /app/net.txt
if curl -fsS --max-time 10 -o /dev/null https://github.com; then
    echo 'github.com reachable'
else
    echo 'github.com blocked'
fi >> /app/net.txt
cat /app/net.txt
