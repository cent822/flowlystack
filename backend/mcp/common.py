"""Small helpers the tool modules share."""
from __future__ import annotations

from datetime import datetime

TEXT_MAX = 100_000        # characters of one prompt or block returned by a `get` tool; longer text is cut and `truncated` says so
EXCERPT = 300
LIMIT = {"type": "integer", "minimum": 1, "maximum": 100, "description": "How many items to return (default 20, at most 100)."}
TAGS = {"type": "array", "maxItems": 20, "items": {"type": "string", "maxLength": 40}, "description": "Only items that carry every one of these tags."}


def iso(ts) -> str:
    """A timestamp (epoch seconds) as a local ISO time; '' for none."""
    try:
        return datetime.fromtimestamp(float(ts)).astimezone().isoformat(timespec="seconds") if ts else ""
    except (TypeError, ValueError, OverflowError, OSError):
        return ""


def clip(text: str, limit: int = TEXT_MAX) -> tuple:
    text = text or ""
    return (text[:limit], True) if len(text) > limit else (text, False)


def excerpt(text: str, n: int = EXCERPT) -> str:
    one = " ".join((text or "").split())
    return one[:n] + ("…" if len(one) > n else "")


def canon_names(tags, known) -> list:
    """Match each tag an agent typed to the spelling in `known` (an iterable of tag names), ignoring case: "Docker" finds "docker". A tag nobody carries is
    passed through unchanged, so it finds nothing. The app's own filters stay exact (the Library API must not change); this only fixes the words before they reach them."""
    if not tags:
        return tags
    exact = set(known)
    lower: dict = {}
    for t in exact:
        lower.setdefault(t.lower(), t)
    return [t if t in exact else lower.get(t.strip().lower(), t) for t in tags]


def canon_tags(tags, *stores) -> list:
    """`canon_names` over the tags of loaded prompts (`stores` are lists from promptstore.load_all)."""
    if not tags:
        return tags
    return canon_names(tags, (t for items in stores for o in items for t in o["meta"]["tags"]))


def limit_of(args: dict, default: int = 20) -> int:
    return int(args.get("limit", default))
