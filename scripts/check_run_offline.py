#!/usr/bin/env python3
"""run.sh offline: when the dependency install fails it starts with the installed packages, and stops only when there are none.
No server and no network: a copy of run.sh in a temp folder, with a stand-in `uv` and `.venv/bin/python`.
    python3 scripts/check_run_offline.py
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if os.name == "nt" or not shutil.which("bash"):
    print("skipped: run.sh needs bash on macOS or Linux")
    sys.exit(0)

fails = []


def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name)
    if not ok:
        fails.append(name)


def script(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n" + body + "\n")
    path.chmod(0o755)


def run(online, installed):
    tmp = Path(tempfile.mkdtemp(prefix="flowlystack-run-offline-check-"))
    shutil.copy(ROOT / "run.sh", tmp / "run.sh")
    script(tmp / "bin" / "uv", "exit %d" % (0 if online else 2))
    # `-c "import ..."` answers whether the packages are there; anything else is the server start
    script(tmp / ".venv" / "bin" / "python", 'if [ "$1" = "-c" ]; then exit %d; fi\necho STARTED "$@"' % (0 if installed else 1))
    env = {**os.environ, "PATH": str(tmp / "bin") + os.pathsep + os.environ["PATH"], "PORT": "1"}
    r = subprocess.run(["bash", str(tmp / "run.sh")], env=env, capture_output=True, text=True, timeout=30)
    shutil.rmtree(tmp, ignore_errors=True)
    return r


r = run(online=True, installed=True)
check("online: starts without a warning", r.returncode == 0 and "STARTED" in r.stdout and "offline" not in r.stderr)
r = run(online=False, installed=True)
check("offline with packages installed: warns and starts", r.returncode == 0 and "STARTED" in r.stdout and "offline" in r.stderr)
r = run(online=False, installed=False)
check("offline with nothing installed: stops with the message", r.returncode == 1 and "STARTED" not in r.stdout and "Could not install" in r.stderr)

print(f"\n{len(fails)} failed" if fails else "\nall passed")
sys.exit(1 if fails else 0)
