#!/bin/bash
python3 - > /app/net.txt <<'PY'
import urllib.request
try:
    body = urllib.request.urlopen("http://host.docker.internal:18080/ping", timeout=10).read().decode().strip()
    print("host", body)
except Exception as e:
    print("host blocked", type(e).__name__, e)
PY
python3 /usr/local/bin/probe.py github.com >> /app/net.txt
cat /app/net.txt
