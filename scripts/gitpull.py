import subprocess
import os
from datetime import datetime

REPO = "/Users/revilth/Documents/Claude_Research/Monitoring_Fed"
LOG = os.path.join(REPO, "logs", "gitpull.log")

def log(msg):
    with open(LOG, "a") as f:
        f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")

log("Starting git pull")
try:
    result = subprocess.run(
        ["/usr/bin/git", "-C", REPO, "pull", "--no-rebase", "origin", "main"],
        capture_output=True, text=True
    )
    if result.stdout:
        log(result.stdout.strip())
    if result.stderr:
        log(result.stderr.strip())
    if result.returncode == 0:
        log("Done")
    else:
        log(f"FAILED with exit code {result.returncode}")
except Exception as e:
    log(f"ERROR: {e}")
