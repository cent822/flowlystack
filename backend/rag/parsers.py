"""Read an imported file into passages. Markdown, text, PDF, JSON and JSONL.

`parse(kind, data)` returns {"passages": [{"n", "text", "locator"}], "units": int, "warnings": [str]} or raises `ParseError`,
whose message says why in plain words (it is shown next to the file). Only this module imports `pypdf`, and only for a PDF.
"""
from __future__ import annotations

import io
import json
import re

from . import chunking

KINDS = {".md": "markdown", ".markdown": "markdown", ".txt": "text", ".text": "text", ".pdf": "pdf",
         ".json": "json", ".jsonl": "jsonl", ".ndjson": "jsonl"}


class ParseError(Exception):
    """The file cannot be read. `str(e)` is the reason shown to the user."""


def kind_of(name: str) -> str | None:
    dot = name.rfind(".")
    return KINDS.get(name[dot:].lower()) if dot != -1 else None


def _decode(data: bytes) -> str:
    if b"\x00" in data[:8192]:
        raise ParseError("This looks like a binary file, not text")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ParseError("The file is not UTF-8 text") from None


def _number(data: list[tuple[str, str]]) -> list[dict]:
    return [{"n": i, "text": t, "locator": loc} for i, (loc, t) in enumerate(data)]


# ---------------------------------------------------------------- Markdown and text
_HEADING = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t#]*$")
_FENCE = re.compile(r"^\s*(```|~~~)")


def _sections(text: str) -> list[tuple[str, str]]:
    """(heading path, text) per heading. Lines inside a fenced block are never headings. Text before the first heading is "Beginning"."""
    secs, stack, cur, fence = [], [], [], None
    loc = "Beginning"

    def close():
        body = "\n".join(cur).strip()
        if body:
            secs.append((loc, body))

    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        f = _FENCE.match(line)
        if f and fence is None:
            fence = f.group(1)
        elif f and f.group(1) == fence:
            fence = None
        h = _HEADING.match(line) if fence is None else None
        if h:
            close()
            level = len(h.group(1))
            stack = [s for s in stack if s[0] < level] + [(level, h.group(2).strip())]
            loc, cur = " › ".join(s[1] for s in stack), [line]
        else:
            cur.append(line)
    close()
    return secs


def _markdown(data: bytes) -> dict:
    secs = _sections(_decode(data))
    if not secs:
        raise ParseError("The file has no text")
    pieces = [(loc, piece) for loc, body in secs for piece in chunking.split_text(body)]
    return {"passages": _number(chunking.merge_small(pieces)), "units": len(secs), "warnings": []}


def _text(data: bytes) -> dict:
    text = _decode(data)
    if not text.strip():
        raise ParseError("The file has no text")
    pieces = [("", p) for p in chunking.split_text(text)]
    return {"passages": _number(pieces), "units": 1, "warnings": []}


# ---------------------------------------------------------------- JSON and JSONL
def _scalar(v) -> str:
    return "null" if v is None else ("true" if v is True else "false" if v is False else str(v))


def _flat(v, prefix=""):
    if isinstance(v, dict):
        for k, x in v.items():
            yield from _flat(x, f"{prefix}.{k}" if prefix else str(k))
    elif isinstance(v, list):
        if all(not isinstance(x, (dict, list)) for x in v):
            yield prefix, ", ".join(_scalar(x) for x in v)
        else:
            for i, x in enumerate(v):
                yield from _flat(x, f"{prefix}[{i}]")
    else:
        yield prefix, _scalar(v)


def _record_text(rec) -> str:
    return "\n".join(f"{k}: {v}" if k else v for k, v in _flat(rec))


def _records(recs: list, label: str = "record") -> list[tuple[str, str]]:
    out = []
    for i, rec in enumerate(recs, 1):
        text = _record_text(rec).strip()
        if not text:
            continue
        for part in chunking.split_long(text) if len(text) > chunking.MAX else [text]:
            out.append((f"{label} {i}", part))
    return out


def _json(data: bytes) -> dict:
    text = _decode(data)
    try:
        obj = json.loads(text)
    except ValueError as e:
        raise ParseError(f"The file is not valid JSON ({e})") from None
    if isinstance(obj, list):
        pieces = _records(obj)
        if not pieces:
            raise ParseError("The file has no records")
        return {"passages": _number(pieces), "units": len(obj), "warnings": []}
    pretty = json.dumps(obj, ensure_ascii=False, indent=2)
    return {"passages": _number([("JSON", p) for p in chunking.split_text(pretty)]), "units": 1, "warnings": []}


def _jsonl(data: bytes) -> dict:
    recs, bad = [], []
    for n, line in enumerate(_decode(data).splitlines(), 1):
        if not line.strip():
            continue
        try:
            recs.append((n, json.loads(line)))
        except ValueError:
            bad.append(n)
    if not recs:
        raise ParseError(f"No line is valid JSON (line {bad[0]} is the first)" if bad else "The file has no records")
    pieces = []
    for n, rec in recs:
        pieces += [(f"line {n}", p) for _, p in _records([rec])]
    if not pieces:
        raise ParseError("The file has no records")
    warn = [f"{len(bad)} line{'s' if len(bad) != 1 else ''} not valid JSON and skipped (first: line {bad[0]})"] if bad else []
    return {"passages": _number(pieces), "units": len(recs), "warnings": warn}


# ---------------------------------------------------------------- PDF
def _pages_join(a: str, b: str) -> str:
    first, last = re.findall(r"\d+", a), re.findall(r"\d+", b)
    return f"p. {first[0]}–{last[-1]}" if first and last and first[0] != last[-1] else a


def _pdf(data: bytes) -> dict:
    from pypdf import PdfReader
    from pypdf.errors import PyPdfError

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            raise ParseError("The PDF is password protected")
        pages = list(reader.pages)
    except ParseError:
        raise
    except (PyPdfError, ValueError, OSError, KeyError, TypeError, AttributeError, NotImplementedError) as e:
        raise ParseError(f"The PDF could not be read ({e or type(e).__name__})") from None
    pieces, warn = [], []
    for i, page in enumerate(pages, 1):
        try:
            body = (page.extract_text() or "").strip()
        except Exception as e:   # one damaged page must not lose the rest of the file
            warn.append(f"page {i} could not be read ({e or type(e).__name__})")
            continue
        pieces += [(f"p. {i}", p) for p in chunking.split_text(body)]
    if not pieces:
        raise ParseError("The PDF has no text to read (a scanned PDF needs OCR, which is not supported)")
    return {"passages": _number(chunking.merge_small(pieces, _pages_join)), "units": len(pages), "warnings": warn}


_PARSERS = {"markdown": _markdown, "text": _text, "json": _json, "jsonl": _jsonl, "pdf": _pdf}


def parse(kind: str, data: bytes) -> dict:
    if kind not in _PARSERS:
        raise ParseError("This file type is not supported (Markdown, text, PDF, JSON and JSONL are)")
    if not data:
        raise ParseError("The file is empty")
    return _PARSERS[kind](data)
