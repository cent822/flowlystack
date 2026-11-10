"""OpenAI-compatible servers (LM Studio, llama.cpp, vLLM, Jan, LocalAI, or any endpoint the user types): GET {url}/models and
POST {url}/chat/completions. Standard library only.

The address is used as typed; only `/models` and `/chat/completions` are appended. A key, when set, goes in the
Authorization header to that address only: redirects are never followed (urllib would forward the key to the new host).
Chat only in this build: `embed` says so.
"""
from __future__ import annotations

import json
import socket
from typing import Iterator
from urllib import error, request

from .base import ProviderError


class _NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


_OPENER = request.build_opener(_NoRedirect)


def _error_text(raw: bytes) -> str | None:
    """The server's own explanation: {"error": {"message": ...}}, {"error": "..."} or {"detail": "..."}."""
    try:
        o = json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        return None
    if not isinstance(o, dict):
        return None
    e = o.get("error")
    if isinstance(e, dict):
        e = e.get("message")
    d = o.get("detail")
    msg = e if isinstance(e, str) and e else d if isinstance(d, str) and d else None
    return msg[:300] if msg else None


class OpenAICompatProvider:
    def __init__(self, id: str, name: str, url: str, key: str = "", timeout: float = 120.0):
        self.id, self.name, self.url, self.key = id, name or "the server", url.rstrip("/"), key
        self.timeout = timeout   # per socket read: the first answer waits while the runtime loads the model

    def _open(self, path: str, body: dict | None = None, timeout: float | None = None):
        headers = {"content-type": "application/json", "accept": "application/json" if body is None else "text/event-stream"}
        if self.key:
            headers["authorization"] = "Bearer " + self.key
        req = request.Request(self.url + path, method="POST" if body is not None else "GET",
                              data=json.dumps(body).encode() if body is not None else None, headers=headers)
        try:
            return _OPENER.open(req, timeout=timeout or self.timeout)
        except error.HTTPError as e:
            raw = e.read() if e.fp else b""
            if e.code in (301, 302, 303, 307, 308):
                raise ProviderError(f"{self.name} redirected the request to another address; set its final address in Settings") from None
            if e.code in (401, 403):
                raise ProviderError(f"{self.name} refused the key (or needs one)") from None
            raise ProviderError(f"{self.name}: {_error_text(raw) or 'answered ' + str(e.code)}") from None
        except (error.URLError, socket.timeout, ConnectionError, OSError) as e:
            raise ProviderError(f"Cannot reach {self.name} at {self.url} ({getattr(e, 'reason', e)})") from None

    def status(self) -> dict:
        try:
            self.models()
            return {"reachable": True, "version": "", "error": ""}
        except ProviderError as e:
            return {"reachable": False, "version": "", "error": str(e)}

    def models(self) -> list[str]:
        with self._open("/models", timeout=5) as r:
            try:
                data = json.load(r).get("data")
            except (ValueError, AttributeError):
                raise ProviderError(f"{self.name} sent an answer that could not be read (is the address the one that ends in /v1?)") from None
        if not isinstance(data, list):
            raise ProviderError(f"{self.name} sent an answer that could not be read (is the address the one that ends in /v1?)")
        return [m["id"] for m in data if isinstance(m, dict) and isinstance(m.get("id"), str) and m["id"]]

    def stream(self, messages: list[dict], options: dict) -> Iterator[str]:
        """Yield the answer piece by piece. Closing the generator closes the connection, which stops the model."""
        body = {"model": options["model"], "messages": messages, "stream": True}
        if "temperature" in options:
            body["temperature"] = options["temperature"]   # num_ctx is an Ollama option and is not sent
        resp = self._open("/chat/completions", body)
        try:
            for raw in resp:
                line = raw.strip()
                if not line.startswith(b"data:"):
                    continue
                payload = line[5:].strip()
                if payload == b"[DONE]":
                    return
                try:
                    o = json.loads(payload)
                except ValueError:
                    raise ProviderError(f"{self.name} sent an answer that could not be read") from None
                if isinstance(o, dict) and o.get("error"):
                    e = o["error"]
                    raise ProviderError(f"{self.name}: {(e.get('message') if isinstance(e, dict) else str(e)) or 'error'}")
                choices = o.get("choices") if isinstance(o, dict) else None
                piece = ((choices[0] or {}).get("delta") or {}).get("content") if choices else None
                if isinstance(piece, str) and piece:
                    yield piece
        except (socket.timeout, ConnectionError, OSError) as e:
            raise ProviderError(f"The connection to {self.name} was lost ({e})") from None
        finally:
            resp.close()

    def embed(self, model: str, texts: list[str]) -> list[list[float]]:
        raise ProviderError(f"{self.name} is not used for embeddings yet")
