"""Live prompt sync from other agents into the Prompt Library (Codex rollouts, Open WebUI chats).

Each agent has a read-only importer module with `pull(state, root) -> int` that saves new prompts through
`promptstore.write_prompt(..., extra={"agent": ...})`. Two controls per agent on the Capture setup card: Import (one
shot, always available, `run_once`) and the Live sync switch (the background task polls while it is on). A ledger under `<prompts dir>/.sources/<agent>.json` records
what was imported (and where each file was read to), so a prompt you trash or delete is never imported again.
The Claude capture hook and Claude import are not touched by any of this.
"""
import importlib
import json
import os
import threading

from .. import sources
from ..config import PROMPTS_DIR

# `source` is the id of the Dashboard source whose folder holds the data
AGENTS = {
    "codex": {"label": "Codex", "source": "codex", "interval": 3},
    "ollama": {"label": "Ollama (Open WebUI)", "source": "ollama", "interval": 10},
}
MODULES = {"codex": "codex", "ollama": "openwebui"}
errors: dict[str, str | None] = {}
_locks = {a: threading.Lock() for a in AGENTS}


def _path(agent):
    return PROMPTS_DIR / ".sources" / f"{agent}.json"


PARSER = {"codex": 2}   # raise an agent's number when its reader learns a new file format: files read with the old rules are read again


def _load(agent) -> dict:
    try:
        st = json.loads(_path(agent).read_text())
    except (OSError, ValueError):
        st = {}
    st.setdefault("enabled", False)
    st.setdefault("imported", 0)
    st["seen"] = set(st.get("seen") or [])
    for k in ("files", "cwd"):
        st.setdefault(k, {})
    if PARSER.get(agent) and st.get("parse") != PARSER[agent]:
        st["files"] = {}   # the reading rules changed: read every file again once (`seen` keeps what is already saved, so nothing doubles)
        st["parse"] = PARSER[agent]
    return st


def _save(agent, st):
    p = _path(agent)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps({**st, "seen": sorted(st["seen"])}))
    os.replace(tmp, p)


def available(agent) -> bool:
    """The agent is offered on this machine (enabled in the sources setting and its data folder exists)."""
    sid = AGENTS[agent]["source"]
    return sid in sources.enabled() and sources.detected(sid)


def is_enabled(agent) -> bool:
    return _load(agent)["enabled"]


def run(agent) -> int:
    """Import what is new for one agent. Returns how many prompts were saved; failures are recorded, not raised."""
    try:
        with _locks[agent]:
            st = _load(agent)
            n = importlib.import_module(f"{__name__}.{MODULES[agent]}").pull(st, PROMPTS_DIR)
            st["imported"] += n
            _save(agent, st)
        errors[agent] = None
        return n
    except Exception as e:
        errors[agent] = str(e)
        return 0


def run_once(agent) -> dict:
    """The Import button: pull everything new right now, whether or not live sync is on. Safe to press again and again."""
    with _locks[agent]:
        st = _load(agent)
        before = len(st["seen"])
        try:
            n = importlib.import_module(f"{__name__}.{MODULES[agent]}").pull(st, PROMPTS_DIR)
        except Exception as e:
            errors[agent] = str(e)
            raise
        st["imported"] += n
        _save(agent, st)
    errors[agent] = None
    return {"imported": n, "already": before}


def set_enabled(agent, on: bool) -> dict:
    """The Live sync switch: the background task polls while it is on (it imports whatever is not saved yet)."""
    with _locks[agent]:
        st = _load(agent)
        st["enabled"] = on
        _save(agent, st)
    return status()[agent]


def status() -> dict:
    out = {}
    for agent, a in AGENTS.items():
        st = _load(agent)
        out[agent] = {"label": a["label"], "available": available(agent), "enabled": st["enabled"],
                      "imported": st["imported"], "error": errors.get(agent)}
    return out
