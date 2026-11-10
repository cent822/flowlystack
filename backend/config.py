"""Settings. Optional overrides live in flowlystack.config.json at the repo root."""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLAUDE_HOME = Path.home() / ".claude"
PROJECTS_DIR = CLAUDE_HOME / "projects"
SESSIONS_DIR = CLAUDE_HOME / "sessions"   # one json per live process
CODEX_HOME = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
DB_PATH = Path(os.environ.get("FLOWLYSTACK_DB") or ROOT / "data" / "flowlystack.db")   # like the two caches below: a throwaway instance sets its own
OLLAMA_DB_PATH = Path(os.environ.get("FLOWLYSTACK_OLLAMA_DB") or ROOT / "data" / "ollama.db")
CODEX_DB_PATH = Path(os.environ.get("FLOWLYSTACK_CODEX_DB") or ROOT / "data" / "codex.db")
# Settings saved from the Settings page, and the API keys typed there (test folder via FLOWLYSTACK_SETTINGS_DIR). Both gitignored.
SETTINGS_DIR = Path(os.environ.get("FLOWLYSTACK_SETTINGS_DIR") or ROOT / "data")
FRONTEND_DIR = ROOT / "frontend"

DEFAULTS = {
    # Context window per model prefix. A session that ever exceeds 200k is treated as 1M.
    "context_windows": {"default": 200_000, "1m": 1_000_000},
    # Anthropic does not expose plan limits on disk, so caps are estimates.
    # null = use your own historical peak window as 100%.
    "limits": {"session_tokens": None},
    "session_window_hours": 5,
    "poll_seconds": 2,
    # Where the hook saves your prompts (relative paths resolve against the repo root).
    # The FLOWLYSTACK_PROMPTS_DIR environment variable wins over this (use it in Docker).
    "prompts": {"dir": "prompts"},
    # Trashed prompts are deleted for good after this many days (0 = never empty the trash automatically).
    "trash": {"days": 30},
    # Meilisearch for the Prompt Library. url null = plain substring search. The key is the master key.
    # FLOWLYSTACK_MEILI_URL / FLOWLYSTACK_MEILI_KEY win over this (use them in Docker).
    "search": {"url": None, "key": None},
    # Agents the Dashboard can show (claude, codex). null = every agent whose folder exists.
    # FLOWLYSTACK_SOURCES (comma list) wins over this (use it in Docker).
    "sources": None,
    # Ollama has no usage history of its own; the Dashboard reads the chat database of Open WebUI (the folder that
    # holds webui.db). null = the Ollama source is not offered. FLOWLYSTACK_WEBUI_DIR wins over this (use it in Docker).
    "ollama": {"webui_dir": None},
}


def load() -> dict:
    cfg = json.loads(json.dumps(DEFAULTS))
    f = ROOT / "flowlystack.config.json"
    if f.exists():
        user = json.loads(f.read_text())
        for k, v in user.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k].update(v)
            else:
                cfg[k] = v
    return cfg


CONFIG = load()
CONFIG["search"]["url"] = os.environ.get("FLOWLYSTACK_MEILI_URL") or CONFIG["search"]["url"]
CONFIG["search"]["key"] = os.environ.get("FLOWLYSTACK_MEILI_KEY") or CONFIG["search"]["key"]
# The 5-hour cap for the usage gauge. The environment variable wins, so it can be set from .env in Docker, where flowlystack.config.json is not mounted.
_cap = (os.environ.get("FLOWLYSTACK_SESSION_TOKENS") or "").strip().replace(",", "").replace("_", "")
if _cap.isdigit() and int(_cap) > 0:
    CONFIG["limits"]["session_tokens"] = int(_cap)


def _prompts_dir() -> Path:
    p = Path(os.environ.get("FLOWLYSTACK_PROMPTS_DIR") or CONFIG["prompts"]["dir"] or "prompts").expanduser()
    return p if p.is_absolute() else ROOT / p


PROMPTS_DIR = _prompts_dir()


def _webui_dir():
    p = os.environ.get("FLOWLYSTACK_WEBUI_DIR") or CONFIG["ollama"]["webui_dir"]
    return Path(p).expanduser() if p else None


WEBUI_DIR = _webui_dir()
