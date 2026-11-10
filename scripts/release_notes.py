#!/usr/bin/env python3
"""Release helper for the release workflow (.github/workflows/release.yml). Stdlib only, Python 3.9+.

    python3 scripts/release_notes.py check v0.1.0     the tag must equal v + the version in pyproject.toml, and CHANGELOG.md
                                                       must have a '## [0.1.0]' block with something in it
    python3 scripts/release_notes.py notes 0.1.0      prints that block (without its heading) as the GitHub Release notes
    python3 scripts/release_notes.py prerelease v0.1.0-rc1    prints 'true' when the tag has a '-' suffix, else 'false'

Options: --root DIR (default: the repository) to read another folder's pyproject.toml and CHANGELOG.md.
Exit code 0 = fine, 1 = a problem (the message says what to fix)."""
import re
import sys
from pathlib import Path

HEAD_RE = re.compile(r"^##\s+\[([^\]]+)\](?:\s*-\s*(\S+))?\s*$")
VERSION_RE = re.compile(r'^\s*version\s*=\s*"([^"]+)"', re.M)


def project_version(root):
    m = VERSION_RE.search((root / "pyproject.toml").read_text(encoding="utf-8"))
    if not m:
        raise SystemExit("no version in pyproject.toml")
    return m.group(1)


def block(root, version):
    """Returns (date, body) of the CHANGELOG block for the version, or None."""
    lines = (root / "CHANGELOG.md").read_text(encoding="utf-8").splitlines()
    start = None
    date = ""
    for i, line in enumerate(lines):
        m = HEAD_RE.match(line.rstrip())
        if m and m.group(1).strip().lstrip("vV") == version:
            start, date = i + 1, m.group(2) or ""
            break
    if start is None:
        return None
    end = len(lines)
    for j in range(start, len(lines)):
        if HEAD_RE.match(lines[j].rstrip()):
            end = j
            break
    return date, "\n".join(lines[start:end]).strip("\n") + "\n"


def main(argv):
    root = Path(__file__).resolve().parent.parent
    if "--root" in argv:
        i = argv.index("--root")
        root = Path(argv[i + 1])
        argv = argv[:i] + argv[i + 2:]
    if len(argv) != 2 or argv[0] not in ("check", "notes", "prerelease"):
        sys.stderr.write(__doc__)
        return 1
    cmd, arg = argv
    if cmd == "prerelease":
        print("true" if "-" in arg.lstrip("vV") else "false")
        return 0
    if cmd == "check":
        if not re.match(r"^v\d+\.\d+\.\d+(-[0-9A-Za-z.]+)?$", arg):
            print("The tag '%s' is not like v1.2.3 (or v1.2.3-rc1)." % arg)
            return 1
        version = arg[1:]
        have = project_version(root)
        if version != have:
            print("The tag says %s but pyproject.toml says %s. Change one so they agree." % (version, have))
            return 1
        found = block(root, version)
        if found is None or not found[1].strip():
            print("CHANGELOG.md has no '## [%s]' block with notes in it." % version)
            return 1
        print("ok: tag %s, pyproject %s, CHANGELOG block dated %s" % (arg, have, found[0] or "(no date)"))
        return 0
    found = block(root, arg.lstrip("vV"))
    if found is None or not found[1].strip():
        sys.stderr.write("CHANGELOG.md has no '## [%s]' block with notes in it.\n" % arg)
        return 1
    sys.stdout.write(found[1])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
