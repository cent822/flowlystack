#!/usr/bin/env python3
"""Checks for the Linkshell storage in backend/linkshell.py. Plain asserts, standard library only.

    python3 scripts/check_linkshell.py

Everything runs in a temp directory; your real prompts are never touched.
"""
import copy
import tempfile as _tf
import os as _o
_o.environ["FLOWLYSTACK_ALIAS_DIR"] = _tf.mkdtemp()   # short-path links go in a temp folder, never in ~/.flowlystack
import hashlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="flowlystack-linkshell-check-"))
os.environ["FLOWLYSTACK_PROMPTS_DIR"] = str(TMP / "unused")   # config reads this at import; every call below passes its own root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import linkshell as ls   # noqa: E402

LIB = TMP / "prompts"
ROOT = LIB / "linkshell"


def step(msg: str) -> None:
    print("ok  ", msg)


def raises(exc, fn, *a, **k):
    try:
        fn(*a, **k)
    except exc as e:
        return e
    raise AssertionError(f"{fn.__name__} should have raised {exc.__name__}")


def tree_hash(path: Path) -> str:
    h = hashlib.sha1()
    for f in sorted(path.rglob("*")):
        if f.is_file() and "linkshell" not in f.relative_to(path).parts:
            h.update(f.relative_to(path).as_posix().encode() + f.read_bytes())
    return h.hexdigest()


# --- a small Library and Studio folder to prove they never change ---
(LIB / "2026-10").mkdir(parents=True)
(LIB / "2026-10" / "a.json").write_text(json.dumps({"id": "a", "prompt": "hello", "ts": time.time()}))
(LIB / "studio" / "2026-10").mkdir(parents=True)
(LIB / "studio" / "2026-10" / "ps-000000000001.json").write_text(json.dumps({"id": "ps-000000000001", "kind": "studio"}))
before = tree_hash(LIB)

# --- create ---
p = ls.create("Personal website", ROOT, brief="A one-page portfolio.")
pid = p["project"]["id"]
assert pid.startswith("ls-") and len(pid) == 15
assert p["project"]["kind"] == "linkshell" and p["project"]["schema_version"] == 1
g = p["graph"]
assert g["rev"] == 1 and len(g["blocks"]) == 1 and g["blocks"][0]["type"] == "start"
start = g["blocks"][0]["id"]
assert p["texts"][start] == "A one-page portfolio."
raises(ls.Invalid, ls.create, "  ", ROOT)
assert ls.get("ls-ffffffffffff", ROOT) is None and ls.get("../etc", ROOT) is None
step("create: one Start block, brief stored, bad names and ids refused")


def block(bid, typ, title, x=0, y=0, **kw):
    return {"id": bid, "type": typ, "title": title, "x": x, "y": y, "w": 190, "h": 88, "frame": "", "agent": "claude", "status": "todo", **kw}


def link(a, b, kind="order", lid=None):
    return {"id": lid or f"l-{a}-{b}", "from": a, "to": b, "kind": kind}


# --- graph save: rev, cycle, duplicates ---
g = copy.deepcopy(ls.get(pid, ROOT)["graph"])
g["blocks"] += [block("scaffold", "prompt", "Scaffold", 280, 80), block("hero", "prompt", "Hero", 520, 40), block("contact", "prompt", "Contact", 520, 160),
                block("seo", "prompt", "SEO", 760, 80), block("tokens", "spec", "Design tokens", 280, 200), block("shot", "reference", "Screenshot", 280, 300, asset="", url="https://example.com")]
g["blocks"][-1].pop("asset")
g["frames"] = [{"id": "f1", "title": "Phase 1", "x": 20, "y": 20, "w": 400, "h": 300, "collapsed": False}]
g["blocks"][1]["frame"] = "f1"
g["links"] = [link(start, "scaffold"), link("scaffold", "hero"), link("scaffold", "contact"), link("hero", "seo"), link("contact", "seo"),
              link("tokens", "scaffold", "context"), link("shot", "scaffold", "context")]
saved = ls.save_graph(pid, g, 1, ROOT)
assert saved["rev"] == 2
e = raises(ls.Conflict, ls.save_graph, pid, g, 1, ROOT)
assert e.rev == 2
step("graph save: new rev, a stale rev is refused with the current one")

vp = ls.save_viewport(pid, {"x": -120, "y": 40, "k": 0.5}, ROOT)
assert vp == {"x": -120, "y": 40, "k": 0.5}
after = ls.get(pid, ROOT)["graph"]
assert after["viewport"] == vp and after["rev"] == 2, "a viewport save keeps the rev"
assert len(after["blocks"]) == len(saved["blocks"])
step("viewport save: stored without a new rev")

bad = copy.deepcopy(saved)
bad["links"].append(link("seo", "scaffold"))
assert "loop" in str(raises(ls.Invalid, ls.save_graph, pid, bad, 2, ROOT))
bad = copy.deepcopy(saved)
bad["links"].append(link("scaffold", "hero", lid="l-dup"))
raises(ls.Invalid, ls.save_graph, pid, bad, 2, ROOT)
bad = copy.deepcopy(saved)
bad["links"].append(link("hero", "hero"))
raises(ls.Invalid, ls.save_graph, pid, bad, 2, ROOT)
bad = copy.deepcopy(saved)
bad["links"].append(link("hero", "ghost"))
raises(ls.Invalid, ls.save_graph, pid, bad, 2, ROOT)
bad = copy.deepcopy(saved)
bad["blocks"].append(block("../evil", "prompt", "x"))
raises(ls.Invalid, ls.save_graph, pid, bad, 2, ROOT)
bad = copy.deepcopy(saved)
bad["blocks"].append(block("second", "start", "Another brief"))
raises(ls.Invalid, ls.save_graph, pid, bad, 2, ROOT)
bad = copy.deepcopy(saved)
bad["blocks"] = [b for b in bad["blocks"] if b["type"] != "start"]
bad["links"] = [l for l in bad["links"] if l["from"] != start]
raises(ls.Invalid, ls.save_graph, pid, bad, 2, ROOT)
ok = copy.deepcopy(saved)   # a context link may point anywhere and may close what an order link would: only `order` loops are refused
ok["links"].append(link("scaffold", "tokens", "context"))
ls.save_graph(pid, ok, 2, ROOT)
assert ls.get(pid, ROOT)["graph"]["rev"] == 3
step("graph rules: order cycle, duplicate, self link, unknown end, unsafe id, two Starts, no Start refused; context loops allowed")

# --- links to and from a frame stand for every block in it ---
fg = {"blocks": [block("st", "start", "Brief"), block("a", "prompt", "A"), block("b", "prompt", "B", frame="fx"), block("b2", "prompt", "B2", frame="fx"), block("c", "prompt", "C")],
      "frames": [{"id": "fx", "title": "Phase", "x": 0, "y": 0, "w": 300, "h": 200, "collapsed": True}], "links": [link("st", "a"), link("a", "fx"), link("fx", "c")]}
assert sorted(ls.order_edges(fg)) == sorted([("st", "a"), ("a", "b"), ("a", "b2"), ("b", "c"), ("b2", "c")])
fb = {x["id"]: x for x in fg["blocks"]}
fb["st"]["status"] = fb["a"]["status"] = "done"
assert ls.status_of(fg, fb["b"]) == "ready" and ls.status_of(fg, fb["c"]) == "todo"   # c waits for every block in the phase
fb["b"]["status"] = "done"
assert ls.status_of(fg, fb["c"]) == "todo"
fb["b2"]["status"] = "skipped"
assert ls.status_of(fg, fb["c"]) == "ready"
assert [b["id"] for b in ls.run_order(fg)].index("a") < [b["id"] for b in ls.run_order(fg)].index("b") < [b["id"] for b in ls.run_order(fg)].index("c")
ls._clean_graph(copy.deepcopy(fg))   # a link may end at a frame
loop = copy.deepcopy(fg)
loop["links"].append(link("c", "fx"))
assert "loop" in str(raises(ls.Invalid, ls._clean_graph, loop))
ghost = copy.deepcopy(fg)
ghost["links"].append(link("a", "fnope"))
raises(ls.Invalid, ls._clean_graph, ghost)
step("frame links: a link from or into a frame means every block in it (order, Ready, run order, loop check, unknown frame refused)")

# --- statuses: Ready is computed ---
g = ls.get(pid, ROOT)["graph"]
by = {b["id"]: b for b in g["blocks"]}
assert ls.status_of(g, by["scaffold"]) == "todo"       # the Brief starts unticked, so the first step waits for it
by[start]["status"] = "done"
assert ls.status_of(g, by["scaffold"]) == "ready"      # its only order source (Start) is done
assert ls.status_of(g, by["hero"]) == "todo"
by["scaffold"]["status"] = "done"
g = ls.save_graph(pid, g, 3, ROOT)
by = {b["id"]: b for b in g["blocks"]}
assert by["scaffold"]["status_at"] > 0
assert ls.status_of(g, by["hero"]) == "ready" and ls.status_of(g, by["contact"]) == "ready" and ls.status_of(g, by["seo"]) == "todo"
by["hero"]["status"] = "skipped"
by["contact"]["status"] = "done"
g = ls.save_graph(pid, g, g["rev"], ROOT)
assert ls.status_of(g, {b["id"]: b for b in g["blocks"]}["seo"]) == "ready"
assert [b["id"] for b in ls.run_order(g)] == ["scaffold", "hero", "contact", "seo"]
s = ls.stats(g)
assert (s["steps"], s["done"], s["next"]) == (4, 2, "SEO"), s
step("statuses: Ready is computed from order links only; run order and stats")

# --- text and versions ---
r = ls.save_text(pid, "hero", "Build the hero for {{site}}.", "", ROOT)
assert r["changed"] and r["version"]["message"] == "Created"
assert ls.save_text(pid, "hero", "Build the hero for {{site}}.", "again", ROOT) == {"changed": False}
ls.save_text(pid, "hero", "Build a bigger hero for {{site}}.", "Bigger", ROOT)
ls.save_text(pid, "hero", "Build the hero for {{site}}, in plain CSS.", "Add CSS", ROOT)
revs = ls.revisions(pid, "hero", ROOT)
assert [v["message"] for v in revs] == ["Add CSS", "Bigger", "Created"] and revs[0]["current"] and not revs[1]["current"]
old = revs[2]["id"]
assert ls.revision_text(pid, "hero", old, ROOT)["text"] == "Build the hero for {{site}}."
ls.save_text(pid, "hero", ls.revision_text(pid, "hero", old, ROOT)["text"], "Rollback to Created", ROOT)   # rollback = save the old text as a new version
assert len(ls.revisions(pid, "hero", ROOT)) == 4 and ls.read_text(pid, "hero", ROOT) == "Build the hero for {{site}}."
assert ls.delete_revision(pid, "hero", revs[1]["id"], ROOT) is True
raises(ls.Invalid, ls.delete_revision, pid, "hero", ls.revisions(pid, "hero", ROOT)[0]["id"], ROOT)
assert ls.delete_revision(pid, "hero", "nope", ROOT) is None
ls.save_text(pid, start, "A portfolio for {{site}}.", "", ROOT)       # Start keeps the current text only
assert ls.revisions(pid, start, ROOT) == []
raises(ls.Invalid, ls.save_text, pid, "shot", "text", "", ROOT)       # a Reference has no text
assert ls.save_text(pid, "ghost", "x", "", ROOT) is None
step("text: versions, no-op save, rollback as a new version, non-current delete only, Start/Reference rules")

# --- assets ---
a = ls.add_asset(pid, "../../Hero Image!.png", b"\x89PNG-data", ROOT)
assert ls._ASSET.match(a) and a.endswith("Hero-Image-.png") and "/" not in a
assert ls.asset_path(pid, a, ROOT).read_bytes() == b"\x89PNG-data"
assert ls.asset_path(pid, "../project.json", ROOT) is None and ls.asset_path(pid, "a-00000000-missing.png", ROOT) is None
g = ls.get(pid, ROOT)["graph"]
{b["id"]: b for b in g["blocks"]}["shot"]["asset"] = a
g = ls.save_graph(pid, g, g["rev"], ROOT)
a2 = ls.add_asset(pid, "second.png", b"two", ROOT)
{b["id"]: b for b in g["blocks"]}["shot"]["assets"] = [a, a2]   # several files per Reference (the single `asset` set above was folded into a list)
g = ls.save_graph(pid, g, g["rev"], ROOT)
shot = {b["id"]: b for b in g["blocks"]}["shot"]
assert shot["assets"] == [a, a2] and "asset" not in shot
raises(ls.Invalid, ls.save_graph, pid, {**g, "blocks": [{**x, "assets": ["../x"]} if x["id"] == "shot" else x for x in g["blocks"]]}, g["rev"], ROOT)
{b["id"]: b for b in g["blocks"]}["shot"]["assets"] = [a]
g = ls.save_graph(pid, g, g["rev"], ROOT)
step("assets: safe stored name, served back, traversal refused, several files per Reference")

# --- update (settings) ---
ls.update(pid, {"variables": [{"name": "site", "value": "ada.dev"}], "tags": ["web", "web", " portfolio "], "star": True, "name": "Site"}, ROOT)
pr = ls.get(pid, ROOT)["project"]
assert "variables" not in pr and pr["tags"] == ["web", "portfolio"] and pr["star"] and pr["name"] == "Site"
raises(ls.Invalid, ls.update, pid, {"name": " "}, ROOT)
step("update: tags de-duplicated, star, name; the old variables field is ignored")

# --- assemble ---
ls.save_text(pid, "scaffold", "Scaffold {{site}} using {{stack}}.", "", ROOT)
ls.save_text(pid, "tokens", "Colours: teal.", "", ROOT)
asm = ls.assemble(pid, "scaffold", root=ROOT)
assert asm["text"].startswith("Scaffold {{site}} using {{stack}}.")   # nothing is filled unless the user types it
assert "## Design tokens\nColours: teal." in asm["text"]
assert "undefined" not in asm
folder = ls.assets_alias(pid, ROOT)
assert asm["references"] == [folder + "/" + a, "https://example.com"]   # the file's short path, then the web link
assert os.path.realpath(asm["references"][0]) == str(ls.asset_path(pid, a, ROOT).resolve()) and len(os.path.basename(folder)) <= 8 and ls.assets_alias(pid, ROOT) == folder
assert asm["text"].endswith(f"## References\nFiles in {folder}/\n- {a}\n- https://example.com")   # the folder is written once, files by stored name
assert asm["text"].count(folder) == 1
assert "{{stack}}" in ls.read_text(pid, "scaffold", ROOT)      # the block text itself is never filled or changed
g = ls.get(pid, ROOT)["graph"]
{b["id"]: b for b in g["blocks"]}["scaffold"]["context_off"] = ["tokens"]
g = ls.save_graph(pid, g, g["rev"], ROOT)
asm = ls.assemble(pid, "scaffold", root=ROOT)
assert "Design tokens" not in asm["text"] and "References" in asm["text"]
assert ls.assemble(pid, "tokens", root=ROOT) is None and ls.assemble(pid, "ghost", root=ROOT) is None
# a note per file of a Reference block: kept for files it lists, dropped for others, written under the file in Copy and in the exports
g = ls.get(pid, ROOT)["graph"]
{b["id"]: b for b in g["blocks"]}["shot"]["file_notes"] = {a: "Keep the grid.\nIgnore footer.  ", "a-00000000-ghost.png": "x", a + "2": " "}
g = ls.save_graph(pid, g, g["rev"], ROOT)
assert {b["id"]: b for b in g["blocks"]}["shot"]["file_notes"] == {a: "Keep the grid.\nIgnore footer."}
asm = ls.assemble(pid, "scaffold", root=ROOT)
assert asm["text"].endswith(f"- {a}\n  Note: Keep the grid.\n  Ignore footer.\n- https://example.com"), asm["text"][-200:]
pl = ls.export_plan(pid, ROOT)
pr = next(q for ph in pl["phases"] for q in ph["prompts"] if q["id"] == "scaffold")
assert pr["reference_notes"] == {folder + "/" + a: "Keep the grid.\nIgnore footer."} and "  Note: Keep the grid." in ls.export_markdown(pid, ROOT)
g = ls.get(pid, ROOT)["graph"]
{b["id"]: b for b in g["blocks"]}["shot"]["file_notes"] = {}
g = ls.save_graph(pid, g, g["rev"], ROOT)
assert "file_notes" not in {b["id"]: b for b in g["blocks"]}["shot"] and "reference_notes" not in next(q for ph in ls.export_plan(pid, ROOT)["phases"] for q in ph["prompts"] if q["id"] == "scaffold")
step("reference notes: per file, cleaned, under the file in Copy and both exports, none = old shape")
# a file no block uses any more is deleted on the next save, but not while it is fresh, and not while a parked block still uses it
import os as _os, time as _t
a2 = ls.add_asset(pid, "orphan.png", b"x", ROOT); p2 = ls.asset_path(pid, a2, ROOT)
g = ls.get(pid, ROOT)["graph"]; g = ls.save_graph(pid, g, g["rev"], ROOT)
assert p2.is_file(), "a fresh upload must survive a save"
_os.utime(p2, (_t.time() - 600, _t.time() - 600)); g = ls.save_graph(pid, g, g["rev"], ROOT)
assert not p2.exists() and ls.asset_path(pid, a, ROOT), "an unused old file goes, a used one stays"
a3 = ls.add_asset(pid, "all-FlowlyStack.png", b"y", ROOT); n3 = ls.rename_asset(pid, a3, "fs", ROOT)
assert n3 == a3[:11] + "fs.png" and ls.asset_path(pid, n3, ROOT) and not ls.asset_path(pid, a3, ROOT), "rename keeps the id prefix and the extension"
raises(ls.Invalid, ls.rename_asset, pid, n3, " ", ROOT); a4 = ls.add_asset(pid, "z.png", b"z", ROOT)
raises(ls.Invalid, ls.rename_asset, pid, a4, "fs", ROOT) if a4[:11] == n3[:11] else None
assert ls.rename_asset(pid, "a-00000000-nope.png", "x", ROOT) is None
step("assets: unused files are swept, a file can be renamed")
step("assemble: undefined list, typed values, context switch, reference path")

# --- delete a block and restore it ---
g = ls.get(pid, ROOT)["graph"]
n_links = len(g["links"])
g2 = copy.deepcopy(g)
g2["blocks"] = [b for b in g2["blocks"] if b["id"] != "hero"]
g2["links"] = [l for l in g2["links"] if "hero" not in (l["from"], l["to"])]
g2 = ls.save_graph(pid, g2, g["rev"], ROOT)
assert "hero" not in {b["id"] for b in g2["blocks"]} and ls.get(pid, ROOT)["removed"] == ["hero"]
assert not (ROOT / pid / "blocks" / "hero.md").exists() and (ROOT / pid / ".removed" / "hero" / "hero.md").is_file()
back = ls.restore_block(pid, "hero", ROOT)
assert "hero" in {b["id"] for b in back["blocks"]} and len(back["links"]) == n_links
assert ls.read_text(pid, "hero", ROOT) == "Build the hero for {{site}}." and len(ls.revisions(pid, "hero", ROOT)) == 3
assert ls.get(pid, ROOT)["removed"] == [] and ls.restore_block(pid, "hero", ROOT) is None
sg = copy.deepcopy(back)
sg["blocks"] = [b for b in sg["blocks"] if b["type"] != "start"]
sg["links"] = [l for l in sg["links"] if start not in (l["from"], l["to"])]
raises(ls.Invalid, ls.save_graph, pid, sg, back["rev"], ROOT)
step("delete block: files and links parked in .removed, restored with text, versions and links; Start cannot be deleted")

# --- Undo on the canvas: saving a graph that contains the deleted block again brings its files back ---
g = ls.get(pid, ROOT)["graph"]
g3 = copy.deepcopy(g)
g3["blocks"] = [b for b in g3["blocks"] if b["id"] != "hero"]
g3["links"] = [l for l in g3["links"] if "hero" not in (l["from"], l["to"])]
ls.save_graph(pid, g3, g["rev"], ROOT)
assert ls.get(pid, ROOT)["removed"] == ["hero"]
ls.save_graph(pid, g, ls.get(pid, ROOT)["graph"]["rev"], ROOT)
assert ls.get(pid, ROOT)["removed"] == [] and ls.read_text(pid, "hero", ROOT) == "Build the hero for {{site}}." and len(ls.revisions(pid, "hero", ROOT)) == 3
step("undo of a delete: the same graph saved again restores the block's text and versions from .removed")

# --- purge of removed blocks ---
g = ls.get(pid, ROOT)["graph"]
g["blocks"] = [b for b in g["blocks"] if b["id"] != "contact"]
g["links"] = [l for l in g["links"] if "contact" not in (l["from"], l["to"])]
ls.save_graph(pid, g, g["rev"], ROOT)
assert ls.purge_removed(0, ROOT) == 0 and ls.purge_removed(30, ROOT) == 0
rec = ROOT / pid / ".removed" / "contact" / "block.json"
o = json.loads(rec.read_text())
o["removed_at"] = time.time() - 40 * 86400
rec.write_text(json.dumps(o))
assert ls.purge_removed(30, ROOT) == 1 and ls.get(pid, ROOT)["removed"] == []
step("purge_removed: only entries older than the limit; 0 keeps all")

# --- duplicate ---
dup = ls.duplicate(pid, ROOT)
did = dup["project"]["id"]
assert did != pid and dup["project"]["name"] == "Site copy" and not dup["project"]["star"]
assert dup["graph"] == ls.get(pid, ROOT)["graph"] and dup["texts"] == ls.get(pid, ROOT)["texts"]
assert ls.asset_path(did, a, ROOT).read_bytes() == b"\x89PNG-data" and ls.revisions(did, "hero", ROOT) == ls.revisions(pid, "hero", ROOT)
ls.save_text(did, "hero", "changed in the copy", "", ROOT)
assert ls.read_text(pid, "hero", ROOT) == "Build the hero for {{site}}."      # the copy is independent
assert ls.duplicate("ls-ffffffffffff", ROOT) is None
step("duplicate: graph, texts, versions and assets copied; the copy is independent")

# --- list ---
ls.create("Blog migration", ROOT)
ls.update(did, {"tags": ["web"]}, ROOT)
lst = ls.list_projects(ROOT)
assert lst["total"] == 3 and {i["name"] for i in lst["items"]} == {"Site", "Site copy", "Blog migration"}
it = next(i for i in lst["items"] if i["id"] == pid)
assert (it["steps"], it["done"], it["next"], it["brief"]) == (3, 1, "SEO", "A portfolio for {{site}}.")   # Contact was deleted above and it["thumb"]["blocks"] and "_hay" not in it
assert [i["name"] for i in ls.list_projects(ROOT, q="blog")["items"]] == ["Blog migration"]
assert [i["name"] for i in ls.list_projects(ROOT, q="hero")["items"]] != ["Blog migration"]     # block titles are searched
assert ls.list_projects(ROOT, q="portfolio")["total"] == 2                                      # the brief is searched
assert {i["name"] for i in ls.list_projects(ROOT, tags=["web"])["items"]} == {"Site", "Site copy"}
assert ls.list_projects(ROOT, tags=["web", "nope"])["total"] == 0
assert ls.list_projects(ROOT)["tags"] == {"web": 2, "portfolio": 1}
assert [i["name"] for i in ls.list_projects(ROOT, show="starred")["items"]] == ["Site"]
assert {i["name"] for i in ls.list_projects(ROOT, show="progress")["items"]} == {"Site", "Site copy"}
assert [i["name"] for i in ls.list_projects(ROOT, sort="name", desc=False)["items"]] == ["Blog migration", "Site", "Site copy"]
assert ls.list_projects(ROOT, page=2, page_size=2)["items"] and len(ls.list_projects(ROOT, page=2, page_size=2)["items"]) == 1
step("list: search over name, brief and block titles, AND tags with counts, show, sort, paging, thumbnail data")

# --- export and re-import ---
ex = ls.export_json(pid, ROOT)
assert ex["format"] == ls.FORMAT and ex["assets"][a]
re = ls.import_json(json.loads(json.dumps(ex)), ROOT)
rid = re["project"]["id"]
assert rid not in (pid, did)
cur = ls.get(pid, ROOT)
clean = lambda bs: [{**b, "status": "todo", "status_at": 0, "note": ""} for b in bs]   # an export is a clean plan: no status, no step notes
assert all(b["status"] == "todo" and b["status_at"] == 0 and not b["note"] for b in ex["graph"]["blocks"])
assert re["graph"]["blocks"] == clean(cur["graph"]["blocks"]) and re["graph"]["links"] == cur["graph"]["links"] and re["graph"]["frames"] == cur["graph"]["frames"]
assert re["texts"] == cur["texts"] and "variables" not in ex["project"] and re["project"]["tags"] == cur["project"]["tags"]
for bid in re["texts"]:
    assert ls.revisions(rid, bid, ROOT) == ls.revisions(pid, bid, ROOT)
assert ls.asset_path(rid, a, ROOT).read_bytes() == b"\x89PNG-data"
assert ls.export_json(rid, ROOT)["blocks"] == ex["blocks"]
raises(ls.Invalid, ls.import_json, {"format": "other"}, ROOT)
bad = json.loads(json.dumps(ex))
bad["assets"]["../x"] = ""
raises(ls.Invalid, ls.import_json, bad, ROOT)
assert not list(ROOT.glob("*/../x"))
bad = json.loads(json.dumps(ex))
bad["graph"]["links"].append(link("seo", "scaffold"))
raises(ls.Invalid, ls.import_json, bad, ROOT)
step("export and import: new project with identical graph, texts, versions, settings and assets; bad exports refused")

# --- markdown ---
md = ls.export_markdown(pid, ROOT)
assert md.startswith("# Site\n\n> A FlowlyStack Linkshell plan.") and "## Brief\n\nA portfolio for {{site}}." in md
assert md.index("## Phase 1") < md.index("### 1. Scaffold") < md.index("## Other prompts") < md.index("### 2. Hero") < md.index("### 3. SEO")   # frames first, then unframed steps
assert "## Phase 1" in md and "Scaffold {{site}}" in md and ls.asset_path(pid, a, ROOT).name in md
assert "```prompt\nScaffold {{site}}" in md and "```text" not in md and "```markdown" not in md, "the fences are labelled prompt, spec and reference"
assert "#### References\n\n```reference\n- " in md and "#### Spec: Design tokens" not in md, "the Design tokens spec is switched off for Scaffold earlier in this check"
assert ls.export_markdown("ls-ffffffffffff", ROOT) is None
pl = ex["plan"]
flat = [p for ph in pl["phases"] for p in ph["prompts"]]
assert pl["name"] == "Site" and pl["brief"].startswith("A portfolio") and [p["n"] for p in flat] == list(range(1, len(flat) + 1))
assert flat[0]["title"] == "Scaffold" and all(set(p) == {"n", "id", "title", "agent", "after", "text", "specs", "references"} for p in flat)
assert all(x < p["n"] for p in flat for x in p["after"]) and "status" not in json.dumps(pl)
assert "Agent: claude" in md and "#### " in md or not any(p["specs"] or p["references"] for p in flat)
step("markdown spec pack: brief, frames, prompts in run order with reference paths")

# --- a Spec or Reference linked FROM the prompt (the canvas draws no arrows) comes along exactly like one linked INTO it ---
rp = ls.create("Reversed", ROOT, brief="Direction does not matter.")
rvid, rg = rp["project"]["id"], copy.deepcopy(rp["graph"])
rst = rg["blocks"][0]["id"]
rg["blocks"] += [block("p1", "prompt", "Build", 280, 80), block("s1", "spec", "Colours", 280, 200), block("r1", "reference", "Shot", 280, 300, urls=["https://example.com/ref"], file_notes={})]
rg["links"] = [link(rst, "p1"), link("p1", "s1", "order"), link("p1", "r1", "order")]   # both dragged OUT of the prompt
rg = ls.save_graph(rvid, rg, rg["rev"], ROOT)
ls.save_text(rvid, "p1", "Build the page.", "", ROOT)
ls.save_text(rvid, "s1", "Teal on dark.", "", ROOT)
asm = ls.assemble(rvid, "p1", root=ROOT)
assert "## Colours\nTeal on dark." in asm["text"] and "https://example.com/ref" in asm["text"], asm["text"]
rpl = ls.export_plan(rvid, ROOT)["phases"][0]["prompts"][0]
assert [s["title"] for s in rpl["specs"]] == ["Colours"] and rpl["references"] == ["https://example.com/ref"], rpl
rg["links"].append(link("s1", "p1", "context"))   # linked both ways: still attached once
rg = ls.save_graph(rvid, rg, rg["rev"], ROOT)
assert ls.assemble(rvid, "p1", root=ROOT)["text"].count("## Colours") == 1 and len(ls.export_plan(rvid, ROOT)["phases"][0]["prompts"][0]["specs"]) == 1
rmd = ls.export_markdown(rvid, ROOT)
assert "```spec\nTeal on dark.\n```" in rmd and "```reference\n- https://example.com/ref\n```" in rmd
assert rmd.count("```prompt") == 1 and "```text" not in rmd
assert ls.trash(rvid, ROOT) and ls.purge(rvid, ROOT)   # the later checks count the projects: leave none behind
step("a Spec or Reference linked from the prompt is attached like one linked into it, once; both exports carry them")

# --- the zip to share: plan.md with relative asset paths, plus exactly the reference files the plan lists ---
import io as _io, zipfile as _zf
g = ls.get(pid, ROOT)["graph"]
{b["id"]: b for b in g["blocks"]}["shot"]["file_notes"] = {a: "Keep the grid."}
g = ls.save_graph(pid, g, g["rev"], ROOT)
zb = ls.export_zip(pid, ROOT)
z = _zf.ZipFile(_io.BytesIO(zb))
assert set(z.namelist()) == {"plan.md", f"assets/{a}"}, z.namelist()
zmd = z.read("plan.md").decode()
assert f"- assets/{a}\n  Note: Keep the grid." in zmd and ls.assets_alias(pid, ROOT) not in zmd and "```reference" in zmd and "next to this file" in zmd
assert z.read(f"assets/{a}") == ls.asset_path(pid, a, ROOT).read_bytes()
assert f"- {ls.assets_alias(pid, ROOT)}/{a}" in ls.export_markdown(pid, ROOT) and "next to this file" not in ls.export_markdown(pid, ROOT)   # the plain Markdown export is unchanged
assert ls.export_zip("ls-ffffffffffff", ROOT) is None
g = ls.get(pid, ROOT)["graph"]
{b["id"]: b for b in g["blocks"]}["shot"]["file_notes"] = {}
g = ls.save_graph(pid, g, g["rev"], ROOT)
step("export to share: zip with plan.md (relative paths, notes kept) and the listed reference files only; no path from this computer; plain Markdown unchanged")

# --- project properties: the user's own name and value pairs, kept in the project and written into both exports ---
assert ls.get(pid, ROOT)["project"]["properties"] == []
up = ls.update(pid, {"properties": [{"key": "Purpose", "value": "Portfolio"}, {"key": "stack", "value": "html\ncss"}, {"key": "empty", "value": ""}]}, ROOT)
assert [q["key"] for q in up["properties"]] == ["Purpose", "stack", "empty"]
for bad_props in ([{"key": "", "value": "x"}], [{"key": "Title", "value": "x"}], [{"key": "a", "value": "1"}, {"key": "A", "value": "2"}], "nope"):
    raises(ls.Invalid, ls.update, pid, {"properties": bad_props}, ROOT)
assert ls.get(pid, ROOT)["project"]["properties"] == up["properties"]   # a refused list changes nothing
pj, pm = ls.export_json(pid, ROOT), ls.export_markdown(pid, ROOT)
assert pj["plan"]["properties"] == {"Purpose": "Portfolio", "stack": "html\ncss"}   # empty values are left out of the readable plan
assert pm.startswith('---\nPurpose: "Portfolio"\nstack: |-\n  html\n  css\n---\n\n# Site\n')
pr = ls.import_json(json.loads(json.dumps(pj)), ROOT)
assert pr["project"]["properties"] == up["properties"]
ls.update(pid, {"properties": []}, ROOT)
assert ls.export_markdown(pid, ROOT).startswith("# Site\n") and ls.export_json(pid, ROOT)["plan"]["properties"] == {}
assert ls.trash(pr["project"]["id"], ROOT) and ls.purge(pr["project"]["id"], ROOT)   # leave the later counts as they were
step("properties: saved and validated like Studio's, in the Markdown header and the JSON plan, restored on import")

# --- trash, restore, purge ---
assert ls.trash(did, ROOT) and ls.get(did, ROOT) is None and not (ROOT / did).exists()
rows = ls.load_trash(ROOT)
assert [r["id"] for r in rows] == [did] and rows[0]["store"] == "linkshell" and rows[0]["deleted_at"] > 0
assert did in ls._taken_ids(ROOT)                                      # a trashed id is never reused
assert ls.list_projects(ROOT)["total"] == 3 and not ls.trash(did, ROOT)
assert ls.restore(did, ROOT) and ls.get(did, ROOT)["project"].get("deleted_at") is None and ls.load_trash(ROOT) == []
ls.trash(did, ROOT)
assert ls.purge(did, ROOT) and not ls.purge(did, ROOT) and ls.load_trash(ROOT) == [] and not list((ROOT / ".trash").glob("*/*"))
ls.trash(rid, ROOT)
f = next((ROOT / ".trash").glob(f"*/{rid}/project.json"))
o = json.loads(f.read_text())
o["deleted_at"] = time.time() - 40 * 86400
f.write_text(json.dumps(o))
assert ls.purge_expired(0, ROOT) == 0 and ls.purge_expired(30, ROOT) == 1
ls.trash(ls.create("Throwaway", ROOT)["project"]["id"], ROOT)
assert ls.empty_trash(ROOT) == 1 and ls.load_trash(ROOT) == []
step("trash: move, list, id stays taken, restore, purge, expiry, empty")

# --- two saves at the same moment (a double click, a second tab): none fails, every version is kept ---
import threading   # noqa: E402
cp = ls.create("Concurrent", ROOT)
cpid, cbid = cp["project"]["id"], cp["graph"]["blocks"][0]["id"]
g = cp["graph"]
g["blocks"].append({"id": "pp", "type": "prompt", "title": "P", "x": 0, "y": 0, "w": 190, "h": 88})
ls.save_graph(cpid, g, cp["graph"]["rev"], ROOT)
errs = []
def hit(i):
    try:
        ls.save_text(cpid, "pp", f"text {i}", f"v{i}", ROOT)
    except Exception as e:   # noqa: BLE001
        errs.append(e)
ts = [threading.Thread(target=hit, args=(i,)) for i in range(12)]
[t.start() for t in ts]; [t.join() for t in ts]
assert not errs, errs
assert len(ls.revisions(cpid, "pp", ROOT)) == 12 and len({r["id"] for r in ls.revisions(cpid, "pp", ROOT)}) == 12
step("concurrent saves of one block: no error, all 12 versions kept")

# --- nothing half-written, nothing else touched ---
assert not list(ROOT.rglob("*.tmp"))
assert tree_hash(LIB) == before
step("no temp files left; Library and Studio folders unchanged")

print("\nall Linkshell storage checks passed")
