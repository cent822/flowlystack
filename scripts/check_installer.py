#!/usr/bin/env python3
"""Checks install.sh with a fake HOME and a stub `docker` (a small Python script put first on PATH). Nothing real is touched: not
~/.claude, not ~/.codex, not Docker. Standard library only. Needs bash and curl (file:// URLs fetch the compose file from this repo)."""
import json
import os
import re
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "install.sh"
MERGE = ROOT / "docker" / "merge_hooks.py"

STUB = f'''#!{sys.executable}
import os, subprocess, sys
a = sys.argv[1:]
state = os.environ["STUB_STATE"]
open(os.path.join(state, "log"), "a").write(" ".join(a) + "\\n")
flag = os.path.join(state, "running")
if a[:2] == ["compose", "version"]:
    sys.exit(1 if os.environ.get("STUB_NO_COMPOSE") else 0)
if a[:1] == ["info"]:
    sys.exit(1 if os.environ.get("STUB_DOWN") else 0)
if a[:1] == ["compose"]:
    if "up" in a:
        open(flag, "w").write("1")
    sys.exit(0)
if a[:1] == ["inspect"]:
    if not os.path.exists(flag):
        sys.exit(1)
    t = a[2] if a[1] == "-f" else ""
    print("stub-image" if "Config.Image" in t else "true" if "State.Running" in t else "healthy")
    sys.exit(0)
if a[:1] == ["run"]:
    work = a[a.index("-v") + 1].split(":/w")[0]
    rest = a[a.index("stub-image") + 1:]
    rest[0] = {str(MERGE)!r}
    rest = [x.replace("/w/", work + "/") for x in rest]
    sys.exit(subprocess.call([sys.executable] + rest))
sys.exit(0)
'''


def sh(args, home, extra_env=None, stub=True, path_extra=None):
    env = {"HOME": str(home), "PATH": "/usr/bin:/bin", "LANG": "C"}
    if stub:
        env["PATH"] = f"{home}/../stubbin:{env['PATH']}"
        env["STUB_STATE"] = str(Path(home).parent / "stubstate")
    env.update(extra_env or {})
    r = subprocess.run(["/bin/bash", str(SCRIPT)] + args, env=env, capture_output=True, text=True, cwd=str(home), timeout=60)
    return r.returncode, r.stdout + r.stderr


def free_port():
    k = socket.socket()
    k.bind(("127.0.0.1", 0))
    n = k.getsockname()[1]
    k.close()
    return str(n)


def tree(p):
    return sorted(str(x.relative_to(p)) for x in Path(p).rglob("*"))


with tempfile.TemporaryDirectory() as base:
    base = Path(base)
    (base / "stubbin").mkdir()
    (base / "stubstate").mkdir()
    dk = base / "stubbin" / "docker"
    dk.write_text(STUB)
    dk.chmod(dk.stat().st_mode | stat.S_IEXEC)
    RAW = f"file://{ROOT}"

    def fresh(name, claude=False, codex=False):
        h = base / name / "home"
        h.mkdir(parents=True)
        # the stub is found through <home>/../stubbin, so mirror it next to each home
        (h.parent / "stubbin").mkdir()
        shutil.copy(dk, h.parent / "stubbin" / "docker")
        (h.parent / "stubstate").mkdir()
        if claude:
            (h / ".claude" / "projects").mkdir(parents=True)
        if codex:
            (h / ".codex" / "sessions").mkdir(parents=True)
            (h / ".codex" / "archived_sessions").mkdir(parents=True)
        return h

    env0 = {"FLOWLYSTACK_RAW_BASE": RAW, "FLOWLYSTACK_NO_PULL": "0"}

    # ---- options and refusals ----
    h = fresh("opts")
    rc, out = sh(["--bogus"], h)
    assert rc == 1 and "unknown option" in out, out
    rc, out = sh(["--port", "abc"], h)
    assert rc == 1 and "--port must be a number" in out, out
    rc, out = sh(["--setup-capture", "--undo-capture"], h)
    assert rc == 1 and "not both" in out, out
    rc, out = sh(["--help"], h)
    assert rc == 0 and "--dry-run" in out and "--setup-capture" in out
    assert tree(h) == [], "options must not write anything"

    # ---- --dir must be a folder of its own; the container name must be safe ----
    h = fresh("guards")
    for bad in (str(h), "/", ".", "~"):
        rc, out = sh(["--dir", bad], h, env0)
        assert rc == 1 and "folder of its own" in out, (bad, out)
    for bad in ("bad name;x", "-lead", "a/b", "x$(id)"):
        rc, out = sh(["--dir", str(h / "fs")], h, {**env0, "FLOWLYSTACK_CONTAINER": bad})
        assert rc == 1 and "not valid" in out, (bad, out)
    assert tree(h) == [], "a refused run wrote something"

    # ---- docker missing / compose missing / daemon down: clear message, exit 1, nothing written ----
    h = fresh("nodocker")
    if shutil.which("docker", path="/usr/bin:/bin") is None:
        rc, out = sh(["--dir", str(h / "fs")], h, stub=False)
        assert rc == 1 and "Docker is not installed" in out, out
        assert tree(h) == [], tree(h)
    rc, out = sh(["--dir", str(h / "fs")], h, {"STUB_NO_COMPOSE": "1"})
    assert rc == 1 and "compose plugin is missing" in out and tree(h) == []
    rc, out = sh(["--dir", str(h / "fs")], h, {"STUB_DOWN": "1"})
    assert rc == 1 and "not answering" in out and tree(h) == []

    # ---- dry run: says what it would do, writes nothing, starts nothing ----
    h = fresh("dry", claude=True, codex=True)
    before = tree(h)
    rc, out = sh(["--dry-run", "--port", "8899"], h, env0)
    assert rc == 0 and "Would write" in out and "FLOWLYSTACK_PORT=8899" in out and "docker-compose.yml" in out, out
    assert tree(h) == before, "dry run wrote something"
    assert not (base / "dry" / "stubstate" / "log").exists() or "up" not in (base / "dry" / "stubstate" / "log").read_text().split(), "dry run started something"

    # ---- a full install with both agents found ----
    h = fresh("full", claude=True, codex=True)
    d = h / "flowlystack"
    P = free_port()
    rc, out = sh(["--port", P], h, {**env0, "CODEX_HOME": str(h / ".codex")})
    assert rc == 0, out
    env = (d / ".env").read_text()
    assert f"FLOWLYSTACK_PORT={P}" in env and "FLOWLYSTACK_SOURCES=claude,codex" in env, env
    assert f"CLAUDE_PROJECTS_DIR={h}/.claude/projects" in env
    assert f"CODEX_SESSIONS_DIR={h}/.codex/sessions" in env and f"CODEX_ARCHIVED_DIR={h}/.codex/archived_sessions" in env
    assert "FLOWLYSTACK_IMAGE=ghcr.io/cent822/flowlystack:latest" in env and re.search(r"^TZ=\S+", env, re.M)
    compose = (d / "docker-compose.yml").read_text()
    assert "build: ." not in compose and "container_name:" in compose and "meilisearch" in compose
    assert (d / "prompts").is_dir() and (d / "empty").is_dir()
    log = (base / "full" / "stubstate" / "log").read_text()
    assert " pull" in log and " up -d" in log and "--project-directory" in log, log
    assert "Claude Code: found. Codex: found." in out and f"http://127.0.0.1:{P}" in out and "/hooks" in out and "hooks.json" in out
    assert "capture_codex_prompt.py" in out
    # a copy of the installer is saved in the install folder and the hints point at it (a curl | bash user has no local file)
    assert (d / "install.sh").read_bytes() == SCRIPT.read_bytes() and f'bash "{d}/install.sh" --setup-capture' in out, out
    # nothing outside the install folder was created in the fake home
    assert [t for t in tree(h) if not t.startswith(("flowlystack", ".claude", ".codex"))] == [], tree(h)
    assert (h / ".codex" / "hooks.json").exists() is False and (h / ".claude" / "settings.json").exists() is False

    # ---- second run: .env, prompts and compose are kept; no .previous when nothing changed ----
    (d / ".env").write_text(env + "# my own line\nFLOWLYSTACK_PORT=9000\n")
    (d / "prompts" / "mine.md").write_text("keep me")
    rc, out = sh(["--port", "8000"], h, {**env0, "CODEX_HOME": str(h / ".codex")})
    assert rc == 0 and "Kept your existing" in out and "http://127.0.0.1:9000" in out, out
    assert "--port 8000 is ignored because your .env already sets FLOWLYSTACK_PORT=9000" in out, out
    assert "# my own line" in (d / ".env").read_text() and (d / "prompts" / "mine.md").read_text() == "keep me"
    assert not (d / "docker-compose.yml.previous").exists()
    # a changed compose file is replaced and the old one saved
    (d / "docker-compose.yml").write_text("# edited by hand\n")
    rc, out = sh([], h, env0)
    assert rc == 0 and (d / "docker-compose.yml.previous").read_text() == "# edited by hand\n" and "build: ." not in (d / "docker-compose.yml").read_text()

    # --version that disagrees with the kept .env: a note, and .env is not touched
    keep_env = (d / ".env").read_text()
    rc, out = sh(["--version", "0.2.0"], h, env0)
    assert rc == 0 and "Your .env uses the image" in out and (d / ".env").read_text() == keep_env, out
    rc, out = sh([], h, env0)
    assert rc == 0 and "Your .env uses the image" not in out

    # ---- no agents at all: starts anyway, says so, creates no agent folders ----
    h = fresh("none")
    rc, out = sh(["--port", free_port()], h, env0)
    assert rc == 0 and "Claude Code: not found. Codex: not found." in out and "Dashboard starts empty" in out, out
    env = (h / "flowlystack" / ".env").read_text()
    assert "FLOWLYSTACK_SOURCES=claude\n" in env and "CLAUDE_PROJECTS_DIR" not in env and "CODEX_SESSIONS_DIR" not in env
    assert not (h / ".claude").exists() and not (h / ".codex").exists()
    assert "hooks.json" not in out

    # ---- port in use (and the app not running): refuses BEFORE writing anything, so a second run with another port just works ----
    h = fresh("port")
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(50)
    used = s.getsockname()[1]
    rc, out = sh(["--port", str(used)], h, env0)
    assert rc == 1 and "already in use" in out and "Nothing was written" in out and "--port" in out, out
    assert not (h / "flowlystack").exists(), "a busy port must leave no files behind"
    assert " up " not in " " + (base / "port" / "stubstate" / "log").read_text().replace("\n", " ") + " "
    rc, out = sh(["--dry-run", "--port", str(used)], h, env0)   # a dry run only warns
    assert rc == 0 and "already in use" in out and not (h / "flowlystack").exists(), out
    p2 = free_port()
    rc, out = sh(["--port", p2], h, env0)   # the second run, as the skill tells an agent to do
    assert rc == 0 and f"FLOWLYSTACK_PORT={p2}" in (h / "flowlystack" / ".env").read_text(), out
    # an existing .env that names a busy port: the message says where to change it
    (h / "flowlystack" / ".env").write_text(f"FLOWLYSTACK_PORT={used}\n")
    (base / "port" / "stubstate" / "running").unlink()
    rc, out = sh(["--port", p2], h, env0)
    s.close()
    assert rc == 1 and "set in your" in out and "Change FLOWLYSTACK_PORT" in out, out

    # ---- no-start writes the files only ----
    h = fresh("nostart")
    rc, out = sh(["--no-start"], h, env0)
    assert rc == 0 and (h / "flowlystack" / ".env").exists()
    assert not (base / "nostart" / "stubstate" / "running").exists()

    # ---- an unreachable compose file is a clear error and leaves no half file ----
    h = fresh("badurl")
    rc, out = sh(["--port", free_port()], h, {"FLOWLYSTACK_RAW_BASE": "file:///nonexistent"})
    assert rc == 1 and "could not download" in out, out
    assert not (h / "flowlystack" / "docker-compose.yml").exists() and not list((h / "flowlystack").glob("*.new*")) and not list((h / "flowlystack").glob("*.part"))

    # ---- capture hook (opt-in): show, ask, back up, merge; undo removes only ours ----
    h = fresh("cap", claude=True)
    rc, out = sh(["--port", free_port()], h, env0)
    assert rc == 0 and (base / "cap" / "stubstate" / "running").exists()
    settings = h / ".claude" / "settings.json"
    original = json.dumps({"model": "x", "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo bye"}]}]}}, indent=2) + "\n"
    settings.write_text(original)
    tty_yes, tty_no = base / "tty_yes", base / "tty_no"
    tty_yes.write_text("yes\n")
    tty_no.write_text("nope\n")
    tmpc = base / "tmpc"
    tmpc.mkdir()
    cap = {**env0, "CLAUDE_SETTINGS": str(settings), "TMPDIR": str(tmpc)}

    rc, out = sh(["--setup-capture", "--dry-run"], h, {**cap, "FLOWLYSTACK_TTY": str(tty_yes)})
    assert rc == 0 and "Would add the capture hook" in out and settings.read_text() == original

    rc, out = sh(["--setup-capture"], h, {**cap, "FLOWLYSTACK_TTY": str(tty_no)})
    assert rc == 0 and "Cancelled" in out and "+" in out and settings.read_text() == original and not list(h.glob(".claude/*backup*"))

    rc, out = sh(["--setup-capture"], h, {**cap, "FLOWLYSTACK_TTY": "/nonexistent/tty"})
    assert "No terminal" in out and settings.read_text() == original and not list(h.glob(".claude/*backup*"))

    rc, out = sh(["--setup-capture"], h, {**cap, "FLOWLYSTACK_TTY": str(tty_yes)})
    assert rc == 0 and "Backup saved" in out, out
    backups = list(h.glob(".claude/settings.json.flowlystack-backup-*"))
    assert len(backups) == 1 and backups[0].read_text() == original
    data = json.loads(settings.read_text())
    cmd = "docker exec -i flowlystack-app /usr/local/bin/entrypoint.sh python hooks/capture_prompt.py >/dev/null 2>&1 || true"
    assert data["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"] == cmd and data["hooks"]["Stop"] and data["model"] == "x"
    assert not list(h.glob(".claude/*flowlystack-tmp"))

    rc, out = sh(["--setup-capture"], h, {**cap, "FLOWLYSTACK_TTY": str(tty_yes)})   # again: nothing to do, no second backup
    assert rc == 0 and "already in" in out and len(list(h.glob(".claude/settings.json.flowlystack-backup-*"))) == 1

    # the user edits the file afterwards; undo keeps that edit and removes only our hook
    edited = json.loads(settings.read_text())
    edited["model"] = "changed-later"
    settings.write_text(json.dumps(edited, indent=2) + "\n")
    rc, out = sh(["--undo-capture"], h, {**cap, "FLOWLYSTACK_TTY": str(tty_yes)})
    assert rc == 0 and "removed" in out, out
    after = json.loads(settings.read_text())
    assert "UserPromptSubmit" not in after["hooks"] and after["model"] == "changed-later" and after["hooks"]["Stop"]

    rc, out = sh(["--undo-capture"], h, {**cap, "FLOWLYSTACK_TTY": str(tty_yes)})
    assert rc == 0 and "not in" in out

    # --yes skips the question; a missing settings file is created; invalid JSON is refused and left alone
    settings.unlink()
    rc, out = sh(["--setup-capture", "--yes"], h, {**cap, "FLOWLYSTACK_TTY": "/nonexistent/tty"})
    assert rc == 0 and "does not exist yet" in out and json.loads(settings.read_text())["hooks"]["UserPromptSubmit"]
    settings.write_text("{not json")
    rc, out = sh(["--setup-capture", "--yes"], h, cap)
    assert rc == 1 and "valid JSON" in out and settings.read_text() == "{not json"

    assert os.listdir(tmpc) == [], f"temporary copies of the settings file were left behind: {os.listdir(tmpc)}"

    # Ctrl-C while it waits for the typed yes: the temporary copy is removed, nothing changes, exit code 130
    h = fresh("intr", claude=True)
    rc, out = sh(["--port", free_port()], h, env0)
    assert rc == 0, out
    settings = h / ".claude" / "settings.json"
    settings.write_text(original)
    tmpi = base / "tmpi"
    tmpi.mkdir()
    fifo = base / "fifo"
    os.mkfifo(fifo)
    fd = os.open(fifo, os.O_RDWR)   # keeps the pipe open both ways, so the installer's read waits instead of ending
    env = {"HOME": str(h), "PATH": f"{h}/../stubbin:/usr/bin:/bin", "STUB_STATE": str(base / "intr" / "stubstate"), "TMPDIR": str(tmpi),
           "CLAUDE_SETTINGS": str(settings), "FLOWLYSTACK_TTY": str(fifo), **env0}
    pr = subprocess.Popen(["/bin/bash", str(SCRIPT), "--setup-capture"], env=env, cwd=str(h), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    import time
    for _ in range(100):
        if os.listdir(tmpi):
            break
        time.sleep(0.2)
    if not os.listdir(tmpi):
        pr.kill()
        o, e = pr.communicate()
        raise AssertionError(f"the temporary copy never appeared: rc={pr.returncode}\n{o}\n{e}")
    time.sleep(0.5)
    pr.send_signal(2)
    pr.communicate(timeout=20)
    os.close(fd)
    assert pr.returncode == 130, pr.returncode
    assert os.listdir(tmpi) == [] and settings.read_text() == original and not list(h.glob(".claude/*backup*")) and not list(h.glob(".claude/*flowlystack-tmp"))

    # a custom container name in .env is the one the hook uses
    h = fresh("cname", claude=True)
    rc, out = sh(["--port", free_port()], h, {**env0, "FLOWLYSTACK_CONTAINER": "fs-two"})
    assert "FLOWLYSTACK_CONTAINER=fs-two" in (h / "flowlystack" / ".env").read_text()
    s2 = h / ".claude" / "settings.json"
    rc, out = sh(["--setup-capture", "--yes"], h, {**env0, "CLAUDE_SETTINGS": str(s2)})
    assert rc == 0 and "docker exec -i fs-two /usr/local/bin/entrypoint.sh" in s2.read_text(), out

# ---- the script itself: no sudo, only expected deletions ----
code = [l for l in SCRIPT.read_text().splitlines() if l.strip() and not l.strip().startswith("#")]
assert not [l for l in code if re.search(r"(^|[;&|(]\s*|\bdo\s+|\bthen\s+)sudo\s", l.strip())], "the installer must never run sudo"
rms = [l.strip() for l in code if re.search(r"(?<![-\w])rm\s", l)]
allowed = ('rm -f "$tmp"', 'rm -rf "$WORK_DIR"')
assert all(any(a in l for a in allowed) for l in rms), [l for l in rms if not any(a in l for a in allowed)]
assert "docker volume" not in "\n".join(code) and "docker rm" not in "\n".join(code) and "docker system" not in "\n".join(code)
assert subprocess.run(["/bin/bash", "-n", str(SCRIPT)]).returncode == 0

print("all installer checks passed")
