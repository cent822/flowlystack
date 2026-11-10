#!/usr/bin/env python3
"""Checks which agents the Dashboard offers (backend/sources/__init__.py: enabled, detected, listing). No server, temp folders only.
    .venv/bin/python scripts/check_sources.py
The rule under test: FLOWLYSTACK_SOURCES (the installer writes `claude,codex`) names the agents the user chose, but Open WebUI is offered
as soon as its real webui.db is found, even when that list does not name it. Only a real file counts, so a placeholder folder never
makes an empty Ollama view appear."""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from backend import sources  # noqa: E402

orig_home = sources.SOURCES["ollama"]["home"]
orig_env = os.environ.get("FLOWLYSTACK_SOURCES")
tmp = Path(tempfile.mkdtemp(prefix="flowlystack-sources-check-"))
with_db = tmp / "with-db"
with_db.mkdir()
(with_db / "webui.db").write_bytes(b"x")
placeholder = tmp / "placeholder"      # what the compose file mounts when no Open WebUI folder is set
placeholder.mkdir()


def offered(listed, ollama_home, claude_codex_detected=True):
    """The Dashboard's list with FLOWLYSTACK_SOURCES=listed (None = unset) and Open WebUI's folder at ollama_home."""
    if listed is None:
        os.environ.pop("FLOWLYSTACK_SOURCES", None)
    else:
        os.environ["FLOWLYSTACK_SOURCES"] = listed
    sources.SOURCES["ollama"]["home"] = ollama_home
    return sources.enabled()


try:
    # The installer's own line, no Open WebUI folder: exactly what it names.
    assert offered("claude,codex", None) == ["claude", "codex"]
    # A placeholder folder (no webui.db) must not make Ollama appear.
    assert offered("claude,codex", placeholder) == ["claude", "codex"]
    assert not sources.detected("ollama")
    # The real file is found: offered although the list does not name it (the bug this check was written for).
    assert offered("claude,codex", with_db) == ["claude", "codex", "ollama"], offered("claude,codex", with_db)
    assert offered("claude", with_db) == ["claude", "ollama"]
    # Named already: once only, in the order the user wrote.
    assert offered("claude,ollama,codex", with_db) == ["claude", "ollama", "codex"]
    # No list at all: every detected agent, Ollama included, never twice.
    on = offered(None, with_db)
    assert on.count("ollama") == 1 and on[0] == "claude", on
    # Claude always leads, whatever the list says.
    assert offered("ollama", with_db)[0] == "claude" and "ollama" in offered("ollama", with_db)
    # The listing shows it as detected and enabled, and the other two unchanged.
    os.environ["FLOWLYSTACK_SOURCES"] = "claude,codex"
    sources.SOURCES["ollama"]["home"] = with_db
    row = {s["id"]: s for s in sources.listing()}
    assert row["ollama"]["detected"] and row["ollama"]["enabled"], row["ollama"]
    assert row["claude"]["enabled"] and row["codex"]["enabled"]
    sources.SOURCES["ollama"]["home"] = placeholder
    row = {s["id"]: s for s in sources.listing()}
    assert not row["ollama"]["detected"] and not row["ollama"]["enabled"], row["ollama"]
    print("ok  Open WebUI is offered when its webui.db is found, even with an explicit list; a placeholder folder never offers it")
    print("\ncheck_sources: all passed")
finally:
    sources.SOURCES["ollama"]["home"] = orig_home
    if orig_env is None:
        os.environ.pop("FLOWLYSTACK_SOURCES", None)
    else:
        os.environ["FLOWLYSTACK_SOURCES"] = orig_env
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)
