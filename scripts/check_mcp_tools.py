#!/usr/bin/env python3
"""Checks for the MCP read tools (backend/mcp/tools_*.py). Plain asserts, no server: it seeds temp folders and calls the
tools through the protocol layer, as an agent would. Needs numpy (Gallery), so run it with the project's Python:

    .venv/bin/python scripts/check_mcp_tools.py

Everything lives in a temp folder; your real prompts, settings, vectors and Linkshell projects are never touched. No model and no service is contacted.
"""
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="flowlystack-mcp-tools-"))
os.environ.update(FLOWLYSTACK_PROMPTS_DIR=str(TMP / "prompts"), FLOWLYSTACK_SETTINGS_DIR=str(TMP / "settings"), FLOWLYSTACK_ALIAS_DIR=str(TMP / "alias"),
                  FLOWLYSTACK_MEILI_URL="http://127.0.0.1:1")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import collections as co  # noqa: E402
from backend import gallery_api, linkshell as ls, promptstore as ps  # noqa: E402
from backend.mcp import server  # noqa: E402
from backend.rag import service  # noqa: E402

assert str(ps.PROMPTS_DIR).startswith(str(TMP)), "the prompts folder must be the temp one"


def step(msg):
    print("ok  ", msg)


def call(name, args=None, scope="read"):
    st, b = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args or {}}}, {}, {"scope": scope, "name": "t", "id": "t-1"})
    r = b["result"]
    text = r["content"][0]["text"]
    assert len(text) <= server.MAX_OUT
    if r["isError"]:
        return True, text
    out = json.loads(text)
    assert out["notice"] == server.NOTICE
    return False, out


def ok(name, args=None):
    err, out = call(name, args)
    assert not err, (name, args, out)
    return out


def fails(name, args, needle):
    err, out = call(name, args)
    assert err and needle.lower() in out.lower(), (name, args, out)


try:
    # ---------- seed ----------
    now = time.time() - 40 * 3600
    topics = [("docker", "Write a Dockerfile and compose file for the %s service, with a healthcheck and a non-root user"),
              ("recipe", "Suggest a weeknight dinner recipe using %s, ready in thirty minutes, for two people"),
              ("sql", "Explain this %s query plan and propose an index that would make the report faster")]
    lib = {}
    for i in range(30):
        word, tpl = topics[i % 3]
        lib[i] = ps.write_prompt(tpl % ["api", "tomato", "orders"][i % 3] + f" variation {i}", now + i * 600, f"sess{i % 4}", "/work/proj",
                                 extra={"agent": "codex" if i % 5 == 0 else "claude"})
    dup = "Please review the pull request for security problems, list each finding with severity and a fix, and keep the answer short"
    dups = [ps.write_prompt(dup + (" now" if k % 2 else ""), now + 90000 + k * 60, "dupsess") for k in range(4)]
    ps.update_meta(lib[0], {"tags": ["infra", "docker"], "note": "my favourite", "starred": True})
    ps.update_meta(lib[1], {"tags": ["food"]})
    ps.update_meta(lib[3], {"tags": ["infra"], "title": "Compose helper"})
    step("seeded 34 Library prompts (two agents, tags, a title, four near-duplicates)")

    # ---------- Library ----------
    r = ok("library_search", {"query": "dockerfile"})
    assert r["total_matches"] == 10 and r["returned"] == 10 and all(set(i) >= {"id", "title", "excerpt", "tags", "agent", "updated"} for i in r["items"])
    assert all("" not in i["excerpt"] and "" not in i["excerpt"] for i in r["items"]), "match markers must not leak"
    assert len(ok("library_search", {"query": "dockerfile", "limit": 3})["items"]) == 3
    assert ok("library_search", {"query": "dockerfile", "agent": "codex"})["total_matches"] == 2
    assert ok("library_search", {"tags": ["infra"]})["total_matches"] == 2 and ok("library_search", {"tags": ["infra", "docker"]})["total_matches"] == 1
    assert ok("library_search", {"starred": True})["items"][0]["id"] == lib[0]
    newest = ok("library_search", {"limit": 2})
    assert newest["total_matches"] == 34 and newest["items"][0]["updated"] >= newest["items"][1]["updated"]
    assert ok("library_search", {"query": "zzzqqq"})["items"] == []
    fails("library_search", {"limit": 0}, "between")
    fails("library_search", {"limit": 101}, "between")
    fails("library_search", {"query": "x" * 201}, "wrong length")
    step("library_search: ranked excerpts without markers, tag AND filter, agent, starred, newest first, limit and bad arguments")

    g = ok("library_get", {"id": lib[0]})
    assert g["text"].startswith("Write a Dockerfile") and g["tags"] == ["infra", "docker"] and g["note"] == "my favourite" and g["starred"] and g["agent"] == "codex"
    assert g["truncated"] is False and g["versions"] == [] and g["created"] and g["updated"]
    ps.save_text(lib[0], "Write a Dockerfile (edited)", "tightened")
    g = ok("library_get", {"id": lib[0]})
    assert g["text"] == "Write a Dockerfile (edited)" and len(g["versions"]) == 2 and g["versions"][0]["message"] == "tightened"
    fails("library_get", {"id": "nope"}, "No Library prompt")
    fails("library_get", {"id": "ps-0123456789ab"}, "No Library prompt")
    fails("library_get", {"id": "ps-0123456789ab"}, "studio_get")   # a Studio-looking id points to the right tool
    fails("library_get", {"id": "nope"}, "library_search")
    # tags ignore case (the app's own filter stays exact; the tool matches the stored spelling first)
    assert {i["id"] for i in ok("library_search", {"tags": ["INFRA"]})["items"]} == {i["id"] for i in ok("library_search", {"tags": ["infra"]})["items"]} and ok("library_search", {"tags": ["Infra"]})["items"]
    assert not ok("library_search", {"tags": ["nosuchtag"]})["items"]
    big = ps.write_prompt("B" * 150_000, now + 5, "big")
    gb = ok("library_get", {"id": big})
    assert gb["truncated"] is True and len(gb["text"]) == 100_000
    tg = ok("library_list_tags")
    assert tg["tags"][0] == {"name": "infra", "n": 2} and {"name": "food", "n": 1} in tg["tags"] and tg["total_tags"] == 3
    assert len(ok("library_list_tags", {"limit": 1})["tags"]) == 1
    step("library_get (full text, versions, 100 KB cap, other stores' ids refused) and library_list_tags")

    # ---------- Studio ----------
    s1 = ps.create_studio("Summarise the text below in three bullets.", "Bullet summary", ["writing"])["id"]
    s2 = ps.create_studio("You are a careful code reviewer. List risks first.", "Reviewer", ["code", "writing"], {"store": "library", "id": dups[0]})["id"]
    ps.update_meta(s1, {"status": "refined", "purpose": "Quick summaries", "target": "claude"}, ps.STUDIO_DIR)
    ps.save_text(s1, "Summarise the text below in exactly three bullets, plain words.", "stricter", ps.STUDIO_DIR)
    r = ok("studio_search", {"query": "summarise"})
    assert r["total_matches"] == 1 and r["items"][0]["id"] == s1 and r["items"][0]["status"] == "refined" and r["items"][0]["purpose"] == "Quick summaries"
    assert [i["id"] for i in ok("studio_search", {"status": "draft"})["items"]] == [s2]
    assert ok("studio_search", {"tags": ["writing"]})["total_matches"] == 2
    assert ok("studio_search", {"query": "reviewer"})["items"][0]["derived_from"] == {"store": "library", "id": dups[0]}
    fails("studio_search", {"status": "weird"}, "one of")
    assert s1 not in json.dumps(ok("library_search", {"limit": 100})), "Studio prompts are not in the Library"
    step("studio_search: query, status, tags, derived_from; Studio and Library stay apart")

    sg = ok("studio_get", {"id": s1})
    assert sg["text"].endswith("plain words.") and sg["status"] == "refined" and sg["target"] == "claude" and len(sg["versions"]) == 2 and sg["versions"][0]["message"] == "stricter"
    fails("studio_get", {"id": lib[0]}, "start with ps-")
    fails("studio_get", {"id": "ps-ffffffffffff"}, "No Studio prompt")
    ps.save_text(s2, "C" * 150_000, "huge", ps.STUDIO_DIR)
    sb = ok("studio_get", {"id": s2})
    assert sb["truncated"] is True and len(sb["text"]) == 100_000
    vs = ok("studio_versions", {"id": s1})["versions"]
    assert [v["message"] for v in vs] == ["stricter", "Created"]
    d = ok("studio_diff", {"id": s1, "a": vs[1]["id"]})
    assert d["changed"] and "-Summarise the text below in three bullets." in d["diff"] and "+Summarise the text below in exactly three bullets, plain words." in d["diff"]
    assert d["a"]["message"] == "Created" and d["b"]["id"] == "current"
    d2 = ok("studio_diff", {"id": s1, "a": vs[1]["id"], "b": vs[0]["id"]})
    assert d2["changed"] and d2["b"]["id"] == vs[0]["id"]
    assert ok("studio_diff", {"id": s1, "a": vs[0]["id"]})["changed"] is False
    fails("studio_diff", {"id": s1, "a": "deadbeef"}, "studio_versions")
    fails("studio_diff", {"id": s1, "a": vs[0]["id"], "b": "deadbeef"}, "studio_versions")
    step("studio_get / studio_versions / studio_diff (unified diff, current by default, 100 KB cap, bad ids explain themselves)")

    # ---------- Collections ----------
    cid = co.create("Field notes", "Notes from the road", ["travel"])["id"]
    co.add_document(cid, "notes.md", b"# Zebra protocol\n\nThe zebra protocol says every herd must cross the river at dawn.\n\n## Lions\n\nLions wait downstream.\n")
    r = ok("collections_list")
    byid = {c["id"]: c for c in r["collections"]}
    assert r["collections"][0]["id"] == "prompts" and byid["prompts"]["built_in"] is True and byid["prompts"]["documents"] >= 36
    assert byid[cid]["name"] == "Field notes" and byid[cid]["documents"] == 1 and byid[cid]["tags"] == ["travel"] and byid[cid]["built_in"] is False
    step("collections_list: My prompts first (built in), then the user's collections with counts")

    r = ok("collections_search", {"query": "zebra herd river dawn"})
    assert r["mode"] == "keyword" and "embedding model" in r["note"].lower()
    assert r["passages"] and r["passages"][0]["source"] == "document" and r["passages"][0]["name"] == "notes.md" and "zebra" in r["passages"][0]["text"].lower()
    assert set(r["passages"][0]) == {"id", "ref", "source", "name", "locator", "text", "truncated", "tags", "collections", "score", "vector_score", "keyword_rank"} and 0 <= r["passages"][0]["score"] <= 1
    rp = ok("collections_search", {"query": "dockerfile healthcheck", "scope": ["prompts"]})
    assert rp["passages"] and all(p["source"] in ("library", "studio") for p in rp["passages"])
    assert not ok("collections_search", {"query": "zebra", "scope": ["prompts"]})["passages"]
    assert ok("collections_search", {"query": "zebra", "scope": [cid]})["passages"]
    assert not ok("collections_search", {"query": "dockerfile", "source": "document"})["passages"]
    assert all(p["source"] == "studio" for p in ok("collections_search", {"query": "summarise", "source": "studio"})["passages"])
    assert len(ok("collections_search", {"query": "dockerfile", "k": 2})["passages"]) == 2
    fails("collections_search", {"query": ""}, "wrong length")
    fails("collections_search", {"query": "x", "k": 31}, "between")
    fails("collections_search", {"query": "x", "min_relevance": 1.5}, "between")
    fails("collections_search", {"query": "x", "min_relevance": "high"}, "must be a number")
    # min_relevance: off by default (no left_out keys); keyword-only passages have no meaning score, so a cutoff never drops them
    assert "left_out" not in ok("collections_search", {"query": "zebra"})
    rc = ok("collections_search", {"query": "zebra herd river dawn", "min_relevance": 0.9})
    assert rc["passages"] and rc["left_out"] == 0 and rc["best_vector_score"] is None and rc["passages"][0]["vector_score"] is None and rc["passages"][0]["keyword_rank"] == 1
    assert ok("collections_search", {"query": "dockerfile", "tags": ["INFRA"], "scope": ["prompts"]})["passages"]   # tag case
    # min_relevance with meaning scores: stand-in retrieval (no model here). Low score + no keyword match is dropped; a keyword match always stays.
    from backend.rag import retrieval as _ret
    _fake = lambda sc, kr, i: {"id": f"p{i}", "ref": f"r{i}", "source": "library", "name": f"n{i}", "locator": "", "text": "t", "tags": [], "collections": ["prompts"], "score": 0.5, "vector_score": sc, "keyword_rank": kr}
    _real, _seen = _ret.search, {}

    def _stub(ix, prov, q, scope=None, source="", tags=None, k=6):
        _seen["k"] = k
        return {"mode": "hybrid", "note": "", "passages": [_fake(0.8, None, 1), _fake(0.3, None, 2), _fake(0.3, 1, 3), _fake(0.7, 2, 4)]}
    _ret.search = _stub
    try:
        rc = ok("collections_search", {"query": "q", "min_relevance": 0.6, "k": 4})
        assert [p["id"] for p in rc["passages"]] == ["p1", "p3", "p4"] and rc["left_out"] == 1 and rc["best_vector_score"] == 0.8 and _seen["k"] == 12
        r0 = ok("collections_search", {"query": "q", "k": 4})
        assert len(r0["passages"]) == 4 and "left_out" not in r0 and _seen["k"] == 4
        assert len(ok("collections_search", {"query": "q", "min_relevance": 0.6, "k": 2})["passages"]) == 2
    finally:
        _ret.search = _real
    step("collections_search: keyword-only with a note when no embedding model; scope, source and k work; nothing is sent to a model")

    gp = ok("collections_get_prompt", {"id": s1})
    assert gp["store"] == "studio" and gp["title"] == "Bullet summary" and gp["text"].endswith("plain words.")
    assert ok("collections_get_prompt", {"id": lib[0]})["store"] == "library"
    fails("collections_get_prompt", {"id": "nope"}, "No saved prompt")
    lt = ok("collections_list_by_tag", {"tag": "writing"})
    assert lt["returned"] == 2 and {i["id"] for i in lt["items"]} == {s1, s2} and all(i["store"] == "studio" for i in lt["items"])
    assert ok("collections_list_by_tag", {"tag": "infra"})["returned"] == 2
    lc = ok("collections_list_by_tag", {"tag": "INFRA"})
    assert lc["returned"] == 2 and lc["tag"] == "infra"
    assert {i["id"] for i in ok("studio_search", {"tags": ["WRITING"]})["items"]} == {s1, s2}
    step("collections_get_prompt and collections_list_by_tag")

    # ---------- Linkshell ----------
    p = ls.create("Launch plan", brief="Ship the beta by Friday.\nKeep scope small.")
    pid, g0 = p["project"]["id"], p["graph"]
    start = g0["blocks"][0]
    start["status"] = "done"
    g0["blocks"] += [{"id": "b-one", "type": "prompt", "title": "Write the spec", "x": 300, "y": 0, "frame": "f-1"},
                     {"id": "b-two", "type": "prompt", "title": "Build it", "x": 600, "y": 0, "frame": "f-1", "agent": "codex"},
                     {"id": "b-spec", "type": "spec", "title": "House rules", "x": 300, "y": 200},
                     {"id": "b-ref", "type": "reference", "title": "Docs", "x": 300, "y": 300, "urls": ["https://example.com/docs"]},
                     {"id": "b-note", "type": "note", "title": "Remember", "x": 0, "y": 300}]
    g0["frames"] = [{"id": "f-1", "title": "Phase 1", "x": 280, "y": -40, "w": 600, "h": 200}]
    g0["links"] = [{"from": start["id"], "to": "b-one", "kind": "order"}, {"from": "b-one", "to": "b-two", "kind": "order"},
                   {"from": "b-spec", "to": "b-one", "kind": "context"}, {"from": "b-ref", "to": "b-one", "kind": "context"}]
    ls.save_graph(pid, g0, g0["rev"])
    ls.save_text(pid, "b-one", "Write the spec for the beta.", "first")
    ls.save_text(pid, "b-one", "Write a one-page spec for the beta.", "tighter")
    ls.save_text(pid, "b-two", "Build the beta from the spec.")
    ls.save_text(pid, "b-spec", "Keep every answer under 200 words.")
    ls.save_text(pid, "b-note", "Do not forget the demo.")
    ls.update(pid, {"tags": ["launch"], "properties": [{"key": "owner", "value": "Alice"}]})

    r = ok("linkshell_list_projects")
    assert r["total_matches"] == 1 and r["items"][0]["id"] == pid and r["items"][0]["name"] == "Launch plan" and r["items"][0]["steps"] == 2
    assert r["items"][0]["next"] == "Write the spec" and r["items"][0]["tags"] == ["launch"] and r["items"][0]["brief"] == "Ship the beta by Friday."
    assert ok("linkshell_list_projects", {"query": "beta"})["total_matches"] == 1, "the brief is searched"
    assert ok("linkshell_list_projects", {"query": "spec"})["total_matches"] == 1, "block titles are searched"
    assert ok("linkshell_list_projects", {"query": "demo"})["total_matches"] == 0, "block bodies are not (that is the app's own rule)"
    assert ok("linkshell_list_projects", {"tags": ["nope"]})["items"] == []
    assert ok("linkshell_list_projects", {"tags": ["LAUNCH"]}) == ok("linkshell_list_projects", {"tags": ["launch"]}) and ok("linkshell_list_projects", {"tags": ["Launch"]})["total_matches"] >= 1
    pr = ok("linkshell_get_project", {"id": pid})
    assert pr["name"] == "Launch plan" and pr["brief"].startswith("Ship the beta") and pr["properties"] == {"owner": "Alice"} and pr["run_order"] == ["b-one", "b-two"]
    by = {b["id"]: b for b in pr["blocks"]}
    assert by["b-one"]["status"] == "ready" and by["b-two"]["status"] == "todo" and by["b-two"]["agent"] == "codex" and by["b-ref"]["urls"] == ["https://example.com/docs"]
    assert by["b-one"]["frame"] == "f-1" and pr["frames"] == [{"id": "f-1", "title": "Phase 1"}] and {"from": "b-spec", "to": "b-one", "kind": "context"} in pr["links"]
    assert "Write a one-page spec" not in json.dumps(pr), "block texts are not in the structure"
    fails("linkshell_get_project", {"id": "ls-ffffffffffff"}, "No Linkshell project")
    fails("linkshell_get_project", {"id": "../x"}, "No Linkshell project")
    step("linkshell_list_projects / linkshell_get_project: progress, ready state, run order, links, properties; unsafe ids are just unknown")

    bl = ok("linkshell_get_block", {"project": pid, "block": "b-one"})
    assert bl["text"] == "Write a one-page spec for the beta." and bl["type"] == "prompt" and bl["status"] == "ready"
    assert [v["message"] for v in bl["versions"]] == ["tighter", "first"] and bl["versions"][0]["current"] is True
    assert ok("linkshell_get_block", {"project": pid, "block": "b-note"})["versions"] == []
    fails("linkshell_get_block", {"project": pid, "block": "b-nope"}, "no block")
    fails("linkshell_get_block", {"project": "ls-ffffffffffff", "block": "b-one"}, "No Linkshell project")
    asm = ok("linkshell_assemble", {"project": pid, "block": "b-one"})
    assert asm["text"].startswith("Write a one-page spec for the beta.") and "## House rules\nKeep every answer under 200 words." in asm["text"]
    assert "https://example.com/docs" in asm["text"] and asm["references"] == ["https://example.com/docs"]
    fails("linkshell_assemble", {"project": pid, "block": "b-spec"}, "not a Prompt block")
    plan = ok("linkshell_export_plan", {"project": pid})["plan"]
    assert plan["name"] == "Launch plan" and plan["brief"].startswith("Ship the beta") and plan["properties"] == {"owner": "Alice"}
    steps = [p_ for ph in plan["phases"] for p_ in ph["prompts"]]
    assert [s["id"] for s in steps] == ["b-one", "b-two"] and steps[1]["after"] == [1] and steps[0]["specs"][0]["title"] == "House rules"
    step("linkshell_get_block / linkshell_assemble / linkshell_export_plan match what Copy and the exports give")

    # ---------- Gallery ----------
    fails("gallery_overview", {}, "not been built")
    fails("gallery_repeats", {}, "not been built")
    gallery_api.get().build_now()
    ov = ok("gallery_overview")
    assert ov["prompts"] == 35 and ov["status"]["state"] in ("ready", "building") and ov["groups"] and ov["top_words"] and ov["library_prompts"] == 35
    assert ov["studio_prompts"] == 2 and "claude" in ov["agents"] and all({"id", "label", "prompts", "words"} <= set(g_) for g_ in ov["groups"])
    assert sum(g_["prompts"] for g_ in ov["groups"]) == 35
    st0 = ov["status"]
    assert st0["library_now"] == 35 and st0["newer_prompts"] == 0 and st0["removed_prompts"] == 0 and st0["out_of_date"] is False and "advice" not in st0
    late = ps.write_prompt("A prompt written after the snapshot.", now + 9, "late")
    ov2 = ok("gallery_overview")   # the snapshot is not rebuilt by a read tool
    assert ov2["prompts"] == 35 and ov2["status"]["library_now"] == 36 and ov2["status"]["newer_prompts"] == 1 and ov2["status"]["out_of_date"] is True
    assert "1 Library prompt(s) added" in ov2["status"]["advice"] and "Knowledge > Gallery" in ov2["status"]["advice"]
    assert ok("gallery_repeats")["status"]["newer_prompts"] == 1 and ok("gallery_group", {"id": ov["groups"][0]["id"]})["status"]["out_of_date"] is True
    ps.trash(late)
    assert ok("gallery_overview")["status"]["out_of_date"] is False, "back to the prompts the snapshot was built from"
    # an edit and a delete are noticed too (the counts of added prompts do not change for an edit)
    ps.save_text(lib[2], "Edited after the snapshot.", "edit")
    se = ok("gallery_overview")["status"]
    assert se["out_of_date"] is True and se["newer_prompts"] == 0 and se["removed_prompts"] == 0 and "edited" in se["advice"], se
    ps.save_text(lib[2], topics[2][1] % "orders" + " variation 2", "back")   # the original text again, then a rebuild makes it current
    gallery_api.get().build_now()
    assert ok("gallery_overview")["status"]["out_of_date"] is False
    ps.trash(lib[2])
    sd = ok("gallery_overview")["status"]
    assert sd["out_of_date"] is True and sd["removed_prompts"] == 1 and "1 removed" in sd["advice"], sd
    ps.restore(lib[2])
    gallery_api.get().build_now()
    assert ok("gallery_overview")["status"]["out_of_date"] is False
    rp = ok("gallery_repeats")
    assert rp["total_families"] >= 1
    fam = next(f for f in rp["families"] if set(f["ids"]) >= set(dups))
    for pid_ in fam["ids"]:
        assert ok("library_get", {"id": pid_})["text"], "family ids are Library prompt ids"
    assert fam["prompts"] >= 4 and fam["sample"] and len(ok("gallery_repeats", {"limit": 1})["families"]) == 1
    gid = ov["groups"][0]["id"]
    grp = ok("gallery_group", {"id": gid})
    assert grp["group"]["id"] == gid and grp["items"] and len(grp["items"]) == grp["group"]["prompts"]
    assert all(ok("library_get", {"id": i["id"]})["text"] for i in grp["items"][:3])
    assert [i["time"] for i in grp["items"]] == sorted((i["time"] for i in grp["items"]), reverse=True)
    assert len(ok("gallery_group", {"id": gid, "limit": 2})["items"]) == 2
    fails("gallery_group", {"id": 999}, "No group")
    step("Gallery tools: refuse to guess before a build (and never start one), then overview, repeat families and group members point at real Library ids")

    # an older project keeps one web link in `url` and one file in `asset`; the structure and block tools must show them like Assemble does
    old = ls.create("Older links")["project"]["id"]
    gp = ls._root(None) / old / "graph.json"
    gj = json.loads(gp.read_text())
    gj["blocks"].append({"id": "b-old", "type": "reference", "title": "Older reference", "x": 0, "y": 0, "w": 170, "h": 70, "frame": "", "agent": "", "status": "todo",
                         "note": "", "context_off": [], "status_at": 0, "url": "https://example.com/older", "asset": "a-0123456789.png"})
    gp.write_text(json.dumps(gj))
    ob = {b["id"]: b for b in ok("linkshell_get_project", {"id": old})["blocks"]}["b-old"]
    assert ob["urls"] == ["https://example.com/older"] and ob["files"] == ["a-0123456789.png"], ob
    gb = ok("linkshell_get_block", {"project": old, "block": "b-old"})
    assert gb["urls"] == ["https://example.com/older"] and gb["files"] == ["a-0123456789.png"]
    ls.trash(old)
    step("older Reference blocks (single url/asset) show their link and file in get_project and get_block")

    # ---------- the trash is invisible ----------
    ps.trash(lib[1])
    ps.trash(s2, ps.STUDIO_DIR)
    assert lib[1] not in json.dumps(ok("library_search", {"limit": 100})) and ok("library_search", {"tags": ["food"]})["total_matches"] == 0
    fails("library_get", {"id": lib[1]}, "No Library prompt")
    fails("studio_get", {"id": s2}, "No Studio prompt")
    assert s2 not in json.dumps(ok("studio_search", {})) and s2 not in json.dumps(ok("collections_list_by_tag", {"tag": "writing"}))
    fails("collections_get_prompt", {"id": s2}, "No saved prompt")
    assert ls.trash(pid) and ok("linkshell_list_projects")["total_matches"] == 0
    fails("linkshell_get_project", {"id": pid}, "No Linkshell project")
    step("trashed prompts and projects are gone from every tool")

    # ---------- nothing was written ----------
    tree = sorted(str(p_.relative_to(TMP)) for p_ in TMP.rglob("*") if p_.is_file() and "gallery" not in str(p_) and "index" not in p_.name)
    before = len(tree)
    for name in ("library_search", "studio_search", "collections_list", "collections_search", "gallery_overview", "linkshell_list_projects"):
        call(name, {"query": "x"} if name.endswith("search") else {})
    after = sorted(str(p_.relative_to(TMP)) for p_ in TMP.rglob("*") if p_.is_file() and "gallery" not in str(p_) and "index" not in p_.name)
    assert tree == after, set(after) ^ set(tree)
    step("calling the read tools writes no files")

    print("\nall MCP tool checks passed")
finally:
    try:
        service.get().close()
    except Exception:
        pass
    shutil.rmtree(TMP, ignore_errors=True)
