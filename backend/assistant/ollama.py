"""Ollama's native API: GET /api/version, GET /api/tags, POST /api/chat (one JSON object per line),
POST /api/embed."""
from __future__ import annotations

import json
import socket
from typing import Iterator
from urllib import error, request

from .base import ProviderError

DEFAULT_URL = "http://127.0.0.1:11434"


class OllamaProvider:
    id = "ollama"

    def __init__(self, url: str = DEFAULT_URL, timeout: float = 120.0):
        self.url = (url or DEFAULT_URL).rstrip("/")
        self.timeout = timeout   # per socket read: the first answer waits while Ollama loads the model

    def _open(self, path: str, body: dict | None = None, timeout: float | None = None):
        req = request.Request(self.url + path, method="POST" if body is not None else "GET",
                              data=json.dumps(body).encode() if body is not None else None,
                              headers={"content-type": "application/json"})
        try:
            return request.urlopen(req, timeout=timeout or self.timeout)
        except error.HTTPError as e:   # Ollama explains itself in the body: {"error": "model 'x' not found"}
            try:
                msg = json.loads(e.read().decode("utf-8", "replace")).get("error")
            except (ValueError, AttributeError, OSError):
                msg = None
            raise ProviderError(msg or f"Ollama answered {e.code}") from None
        except (error.URLError, socket.timeout, ConnectionError, OSError) as e:
            raise ProviderError(f"Cannot reach Ollama at {self.url} ({getattr(e, 'reason', e)})") from None

    def status(self) -> dict:
        try:
            with self._open("/api/version", timeout=3) as r:
                return {"reachable": True, "version": str(json.load(r).get("version", "")), "error": ""}
        except (ProviderError, ValueError) as e:
            return {"reachable": False, "version": "", "error": str(e)}

    def models(self) -> list[str]:
        try:
            with self._open("/api/tags", timeout=5) as r:
                return [m["name"] for m in json.load(r).get("models", []) if isinstance(m, dict) and m.get("name")]
        except ValueError:
            raise ProviderError("Ollama sent an answer that could not be read") from None

    def stream(self, messages: list[dict], options: dict) -> Iterator[str]:
        """Yield the answer piece by piece. Closing the generator closes the connection, which stops the model."""
        body = {"model": options["model"], "messages": messages, "stream": True,
                "options": {k: options[k] for k in ("temperature", "num_ctx") if k in options}}
        resp = self._open("/api/chat", body)
        try:
            for raw in resp:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    o = json.loads(raw)
                except ValueError:
                    raise ProviderError("Ollama sent an answer that could not be read") from None
                if o.get("error"):
                    raise ProviderError(str(o["error"]))
                piece = (o.get("message") or {}).get("content")
                if piece:
                    yield piece
                if o.get("done"):
                    return
        except (socket.timeout, ConnectionError, OSError) as e:
            raise ProviderError(f"The connection to Ollama was lost ({e})") from None
        finally:
            resp.close()

    def embed(self, model: str, texts: list[str]) -> list[list[float]]:
        """One vector per text, in the same order. Ollama cuts a text longer than the model's context instead of failing."""
        if not texts:
            return []
        with self._open("/api/embed", {"model": model, "input": texts}) as r:
            try:
                vecs = json.load(r).get("embeddings")
            except ValueError:
                raise ProviderError("Ollama sent an answer that could not be read") from None
        ok = (isinstance(vecs, list) and len(vecs) == len(texts)
              and all(isinstance(v, list) and v and all(isinstance(x, (int, float)) for x in v) for v in vecs))
        if not ok or len({len(v) for v in vecs}) != 1:
            raise ProviderError(f"{model} did not return one vector per text (is it an embedding model?)")
        return vecs
