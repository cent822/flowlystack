"""What every model provider has in common. Standard library only.

A provider exposes four things: `status()`, `models()`, `stream(messages, options)` and `embed(model, texts)`. A failure the user can act on
(server down, model missing, the model reported an error) is a `ProviderError` with a plain message for the panel.
"""
from __future__ import annotations

from typing import Iterator, Protocol
from urllib.parse import urlparse


class ProviderError(Exception):
    """A readable problem talking to a model. `str(e)` is shown to the user as is."""


class Provider(Protocol):
    id: str
    url: str

    def status(self) -> dict: ...                 # {"reachable": bool, "version": str, "error": str}
    def models(self) -> list[str]: ...            # model names; raises ProviderError when unreachable
    def stream(self, messages: list[dict], options: dict) -> Iterator[str]: ...   # text pieces; raises ProviderError
    def embed(self, model: str, texts: list[str]) -> list[list[float]]: ...       # one vector per text, same order; raises ProviderError


def is_local(url: str) -> bool:
    """True when the URL points at this computer (the panel labels anything else Remote)."""
    host = (urlparse(url).hostname or "").lower()
    return host in ("localhost", "127.0.0.1", "::1", "host.docker.internal") or host.endswith(".localhost")   # host.docker.internal: the computer that runs Docker, i.e. this one
