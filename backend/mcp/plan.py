"""Turn a small plan an agent writes into a Linkshell project. Pure functions, standard library only.

The agent sends phases of prompts with keys and `after` lists; this module checks it, lays the blocks out like the canvas's own "Tidy up" would (one frame per
phase, frames stacked top to bottom; inside a phase the prompts are layered left to right by what they wait for, prompts that can run side by side are stacked
in one column, a prompt's Specs underneath it, the Brief at the left of the first phase) and returns the dict `linkshell.import_json` reads, so the project is
validated and written by the same code as an import and is always a NEW project.
"""
from __future__ import annotations

import re
import uuid

KEY = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
MAX_PHASES, MAX_PROMPTS, MAX_SPECS, MAX_BLOCKS, MAX_LINKS = 20, 60, 8, 80, 200
TOP_KEYS = ("name", "brief", "default_agent", "tags", "properties", "phases")
PHASE_KEYS = ("title", "prompts")
PROMPT_KEYS = ("key", "title", "text", "agent", "after", "specs")
SPEC_KEYS = ("title", "text")
# layout, in the canvas's own units (the sample projects use the same numbers)
X0, Y0, W, H, SPEC_H, GAP, PAD_TOP, PAD_BOTTOM, PAD_RIGHT, ROW_GAP = 30, 40, 190, 88, 70, 16, 40, 30, 30, 60
BRIEF_W, BRIEF_H, RANK_GAP, STACK_GAP = 160, 70, 80, 40   # the gaps Tidy up uses between columns and between blocks in a column
MAX_DRIFT = 2400   # a later phase is moved right of what it waits for, but not past this right edge (or the widest phase so far)
MARK = "via-mcp"


class PlanError(ValueError):
    """The plan is not usable; the message tells the agent what to change."""


def _str(v, where: str, lo: int, hi: int) -> str:
    if not isinstance(v, str):
        raise PlanError(f"{where} must be text.")
    v = v.strip()
    if not lo <= len(v) <= hi:
        raise PlanError(f"{where} must be {lo} to {hi} characters" if lo else f"{where} must be at most {hi} characters")
    return v


def _only(d, allowed: tuple, where: str) -> None:
    if not isinstance(d, dict):
        raise PlanError(f"{where} must be an object.")
    bad = [k for k in d if k not in allowed]
    if bad:
        raise PlanError(f"{where} has unknown field '{bad[0]}'. Allowed: {', '.join(allowed)}.")


def check(plan) -> dict:
    """The plan, cleaned. Raises PlanError."""
    _only(plan, TOP_KEYS, "The plan")
    name = _str(plan.get("name"), "name", 1, 120)
    brief = _str(plan.get("brief", ""), "brief", 0, 20_000)
    agent = _str(plan.get("default_agent", "claude"), "default_agent", 1, 40)
    tags = plan.get("tags", [])
    if not isinstance(tags, list) or len(tags) > 19 or not all(isinstance(t, str) and 0 < len(t.strip()) <= 40 for t in tags):
        raise PlanError("tags must be a list of up to 19 short texts.")
    props = plan.get("properties", {})
    if isinstance(props, dict):
        props = [{"key": k, "value": v} for k, v in props.items()]
    if not isinstance(props, list) or len(props) > 20 or not all(isinstance(p, dict) and isinstance(p.get("key"), str) and isinstance(p.get("value", ""), str) for p in props):
        raise PlanError("properties must be an object of text values (for example {\"owner\": \"Alice\"}).")
    phases = plan.get("phases")
    if not isinstance(phases, list) or not 1 <= len(phases) <= MAX_PHASES:
        raise PlanError(f"phases must be a list of 1 to {MAX_PHASES} phases.")
    keys, out_phases, n_prompts, n_specs = {}, [], 0, 0
    for i, ph in enumerate(phases, 1):
        _only(ph, PHASE_KEYS, f"Phase {i}")
        ptitle = _str(ph.get("title"), f"Phase {i} title", 1, 120)
        prompts = ph.get("prompts")
        if not isinstance(prompts, list) or not prompts:
            raise PlanError(f"Phase {i} ('{ptitle}') needs a list of prompts.")
        out = []
        for j, p in enumerate(prompts, 1):
            where = f"Prompt {j} of phase {i}"
            _only(p, PROMPT_KEYS, where)
            key = p.get("key")
            if not isinstance(key, str) or not KEY.match(key):
                raise PlanError(f"{where}: key must be 1 to 40 letters, digits, - or _ (it is how other prompts point at this one).")
            if key in keys:
                raise PlanError(f"The key '{key}' is used twice. Keys must be unique in the plan.")
            keys[key] = True
            specs = p.get("specs", [])
            if not isinstance(specs, list) or len(specs) > MAX_SPECS:
                raise PlanError(f"{where} ('{key}'): specs must be a list of at most {MAX_SPECS}.")
            clean_specs = []
            for k, s in enumerate(specs, 1):
                _only(s, SPEC_KEYS, f"Spec {k} of '{key}'")
                clean_specs.append({"title": _str(s.get("title"), f"Spec {k} of '{key}' title", 1, 200), "text": _str(s.get("text"), f"Spec {k} of '{key}' text", 1, 100_000)})
            after = p.get("after")
            if after is not None and (not isinstance(after, list) or not all(isinstance(a, str) for a in after)):
                raise PlanError(f"'{key}': after must be a list of prompt keys (an empty list means it only waits for the Brief).")
            out.append({"key": key, "title": _str(p.get("title"), f"'{key}' title", 1, 200), "text": _str(p.get("text"), f"'{key}' text", 1, 100_000),
                        "agent": _str(p.get("agent", ""), f"'{key}' agent", 0, 40), "after": after, "specs": clean_specs})
            n_prompts += 1
            n_specs += len(clean_specs)
        out_phases.append({"title": ptitle, "prompts": out})
    if n_prompts > MAX_PROMPTS or 1 + n_prompts + n_specs > MAX_BLOCKS:
        raise PlanError(f"The plan is too large: at most {MAX_PROMPTS} prompts and {MAX_BLOCKS} blocks in all (the Brief, prompts and specs together). Split it into several projects.")
    flat = [p for ph in out_phases for p in ph["prompts"]]
    for idx, p in enumerate(flat):
        if p["after"] is None:   # not given: it follows the previous prompt in the plan (the first follows the Brief)
            p["after"] = [flat[idx - 1]["key"]] if idx else []
        for a in p["after"]:
            if a not in keys:
                raise PlanError(f"'{p['key']}' waits for '{a}', which is not a key in the plan. Use the key of another prompt.")
            if a == p["key"]:
                raise PlanError(f"'{p['key']}' cannot wait for itself.")
    return {"name": name, "brief": brief, "agent": agent, "tags": list(dict.fromkeys([t.strip() for t in tags] + [MARK])), "properties": props, "phases": out_phases}


def _block(bid, typ, title, x, y, w, h, frame, **kw) -> dict:
    return {"id": bid, "type": typ, "title": title, "x": x, "y": y, "w": w, "h": h, "frame": frame, "agent": kw.get("agent", ""), "status": "todo", "status_at": 0, "note": "",
            "context_off": []}


def _phase_layout(prompts: list, first: bool) -> tuple:
    """Where the blocks of one phase go, relative to the frame's inner corner: ({key: (x, top)}, "_brief": y of the Brief, used width, used height).
    Columns: a prompt sits one column right of the latest prompt (of this phase) it waits for; one that waits for nothing here is in the first column
    (in the first phase the Brief is column 0, so every prompt starts at column 1). Prompts in the same column are stacked, ordered by the average row
    of what they wait for, and each is centred on its parents where it can. A prompt's Specs hang underneath it, so its cell is taller."""
    keys = {p["key"]: p for p in prompts}
    parents = {p["key"]: [a for a in p["after"] if a in keys] for p in prompts}
    rank, busy = {}, set()

    def rk(k):
        if k in rank:
            return rank[k]
        if k in busy:   # a loop inside the phase: the import refuses the plan later, just do not recurse for ever
            return 0
        busy.add(k)
        r = max((rk(a) + 1 for a in parents[k]), default=0)
        busy.discard(k)
        rank[k] = r
        return r

    for k in keys:
        rk(k)
    off = 1 if first else 0
    cols: dict = {}
    for p in prompts:
        cols.setdefault(rank[p["key"]] + off, []).append(p["key"])
    cell = lambda k: H + len(keys[k]["specs"]) * (SPEC_H + GAP)
    x_of, centre, top_of = {}, {}, {}
    x = 0
    if first:
        x_of["_brief"] = 0
        x = BRIEF_W + RANK_GAP
    row = {}
    for c in sorted(cols):
        order = sorted(cols[c], key=lambda k: (sum(row[a] for a in parents[k] if a in row) / max(1, sum(1 for a in parents[k] if a in row)) if any(a in row for a in parents[k]) else 1e9, list(keys).index(k)))
        bottom = None
        for n, k in enumerate(order):
            row[k] = n
            want = None
            ps = [centre[a] for a in parents[k] if a in centre]
            if ps:
                want = sum(ps) / len(ps) - H / 2
            elif first and c == 1:
                want = BRIEF_H / 2 - H / 2   # sits level with the Brief
            top = want if want is not None else (bottom + STACK_GAP if bottom is not None else 0)
            if bottom is not None:
                top = max(top, bottom + STACK_GAP)
            top_of[k], x_of[k], centre[k] = top, x, top + H / 2
            bottom = top + cell(k)
        x += W + RANK_GAP
    lo = min(top_of.values())
    brief_top = 0.0
    if first:   # the Brief is centred on the prompts that follow it directly
        kids = [centre[k] for k in keys if not parents[k]]
        brief_top = (sum(kids) / len(kids) - BRIEF_H / 2) if kids else 0.0
        lo = min(lo, brief_top)
    shift = -lo
    out = {k: (x_of[k], round(top_of[k] + shift)) for k in keys}
    out["_brief"] = round(brief_top + shift) if first else 0
    right = max(x_of[k] + W for k in keys)
    bottom = max(top_of[k] + shift + cell(k) for k in keys)
    if first:
        bottom = max(bottom, out["_brief"] + BRIEF_H)
    return out, right, round(bottom)


def build(plan) -> tuple:
    """(import dict for linkshell.import_json, stats). The Brief is left unticked, like a hand-made project: the user reads the plan, then ticks it."""
    c = check(plan)
    new = lambda prefix, n=8: prefix + uuid.uuid4().hex[:n]
    start_id = new("b-")
    frames, blocks, links, texts, ids = [], [], [], {start_id: c["brief"]}, {}
    placed, maxright = {}, 0   # key -> x of the prompt on the canvas; the right edge of the widest frame so far
    y, first = Y0, True
    for ph in c["phases"]:
        fid = new("f-", 6)
        pos, width, height = _phase_layout(ph["prompts"], first)
        # a prompt of a later phase that waits for earlier prompts starts under the leftmost of them, so the link runs down or right, never back to the left
        here = {p["key"] for p in ph["prompts"]}
        # the canvas draws a link from the right side of a block to the left side of the next, so the first prompt of a later phase that waits for earlier
        # prompts is put one column to the RIGHT of the rightmost of them: every link then flows forward (a block directly under its parent makes the link loop back)
        lead = next((p for p in ph["prompts"] if not first and not any(a in here for a in p["after"]) and any(a in placed for a in p["after"])), None)
        shift = 0
        if lead:
            shift = max(0, max(placed[a] for a in lead["after"] if a in placed) + W + RANK_GAP - (60 + pos[lead["key"]][0]))
        shift = min(shift, max(0, max(maxright, MAX_DRIFT) - (60 + width)))
        frames.append({"id": fid, "title": ph["title"], "x": X0 + shift, "y": y, "w": 60 + width + PAD_RIGHT - X0, "h": PAD_TOP + height + PAD_BOTTOM, "collapsed": False})
        if first:
            blocks.append(_block(start_id, "start", "Brief", 60, y + PAD_TOP + pos["_brief"], BRIEF_W, BRIEF_H, fid))
        for p in ph["prompts"]:
            x, top = pos[p["key"]]
            bid = ids[p["key"]] = new("b-")
            placed[p["key"]] = 60 + shift + x
            blocks.append(_block(bid, "prompt", p["title"], 60 + shift + x, y + PAD_TOP + top, W, H, fid, agent=p["agent"]))
            texts[bid] = p["text"]
            for k, s_ in enumerate(p["specs"]):
                sid = new("b-")
                blocks.append(_block(sid, "spec", s_["title"], 60 + shift + x, y + PAD_TOP + top + H + GAP + k * (SPEC_H + GAP), W, SPEC_H, fid))
                texts[sid] = s_["text"]
                links.append({"from": sid, "to": bid, "kind": "context"})
        maxright = max(maxright, 60 + shift + width)
        y += frames[-1]["h"] + ROW_GAP
        first = False
    for ph in c["phases"]:
        for p in ph["prompts"]:
            for a in (p["after"] or [None]):
                links.append({"from": ids[a] if a else start_id, "to": ids[p["key"]], "kind": "order"})
    if len(links) > MAX_LINKS:
        raise PlanError(f"The plan has {len(links)} links; at most {MAX_LINKS}. Remove some 'after' entries.")
    data = {"format": "flowlystack-linkshell", "version": 1, "project": {"name": c["name"], "default_agent": c["agent"], "properties": c["properties"], "tags": c["tags"], "star": False},
            "graph": {"blocks": blocks, "links": links, "frames": frames, "viewport": {"x": 0, "y": 0, "k": 1}},
            "blocks": {bid: {"text": t} for bid, t in texts.items()}, "assets": {}}
    return data, {"phases": len(c["phases"]), "prompts": len(ids), "specs": sum(len(p["specs"]) for ph in c["phases"] for p in ph["prompts"]), "links": len(links), "tags": c["tags"]}
