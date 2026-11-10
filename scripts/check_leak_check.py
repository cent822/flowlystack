#!/usr/bin/env python3
"""Checks scripts/leak_check.py and the git hooks in scripts/githooks/, stdlib only, no server.
    python3 scripts/check_leak_check.py
Everything happens in throwaway git repos in a temp folder; the real repo and its .git/hooks are never touched.
The fake name and e-mail below are made up for this check."""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "leak_check.py"
HOOKS = ROOT / "scripts" / "githooks"
FAKE_NAME = "jordanfake"
# Built from pieces so this file itself never contains a path or key the leak check would refuse.
FAKE_HOME = "/" + "Users/" + "realperson"
FAKE_MAIL = "jordan.fake@example.invalid"
PRIVATE = "# test rules\npattern: %s\npattern: %s\nforbid: secret-notes/*\nskip: leaving/*\n" % (FAKE_NAME, FAKE_MAIL.replace(".", r"\."))


def sh(args, cwd, env=None, ok=True):
    e = dict(os.environ)
    e.pop("LEAK_PRIVATE", None)
    e.pop("LEAK_PRIVATE_FILE", None)
    e.update(env or {})
    r = subprocess.run(args, cwd=str(cwd), env=e, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
    if ok and r.returncode != 0:
        raise AssertionError("failed: %s\n%s" % (args, r.stdout))
    return r


def new_repo(base, name, private=True, hooks=False):
    d = Path(base) / name
    d.mkdir()
    sh(["git", "init", "-q"], d)
    sh(["git", "config", "user.name", "Test"], d)
    sh(["git", "config", "user.email", "noreply@example.invalid"], d)
    (d / "scripts").mkdir()
    shutil.copy(SCRIPT, d / "scripts" / "leak_check.py")
    if private:
        (d / ".git" / "info").mkdir(exist_ok=True)
        (d / ".git" / "info" / "leak-private").write_text(PRIVATE)
    if hooks:
        for h in ("pre-commit", "pre-push"):
            dst = d / ".git" / "hooks" / h
            shutil.copy(HOOKS / h, dst)
            dst.chmod(0o755)
    return d


def put(d, rel, text):
    p = Path(d) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    sh(["git", "add", "-f", rel], d)


def commit(d, msg="x", ok=True, env=None):
    return sh(["git", "commit", "-q", "-m", msg], d, env=env, ok=ok)


def main():
    base = tempfile.mkdtemp(prefix="leakcheck-")
    try:
        # 1. A clean tree passes; example names and the leak-ok marker are allowed.
        d = new_repo(base, "clean")
        put(d, "README.md", "Use /Users/alice/project or C:\\Users\\You\\x or /Users/... as examples.\n")
        put(d, "t.py", 'KEY = "sk-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"  # leak-ok: fake\n')
        put(d, "z.md", "one zip with plan.md and an assets folder; see docs/quick-start.md and CONTRIBUTING.md; a development log\n")
        r = sh([sys.executable, "scripts/leak_check.py", "--tree"], d, ok=False)
        assert r.returncode == 0 and "clean" in r.stdout, r.stdout
        print("ok  clean tree, placeholder names and leak-ok pass")

        # 2. Public rules fire on a tree scan.
        for text, label in [
            ("path " + FAKE_HOME + "/Desktop/x\n", "Mac home path"),
            ("path C:\\Users\\RealPerson\\Desktop\n", "Windows home path"),
            ("-----BEGIN RSA " + "PRIVATE KEY-----\n", "private key block"),
            ("token ghp_" + "a" * 36 + "\n", "GitHub token"),
            ("key sk-" + "b" * 30 + "\n", "API key (sk-)"),
            ("key AKIA" + "C" * 16 + "\n", "AWS access key"),
            ("see docs/" + "mcp-plan.md, section 3\n", "private doc citation"),
            ("see docs/" + "reference-lattice.md\n", "private doc citation"),
            ("rules in CLAUDE" + ".md\n", "private doc citation"),
            ("the log is logs/" + "devlog.md\n", "private doc citation"),
        ]:
            d = new_repo(base, "pub")
            put(d, "doc.md", text)
            r = sh([sys.executable, "scripts/leak_check.py", "--tree"], d, ok=False)
            assert r.returncode == 1 and label in r.stdout, (label, r.stdout)
            shutil.rmtree(d)
        print("ok  public rules: home paths, key shapes, private key block")

        # 3. Forbidden files, public and private.
        for rel in (".env", "flowlystack.config.json", "prompts/a.json", "data/x.db", "logs/notes.md", "secret-notes/n.md"):
            d = new_repo(base, "forb")
            put(d, rel, "harmless text\n")
            r = sh([sys.executable, "scripts/leak_check.py", "--tree"], d, ok=False)
            assert r.returncode == 1 and "forbidden" in r.stdout, (rel, r.stdout)
            shutil.rmtree(d)
        d = new_repo(base, "envex")
        put(d, ".env.example", "PORT=8372\n")
        assert sh([sys.executable, "scripts/leak_check.py", "--tree"], d, ok=False).returncode == 0
        print("ok  forbidden files refused; .env.example allowed")

        # 4. Private patterns: found, but the matched text is never printed.
        d = new_repo(base, "priv")
        put(d, "a.md", "written by %s today\ncontact %s\n" % (FAKE_NAME, FAKE_MAIL))
        r = sh([sys.executable, "scripts/leak_check.py", "--tree"], d, ok=False)
        assert r.returncode == 1 and "private pattern #1" in r.stdout and "private pattern #2" in r.stdout, r.stdout
        assert FAKE_NAME not in r.stdout and "jordan.fake" not in r.stdout, "a private match was printed:\n" + r.stdout
        print("ok  private patterns found and never echoed")

        # 5. Private rules from the environment (the CI secret) work with no file.
        d = new_repo(base, "env", private=False)
        put(d, "a.md", "by %s\n" % FAKE_NAME)
        assert sh([sys.executable, "scripts/leak_check.py", "--tree"], d, ok=False).returncode == 0
        r = sh([sys.executable, "scripts/leak_check.py", "--tree"], d, env={"LEAK_PRIVATE": PRIVATE}, ok=False)
        assert r.returncode == 1 and FAKE_NAME not in r.stdout, r.stdout
        print("ok  LEAK_PRIVATE from the environment works")

        # 6. skip: paths that leave the repo are not scanned.
        d = new_repo(base, "skip")
        put(d, "leaving/notes.md", "" + FAKE_HOME + " and %s\n" % FAKE_NAME)
        assert sh([sys.executable, "scripts/leak_check.py", "--tree"], d, ok=False).returncode == 0
        print("ok  skipped paths are not scanned")

        # 7. pre-commit hook: refuses a leak, allows a clean commit, only looks at ADDED lines.
        d = new_repo(base, "hook", hooks=True)
        put(d, "ok.md", "fine\n")
        commit(d, "clean")
        put(d, "bad.md", "see " + FAKE_HOME + "/x\n")
        r = commit(d, "leak", ok=False)
        assert r.returncode != 0 and "Mac home path" in r.stdout, r.stdout
        sh(["git", "reset", "-q"], d)
        (d / "bad.md").unlink()
        put(d, "bad2.md", "by %s\n" % FAKE_NAME)
        r = commit(d, "leak2", ok=False)
        assert r.returncode != 0 and "private pattern #1" in r.stdout and FAKE_NAME not in r.stdout.replace("bad2.md", ""), r.stdout
        sh(["git", "reset", "-q"], d)
        (d / "bad2.md").unlink()
        put(d, "ok2.md", "fine too\n")
        commit(d, "clean again")
        # a line already committed before the hook existed is not re-flagged when other lines change
        d2 = new_repo(base, "old", hooks=False)
        put(d2, "old.md", "legacy " + FAKE_HOME + "/x\n")
        commit(d2, "old")
        for h in ("pre-commit",):
            dst = d2 / ".git" / "hooks" / h
            shutil.copy(HOOKS / h, dst)
            dst.chmod(0o755)
        (d2 / "old.md").write_text("legacy " + FAKE_HOME + "/x\nnew clean line\n")
        sh(["git", "add", "old.md"], d2)
        r = commit(d2, "touch", ok=False)
        assert r.returncode == 0, "an old untouched line must not block a commit:\n" + r.stdout
        print("ok  pre-commit refuses new leaks, allows clean commits, ignores old untouched lines")

        # 8. --no-verify is the emergency exit.
        put(d, "bad3.md", "see " + FAKE_HOME + "/x\n")
        r = sh(["git", "commit", "-q", "--no-verify", "-m", "bypass"], d, ok=False)
        assert r.returncode == 0
        print("ok  --no-verify still bypasses (documented)")

        # 9. pre-push: a commit message with the private e-mail and a leak in an OLD commit are both caught.
        remote = Path(base) / "remote.git"
        sh(["git", "init", "-q", "--bare", str(remote)], base)
        src = new_repo(base, "pushsrc", hooks=False)
        put(src, "a.md", "fine\n")
        commit(src, "first")
        put(src, "b.md", "leak " + FAKE_HOME + "/y\n")
        commit(src, "second has a leak")
        put(src, "c.md", "fixed\n")
        commit(src, "contact " + FAKE_MAIL)
        sh(["git", "remote", "add", "origin", str(remote)], src)
        dst = src / ".git" / "hooks" / "pre-push"
        shutil.copy(HOOKS / "pre-push", dst)
        dst.chmod(0o755)
        branch = sh(["git", "rev-parse", "--abbrev-ref", "HEAD"], src).stdout.strip()
        r = sh(["git", "push", "-q", "origin", branch], src, ok=False)
        assert r.returncode != 0 and "Mac home path" in r.stdout and "commit " in r.stdout, r.stdout
        assert "jordan.fake" not in r.stdout, "e-mail echoed:\n" + r.stdout
        # a clean history pushes, then only the new range is scanned
        clean = new_repo(base, "pushclean", hooks=False)
        put(clean, "a.md", "fine\n")
        commit(clean, "first")
        sh(["git", "remote", "add", "origin", str(remote)], clean)
        shutil.copy(HOOKS / "pre-push", clean / ".git" / "hooks" / "pre-push")
        (clean / ".git" / "hooks" / "pre-push").chmod(0o755)
        b2 = sh(["git", "rev-parse", "--abbrev-ref", "HEAD"], clean).stdout.strip()
        r = sh(["git", "push", "-q", "origin", b2 + ":cleanbranch"], clean, ok=False)
        assert r.returncode == 0, r.stdout
        put(clean, "b.md", "leak " + FAKE_HOME + "/z\n")
        commit(clean, "second")
        r = sh(["git", "push", "-q", "origin", b2 + ":cleanbranch"], clean, ok=False)
        assert r.returncode != 0 and "Mac home path" in r.stdout, r.stdout
        print("ok  pre-push scans every unpushed commit, messages too, and never echoes private matches")

        # 10. --range checks added lines and messages (the CI pull request mode).
        base_sha = sh(["git", "rev-parse", "HEAD~1"], src).stdout.strip()
        r = sh([sys.executable, "scripts/leak_check.py", "--range", base_sha + "..HEAD"], src, ok=False)
        assert r.returncode == 1 and "private pattern" in r.stdout, r.stdout
        print("ok  --range checks added lines and commit messages")

        # 11. The hooks and the installer are real files with the right mode.
        for h in ("pre-commit", "pre-push", "install.sh"):
            assert os.access(HOOKS / h, os.X_OK), h
        print("ok  hook scripts are executable")
        print("\ncheck_leak_check: all passed")
    finally:
        shutil.rmtree(base, ignore_errors=True)


if __name__ == "__main__":
    main()
