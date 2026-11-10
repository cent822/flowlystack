"""How text is shown to an embedding model. Standard library only.

Some embedding models are trained to see a short task prefix in front of a passage and another in front of a question; without it
they still work but rank worse. The table maps a model name (before the ":" tag) to (question prefix, passage prefix). Models not in
the table get no prefix. The prefixes are part of the vectors, so changing the table means rebuilding the index; they are a
candidate for the recall check on real data.
"""
from __future__ import annotations

PREFIXES = {
    "nomic-embed-text": ("search_query: ", "search_document: "),
    "embeddinggemma": ("task: search result | query: ", "title: none | text: "),
}


def _family(model: str) -> str:
    name = (model or "").lower().split(":")[0]
    return next((k for k in PREFIXES if name == k or name.startswith(k + "-")), "")


def passage_text(model: str, text: str) -> str:
    return PREFIXES.get(_family(model), ("", ""))[1] + text


def question_text(model: str, text: str) -> str:
    return PREFIXES.get(_family(model), ("", ""))[0] + text
