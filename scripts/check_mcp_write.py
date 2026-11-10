#!/usr/bin/env python3
"""Checks for the MCP write tools, the plan builder, the activity log and Undo. Plain asserts, no server: it seeds temp folders and calls
the tools through the protocol layer, as an agent with a write token would. Needs the project's Python:

    .venv/bin/python scripts/check_mcp_write.py

Everything lives in a temp folder; your real prompts, settings and Linkshell projects are never touched.
"""
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="flowlystack-mcp-write-"))
os.environ.update(FLOWLYSTACK_PROMPTS_DIR=str(TMP / "prompts"), FLOWLYSTACK_SETTINGS_DIR=str(TMP / "settings"), FLOWLYSTACK_ALIAS_DIR=str(TMP / "alias"),
                  FLOWLYSTACK_MEILI_URL="http://127.0.0.1:1")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import linkshell as ls  # noqa: E402
from backend import promptstore as ps  # noqa: E402
from backend.mcp import activity, plan as planmod, server  # noqa: E402
from backend.rag import service  # noqa: E402

assert str(ps.PROMPTS_DIR).startswith(str(TMP))
READ = {"scope": "read", "name": "Claude Code", "id": "t-1"}
WRITE = {"scope": "write", "name": "Cursor", "id": "t-2"}
LOG = TMP / "settings" / "mcp_activity.json"


def step(msg):
    print("ok  ", msg)


def call(name, args=None, ctx=WRITE):
    st, b = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args or {}}}, {}, ctx)
    r = b["result"]
    text = r["content"][0]["text"]
    return (True, text) if r["isError"] else (False, json.loads(text))


def ok(name, args=None, ctx=WRITE):
    err, out = call(name, args, ctx)
    assert not err, (name, out)
    assert out["notice"] == server.NOTICE
    return out


def fails(name, args, needle, ctx=WRITE):
    err, out = call(name, args, ctx)
    assert err and needle.lower() in out.lower(), (name, str(args)[:120], out)


def tree_hash(root: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if p.is_file():
            h.update(str(p.relative_to(root)).encode())
            h.update(p.read_bytes())
    return h.hexdigest()


def prompt(title, text, deps=None, specs=None, agent=None, key=None):
    return {"key": key or title.lower().replace(" ", "-"), "title": title, "text": text, **({"after": deps} if deps is not None else {}), **({"specs": specs} if specs else {}),
            **({"agent": agent} if agent else {})}


try:
    # ---------- seed: Library, Studio and one pre-existing Linkshell project ----------
    lib1 = ps.write_prompt("Please review this pull request for security problems and list each finding", 1_700_000_000, "s1", "/work/p", extra={"agent": "claude"})
    lib_files_before = tree_hash(ps.PROMPTS_DIR / "2023-11")
    old = ls.create("My own project", brief="Hand made, must never change.")
    ls.save_text(old["project"]["id"], old["graph"]["blocks"][0]["id"], "Hand made, must never change.")
    old_dir = ls.LS_ROOT / old["project"]["id"] if hasattr(ls, "LS_ROOT") else None
    if old_dir is None:
        old_dir = ls._dir(old["project"]["id"], None)
    old_hash = tree_hash(old_dir)

    # ---------- scopes ----------
    names_r = [t["name"] for t in server.visible("read")]
    names_w = [t["name"] for t in server.visible("write")]
    new_tools = {"studio_create", "studio_save_version", "linkshell_create_project_from_plan"}
    assert new_tools.isdisjoint(names_r) and new_tools <= set(names_w) and len(names_w) == len(names_r) + 5
    for n in new_tools:
        t = server.TOOLS[n]
        assert t["scope"] == "write" and t["annotations"] == {"readOnlyHint": False, "destructiveHint": False} and "agreed" in t["description"].lower()
    fails("studio_create", {"text": "x"}, "only read", READ)
    fails("studio_save_version", {"id": "ps-0123456789ab", "text": "x"}, "only read", READ)
    fails("linkshell_create_project_from_plan", {"plan": {"name": "x", "phases": []}}, "only read", READ)
    assert not LOG.exists(), "a refused call writes no log entry"
    step("the three write tools exist only for write tokens (hidden from a read token's list, refused with a clear message, no log entry), annotated non-destructive")

    # ---------- studio_create ----------
    r = ok("studio_create", {"text": "Summarise the text below in three bullets.", "title": "Bullet summary", "tags": ["writing", " ", "writing"]})
    sid = r["id"]
    d = ps.detail(sid, ps.STUDIO_DIR)
    assert sid.startswith("ps-") and r["status"] == "draft" and r["open"] == "#/studio/" + sid and r["activity_id"].startswith("a-")
    assert d["text"] == "Summarise the text below in three bullets." and d["title"] == "Bullet summary" and d["meta"]["status"] == "draft"
    assert d["meta"]["tags"] == ["writing", "via-mcp"] and r["tags"] == ["writing", "via-mcp"]
    assert [v["message"] for v in d["revisions"]] == ["Created (via MCP: Cursor)"]
    assert "other_copies" not in r
    assert ok("studio_search", {"query": "bullets"}, READ)["items"][0]["id"] == sid, "the search index was brought up to date"
    r2 = ok("studio_create", {"text": "Second, untitled prompt body.\nMore."})
    assert ps.detail(r2["id"], ps.STUDIO_DIR)["title"] == "Second, untitled prompt body." and r2["tags"] == ["via-mcp"]
    assert r2["id"] != sid and ok("studio_create", {"text": "Second, untitled prompt body.\nMore."})["id"] not in (sid, r2["id"]), "every call makes a new prompt"
    step("studio_create: a draft in Studio with the via-mcp tag and a version message naming the token, tags cleaned, auto title, always a new prompt, searchable at once")

    fails("studio_create", {"text": "   \n "}, "empty")
    fails("studio_create", {"text": ""}, "wrong length")
    fails("studio_create", {"text": "x" * 200_001}, "wrong length")
    fails("studio_create", {"text": "x", "title": "t" * 201}, "wrong length")
    fails("studio_create", {"text": "x", "tags": ["t"] * 20}, "at most 19")
    fails("studio_create", {"text": "x", "tags": ["t" * 41]}, "short strings")
    fails("studio_create", {"text": "x", "extra": 1}, "unknown argument")
    fails("studio_create", {}, "missing argument")
    fails("studio_create", {"text": "x", "from_library": "nope"}, "No Library prompt")
    fails("studio_create", {"text": "x", "from_library": sid}, "No Library prompt")
    step("studio_create refuses empty or oversized text, bad titles and tags, unknown arguments and unknown Library ids, in words the agent can act on")

    r = ok("studio_create", {"text": "Review the pull request. List findings by severity, each with a fix.", "title": "PR review", "from_library": lib1})
    assert r["derived_from"] == {"store": "library", "id": lib1} and "other_copies" not in r
    r_b = ok("studio_create", {"text": "Review the pull request again, shorter.", "from_library": lib1})
    assert r_b["other_copies"] == [r["id"]] and "already had a copy" in r_b["warning"]
    assert tree_hash(ps.PROMPTS_DIR / "2023-11") == lib_files_before, "the Library original was only read"
    assert ok("studio_get", {"id": r["id"]}, READ)["derived_from"] == {"store": "library", "id": lib1}
    step("from_library links Studio back to the original (a second copy is allowed but reported) and the Library prompt's files stay byte for byte the same")

    # ---------- studio_save_version ----------
    v0 = ok("studio_versions", {"id": sid}, READ)["versions"][0]["id"]
    r = ok("studio_save_version", {"id": sid, "text": "Summarise the text below in exactly three bullets, plain words.", "message": "stricter"})
    assert r["changed"] is True and r["previous_version"] == v0 and r["version"] != v0 and r["activity_id"].startswith("a-")
    vs = ok("studio_versions", {"id": sid}, READ)["versions"]
    assert [v["message"] for v in vs] == ["stricter (via MCP: Cursor)", "Created (via MCP: Cursor)"] and vs[0]["id"] == r["version"]
    assert ok("studio_get", {"id": sid}, READ)["text"].endswith("plain words.")
    r = ok("studio_save_version", {"id": sid, "text": "Third wording of the summary prompt."})
    assert ok("studio_versions", {"id": sid}, READ)["versions"][0]["message"] == "Update (via MCP: Cursor)"
    n_log = len(json.loads(LOG.read_text())["items"])
    same = ok("studio_save_version", {"id": sid, "text": "Third wording of the summary prompt."})
    assert same["changed"] is False and len(ok("studio_versions", {"id": sid}, READ)["versions"]) == 3 and len(json.loads(LOG.read_text())["items"]) == n_log
    fails("studio_save_version", {"id": sid, "text": "  "}, "empty")
    fails("studio_save_version", {"id": "ps-ffffffffffff", "text": "x"}, "No Studio prompt")
    fails("studio_save_version", {"id": lib1, "text": "x"}, "start with ps-")
    fails("studio_save_version", {"id": sid}, "missing argument")
    fails("studio_save_version", {"id": sid, "text": "x", "message": "m" * 151}, "wrong length")
    step("studio_save_version: a new version with the message and the token's name, old versions kept, identical text is a no-op (no version, no log), bad ids and empty text refused")

    # ---------- the plan builder, directly ----------
    for bad, needle in (([], "must be an object"), ({"name": "x", "phases": [], "zzz": 1}, "unknown field 'zzz'"), ({"phases": [{"title": "p", "prompts": [prompt("a", "t")]}]}, "name must"),
                        ({"name": "x"}, "phases must"), ({"name": "x", "phases": [{"title": "p", "prompts": []}]}, "needs a list of prompts"),
                        ({"name": "x", "phases": [{"title": "p", "prompts": [prompt("a", "t"), prompt("a", "u")]}]}, "used twice"),
                        ({"name": "x", "phases": [{"title": "p", "prompts": [prompt("a", "t", key="bad key!")]}]}, "key must be"),
                        ({"name": "x", "phases": [{"title": "p", "prompts": [prompt("a", "t", deps=["ghost"])]}]}, "not a key in the plan"),
                        ({"name": "x", "phases": [{"title": "p", "prompts": [prompt("a", "t", deps=["a"])]}]}, "cannot wait for itself"),
                        ({"name": "x", "phases": [{"title": "p", "prompts": [{**prompt("a", "t"), "oops": 1}]}]}, "unknown field 'oops'"),
                        ({"name": "x", "phases": [{"title": "p", "prompts": [{**prompt("a", "t"), "text": 5}]}]}, "must be text"),
                        ({"name": "x", "phases": [{"title": "p", "prompts": [prompt("a", "x" * 100_001)]}]}, "text must be"),
                        ({"name": "x", "phases": [{"title": "p", "prompts": [prompt("a", "t", specs=[{"title": "s", "text": "t"}] * 9)]}]}, "at most 8"),
                        ({"name": "x", "phases": [{"title": "p", "prompts": [prompt("a", "t", specs=[{"title": "s"}])]}]}, "text must be"),
                        ({"name": "x", "phases": [{"title": "p", "prompts": [prompt(f"p{i}", "t") for i in range(61)]}]}, "too large"),
                        ({"name": "x", "tags": "web", "phases": [{"title": "p", "prompts": [prompt("a", "t")]}]}, "tags must"),
                        ({"name": "x", "phases": [{"title": "p", "prompts": [{**prompt("a", "t"), "after": "b"}]}]}, "after must be a list"),
                        ({"name": "x", "phases": [{"title": f"p{i}", "prompts": [prompt(f"k{i}", "t")]} for i in range(21)]}, "1 to 20 phases")):
        try:
            planmod.build(bad)
        except planmod.PlanError as e:
            assert needle.lower() in str(e).lower(), (needle, str(e))
        else:
            raise AssertionError(f"expected a PlanError containing {needle!r}")
    many = [prompt(f"p{i}", "t", deps=[f"p{j}" for j in range(i)]) for i in range(60)]
    try:
        planmod.build({"name": "x", "phases": [{"title": "all", "prompts": many}]})
    except planmod.PlanError as e:
        assert "links" in str(e) and "at most 200" in str(e), str(e)
    else:
        raise AssertionError("too many links must be refused")
    step("the plan builder refuses 18 kinds of bad plan (types, unknown fields, duplicate or bad keys, unknown or self `after`, sizes, too many links), each with a message that says what to change")

    # ---------- the layout of a built plan (the way Tidy up would arrange it) ----------
    def _overlap(a, b):
        return a["x"] < b["x"] + b["w"] and b["x"] < a["x"] + a["w"] and a["y"] < b["y"] + b["h"] and b["y"] < a["y"] + a["h"]

    def _laid(pl):
        data, _ = planmod.build(pl)
        g = data["graph"]
        return {b["title"]: b for b in g["blocks"]}, g
    # a prompt that waits only for the Brief sits UNDER the first prompt (same column), not at the end of the row; a chain runs left to right
    by, g = _laid({"name": "L", "phases": [{"title": "one", "prompts": [prompt("First", "t", key="one"), prompt("Second", "t", key="two"), prompt("Parallel", "t", deps=[], key="free")]}]})
    assert by["Parallel"]["x"] == by["First"]["x"] and by["Parallel"]["y"] > by["First"]["y"] + by["First"]["h"] and by["Second"]["x"] > by["First"]["x"] and by["Second"]["y"] == by["First"]["y"]
    assert by["Brief"]["x"] < by["First"]["x"] and by["Parallel"]["y"] + by["Parallel"]["h"] <= g["frames"][0]["y"] + g["frames"][0]["h"]
    # a prompt of a later phase starts at the left of its own frame, below the earlier frame
    by, g = _laid({"name": "L", "phases": [{"title": "one", "prompts": [prompt("A", "t", specs=[{"title": "Spec", "text": "s"}], key="a"), prompt("B", "t", deps=["a"], key="b")]}, {"title": "two", "prompts": [prompt("C", "t", deps=["a"], key="c")]}]})
    f1, f2 = g["frames"]
    assert f2["y"] >= f1["y"] + f1["h"] and by["C"]["y"] >= f2["y"] and by["C"]["x"] >= f2["x"] and by["Spec"]["x"] == by["A"]["x"] and by["Spec"]["y"] > by["A"]["y"]
    col = planmod.W + planmod.RANK_GAP
    assert by["C"]["x"] >= by["A"]["x"] + col and f2["x"] > f1["x"], "a later phase starts one column right of what it waits for (the canvas draws links from the right side of a block to the left side of the next)"
    # a fan out and in: the parallel prompts of phase 2 are stacked one column right of their parent (a clean fan of links), the merge one column right of them
    by, g = _laid({"name": "L", "phases": [{"title": "s", "prompts": [prompt("S", "t", key="s")]}, {"title": "b", "prompts": [prompt("U", "t", deps=["s"], key="u"), prompt("V", "t", deps=["s"], key="v")]},
                                         {"title": "m", "prompts": [prompt("M", "t", deps=["u", "v"], key="m"), prompt("D", "t", deps=["m"], key="d")]}]})
    assert by["U"]["x"] == by["V"]["x"] >= by["S"]["x"] + col and by["V"]["y"] > by["U"]["y"], "stacked, one column right of S"
    assert by["M"]["x"] >= by["U"]["x"] + col and by["M"]["y"] > by["U"]["y"] and by["D"]["x"] > by["M"]["x"] and by["D"]["y"] == by["M"]["y"]
    byid = {b["id"]: b for b in g["blocks"]}
    assert all(byid[l["to"]]["x"] >= byid[l["from"]]["x"] + planmod.W for l in g["links"] if l["kind"] == "order" and byid[l["from"]]["type"] == "prompt"), "every link between prompts flows forward"
    # a very long plan does not drift for ever: past MAX_DRIFT the phases stop moving right
    long_plan = {"name": "Long", "phases": [{"title": f"P{i}", "prompts": [prompt(f"a{i}", "t", key=f"a{i}"), prompt(f"b{i}", "t", key=f"b{i}")]} for i in range(14)]}
    _, g = _laid(long_plan)
    assert max(f["x"] + f["w"] for f in g["frames"]) <= planmod.MAX_DRIFT + planmod.PAD_RIGHT
    assert max(f["x"] for f in g["frames"]) > 1000, "it did drift right before the cap"
    # every block is inside its frame and nothing overlaps, for a lot of random plans (a fixed seed)
    import random
    rnd = random.Random(3)
    for _ in range(150):
        phases, seen = [], []
        for i in range(rnd.randint(1, 5)):
            prs = []
            for j in range(rnd.randint(1, 6)):
                k = f"k{len(seen)}"
                seen.append(k)
                deps = rnd.sample(seen[:-1], rnd.randint(0, min(3, len(seen) - 1))) if len(seen) > 1 and rnd.random() < 0.6 else None
                prs.append(prompt(k, "t", deps=deps, specs=[{"title": "s", "text": "t"}] * rnd.randint(1, 3) if rnd.random() < 0.3 else None, key=k))
            phases.append({"title": f"P{i}", "prompts": prs})
        data, _ = planmod.build({"name": "F", "phases": phases})
        gr, fr = data["graph"], {f["id"]: f for f in data["graph"]["frames"]}
        bl = gr["blocks"]
        for i, a in enumerate(bl):
            assert not any(_overlap(a, b) for b in bl[i + 1:]), ("blocks overlap", a["title"])
            f = fr[a["frame"]]
            assert f["x"] <= a["x"] and a["x"] + a["w"] <= f["x"] + f["w"] and f["y"] <= a["y"] and a["y"] + a["h"] <= f["y"] + f["h"], ("outside its frame", a["title"])
        ys = sorted(fr.values(), key=lambda f: f["y"])
        assert all(a["y"] + a["h"] <= b["y"] for a, b in zip(ys, ys[1:])), "frames overlap"
        byid = {b["id"]: b for b in bl}
        assert all(byid[l["from"]]["x"] < byid[l["to"]]["x"] for l in gr["links"] if l["kind"] == "order" and byid[l["from"]]["frame"] == byid[l["to"]]["frame"]), "order links run left to right inside a phase"
    step("a built plan is laid out like Tidy up: columns by what a prompt waits for, parallel prompts stacked, specs underneath, frames stacked; no overlaps in 150 random plans")

    # ---------- linkshell_create_project_from_plan ----------
    before_ids = {p["id"] for p in ls.list_projects(page_size=200)["items"]}
    plan = {"name": "Launch plan", "brief": "Ship the beta by Friday.\nKeep scope small.", "default_agent": "codex", "tags": ["launch"], "properties": {"owner": "Alice"},
            "phases": [
                {"title": "Phase 1 · Foundation", "prompts": [
                    prompt("Write the spec", "Write a one-page spec for the beta.", specs=[{"title": "House rules", "text": "Keep every answer under 200 words."}, {"title": "Glossary", "text": "Beta = first public build."}]),
                    prompt("Scaffold", "Create the project folders.", agent="claude")]},
                {"title": "Phase 2 · Build", "prompts": [
                    prompt("Frontend", "Build the screens.", deps=["write-the-spec"]),
                    prompt("Backend", "Build the API.", deps=[]),
                    prompt("Integrate", "Join frontend and backend.", deps=["frontend", "backend"], specs=[{"title": "API notes", "text": "JSON only."}])]},
            ]}
    r = ok("linkshell_create_project_from_plan", {"plan": plan})
    pid = r["id"]
    assert pid.startswith("ls-") and pid not in before_ids and r["name"] == "Launch plan" and (r["phases"], r["prompts"], r["specs"]) == (2, 5, 3) and r["tags"] == ["launch", "via-mcp"]
    assert r["open"] == "#/linkshell/" + pid and r["activity_id"].startswith("a-") and "Brief is not ticked" in r["message"]
    p = ls.get(pid)
    g, proj = p["graph"], p["project"]
    assert proj["name"] == "Launch plan" and proj["default_agent"] == "codex" and proj["tags"] == ["launch", "via-mcp"] and proj["properties"] == [{"key": "owner", "value": "Alice"}]
    by_title = {b["title"]: b for b in g["blocks"]}
    assert len(g["blocks"]) == 1 + 5 + 3 and len(g["frames"]) == 2 and {b["type"] for b in g["blocks"]} == {"start", "prompt", "spec"}
    start = by_title["Brief"]
    assert start["type"] == "start" and start["status"] == "todo" and p["texts"][start["id"]] == "Ship the beta by Friday.\nKeep scope small."
    assert by_title["Write the spec"]["agent"] == "" and by_title["Scaffold"]["agent"] == "claude"
    assert p["texts"][by_title["Write the spec"]["id"]] == "Write a one-page spec for the beta." and p["texts"][by_title["House rules"]["id"]] == "Keep every answer under 200 words."
    fr = {f["id"]: f for f in g["frames"]}
    f1, f2 = sorted(g["frames"], key=lambda f: f["y"])
    assert (f1["title"], f2["title"]) == ("Phase 1 · Foundation", "Phase 2 · Build")
    assert start["frame"] == f1["id"] and by_title["Frontend"]["frame"] == f2["id"] and by_title["API notes"]["frame"] == f2["id"] and by_title["Scaffold"]["frame"] == f1["id"]
    edges = {(next(b["title"] for b in g["blocks"] if b["id"] == l["from"]), next(b["title"] for b in g["blocks"] if b["id"] == l["to"]), l["kind"]) for l in g["links"]}
    assert edges == {("Brief", "Write the spec", "order"), ("Write the spec", "Scaffold", "order"),            # no `after`: follows the previous prompt, the first follows the Brief
                     ("Write the spec", "Frontend", "order"), ("Brief", "Backend", "order"),                  # explicit after / [] (only the Brief)
                     ("Frontend", "Integrate", "order"), ("Backend", "Integrate", "order"),
                     ("House rules", "Write the spec", "context"), ("Glossary", "Write the spec", "context"), ("API notes", "Integrate", "context")}, edges
    assert len(g["links"]) == 9
    steps = [b["title"] for b in ls.run_order(g)]
    assert steps.index("Write the spec") < steps.index("Scaffold") and steps.index("Frontend") < steps.index("Integrate") and steps.index("Backend") < steps.index("Integrate")
    assert ls.status_of(g, by_title["Write the spec"]) == "todo" and ls.stats(g)["next"] == "", "nothing is ready until the Brief is ticked"
    ticked = json.loads(json.dumps(g))
    next(b for b in ticked["blocks"] if b["type"] == "start")["status"] = "done"
    assert ls.status_of(ticked, by_title["Write the spec"]) == "ready" and ls.status_of(ticked, by_title["Backend"]) == "ready" and ls.status_of(ticked, by_title["Frontend"]) == "todo"
    ex = ls.export_plan(pid)
    assert ex["brief"].startswith("Ship the beta") and [ph["title"] for ph in ex["phases"]] == ["Phase 1 · Foundation", "Phase 2 · Build"]
    flat = {x["title"]: x for ph in ex["phases"] for x in ph["prompts"]}
    assert [s["title"] for s in flat["Write the spec"]["specs"]] == ["House rules", "Glossary"] and flat["Integrate"]["after"] == sorted([flat["Frontend"]["n"], flat["Backend"]["n"]])
    assert ok("linkshell_get_project", {"id": pid}, READ)["name"] == "Launch plan" and ok("linkshell_list_projects", {"query": "launch"}, READ)["total_matches"] == 1
    step("a plan becomes a real project: frames per phase, Brief unticked in the first frame, the right order and context links (default, explicit and empty `after`), texts, agents, tags, properties; nothing is ready until the Brief is ticked; exports and read tools agree")

    # layout
    def rect(b):
        return (b["x"], b["y"], b["x"] + b["w"], b["y"] + b["h"])

    def overlap(a, b):
        return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]
    rects = [(b["title"], rect(b)) for b in g["blocks"]]
    for i, (n1, ra) in enumerate(rects):
        assert ra[0] >= 0 and ra[1] >= 0, n1
        for n2, rb in rects[i + 1:]:
            assert not overlap(ra, rb), (n1, n2)
    for b in g["blocks"]:
        f = fr[b["frame"]]
        assert f["x"] <= b["x"] and f["y"] <= b["y"] and b["x"] + b["w"] <= f["x"] + f["w"] and b["y"] + b["h"] <= f["y"] + f["h"], (b["title"], "outside its frame")
    assert not overlap(rect(f1), rect(f2)) and f2["y"] > f1["y"] + f1["h"]
    assert by_title["Write the spec"]["x"] > start["x"] + start["w"] and by_title["Scaffold"]["x"] > by_title["Write the spec"]["x"]
    assert by_title["House rules"]["y"] > by_title["Write the spec"]["y"] and by_title["Glossary"]["y"] > by_title["House rules"]["y"] and by_title["House rules"]["x"] == by_title["Write the spec"]["x"]
    assert ls.get(pid)["graph"]["rev"] == 1
    step("the layout is tidy: no overlapping blocks, every block inside its frame, phases stacked top to bottom, prompts left to right, specs under their prompt")

    # errors and safety
    n_projects = len(ls.list_projects(page_size=200)["items"])
    fails("linkshell_create_project_from_plan", {"plan": {"name": "Loop", "phases": [{"title": "p", "prompts": [prompt("a", "t", deps=["b"]), prompt("b", "t", deps=["a"])]}]}}, "loop")
    fails("linkshell_create_project_from_plan", {"plan": {"name": "x", "phases": [{"title": "p", "prompts": [prompt("a", "t", deps=["zzz"])]}]}}, "not a key in the plan")
    fails("linkshell_create_project_from_plan", {"plan": "just text"}, "must be an object")
    fails("linkshell_create_project_from_plan", {"plan": {"name": "x", "phases": [{"title": "p", "prompts": [prompt(f"p{i}", "t") for i in range(61)]}]}}, "too large")
    fails("linkshell_create_project_from_plan", {}, "missing argument")
    assert len(ls.list_projects(page_size=200)["items"]) == n_projects, "a refused plan creates nothing"
    r_again = ok("linkshell_create_project_from_plan", {"plan": plan})
    assert r_again["id"] != pid and len(ls.list_projects(page_size=200)["items"]) == n_projects + 1, "the same plan twice is two projects"
    assert tree_hash(old_dir) == old_hash, "the user's own project was not touched"
    step("loops, unknown keys and oversized plans are refused with nothing created; the same plan twice makes two projects; an existing project stays byte for byte the same")

    # ---------- the activity log ----------
    raw = LOG.read_text()
    log = json.loads(raw)
    assert log["schema_version"] == 1 and all(set(i) >= {"id", "ts", "token", "tool", "store", "ref", "title", "undone"} for i in log["items"])
    assert "Summarise the text below" not in raw and "Write a one-page spec" not in raw and "Ship the beta" not in raw, "the log holds titles, never prompt text"
    assert not any(k in raw for k in ("fls_", "Bearer")) and (LOG.stat().st_mode & 0o777) in (0o600, 0o644, 0o664)
    items = activity.list_items(100)
    assert items[0]["what"] == "Created Linkshell project" and items[0]["title"] == "Launch plan" and items[0]["token"] == "Cursor" and items[0]["open"].startswith("#/linkshell/ls-")
    whats = [i["what"] for i in items]
    assert "Saved a new version of Studio prompt" in whats and "Created Studio prompt" in whats and items[0]["time"] >= items[-1]["time"]
    assert activity.list_items(2) == items[:2]
    step("the activity log lists newest first with the token's name, what and where to open; the file holds titles and ids only, no text, no secrets")

    # ---------- Undo ----------
    a_create = next(i for i in activity.list_items(100) if i["what"] == "Created Studio prompt" and i["ref"] == r2["id"])
    note = activity.undo(a_create["id"])
    assert "Trash" in note and ps.get(r2["id"], ps.STUDIO_DIR) is None and any(t["id"] == r2["id"] for t in ps.load_trash(ps.STUDIO_DIR))
    assert ok("studio_search", {"query": "untitled prompt body"}, READ)["total_matches"] == 1, "only the other copy is left in the search"
    for again in (a_create["id"],):
        try:
            activity.undo(again)
        except activity.UndoError as e:
            assert "already undone" in str(e) and e.status == 409
        else:
            raise AssertionError("a second undo must be refused")
    assert next(i for i in activity.list_items(100) if i["id"] == a_create["id"])["undone"] and "Trash" in next(i for i in activity.list_items(100) if i["id"] == a_create["id"])["note"]
    try:
        activity.undo("a-00000000")
    except activity.UndoError as e:
        assert e.status == 404
    else:
        raise AssertionError("unknown entry")
    step("undo of a created prompt moves it to the Trash (and out of search), a second undo and an unknown entry are refused")

    a_ver = next(i for i in activity.list_items(100) if i["what"].startswith("Saved a new version") and i["ref"] == sid and not i["undone"])   # the newest one ("Update")
    cur_before = ps.detail(sid, ps.STUDIO_DIR)
    n_before = len(cur_before["revisions"])
    note = activity.undo(a_ver["id"])
    after = ps.detail(sid, ps.STUDIO_DIR)
    assert "previous text" in note and after["text"].endswith("plain words.") and len(after["revisions"]) == n_before + 1 and after["revisions"][0]["message"].startswith("Undo: version saved via MCP")
    assert "Third wording" in ps.revision_text(sid, cur_before["revisions"][0]["short"], ps.STUDIO_DIR)["text"], "the agent's version stays in the history"
    r_new = ok("studio_save_version", {"id": sid, "text": "Fourth wording by the agent."})
    ps.save_text(sid, "The user then edited it by hand.", "my edit", ps.STUDIO_DIR)
    a_edit = next(i for i in activity.list_items(100) if i["ref"] == sid and not i["undone"] and i["what"].startswith("Saved"))
    try:
        activity.undo(a_edit["id"])
    except activity.UndoError as e:
        assert "edited after" in str(e)
    else:
        raise AssertionError("an undo must not overwrite a later human edit")
    assert ps.detail(sid, ps.STUDIO_DIR)["text"] == "The user then edited it by hand."
    ps.trash(r["id"] if False else sid, ps.STUDIO_DIR)
    try:
        activity.undo(a_edit["id"])
    except activity.UndoError as e:
        assert "not in Studio" in str(e)
    else:
        raise AssertionError("a trashed prompt cannot be reverted")
    step("undo of a new version puts the previous text back as a new version (the agent's stays in the history); it refuses when a person edited the prompt since, or the prompt is gone")

    a_ls = next(i for i in activity.list_items(100) if i["what"] == "Created Linkshell project" and i["ref"] == pid)
    assert "Trash" in activity.undo(a_ls["id"]) and ls.get(pid) is None and any(t["id"] == pid for t in ls.load_trash())
    assert ok("linkshell_list_projects", {}, READ)["total_matches"] == n_projects, "the other new project and the old one remain"
    ls.trash(r_again["id"])
    a_gone = next(i for i in activity.list_items(100) if i["ref"] == r_again["id"])
    assert "already gone" in activity.undo(a_gone["id"])
    assert tree_hash(old_dir) == old_hash
    step("undo of a created project moves it to the Trash; an item already gone is reported as such; the user's own project is never touched")

    # ---------- the log is capped ----------
    for i in range(210):
        activity.record(WRITE, "studio_create", "studio", f"ps-{i:012x}", f"t{i}")
    assert len(json.loads(LOG.read_text())["items"]) == activity.MAX_ITEMS == 200
    assert activity.list_items(5)[0]["title"] == "t209"
    LOG.write_text("{ not json")
    assert activity.list_items(5) == []
    ok("studio_create", {"text": "After a damaged log."})
    assert len(activity.list_items(5)) == 1
    step("the log keeps the newest 200 entries, and a damaged file is replaced instead of breaking a save")

    print("\nall MCP write checks passed")
finally:
    try:
        service.get().close()
    except Exception:
        pass
    shutil.rmtree(TMP, ignore_errors=True)
