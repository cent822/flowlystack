#!/usr/bin/env python3
"""Checks docker/merge_hooks.py (add and remove the capture hook in a hooks JSON file) and, when the app's dependencies are
importable (run with .venv/bin/python), the hook command the setup endpoint prints in and out of Docker. No server, no real files."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "docker" / "merge_hooks.py"
sys.path.insert(0, str(ROOT / "docker"))
import merge_hooks as mh  # noqa: E402

CMD = "docker exec -i flowlystack-app /usr/local/bin/entrypoint.sh python hooks/capture_prompt.py >/dev/null 2>&1 || true"
OTHER = {"hooks": [{"type": "command", "command": "echo other"}]}


def run(path, action, command=CMD):
    r = subprocess.run([sys.executable, str(SCRIPT), action, str(path), command], capture_output=True, text=True)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


with tempfile.TemporaryDirectory() as d:
    f = Path(d) / "settings.json"

    # no file yet: created with just the hook
    assert run(f, "add") == (0, "added", "")
    assert json.loads(f.read_text()) == {"hooks": {"UserPromptSubmit": [{"hooks": [{"type": "command", "command": CMD}]}]}}
    # again: nothing changes
    before = f.read_text()
    assert run(f, "add") == (0, "already", "") and f.read_text() == before
    # remove brings the file back to {} (the keys the add created are pruned)
    assert run(f, "remove") == (0, "removed", "") and json.loads(f.read_text()) == {}
    assert run(f, "remove")[1] == "absent"

    # other keys and other hooks are kept, order too, and a 4-space file stays 4-space
    orig = json.dumps({"model": "x", "permissions": {"allow": ["Bash(ls)"]}, "hooks": {"UserPromptSubmit": [OTHER], "Stop": [OTHER]}}, indent=4) + "\n"
    f.write_text(orig)
    assert run(f, "add")[1] == "added"
    new = f.read_text()
    data = json.loads(new)
    assert list(data) == ["model", "permissions", "hooks"] and data["hooks"]["Stop"] == [OTHER]
    assert data["hooks"]["UserPromptSubmit"][0] == OTHER and len(data["hooks"]["UserPromptSubmit"]) == 2
    assert new.startswith('{\n    "model"') and new.endswith("\n")
    # remove restores the original text exactly
    assert run(f, "remove")[1] == "removed" and f.read_text() == orig

    # a different command (another install) is left alone by remove
    f.write_text(orig)
    run(f, "add")
    assert run(f, "remove", "docker exec -i other python x")[1] == "absent"
    assert json.loads(f.read_text())["hooks"]["UserPromptSubmit"][1]["hooks"][0]["command"] == CMD

    # a hook that shares an entry with another command: only ours is removed
    shared = {"hooks": {"UserPromptSubmit": [{"hooks": [{"type": "command", "command": "echo other"}, {"type": "command", "command": CMD}]}]}}
    f.write_text(json.dumps(shared, indent=2))
    assert run(f, "remove")[1] == "removed"
    assert json.loads(f.read_text())["hooks"]["UserPromptSubmit"] == [{"hooks": [{"type": "command", "command": "echo other"}]}]

    # a compact one-line file stays one line (with or without spaces), and remove restores it exactly
    for compact in ('{"model":"x","hooks":{"Stop":[]}}\n', '{"model": "x", "hooks": {"Stop": []}}'):
        f.write_text(compact)
        assert run(f, "add")[1] == "added" and "\n" not in f.read_text().strip()
        assert run(f, "remove")[1] == "removed" and f.read_text() == compact, (compact, f.read_text())

    # a file saved with a byte-order mark (Windows editors do this) is read, and written back without it
    f.write_bytes(b"\xef\xbb\xbf" + b'{\n  "model": "x"\n}\n')
    assert run(f, "add")[1] == "added" and not f.read_bytes().startswith(b"\xef\xbb\xbf") and json.loads(f.read_text())["model"] == "x"

    # refusals leave the file untouched
    for bad in ("{not json", "[]", '{"hooks": []}', '{"hooks": {"UserPromptSubmit": {}}}'):
        f.write_text(bad)
        rc, out, err = run(f, "add")
        assert rc == 2 and out == "" and err.startswith("refused") and f.read_text() == bad, (bad, rc, out, err)
    assert subprocess.run([sys.executable, str(SCRIPT)], capture_output=True).returncode == 64

# the hook command the app prints (needs the app's dependencies)
if sys.version_info >= (3, 10):
    try:
        sys.path.insert(0, str(ROOT))
        from backend.main import _hook_command
    except Exception as e:   # not the venv python
        print(f"(skipped the setup-command check: {type(e).__name__})")
    else:
        keep = {k: os.environ.pop(k, None) for k in ("FLOWLYSTACK_IN_DOCKER", "FLOWLYSTACK_CONTAINER")}
        try:
            assert _hook_command("capture_prompt.py") == f"python3 {ROOT / 'hooks' / 'capture_prompt.py'}"
            os.environ["FLOWLYSTACK_IN_DOCKER"] = "1"
            assert _hook_command("capture_prompt.py") == CMD
            assert _hook_command("capture_codex_prompt.py").startswith("docker exec -i flowlystack-app /usr/local/bin/entrypoint.sh python hooks/capture_codex_prompt.py")
            os.environ["FLOWLYSTACK_CONTAINER"] = "fs-two"
            assert _hook_command("capture_prompt.py").startswith("docker exec -i fs-two /usr/local/bin/entrypoint.sh python hooks/")
        finally:
            for k, v in keep.items():
                os.environ.pop(k, None)
                if v is not None:
                    os.environ[k] = v

print("all merge-hooks checks passed")
