"""The one Indexer of the running app, built from the settings on first use, plus the way routes wake its background loop. The settings
are read on every call (a change on the Settings page applies at once). Paths: the vector folder and `embeddings.db` live in the data
folder (`data/`, or FLOWLYSTACK_SETTINGS_DIR in tests); documents live under the prompts folder, in `collections/`.
"""
from __future__ import annotations

import json
import threading

from .. import settings
from ..assistant import registry
from ..config import CONFIG, SETTINGS_DIR
from ..promptstore import PROMPTS_DIR, STUDIO_DIR
from .indexer import Indexer
from .keyword import KeywordIndex

_lock = threading.Lock()
_indexer: Indexer | None = None
kicked = threading.Event()   # set by a route that changed something; the loop in main.py wakes up and looks


_flag = {"v": None}   # cached answer of prompts_enabled()


def _flag_file():
    return SETTINGS_DIR / "index-prompts.json"


def prompts_enabled() -> bool:
    """Does the Library and Studio get vectors? On by default (like documents, it still needs a model and the auto-index switch); the user can
    stop it with "Turn off auto-indexing" and start it again with "Turn on auto-indexing". The choice is kept in the data folder, not in Settings."""
    if _flag["v"] is None:
        try:
            _flag["v"] = bool(json.loads(_flag_file().read_text()).get("enabled"))
        except (OSError, ValueError, AttributeError):
            _flag["v"] = True
    return _flag["v"]


def set_prompts_enabled(on: bool) -> None:
    _flag["v"] = bool(on)
    SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _flag_file().with_name(f"index-prompts.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps({"enabled": bool(on)}))
    tmp.replace(_flag_file())


def trim_vectors() -> bool:
    """At server start: drop the old versions of an existing vector index (see `lance.trim`). Never raises."""
    try:
        from .lance import trim
        return trim(SETTINGS_DIR / "vectors")
    except Exception as e:
        print(f"flowlystack: could not trim the vector index: {e}")
        return False


def provider():
    return registry.get("ollama")


def get() -> Indexer:
    global _indexer
    with _lock:
        if _indexer is None:
            holder: dict = {}
            kw = KeywordIndex(CONFIG["search"].get("url"), CONFIG["search"].get("key"), scan=lambda: holder["ix"].iter_passages())
            holder["ix"] = _indexer = Indexer(
                data_dir=SETTINGS_DIR, collections_root=PROMPTS_DIR / "collections", library_dir=PROMPTS_DIR, studio_dir=STUDIO_DIR,
                provider=provider, model=lambda: settings.get("knowledge.embedding_model"), auto=lambda: settings.get("knowledge.auto_index"), keyword=kw,
                prompts=prompts_enabled)
        return _indexer


def kick() -> None:
    kicked.set()
