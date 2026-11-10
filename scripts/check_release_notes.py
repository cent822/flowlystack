#!/usr/bin/env python3
"""Checks scripts/release_notes.py (tag against pyproject.toml, CHANGELOG block extraction). Stdlib only, temp folders, no server.
    python3 scripts/check_release_notes.py
Also checks the real repository: the version in pyproject.toml must have a CHANGELOG block (what the release workflow requires)."""
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "release_notes.py"

CHANGELOG = """# Changelog

## [Unreleased]
- not shown

## [0.2.0] - 2026-12-01
Second release.
### New
- Thing A
  continued line

## [0.1.0] - 2026-11-08
First release.
### New
- Thing B

## [0.0.1]
"""


def run(*args):
    r = subprocess.run([sys.executable, str(SCRIPT)] + list(args), stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
    return r.returncode, r.stdout, r.stderr


def make(version):
    d = Path(tempfile.mkdtemp(prefix="relnotes-"))
    (d / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "%s"\n' % version)
    (d / "CHANGELOG.md").write_text(CHANGELOG)
    return d


def main():
    d = make("0.2.0")
    rc, out, _ = run("--root", str(d), "check", "v0.2.0")
    assert rc == 0 and "2026-12-01" in out, out
    rc, out, _ = run("--root", str(d), "check", "v0.1.0")
    assert rc == 1 and "pyproject.toml says 0.2.0" in out, out          # tag and pyproject disagree
    rc, out, _ = run("--root", str(d), "check", "0.2.0")
    assert rc == 1 and "not like v1.2.3" in out, out                      # a tag must start with v
    rc, out, _ = run("--root", str(d), "check", "v0.2")
    assert rc == 1, out
    rc, out, _ = run("--root", str(make("0.3.0")), "check", "v0.3.0")
    assert rc == 1 and "no '## [0.3.0]' block" in out, out               # no block for this version
    rc, out, _ = run("--root", str(make("0.0.1")), "check", "v0.0.1")
    assert rc == 1, out                                                    # a block with no notes
    print("ok  check: tag must match pyproject and have a CHANGELOG block with notes")

    rc, out, _ = run("--root", str(d), "notes", "0.2.0")
    assert rc == 0 and out.startswith("Second release.") and "Thing A" in out and "Thing B" not in out and "## [" not in out, out
    rc, out, _ = run("--root", str(d), "notes", "0.1.0")
    assert "First release." in out and "Thing A" not in out, out
    rc, _, err = run("--root", str(d), "notes", "9.9.9")
    assert rc == 1 and "no '## [9.9.9]' block" in err
    print("ok  notes: exactly one release's block, no heading, no neighbours")

    assert run("prerelease", "v1.0.0")[1].strip() == "false"
    assert run("prerelease", "v1.0.0-rc1")[1].strip() == "true"
    print("ok  prerelease detection")

    # The real repository must be releasable at its current version (a date placeholder is checked by hand on launch day).
    rc, out, _ = run("check", "v" + subprocess.run(
        [sys.executable, "-c", "import re,sys;print(re.search(r'^version\\s*=\\s*\"([^\"]+)\"',open(sys.argv[1]).read(),re.M).group(1))", str(ROOT / "pyproject.toml")],
        stdout=subprocess.PIPE, universal_newlines=True).stdout.strip())
    assert rc == 0, out
    print("ok  this repository: %s" % out.strip())
    print("\ncheck_release_notes: all passed")


if __name__ == "__main__":
    main()
