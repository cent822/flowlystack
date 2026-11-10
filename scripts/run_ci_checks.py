#!/usr/bin/env python3
"""Runs every check that needs no server: what CI runs on each push, and what you can run before one.
    .venv/bin/python scripts/run_ci_checks.py        (Python 3.10+ with the project's dependencies; CI uses 3.12)
    .venv/bin/python scripts/run_ci_checks.py -k mcp  (only the checks whose name contains 'mcp')

Each check runs in its own process with a throwaway HOME, settings folder, prompts folder and usage cache, so nothing real is
read or written. The checks that need a TEST server (the *_api.py ones) are listed in SERVER_CHECKS and are NOT run here.
Every other scripts/check_*.py runs, so a new server-free check is picked up by itself. A NEW check that needs a server must be
added to SERVER_CHECKS, or it fails here (loudly, which is the point). A name listed here that no longer exists also fails."""
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"

# Need a running TEST server (see CONTRIBUTING.md, "Run the checks"): run by hand before a release, not here.
SERVER_CHECKS = {
    "check_assistant_api.py", "check_auth_api.py", "check_collections_api.py", "check_gallery_api.py",
    "check_gallery_docs_api.py", "check_kgraph_api.py", "check_linkshell_api.py", "check_mcp_api.py",
    "check_runtimes_api.py", "check_samples_api.py", "check_settings_api.py", "check_studio_api.py",
}
# Need Node instead of Python.
NODE_CHECKS = {"check_lattice_layouts.mjs"}

TIMEOUT = 300


def main(argv):
    only = argv[1] if len(argv) > 2 and argv[0] == "-k" else None
    present = {p.name for p in SCRIPTS.glob("check_*.py")} | {p.name for p in SCRIPTS.glob("check_*.mjs")}
    stale = (SERVER_CHECKS | NODE_CHECKS) - present
    if stale:
        print("Listed but missing: %s. Update run_ci_checks.py." % ", ".join(sorted(stale)))
        return 1
    plain = sorted(n for n in present if n.endswith(".py") and n not in SERVER_CHECKS)
    jobs = [(n, [sys.executable, str(SCRIPTS / n)]) for n in plain]
    node = shutil.which("node")
    for n in sorted(NODE_CHECKS):
        if node:
            jobs.append((n, [node, str(SCRIPTS / n)]))
        else:
            print("SKIP  %s (Node not found)" % n)
    if only:
        jobs = [j for j in jobs if only in j[0]]

    tmp = tempfile.mkdtemp(prefix="flowly-ci-")
    env = dict(os.environ)
    env.update({
        "HOME": tmp, "USERPROFILE": tmp, "FLOWLYSTACK_SETTINGS_DIR": os.path.join(tmp, "settings"),
        "FLOWLYSTACK_PROMPTS_DIR": os.path.join(tmp, "prompts"), "FLOWLYSTACK_DB": os.path.join(tmp, "usage.sqlite"),
        "FLOWLYSTACK_ALIAS_DIR": os.path.join(tmp, "alias"), "FLOWLYSTACK_WEBUI_DIR": "/nonexistent",
        "FLOWLYSTACK_AUTH": "off",
    })
    env.pop("BASE", None)   # a stray BASE would make some checks call a server
    failed = []
    try:
        for name, cmd in jobs:
            start = time.time()
            try:
                r = subprocess.run(cmd, cwd=str(ROOT), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   universal_newlines=True, timeout=TIMEOUT)
                code, out = r.returncode, r.stdout
            except subprocess.TimeoutExpired as e:
                code, out = 124, "timed out after %ds\n%s" % (TIMEOUT, e.stdout or "")
            print("%s  %-34s %4.1fs" % ("ok  " if code == 0 else "FAIL", name, time.time() - start), flush=True)
            if code != 0:
                failed.append(name)
                print("\n".join("      " + l for l in out.strip().splitlines()[-15:]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n%d checks, %d failed%s" % (len(jobs), len(failed), (": " + ", ".join(failed)) if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
