"""Which providers are configured right now, built from the saved settings (read on every call, so a change in Settings
takes effect at once). Phase 2 of the product adds more entries here; the rest of the app only asks this module."""
from __future__ import annotations

from urllib.parse import urlparse

from .. import settings
from .base import is_local
from .ollama import OllamaProvider
from .openai_compat import OpenAICompatProvider

LABELS = {"ollama": "Ollama"}


def get(provider_id: str):
    """The provider object for an id, or None when that provider is unknown or not configured."""
    if provider_id == "ollama":
        return OllamaProvider(settings.get("connections.ollama.url"))
    r = settings.runtime(provider_id) if isinstance(provider_id, str) else None
    if r:
        return OpenAICompatProvider(r["id"], r["name"], r["url"], settings.get_secret(r["id"]))
    return None


def configured() -> list:
    """Ollama, then the saved connections in list order."""
    return [p for p in (get(i) for i in ["ollama", *(r["id"] for r in settings.runtimes())]) if p]


def describe(p) -> dict:
    return {"id": p.id, "label": getattr(p, "name", None) or LABELS.get(p.id, p.id), "kind": "local" if is_local(p.url) else "remote", "host": urlparse(p.url).netloc}


def chat_models(names: list[str]) -> list[str]:
    """Models worth offering in the picker. Embedding models cannot chat; they all say so in their name (a heuristic:
    a model that does not follow the convention is still offered, and a failed send explains itself)."""
    return [n for n in names if "embed" not in n.lower()]


def embedding_models(names: list[str], show_all: bool = False) -> list[str]:
    """Models worth offering as the embedding model: the ones with "embed" in the name (the same convention that
    keeps them out of the chat picker). `show_all` returns every installed model, for an embedding model that does
    not follow the convention (for example bge-m3); a model that cannot embed fails with a readable message."""
    return list(names) if show_all else [n for n in names if "embed" in n.lower()]
