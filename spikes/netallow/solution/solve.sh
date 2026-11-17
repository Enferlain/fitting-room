#!/bin/bash
# Runs in the agent phase, so it is subject to [agent] network policy.
python3 /usr/local/bin/probe.py github.com > /app/net.txt
python3 /usr/local/bin/probe.py pypi.org >> /app/net.txt
cat /app/net.txt
