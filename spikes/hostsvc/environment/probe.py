import sys, urllib.request
host = sys.argv[1]
try:
    urllib.request.urlopen(f"https://{host}/", timeout=10)
    print(f"{host} reachable")
except Exception as e:  # HTTP errors still mean the host was reachable
    reached = hasattr(e, "code")
    print(f"{host} {'reachable' if reached else 'blocked'} ({type(e).__name__})")
