"""Start server + run API test in one process.

A developer script, not a pytest test: pytest's default collection pattern is
``test_*.py``, so this file is not collected, and running it starts a uvicorn
server on 127.0.0.1:8000.  Paths are derived from this file, not written out for
one machine — a hard-coded ``D:\\oms-wms-tms`` worked here and nowhere else.
"""

import os
import subprocess
import sys
import time

os.environ["TESTING"] = "true"
os.environ["PYTHONIOENCODING"] = "utf-8"

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
FULL_API_SCRIPT = os.path.join(os.path.dirname(__file__), "test_full_api.py")

# Start server with TESTING env var
env = os.environ.copy()
env["TESTING"] = "true"
proc = subprocess.Popen(
    [sys.executable, "-m", "uvicorn", "src.main:app", "--host", "127.0.0.1", "--port", "8000"],
    cwd=REPO_ROOT,
    env=env,
    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
)

print(f"Server PID={proc.pid}, waiting 6s...")
time.sleep(6)

# Verify server is up
import requests  # noqa: E402 — imported after the server is up: this file's purpose is the run, not the module

try:
    r = requests.get("http://127.0.0.1:8000/health", timeout=5)
    print(f"Health: {r.status_code}")
except Exception as e:
    print(f"Health FAIL: {e}")
    proc.kill()
    sys.exit(1)

# Quick auth test
try:
    r = requests.post("http://127.0.0.1:8000/api/v1/auth/register",
                      json={"username":"quicktest","email":"q@t.com","password":"test12345"}, timeout=10)
    print(f"Register: {r.status_code}")
except Exception as e:
    print(f"Register FAIL: {e}")

# Run full test
result = subprocess.run(
    [sys.executable, FULL_API_SCRIPT],
    timeout=120,
)

proc.kill()
proc.wait()
print("Done.")
sys.exit(result.returncode)
