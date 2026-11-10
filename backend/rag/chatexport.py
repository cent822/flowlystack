"""The Markdown and JSON export of a collection conversation. Pure, stdlib only.

Same shape and fencing rules as `assistant/pairs.py` (every text is a fenced block longer than any backtick run inside it, the only split
points are the `<!-- pair ... -->` comments), with a Sources block per pair listing what the search found and which passages were sent.
"""
from __future__ import annotations

import json
from datetime import datetime

from ..assistant.pairs import _block, _iso, _tok

FORMAT = "flowlystack-collection-chat"
SCHEMA = 1


def _sources(e: dict) -> str:
    if not e.get("searched"):
        return "not searched"
    sent = set(e.get("included") or [])
    lines = []
    for p in e.get("retrieved") or []:
        mark = f"[{p['cite']}]" if p.get("cite") else "[-]"
        where = f" · {p['locator']}" if p.get("locator") else ""
        lines.append(f"{mark} {p.get('name', '')}{where} · score {round(float(p.get('score') or 0) * 100)} · {'sent' if p.get('id') in sent else 'not sent'} · {p.get('id', '')}")
    return "\n".join(lines) or "nothing found"


def export_markdown(collection_id: str, collection_name: str, chat: dict, now: float | None = None) -> str:
    pairs = chat.get("exchanges") or []
    out = ["---", f"format: {FORMAT}", f"schema_version: {SCHEMA}", f"collection: {collection_id}", f"collection_name: {json.dumps(collection_name, ensure_ascii=False)}",
           f"chat: {chat.get('id', '')}", f"title: {json.dumps(chat.get('title', ''), ensure_ascii=False)}",
           f"scope: {json.dumps(chat.get('scope') or [], ensure_ascii=False)}",
           f"exported: {_iso(now if now is not None else datetime.now().timestamp())}", f"pairs: {len(pairs)}", "---", ""]
    for n, e in enumerate(pairs, 1):
        model, params = e.get("model") or {}, e.get("params") or {}
        attrs = [("id", e.get("id", "")), ("ts", _iso(e.get("ts") or 0)), ("model", f"{model.get('provider', '')}/{model.get('name', '')}"), *params.items(),
                 ("searched", str(bool(e.get("searched"))).lower()), ("mode", e.get("mode") or "none"), ("partial", str(bool(e.get("partial"))).lower())]
        out += [f"<!-- pair {' '.join(f'{k}={_tok(v)}' for k, v in attrs)} -->", "", f"## Pair {n}", "",
                _block("System", e.get("system", "")), _block("Context", e.get("context", "")), _block("Prompt", e.get("prompt", "")),
                _block("Response", e.get("response", "")), _block("Sources", _sources(e))]
        if (e.get("proposal") or {}).get("text"):
            out.append(_block(f"Proposed edit ({e['proposal'].get('status', 'open')})", e["proposal"]["text"]))
        out += ["<!-- /pair -->", ""]
    return "\n".join(out)


def export_json(collection_id: str, collection_name: str, chat: dict, now: float | None = None) -> dict:
    """The stored conversation, unchanged, with the export header."""
    return {"format": FORMAT, "schema_version": SCHEMA, "collection": collection_id, "collection_name": collection_name,
            "exported": _iso(now if now is not None else datetime.now().timestamp()), "chat": chat}
