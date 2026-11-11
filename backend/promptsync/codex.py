"""Codex prompts: the typed-prompt events in ~/.codex rollout files (read-only).

Older Codex writes `user_message` events, current Codex writes `UserMessage` items (see promptstore.codex_typed_text);
other user-role messages in the files are injected context.
The VS Code extension wraps a prompt in an "IDE context" block: only the text after its request marker is kept.
Each prompt is keyed by session and byte position in the file, never by its text, so a prompt sent twice stays twice.
"""
import json
from datetime import datetime

from .. import promptstore
from ..config import CODEX_HOME

DUP_SECONDS = 120   # the hook saves a prompt at submit time, the rollout line follows a moment later


def _ts(s):
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except (AttributeError, ValueError):
        return None


def _hook_saved(root) -> dict:
    """Prompts the Codex hook saved (source "hook"), by text, so the same prompt is not saved a second time by the poll.
    Only hook-saved ones count: two identical prompts in the rollout itself are real repeats."""
    out: dict[str, list[float]] = {}
    for o in promptstore.load_all(root):
        if o["agent"] == "codex" and o.get("source") == "hook":
            out.setdefault(o["prompt"], []).append(o.get("ts") or 0)
    return out


def _rollouts():
    yield from sorted((CODEX_HOME / "sessions").glob("*/*/*/rollout-*.jsonl"))
    yield from sorted((CODEX_HOME / "archived_sessions").glob("rollout-*.jsonl"))


def pull(st, root) -> int:
    n = 0
    hooked = None   # loaded only when there is something new to save
    for path in _rollouts():
        key, size = str(path), path.stat().st_size
        off = st["files"].get(key, 0)
        if off > size:   # file was rewritten
            off = 0
        if off == size:
            continue
        sid = path.stem[-36:]   # rollout-<timestamp>-<uuid>
        with open(path, "rb") as f:
            f.seek(off)
            while True:
                pos = off
                line = f.readline()
                if not line or not line.endswith(b"\n"):   # end, or a partial write: retry next time
                    break
                off += len(line)
                try:
                    o = json.loads(line)
                except ValueError:
                    continue
                pl = o.get("payload") or {}
                if o.get("type") in ("session_meta", "turn_context") and pl.get("cwd"):
                    st["cwd"][sid] = pl["cwd"]
                elif (typed := promptstore.codex_typed_text(o)) is not None:
                    k = f"{sid}:{pos}"
                    text, ts = promptstore.clean_codex_prompt(typed), _ts(o.get("timestamp"))
                    if k in st["seen"] or not text or ts is None:
                        continue
                    if hooked is None:
                        hooked = _hook_saved(root)
                    if any(abs(ts - t) < DUP_SECONDS for t in hooked.get(text, [])):
                        st["seen"].add(k)   # the hook already has it
                        continue
                    promptstore.write_prompt(text, ts, sid, st["cwd"].get(sid, ""), source="sync", root=root,
                                             extra={"agent": "codex"})
                    st["seen"].add(k)
                    n += 1
        st["files"][key] = off
    return n
