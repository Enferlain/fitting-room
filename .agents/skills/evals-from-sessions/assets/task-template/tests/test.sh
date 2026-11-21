#!/bin/bash
# Runs offline after the agent finishes. Never download anything here.
# Always writes a reward: a missing reward file is a Harbor error, not a 0.
mkdir -p /logs/verifier
reward=0
trap 'echo "$reward" > /logs/verifier/reward.txt' EXIT
"${VIRTUAL_ENV:?Set the task verifier interpreter}/bin/python" /tests/verify.py && reward=1
exit 0
