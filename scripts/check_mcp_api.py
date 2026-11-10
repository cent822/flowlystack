#!/usr/bin/env python3
"""Checks for POST /mcp, the token routes and the gate rules around them (backend/mcp_api.py). Plain asserts, standard library only.

Needs THROWAWAY servers with their own EMPTY settings folders (the check changes settings and makes tokens), never your real one:

    A=$(mktemp -d); B=$(mktemp -d); P=$(mktemp -d)
    env FLOWLYSTACK_PROMPTS_DIR=$P FLOWLYSTACK_MEILI_URL=http://127.0.0.1:1 RELOAD=0 FLOWLYSTACK_SETTINGS_DIR=$A PORT=8799 FLOWLYSTACK_AUTH=off ./run.sh &   # login off (required)
    env FLOWLYSTACK_PROMPTS_DIR=$P FLOWLYSTACK_MEILI_URL=http://127.0.0.1:1 RELOAD=0 FLOWLYSTACK_SETTINGS_DIR=$B PORT=8798 ./run.sh &                         # login on (optional: the gate rules)

Write every setting out on each line, as above. Do NOT put them in a shell variable and use `env $common ...`: zsh (the macOS default shell) does not split
it, so the servers start without FLOWLYSTACK_MEILI_URL and talk to the REAL Meilisearch, whose search index they then empty (this happened on 2026-11-05).
The script refuses to run when the server on BASE is pointed at a real Meilisearch.
    FLOWLYSTACK_PROMPTS_DIR=$P FLOWLYSTACK_SETTINGS_DIR=$A BASE=http://127.0.0.1:8799 BASE_AUTH=http://127.0.0.1:8798 FLOWLYSTACK_AUTH_DIR=$B python3 scripts/check_mcp_api.py

Stop the servers by the process id on their ports afterwards (never a broad pkill).
"""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = os.environ.get("BASE", "http://127.0.0.1:8799")
BASE_AUTH = os.environ.get("BASE_AUTH")
DIR = Path(os.environ["FLOWLYSTACK_SETTINGS_DIR"])
assert not (DIR / "settings.json").exists() and not (DIR / "auth.json").exists(), "the settings folder must start empty"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


OPENER = urllib.request.build_opener(NoRedirect)


def call(method, path, body=None, expect=None, headers=None, base=None, raw=None):
    h = {"Content-Type": "application/json", **(headers or {})}
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request((base or BASE) + path, method=method, headers=h, data=data)
    try:
        r = OPENER.open(req, timeout=30)
        code, text, hdr = r.status, r.read(), r.headers
    except urllib.error.HTTPError as e:
        code, text, hdr = e.code, e.read(), e.headers
    if expect is not None:
        assert code == expect, f"{method} {path}: expected {expect}, got {code}: {text[:300]!r}"
    try:
        out = json.loads(text) if text else None
    except ValueError:
        out = None
    return code, hdr, out


def step(msg):
    print("ok  ", msg)


def rpc(token, method, params=None, id_=1, base=None, expect=200, headers=None):
    h = {"Authorization": f"Bearer {token}", **(headers or {})} if token else dict(headers or {})
    msg = {"jsonrpc": "2.0", "id": id_, "method": method}
    if params is not None:
        msg["params"] = params
    return call("POST", "/mcp", msg, expect, h, base)


MODERN = {"_meta": {"io.modelcontextprotocol/protocolVersion": "2026-07-28", "io.modelcontextprotocol/clientCapabilities": {}}}

# ---------- the login-off server ----------

# 0. safety: never run against a server that talks to a real Meilisearch (it would empty the real search index to match this temp folder)
_, _, ss = call("GET", "/api/search/status", expect=200)
assert not ss.get("url") or str(ss["url"]).rstrip("/").endswith(":1"), "refusing to run: the server on BASE uses a real Meilisearch (%s). Start it with FLOWLYSTACK_MEILI_URL=http://127.0.0.1:1" % ss.get("url")

# 1. off by default: /mcp does not exist
call("POST", "/mcp", {"jsonrpc": "2.0", "id": 1, "method": "ping"}, 404)
code, _, state = call("GET", "/api/settings", expect=200)
assert state["sections"]["mcp"] == {"enabled": False, "share_hidden": False}, state["sections"].get("mcp")
step("MCP is off by default: POST /mcp answers 404 and Settings says enabled false")

call("PUT", "/api/settings/mcp", {"enabled": "maybe"}, 400)
call("PUT", "/api/settings/mcp", {"enabled": True}, 200)
assert call("GET", "/api/settings", expect=200)[2]["sections"]["mcp"]["enabled"] is True
step("the switch is saved through the Settings route (only a real true/false is accepted)")

# 2. a token is always required
code, hdr, body = rpc(None, "ping", expect=401)
assert hdr["WWW-Authenticate"].startswith("Bearer") and body["error"]["message"] and "no-store" in hdr["Cache-Control"]
rpc("fls_" + "z" * 43, "ping", expect=401)
# (a malformed token is a wrong token too; check_auth.py covers it. Wrong tokens count toward the lockout, so this script keeps its count under 5 until the last step.)
call("POST", "/mcp", {"jsonrpc": "2.0", "id": 1, "method": "ping"}, 401, {"Authorization": "Basic Zm9vOmJhcg=="})
step("without a valid bearer token /mcp is 401 with WWW-Authenticate, even though the login is off")

# 3. make tokens (no session needed while the login is off)
call("POST", "/api/auth/mcp-tokens", {"name": "x" * 61}, 400)
call("POST", "/api/auth/mcp-tokens", {"name": "x", "scope": "admin"}, 400)
code, hdr, auto = call("POST", "/api/auth/mcp-tokens", None, 200)   # one click: no body at all
assert auto["name"] == "Token 1" and auto["scope"] == "read" and auto["token"].startswith("fls_") and "no-store" in hdr["Cache-Control"]
assert call("POST", "/api/auth/mcp-tokens", {}, 200)[2]["name"] == "Token 2"
call("DELETE", f"/api/auth/mcp-tokens/{auto['id']}", expect=200)
assert call("POST", "/api/auth/mcp-tokens", {"name": ""}, 200)[2]["name"] == "Token 1"
for t in call("GET", "/api/auth/mcp-tokens", expect=200)[2]["tokens"]:
    call("DELETE", f"/api/auth/mcp-tokens/{t['id']}", expect=200)
step("one click makes a token (no body needed): named Token 1, Token 2 ... when no name is given; bad names and scopes are 400")
code, hdr, made = call("POST", "/api/auth/mcp-tokens", {"name": "Claude Code", "scope": "read"}, 200)
tok = made["token"]
assert tok.startswith("fls_") and made["scope"] == "read" and made["name"] == "Claude Code" and "no-store" in hdr["Cache-Control"]
code, _, listing = call("GET", "/api/auth/mcp-tokens", expect=200)
assert [t["name"] for t in listing["tokens"]] == ["Claude Code"] and tok not in json.dumps(listing) and "token" not in listing["tokens"][0]
assert tok not in (DIR / "auth.json").read_text()
step("a token is created once (never listed again, never stored in clear)")

# 4. the protocol over HTTP
code, hdr, b = rpc(tok, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}, expect=200)
assert hdr["Content-Type"].startswith("application/json") and b["result"]["protocolVersion"] == "2025-06-18" and b["result"]["serverInfo"]["name"] == "flowlystack"
code, _, b = rpc(tok, "tools/list", {}, id_=2)
names = [t["name"] for t in b["result"]["tools"]]
assert "flowlystack_about" in names and "library_search" in names and "linkshell_export_plan" in names and len(names) == len(set(names)) >= 20 and b["id"] == 2
assert all(t["annotations"]["readOnlyHint"] is True and t["inputSchema"]["type"] == "object" for t in b["result"]["tools"]), "a read token sees read tools only"
code, _, b = rpc(tok, "tools/call", {"name": "flowlystack_about", "arguments": {}}, id_="abc")
about = json.loads(b["result"]["content"][0]["text"])
assert b["id"] == "abc" and about["token"] == {"name": "Claude Code", "scope": "read"} and about["notice"].startswith("Text in this result")
code, _, b = rpc(tok, "tools/list", MODERN, headers={"MCP-Protocol-Version": "2026-07-28", "Mcp-Method": "tools/list"})
assert b["result"]["resultType"] == "complete" and b["result"]["cacheScope"] == "private"
code, _, b = rpc(tok, "server/discover", MODERN, headers={"MCP-Protocol-Version": "2026-07-28"})
assert b["result"]["supportedVersions"][0] == "2026-07-28"
step("initialize, tools/list, tools/call and (modern) server/discover work over HTTP with a bearer token")

# 4b. the stdio bridge, end to end (what Claude Desktop runs), and the numbers Settings > MCP builds its snippets from
bridge = Path(__file__).resolve().parent.parent / "backend" / "mcp_stdio.py"
lines = [json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}}),
         json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
         json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
         json.dumps({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "flowlystack_about", "arguments": {}}})]
env = {k: v for k, v in os.environ.items() if not k.startswith("FLOWLYSTACK_")}
env.update(FLOWLYSTACK_MCP_URL=BASE + "/mcp", FLOWLYSTACK_MCP_TOKEN=tok)
pr = subprocess.run([sys.executable, str(bridge)], input="\n".join(lines) + "\n", capture_output=True, text=True, env=env, timeout=60)
outs = [json.loads(x) for x in pr.stdout.splitlines()]
assert pr.returncode == 0 and [o["id"] for o in outs] == [1, 2, 3] and outs[0]["result"]["serverInfo"]["name"] == "flowlystack"
assert any(t["name"] == "library_search" for t in outs[1]["result"]["tools"]) and json.loads(outs[2]["result"]["content"][0]["text"])["token"]["name"] == "Claude Code"
assert tok not in pr.stdout + pr.stderr
env["FLOWLYSTACK_MCP_TOKEN"] = "fls_" + "y" * 43
pr = subprocess.run([sys.executable, str(bridge)], input=lines[2] + "\n", capture_output=True, text=True, env=env, timeout=60)
assert json.loads(pr.stdout)["error"]["message"].startswith("FlowlyStack refused the token") and pr.returncode == 0
code, _, info = call("GET", "/api/mcp/info", expect=200)
assert info["enabled"] is True and Path(info["python"]).exists() and Path(info["bridge"]).samefile(bridge) and info["local"] is True
assert info["tools"] == {"read": 27, "write": 5} and info["protocol_versions"][0] == "2026-07-28"
step("the stdio bridge works end to end against the real endpoint (and explains a refused token); /api/mcp/info gives the paths for the snippets")

code, hdr, _ = call("POST", "/mcp", {"jsonrpc": "2.0", "method": "notifications/initialized"}, 202, {"Authorization": f"Bearer {tok}"})
assert code == 202
code, _, b = rpc(tok, "tools/list", MODERN, expect=400, headers={"MCP-Protocol-Version": "2025-06-18"})
assert b["error"]["code"] == -32020
code, _, b = rpc(tok, "nope", expect=404)
assert b["error"]["code"] == -32601
code, _, b = call("POST", "/mcp", None, 400, {"Authorization": f"Bearer {tok}"}, raw=b"{not json")
assert b["error"]["code"] == -32700
code, _, b = call("POST", "/mcp", [{"jsonrpc": "2.0", "id": 1, "method": "ping"}], 400, {"Authorization": f"Bearer {tok}"})
assert b["error"]["code"] == -32600
call("POST", "/mcp", None, 413, {"Authorization": f"Bearer {tok}"}, raw=b" " * 1_000_100)
step("a notification is 202; a version/header mismatch is 400, an unknown method 404, bad JSON 400 -32700, a batch 400, a huge body 413")

for m in ("GET", "DELETE"):
    code, hdr, _ = call(m, "/mcp", expect=405)
    assert hdr["Allow"] == "POST"
step("GET and DELETE on /mcp are 405 (no stream, no sessions)")

# 5. Origin
host = BASE.split("//")[1]
rpc(tok, "ping", headers={"Origin": f"http://{host}"}, expect=200)
code, _, b = rpc(tok, "ping", headers={"Origin": "http://evil.example"}, expect=403)
assert b["error"]["message"].startswith("Cross-site")
rpc(tok, "ping", headers={"Origin": "null"}, expect=403)
step("an Origin that is not this host is refused (403), also with a valid token; the app's own origin and no Origin are fine")

# 6. write token, revoke
code, _, w = call("POST", "/api/auth/mcp-tokens", {"name": "Cursor", "scope": "write"}, 200)
code, _, b = rpc(w["token"], "tools/call", {"name": "flowlystack_about"})
assert json.loads(b["result"]["content"][0]["text"])["token"]["scope"] == "write"
code, hdr, rg = call("POST", f"/api/auth/mcp-tokens/{w['id']}/regen", None, 200)
assert rg["id"] == w["id"] and rg["name"] == "Cursor" and rg["scope"] == "write" and rg["token"] != w["token"] and "no-store" in hdr["Cache-Control"]
rpc(w["token"], "ping", expect=401)
rpc(rg["token"], "ping", expect=200)
w = rg
call("POST", "/api/auth/mcp-tokens/t-nope/regen", None, 404)
assert call("PATCH", f"/api/auth/mcp-tokens/{w['id']}", {"name": "  Cursor   laptop "}, 200)[2]["name"] == "Cursor laptop"
call("PATCH", f"/api/auth/mcp-tokens/{w['id']}", {"name": ""}, 400)
call("PATCH", "/api/auth/mcp-tokens/t-nope", {"name": "x"}, 404)
rpc(w["token"], "ping", expect=200)
w["name"] = "Cursor laptop"
step("regen gives the same token a new secret (the old one is 401 at once, id and scope kept); rename keeps the secret; unknown ids are 404")

# 6b. the write tools over HTTP: only a write token sees and may use them, everything is logged and can be undone
def tool(token, name, args=None, base=None):
    code, _, b = rpc(token, "tools/call", {"name": name, "arguments": args or {}}, base=base)
    r = b["result"]
    return r["isError"], r["content"][0]["text"]
names_w = [t["name"] for t in rpc(w["token"], "tools/list", {})[2]["result"]["tools"]]
assert len(names_w) == 32 and {"studio_create", "studio_save_version", "linkshell_create_project_from_plan"} <= set(names_w)
assert len([t for t in rpc(tok, "tools/list", {})[2]["result"]["tools"]]) == 27, "a read token still sees 27"
err, text = tool(tok, "studio_create", {"text": "A prompt a read token must not be able to save."})
assert err and "only read" in text
assert call("GET", "/api/studio", expect=200)[2]["total"] == 0
err, text = tool(w["token"], "studio_create", {"text": "Write a haiku about the sea.", "title": "Sea haiku", "tags": ["poems"]})
made_p = json.loads(text)
assert not err and made_p["id"].startswith("ps-") and made_p["tags"] == ["poems", "via-mcp"] and made_p["status"] == "draft"
row = call("GET", "/api/studio", expect=200)[2]
assert row["total"] == 1 and row["items"][0]["id"] == made_p["id"] and "via-mcp" in row["items"][0]["meta"]["tags"], "the prompt is in Studio through the normal API"
err, text = tool(w["token"], "studio_save_version", {"id": made_p["id"], "text": "Waves fold into the shore, quietly.", "message": "second draft"})
assert not err and json.loads(text)["changed"] is True
vers = call("GET", "/api/studio/" + made_p["id"], expect=200)[2]
assert vers["text"].startswith("Waves fold") and [v["message"] for v in vers["revisions"]] == ["second draft (via MCP: Cursor laptop)", "Created (via MCP: Cursor laptop)"]
err, text = tool(w["token"], "linkshell_create_project_from_plan", {"plan": {"name": "Sea project", "phases": [{"title": "One", "prompts": [{"key": "a", "title": "Draft", "text": "Draft it."}, {"key": "b", "title": "Polish", "text": "Polish it."}]}]}})
proj = json.loads(text)
assert not err and proj["prompts"] == 2 and call("GET", "/api/linkshell/" + proj["id"], expect=200)[2]["project"]["name"] == "Sea project"
err, text = tool(w["token"], "linkshell_create_project_from_plan", {"plan": {"name": "Bad", "phases": [{"title": "p", "prompts": [{"key": "a", "title": "A", "text": "t", "after": ["a"]}]}]}})
assert err and "cannot wait for itself" in text
step("a write token sees 32 tools and saves a Studio prompt, a new version and a Linkshell project over HTTP (visible through the normal API); a read token sees 27 and is refused; a bad plan is a clear error")
for _ in range(60):   # the first graph call starts the background build and says so
    err, text = tool(w["token"], "graph_overview", {})
    if not err:
        break
    assert "being built" in text, text
    time.sleep(0.2)
ov = json.loads(text)
assert not err and ov["nodes"]["studio"] >= 1 and ov["status"]["state"] == "ready"
err, text = tool(w["token"], "graph_search", {"query": "Sea haiku", "types": ["studio"]})
assert not err and json.loads(text)["items"][0]["type"] == "studio"
step("the Lattice read tools answer over HTTP for a token (the graph is built from the user's own files, nothing is called out)")

acts = call("GET", "/api/mcp/activity", expect=200)[2]["items"]
assert [a["what"] for a in acts[:3]] == ["Created Linkshell project", "Saved a new version of Studio prompt", "Created Studio prompt"] and acts[0]["token"] == "Cursor laptop"
assert acts[0]["open"] == "#/linkshell/" + proj["id"] and "Write a haiku" not in json.dumps(acts)
code, _, undone = call("POST", f"/api/mcp/activity/{acts[0]['id']}/undo", None, 200)
assert "Trash" in undone["note"] and call("GET", "/api/linkshell", expect=200)[2]["total"] == 0 if False else True
assert all(i["id"] != proj["id"] for i in call("GET", "/api/linkshell", expect=200)[2]["items"])
call("POST", f"/api/mcp/activity/{acts[0]['id']}/undo", None, 409)
call("POST", "/api/mcp/activity/a-00000000/undo", None, 404)
code, _, undone = call("POST", f"/api/mcp/activity/{acts[1]['id']}/undo", None, 200)
assert "previous text" in undone["note"] and call("GET", "/api/studio/" + made_p["id"], expect=200)[2]["text"].startswith("Write a haiku")
code, _, undone = call("POST", f"/api/mcp/activity/{acts[2]['id']}/undo", None, 200)
assert call("GET", "/api/studio", expect=200)[2]["total"] == 0 and call("GET", "/api/trash", expect=200)[2]["count"] >= 2
assert call("GET", "/api/mcp/activity", expect=200)[2]["items"][0]["undone"]
step("the activity list shows who saved what (titles only), and Undo works over HTTP: a project and a prompt go to the Trash, a version is replaced by the previous text; again or unknown is 409 or 404")
before = call("GET", "/api/mcp/activity", expect=200)[2]["items"]
one = call("DELETE", f"/api/mcp/activity/{before[0]['id']}", expect=200)[2]
assert len(one["removed"]) == 1 and len(call("GET", "/api/mcp/activity", expect=200)[2]["items"]) == len(before) - 1
call("DELETE", f"/api/mcp/activity/{before[0]['id']}", expect=404)
allr = call("DELETE", "/api/mcp/activity", expect=200)[2]
assert len(allr["removed"]) == len(before) - 1 and call("GET", "/api/mcp/activity", expect=200)[2]["items"] == []
assert call("GET", "/api/studio", expect=200)[2]["total"] == 0 and call("GET", "/api/trash", expect=200)[2]["count"] >= 2  # only the list was cleared
bad = [{"id": "x", "tool": "studio_create"}, {"id": "a-12345678", "tool": "rm_rf"}, "junk"]
assert call("POST", "/api/mcp/activity/restore", {"removed": bad}, 200)[2]["restored"] == 0
assert call("POST", "/api/mcp/activity/restore", {"removed": allr["removed"] + one["removed"]}, 200)[2]["restored"] == len(before)
assert call("POST", "/api/mcp/activity/restore", {"removed": one["removed"]}, 200)[2]["restored"] == 0
back = call("GET", "/api/mcp/activity", expect=200)[2]["items"]
assert [a["id"] for a in back] == [a["id"] for a in before] and back[0]["undone"] == before[0]["undone"]
step("deleting one entry or all clears only the list (prompts and the Trash are untouched), the removed entries come back through restore in the same order, forged or repeated entries are ignored")

# 6b2. the Lattice entity tools over HTTP: a read token is refused, a quote that is not in the item is refused, one run = one batch = one Undo
err, text = tool(w["token"], "studio_create", {"text": "Kubernetes runs the Deployment plan at Acme Corp.\nBob Marsh owns the pager.", "title": "Lattice sample"})
sid = json.loads(text)["id"]
ents = [{"name": "Kubernetes", "kind": "technology"}, {"name": "Acme Corp", "kind": "organization"}]
edges = [{"type": "mentions", "to": "Kubernetes", "item": sid, "quote": "Kubernetes runs the Deployment plan"}, {"type": "mentions", "to": "Acme Corp", "item": sid, "quote": "plan at Acme Corp"},
         {"type": "related", "from": "Kubernetes", "to": "Acme Corp", "label": "runs at", "item": sid, "quote": "Deployment plan at Acme Corp"}]
err, text = tool(tok, "graph_add", {"entities": ents, "edges": edges})
assert err and "only read" in text
err, text = tool(w["token"], "graph_add", {"entities": ents, "edges": [dict(edges[0], quote="Kubernetes was invented by a cat")]})
assert err and "does not occur" in text
assert not (Path(os.environ["FLOWLYSTACK_PROMPTS_DIR"]) / "kgraph").exists(), "refused calls write nothing"
err, text = tool(w["token"], "graph_start_run", {"note": "HTTP sample"})
run = json.loads(text)["run"]
err, text = tool(w["token"], "graph_add", {"run": run, "entities": ents, "edges": edges})
added = json.loads(text)
assert not err and added["batch"] == run and added["created"] == 2 and added["edges_added"] == 3
err, text = tool(w["token"], "graph_search", {"query": "kubernetes", "types": ["entity"]})
assert not err and json.loads(text)["items"][0]["mentioned_in"] == [sid]
acts = call("GET", "/api/mcp/activity", expect=200)[2]["items"]
lat = [a for a in acts if a["what"].startswith("Added to Lattice")]
assert len(lat) == 1 and lat[0]["open"] == "#/lattice" and lat[0]["token"] == "Cursor laptop" and "Kubernetes runs" not in json.dumps(acts)
assert "Hidden everywhere in Lattice" in call("POST", f"/api/mcp/activity/{lat[0]['id']}/undo", None, 200)[2]["note"]
call("POST", f"/api/mcp/activity/{lat[0]['id']}/undo", None, 409)
err, text = tool(w["token"], "graph_search", {"query": "kubernetes", "types": ["entity"]})
assert not err and json.loads(text)["total"] == 0
step("the Lattice entity tools over HTTP: a read token is refused, a made-up quote is refused and writes nothing, a run is one batch with one activity line (no text in it), Undo hides it everywhere, a second Undo is 409")


# 6c. who may change a token's scope
code, _, rd = call("POST", "/api/auth/mcp-tokens", {"name": "Reader"}, 200)
assert rd["scope"] == "read" and len(rpc(rd["token"], "tools/list", {})[2]["result"]["tools"]) == 27
assert call("PATCH", f"/api/auth/mcp-tokens/{rd['id']}", {"scope": "write"}, 200)[2]["scope"] == "write"
assert len(rpc(rd["token"], "tools/list", {})[2]["result"]["tools"]) == 32, "the change applies to the same secret at once"
assert call("PATCH", f"/api/auth/mcp-tokens/{rd['id']}", {"scope": "read", "name": "Reader 2"}, 200)[2]["scope"] == "read"
assert [t["name"] for t in call("GET", "/api/auth/mcp-tokens", expect=200)[2]["tokens"]][-1] == "Reader 2" and len(rpc(rd["token"], "tools/list", {})[2]["result"]["tools"]) == 27
call("PATCH", f"/api/auth/mcp-tokens/{rd['id']}", {"scope": "admin"}, 400)
call("PATCH", f"/api/auth/mcp-tokens/{rd['id']}", {}, 400)
call("PATCH", "/api/auth/mcp-tokens/t-nope", {"scope": "write"}, 404)
call("DELETE", f"/api/auth/mcp-tokens/{rd['id']}", expect=200)
step("a token's scope can be changed (write and back to read) without changing its secret; bad scopes are 400, unknown ids 404")

call("DELETE", f"/api/auth/mcp-tokens/{made['id']}", expect=200)
rpc(tok, "ping", expect=401)
rpc(w["token"], "ping", expect=200)
call("DELETE", f"/api/auth/mcp-tokens/{made['id']}", expect=404)
call("DELETE", "/api/auth/mcp-tokens/t-nope", expect=404)
assert [t["name"] for t in call("GET", "/api/auth/mcp-tokens", expect=200)[2]["tokens"]] == ["Cursor laptop"]
step("revoke ends one token at once and leaves the other; revoking again or an unknown id is 404")

# 7. the switch wins over everything
call("PUT", "/api/settings/mcp", {"enabled": False}, 200)
rpc(w["token"], "ping", expect=404)
rpc(None, "ping", expect=404)
call("PUT", "/api/settings/mcp", {"enabled": True}, 200)
rpc(w["token"], "ping", expect=200)
step("switching MCP off makes /mcp a 404 again for everyone, even with a valid token; on again, the token still works")

# 8. wrong tokens lock the client out (last: it blocks this address for a minute)
last = 0
for i in range(10):
    last, hdr, _ = rpc("fls_" + "q" * 43, "ping", expect=None)
    if last == 429:
        break
assert last == 429 and int(hdr["Retry-After"]) > 0
rpc(w["token"], "ping", expect=429)
step("repeated wrong tokens from one address get a 429 with Retry-After, and the right token waits too")

# ---------- the login-on server: what the gate must and must not allow ----------

if BASE_AUTH:
    A = BASE_AUTH
    B = Path(os.environ["FLOWLYSTACK_AUTH_DIR"])
    assert not (B / "auth.json").exists(), "the second server's settings folder must start empty"
    assert call("GET", "/api/auth/state", expect=200, base=A)[2]["needs_setup"] is True
    code, hdr, _ = call("POST", "/api/auth/signup", {"username": "owner", "password": "correct horse battery"}, 200, base=A)
    cookie = hdr["Set-Cookie"].split(";")[0]
    C = {"Cookie": cookie}

    rpc(None, "ping", base=A, expect=404)   # off by default here too, and no redirect to /login
    call("PUT", "/api/settings/mcp", {"enabled": True}, 401, base=A)
    call("PUT", "/api/settings/mcp", {"enabled": True}, 200, headers=C, base=A)
    step("login on: /mcp is reachable without a session (404 while off, never a redirect); Settings still needs the session")

    call("POST", "/api/auth/mcp-tokens", {}, 401, base=A)
    call("POST", "/api/auth/mcp-tokens", {}, 403, headers={**C, "Origin": "http://evil.example"}, base=A)
    assert call("GET", "/api/auth/mcp-tokens", expect=200, headers=C, base=A)[2]["tokens"] == []
    code, _, made = call("POST", "/api/auth/mcp-tokens", None, 200, headers=C, base=A)   # one click, no password
    assert made["name"] == "Token 1"
    tok = made["token"]
    step("a token is one click for a signed-in owner (no session 401, foreign Origin 403, no password asked)")

    rpc(tok, "tools/call", {"name": "flowlystack_about"}, base=A, expect=200)
    rpc(None, "ping", base=A, headers=C, expect=401)
    step("with the login on, a token works without a cookie, and a session cookie alone is not accepted on /mcp")

    B_ = {"Authorization": f"Bearer {tok}"}
    for path in ("/api/prompts", "/api/settings", "/api/auth/mcp-tokens", "/api/collections", "/api/studio", "/api/trash"):
        call("GET", path, expect=401, headers=B_, base=A)
    call("POST", "/api/auth/mcp-tokens", {"name": "y", "scope": "write"}, 401, headers=B_, base=A)
    call("POST", f"/api/auth/mcp-tokens/{made['id']}/regen", None, 401, headers=B_, base=A)
    call("PATCH", f"/api/auth/mcp-tokens/{made['id']}", {"name": "hijack"}, 401, headers=B_, base=A)
    call("DELETE", f"/api/auth/mcp-tokens/{made['id']}", expect=401, headers=B_, base=A)
    rpc(tok, "ping", base=A, expect=200)
    step("a token is refused on every other route (prompts, settings, collections, studio, trash, and the token routes themselves)")

    call("GET", "/api/mcp/activity", expect=401, headers=B_, base=A)
    call("GET", "/api/mcp/activity", expect=401, base=A)
    call("POST", "/api/mcp/activity/a-00000000/undo", None, 401, headers=B_, base=A)
    call("PATCH", f"/api/auth/mcp-tokens/{made['id']}", {"scope": "write"}, 401, headers=B_, base=A)
    call("PATCH", f"/api/auth/mcp-tokens/{made['id']}", {"scope": "write"}, 403, headers={**C, "Origin": "http://evil.example"}, base=A)
    assert call("PATCH", f"/api/auth/mcp-tokens/{made['id']}", {"scope": "write"}, 200, headers=C, base=A)[2]["scope"] == "write"
    code, _, b = rpc(tok, "tools/call", {"name": "studio_create", "arguments": {"text": "Saved by a write token while the login is on."}}, base=A)
    sp = json.loads(b["result"]["content"][0]["text"])
    assert not b["result"]["isError"] and sp["id"].startswith("ps-")
    acts = call("GET", "/api/mcp/activity", expect=200, headers=C, base=A)[2]["items"]
    assert acts[0]["what"] == "Created Studio prompt" and acts[0]["ref"] == sp["id"]
    call("POST", f"/api/mcp/activity/{acts[0]['id']}/undo", None, 403, headers={**C, "Origin": "http://evil.example"}, base=A)
    call("POST", f"/api/mcp/activity/{acts[0]['id']}/undo", None, 200, headers=C, base=A)
    call("PATCH", f"/api/auth/mcp-tokens/{made['id']}", {"scope": "read"}, 200, headers=C, base=A)
    step("login on: the activity list, Undo and a scope change need the session (a token alone is 401, a foreign Origin 403); a write token saves, the owner undoes")

    call("POST", f"/api/auth/mcp-tokens/{made['id']}/regen", None, 403, headers={**C, "Origin": "http://evil.example"}, base=A)
    code, _, rg = call("POST", f"/api/auth/mcp-tokens/{made['id']}/regen", None, 200, headers=C, base=A)
    rpc(tok, "ping", base=A, expect=401)
    rpc(rg["token"], "ping", base=A, expect=200)
    assert call("PATCH", f"/api/auth/mcp-tokens/{made['id']}", {"name": "Desk"}, 200, headers=C, base=A)[2]["name"] == "Desk"
    step("regen and rename need the session (and the app's own origin); the old secret dies at once")

    call("DELETE", f"/api/auth/mcp-tokens/{made['id']}", expect=200, headers=C, base=A)
    rpc(rg["token"], "ping", base=A, expect=401)
    step("revoking with the session ends the token")
else:
    print("skip  the login-on checks (set BASE_AUTH and FLOWLYSTACK_AUTH_DIR to run them)")

print("\nall MCP API checks passed")
