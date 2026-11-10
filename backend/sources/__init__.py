"""Agent sources for the Dashboard. Claude Code is the built-in one (backend/ingest.py + queries.py, untouched).

Every other source lives in its own module here and answers the same routes in the same JSON shapes. A route
that a source cannot feed returns na(reason), and the frontend draws the N/A state for that card.
"""
import importlib
import os

from ..config import CLAUDE_HOME, CODEX_HOME, CONFIG, WEBUI_DIR

DEFAULT = "claude"
SOURCES = {
    "claude": {"label": "Claude Code / Claude Desktop Code", "home": CLAUDE_HOME},
    "codex": {"label": "Codex", "home": CODEX_HOME},
    # Ollama keeps no history; its usage is read from Open WebUI's chat database (offered only when configured)
    "ollama": {"label": "Ollama (Open WebUI)", "home": WEBUI_DIR, "marker": "webui.db"},
}


def na(reason: str) -> dict:
    return {"na": True, "reason": reason}


def detected(sid: str) -> bool:
    s = SOURCES[sid]
    if s["home"] is None:
        return False
    return (s["home"] / s["marker"]).is_file() if s.get("marker") else s["home"].is_dir()


def enabled() -> list[str]:
    """FLOWLYSTACK_SOURCES (comma list) or config "sources"; otherwise every detected agent. Claude always leads.
    Open WebUI is the exception to an explicit list: the installer writes `claude,codex`, and the user who later sets the Open WebUI folder
    expects the Ollama view to appear. It is detected only when the real webui.db exists (a placeholder folder cannot trigger it), so it is
    added whenever it is found."""
    raw = os.environ.get("FLOWLYSTACK_SOURCES") or CONFIG.get("sources")
    if isinstance(raw, str):
        raw = [s.strip() for s in raw.split(",")]
    ids = [s for s in (raw or []) if s in SOURCES] or [s for s in SOURCES if detected(s)]
    if "ollama" not in ids and detected("ollama"):
        ids.append("ollama")
    return [DEFAULT] + [s for s in ids if s != DEFAULT]


def listing() -> list[dict]:
    on = enabled()
    return [{"id": sid, "label": s["label"], "detected": detected(sid), "enabled": sid in on} for sid, s in SOURCES.items()]


def adapter(sid: str):
    """The source's module, or None while it is not built yet."""
    try:
        return importlib.import_module(f"{__name__}.{sid}")
    except ModuleNotFoundError as e:
        if e.name == f"{__name__}.{sid}":
            return None
        raise
