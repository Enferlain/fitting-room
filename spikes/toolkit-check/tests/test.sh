#!/bin/bash
mkdir -p /logs/verifier
reward=0
trap 'echo "$reward" > /logs/verifier/reward.txt' EXIT
cd /work/hermes-agora && /opt/venv/bin/python /tests/verify.py && reward=1
exit 0
