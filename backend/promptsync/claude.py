"""Claude Code prompts: live sync from the transcripts in ~/.claude/projects (read-only), so no hook is needed.

The parsing and the duplicate rules are in `promptstore.import_transcripts`, which the Import button uses too.
"""
from .. import promptstore
from ..config import PROJECTS_DIR

SETTLE = 10   # seconds a new prompt waits before live sync saves it, so the capture hook (slower through Docker) wins


def pull(st, root) -> int:
    return promptstore.import_transcripts(PROJECTS_DIR, root, state=st, tail=True, settle=SETTLE)["imported"]


def import_all(st, root) -> dict:
    """The Import button: read every transcript in full."""
    return promptstore.import_transcripts(PROJECTS_DIR, root, state=st)
