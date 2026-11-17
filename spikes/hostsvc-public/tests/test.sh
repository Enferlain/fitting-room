#!/bin/bash
mkdir -p /logs/verifier
cp /app/net.txt /logs/verifier/net.txt 2>/dev/null
if grep -q '^host fitting-room-pong' /app/net.txt; then echo 1; else echo 0; fi > /logs/verifier/reward.txt
