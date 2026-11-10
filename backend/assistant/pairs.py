"""The Markdown export of a conversation: the dataset view. Pure, stdlib only.

Fixed and machine-readable. Every text block is a fenced code block whose fence is longer than any run of backticks
inside it, so headings, fences or marker lookalikes in a model's answer cannot break the structure. The only split
points are the `<!-- pair ... -->` and `<!-- /pair -->` comments, found outside fences. Stored data stays JSON; this is
only ever built from it.
"""
from __future__ import annotations

import json
import re
from datetime import datetime

FORMAT = "flowlystack-pairs"
SCHEMA = 1


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts).astimezone().isoformat(timespec="seconds")


def _tok(v) -> str:
    """A value in a pair comment: bare when safe, JSON-quoted when it holds spaces, quotes or the end of a comment."""
    s = str(v)
    return json.dumps(s, ensure_ascii=False) if not s or re.search(r'[\s"\\]|--', s) else s


def _block(heading: str, text: str) -> str:
    longest = max((len(m) for m in re.findall(r"`+", text)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"### {heading}\n{fence}text\n{text}\n{fence}\n"


def export_markdown(prompt_id: str, title: str, exchanges: list[dict], only_kept: bool = False, now: float | None = None) -> str:
    """The conversation as one Markdown document. `only_kept` leaves out every pair whose curation `keep` is not true."""
    pairs = [e for e in exchanges if not only_kept or (e.get("curation") or {}).get("keep") is True]
    out = ["---", f"format: {FORMAT}", f"schema_version: {SCHEMA}", f"source_prompt: {prompt_id}", f"title: {json.dumps(title, ensure_ascii=False)}",
           f"exported: {_iso(now if now is not None else datetime.now().timestamp())}", f"pairs: {len(pairs)}", "---", ""]
    for n, e in enumerate(pairs, 1):
        model, params, cur = e.get("model") or {}, e.get("params") or {}, e.get("curation") or {}
        attrs = [("id", e["id"]), ("ts", _iso(e.get("ts") or 0)), ("kind", e.get("kind") or "chat"),
                 ("model", f"{model.get('provider', '')}/{model.get('name', '')}"),
                 *params.items(), ("partial", str(bool(e.get("partial"))).lower()),
                 ("keep", {True: "true", False: "false"}.get(cur.get("keep"), "none"))]
        out += [f"<!-- pair {' '.join(f'{k}={_tok(v)}' for k, v in attrs)} -->", "", f"## Pair {n}", "",
                _block("System", e.get("system", "")), _block("Context", e.get("context", "")),
                _block("Prompt", e.get("prompt", "")), _block("Response", e.get("response", ""))]
        if e.get("proposal"):
            out.append(_block(f"Proposed edit ({e['proposal'].get('status', 'open')})", e["proposal"].get("text", "")))
        out += ["### Curation", f"- keep: {attrs[-1][1]}", f"- note: {json.dumps(cur.get('note') or '', ensure_ascii=False)}", "", "<!-- /pair -->", ""]
    return "\n".join(out)


def export_json(prompt_id: str, title: str, exchanges: list[dict], only_kept: bool = False, now: float | None = None) -> dict:
    """The same pairs as plain JSON (the stored exchanges, unchanged), for people who would rather not parse Markdown."""
    pairs = [e for e in exchanges if not only_kept or (e.get("curation") or {}).get("keep") is True]
    return {"format": FORMAT, "schema_version": SCHEMA, "source_prompt": prompt_id, "title": title,
            "exported": _iso(now if now is not None else datetime.now().timestamp()), "pairs": pairs}
