#!/usr/bin/env python3
"""Leak check: refuses text and files that must never reach the public repository. Stdlib only (Python 3.9+).

    python3 scripts/leak_check.py --tree [DIR]        every tracked file in DIR (default: the repo), for CI and clean clones
    python3 scripts/leak_check.py --staged            the lines and files in the git index (the pre-commit hook)
    python3 scripts/leak_check.py --range A..B        lines and commit messages of a commit range (CI on a pull request)
    python3 scripts/leak_check.py --push              reads the pre-push hook's stdin (one line per ref being pushed)

Public rules (written here, safe to publish): Mac and Windows home paths, key-shaped strings, private-key blocks,
notes that cite private planning docs (the project's own private notes and logs),
and files that never belong in the repo (.env, flowlystack.config.json, prompts/, data/, logs/, databases, secrets).

Private rules (your username, e-mail, private file names) are NOT in this file, or publishing it would leak them.
They come from, in this order: the text in env LEAK_PRIVATE (a CI secret), the file named in env LEAK_PRIVATE_FILE,
or <git dir>/info/leak-private. One rule per line, '#' starts a comment:
    pattern: <regex>      a line (or commit author/message) matching this is refused; case-insensitive
    forbid: <glob>        a path matching this is refused
    skip: <glob>          a path matching this is not scanned at all (files that leave the repo at launch)
A line holding the marker  leak-ok  is ignored (for fake keys in tests). Output never prints a line that matched a
private pattern (CI logs of a public repo are public); it prints file:line and the rule number only.

Exit code 0 = clean, 1 = something found, 2 = could not run."""
import fnmatch
import os
import re
import subprocess
import sys

OK_MARKER = "leak-ok"

# Example names that are fine in docs and tests (not a real person's folder).
PLACEHOLDER = r"(?:(?:alice|bob|x|you|your[-_]?name|user|username|name|me|example|jane|john|someone|public)(?![A-Za-z0-9])|\.{2,})"

PUBLIC_PATTERNS = [
    ("Mac home path", re.compile(r"/Users/(?!" + PLACEHOLDER + r")[A-Za-z0-9._-]+")),
    ("Windows home path", re.compile(r"[A-Za-z]:\\Users\\(?!" + PLACEHOLDER + r")[A-Za-z0-9._ -]+", re.I)),
    ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
    ("API key (sk-)", re.compile(r"\bsk-[A-Za-z0-9_-]{24,}\b")),
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    # Notes that point at private planning docs, which are not part of the public repository (nobody could follow them).
    ("private doc citation", re.compile(
        r"docs/[a-z-]*(?:plan|buildplan)\.md|docs/reference-[a-z-]+\.md|docs/(?:dashboard-adapters|ui-dialog-rules|devlog-template)\.md"
        r"|\bCLAUDE\.md\b|logs/devl[o]g")),
]

# Paths that never belong in the public repo. Matched against the whole path and each folder prefix.
PUBLIC_FORBID = [
    ".env", "*/.env", "flowlystack.config.json", "*/flowlystack.config.json",
    "prompts/*", "data/*", "logs/*", ".venv/*", ".claude/*", "reference/*",
    "*.db", "*.sqlite", "*.sqlite3", "*/secrets.json", "secrets.json", "*/auth.json", "auth.json", ".DS_Store", "*/.DS_Store",
]


def run(args, cwd=None, check=True, text=True):
    r = subprocess.run(args, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=text)
    if check and r.returncode != 0:
        sys.stderr.write("leak_check: command failed: %s\n%s\n" % (" ".join(args), r.stderr))
        sys.exit(2)
    return r


def git_dir(cwd):
    return run(["git", "rev-parse", "--git-dir"], cwd=cwd).stdout.strip()


def private_patterns(root):
    """The private regexes (see the module text), for other scripts that want to refuse the same words. Never runs git and never fails:
    with no rule file and no LEAK_PRIVATE (a Docker build, a tarball, a fork) it returns an empty list, so those scripts still work."""
    text = os.environ.get("LEAK_PRIVATE")
    if text is None:
        path = os.environ.get("LEAK_PRIVATE_FILE") or os.path.join(str(root), ".git", "info", "leak-private")
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
        except OSError:
            return []
    return [rx for _n, rx in parse_rules(text)["patterns"]]


def parse_rules(text):
    out = {"patterns": [], "forbid": [], "skip": []}   # patterns: (number, regex)
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        kind, value = line.split(":", 1)
        kind, value = kind.strip().lower(), value.strip()
        if not value:
            continue
        if kind == "pattern":
            out["patterns"].append((len(out["patterns"]) + 1, re.compile(value, re.I)))
        elif kind in ("forbid", "skip"):
            out[kind].append(value)
    return out


class Rules:
    def __init__(self, cwd):
        text = os.environ.get("LEAK_PRIVATE")
        if text is None:
            path = os.environ.get("LEAK_PRIVATE_FILE")
            if not path:
                path = os.path.join(cwd, git_dir(cwd), "info", "leak-private")   # join keeps an absolute git dir as is
            if os.path.isfile(path):
                with open(path, encoding="utf-8") as f:
                    text = f.read()
        parsed = parse_rules(text)
        self.patterns, self.forbid, self.skip = parsed["patterns"], parsed["forbid"], parsed["skip"]

    def skipped(self, path):
        return any(fnmatch.fnmatch(path, g) for g in self.skip)

    def forbidden(self, path):
        """Returns a label if the path may not be in the repo, else None."""
        for g in PUBLIC_FORBID:
            if fnmatch.fnmatch(path, g):
                return "forbidden file (%s)" % g
        for i, g in enumerate(self.forbid, 1):
            if fnmatch.fnmatch(path, g):
                return "private forbidden path #%d" % i
        return None


def scan_line(rules, line):
    """Returns a list of (label, shown) findings for one line; shown is None for private rules."""
    if OK_MARKER in line:
        return []
    found = []
    for label, rx in PUBLIC_PATTERNS:
        m = rx.search(line)
        if m:
            found.append((label, m.group(0)[:60]))
    for n, rx in rules.patterns:
        if rx.search(line):
            found.append(("private pattern #%d" % n, None))
    return found


class Report:
    def __init__(self):
        self.items = []

    def add(self, where, label, shown=None):
        self.items.append((where, label, shown))

    def finish(self):
        if not self.items:
            print("leak_check: clean")
            return 0
        for where, label, shown in self.items:
            print("LEAK  %s  %s%s" % (where, label, ("  [%s]" % shown) if shown else ""))
        print("leak_check: %d finding(s). Fix them, or mark a harmless line with '%s'." % (len(self.items), OK_MARKER))
        return 1


def is_binary(data):
    return b"\0" in data[:4096]


def scan_paths(rules, paths, report):
    for p in paths:
        label = rules.forbidden(p)
        if label and not rules.skipped(p):
            report.add(p, label)


def scan_tree(rules, cwd, report):
    out = run(["git", "ls-files", "-z"], cwd=cwd).stdout
    paths = [p for p in out.split("\0") if p]
    scan_paths(rules, paths, report)
    for p in paths:
        if rules.skipped(p) or rules.forbidden(p):
            continue
        full = os.path.join(cwd, p)
        if not os.path.isfile(full):
            continue
        with open(full, "rb") as f:
            data = f.read()
        if is_binary(data):
            continue
        for no, line in enumerate(data.decode("utf-8", "replace").splitlines(), 1):
            for label, shown in scan_line(rules, line):
                report.add("%s:%d" % (p, no), label, shown)


def scan_diff(rules, diff_args, cwd, report):
    """Scans the added lines and added paths of a git diff/log -p output."""
    names = run(["git"] + diff_args + ["--name-only", "--diff-filter=AMR", "-z", "--format="], cwd=cwd).stdout
    scan_paths(rules, sorted(set(p for p in names.split("\0") if p.strip())), report)
    text = run(["git"] + diff_args + ["-U0", "--no-color", "--diff-filter=AMR", "--format="], cwd=cwd, text=False).stdout
    path, lineno = None, 0
    for raw in text.decode("utf-8", "replace").splitlines():
        if raw.startswith("+++ "):
            path = raw[6:] if raw.startswith("+++ b/") else None
            continue
        if raw.startswith("@@"):
            m = re.search(r"\+(\d+)", raw)
            lineno = int(m.group(1)) if m else 0
            continue
        if raw.startswith("+") and path:
            if not rules.skipped(path) and not rules.forbidden(path):
                for label, shown in scan_line(rules, raw[1:]):
                    report.add("%s:%d" % (path, lineno), label, shown)
            lineno += 1


def scan_messages(rules, rev_args, cwd, report):
    """Commit author, committer and message text of the given commits."""
    out = run(["git", "log", "--format=%H%x1f%an%x1f%ae%x1f%cn%x1f%ce%x1f%B%x1e"] + rev_args, cwd=cwd).stdout
    for rec in out.split("\x1e"):
        rec = rec.strip("\n")
        if not rec.strip():
            continue
        parts = rec.split("\x1f")
        sha = parts[0][:10]
        for chunk in parts[1:]:
            for label, shown in scan_line(rules, chunk):
                report.add("commit %s" % sha, label + " (author or message)", shown)


def main(argv):
    if not argv or argv[0] not in ("--tree", "--staged", "--range", "--push"):
        sys.stderr.write(__doc__)
        return 2
    mode = argv[0]
    here = os.getcwd()
    cwd = run(["git", "rev-parse", "--show-toplevel"], cwd=argv[1] if mode == "--tree" and len(argv) > 1 else here).stdout.strip()
    rules = Rules(cwd)
    report = Report()
    if mode == "--tree":
        scan_tree(rules, cwd, report)
    elif mode == "--staged":
        scan_diff(rules, ["diff", "--cached"], cwd, report)
    elif mode == "--range":
        if len(argv) < 2:
            sys.stderr.write("--range needs A..B\n")
            return 2
        scan_diff(rules, ["diff", argv[1]], cwd, report)
        scan_messages(rules, [argv[1]], cwd, report)
    else:  # --push: stdin lines "<local ref> <local sha> <remote ref> <remote sha>"
        zero = "0" * 40
        for line in sys.stdin.read().splitlines():
            bits = line.split()
            if len(bits) != 4 or bits[1] == zero:
                continue   # a deletion pushes nothing
            local_sha, remote_sha = bits[1], bits[3]
            if remote_sha == zero:   # new branch: everything not already on some remote
                revs = [local_sha, "--not", "--remotes"]
                scan_messages(rules, revs, cwd, report)
                commits = run(["git", "rev-list"] + revs, cwd=cwd).stdout.split()
                for c in commits:
                    scan_diff(rules, ["show", c], cwd, report)
            else:
                scan_diff(rules, ["diff", "%s..%s" % (remote_sha, local_sha)], cwd, report)
                scan_messages(rules, ["%s..%s" % (remote_sha, local_sha)], cwd, report)
    return report.finish()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
