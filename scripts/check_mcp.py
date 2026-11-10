#!/usr/bin/env python3
"""Checks for the MCP protocol layer (backend/mcp/server.py). Plain asserts, standard library only, no server.

    python3 scripts/check_mcp.py

It also guards every tool that is registered (names, descriptions, schemas), so each later phase is held to the same rules.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.mcp import server  # noqa: E402

READ = {"scope": "read", "name": "Claude Code", "id": "t-1"}
WRITE = {"scope": "write", "name": "Cursor", "id": "t-2"}
MODERN_META = {"io.modelcontextprotocol/protocolVersion": "2026-07-28", "io.modelcontextprotocol/clientCapabilities": {},
               "io.modelcontextprotocol/clientInfo": {"name": "t", "version": "1"}}


def step(msg):
    print("ok  ", msg)


def rpc(method, params=None, id_=1, ctx=READ, headers=None, **extra):
    msg = {"jsonrpc": "2.0", "id": id_, "method": method, **extra}
    if params is not None:
        msg["params"] = params
    return server.handle(msg, headers or {}, ctx)


def modern(params=None):
    return {**(params or {}), "_meta": MODERN_META}


# temporary tools to exercise the rules (removed at the end)
@server.tool("_t_echo", "Echo for tests.", {"text": {"type": "string", "maxLength": 10}, "n": {"type": "integer", "minimum": 1, "maximum": 5},
                                          "flag": {"type": "boolean"}, "tags": {"type": "array", "maxItems": 2, "items": {"type": "string", "maxLength": 4}},
                                          "mode": {"type": "string", "enum": ["a", "b"]}}, required=("text",))
def _t_echo(args, ctx):
    return {"echo": args, "who": ctx["name"]}


@server.tool("_t_write", "Write for tests.", {"v": {"type": "string"}}, scope="write")
def _t_write(args, ctx):
    return {"wrote": args.get("v", "")}


@server.tool("_t_fail", "Always says no.")
def _t_fail(args, ctx):
    raise server.ToolError("That id does not exist.")


@server.tool("_t_boom", "Always breaks.")
def _t_boom(args, ctx):
    raise RuntimeError("secret internal detail /Users/x/data")


@server.tool("_t_big", "Too much.")
def _t_big(args, ctx):
    return {"text": "x" * (server.MAX_OUT + 10)}


def text_of(body):
    return body["result"]["content"][0]["text"]


try:
    # --- envelope
    for bad in ([], [{"jsonrpc": "2.0", "id": 1, "method": "ping"}], "x", 5, {"id": 1, "method": "ping"}, {"jsonrpc": "1.0", "id": 1, "method": "ping"}):
        st, body = server.handle(bad, {}, READ)
        assert st == 400 and body["error"]["code"] == -32600, (bad, st, body)
    assert server.handle({"jsonrpc": "2.0", "id": True, "method": "ping"}, {}, READ)[0] == 400
    assert server.handle({"jsonrpc": "2.0", "id": 1, "method": "ping", "params": 5}, {}, READ)[1]["error"]["code"] == -32602
    assert server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}, {}, READ) == (202, None)
    assert server.handle({"jsonrpc": "2.0", "method": "anything/at/all", "params": {"x": 1}}, {}, READ) == (202, None)
    assert server.handle({"jsonrpc": "2.0", "id": 1, "result": {}}, {}, READ) == (202, None)
    step("batches and malformed messages are 400; a notification or a response from the client is 202 with no body")

    # --- older clients: initialize without a session
    st, b = rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "c", "version": "1"}})
    r = b["result"]
    assert st == 200 and r["protocolVersion"] == "2025-06-18" and r["serverInfo"]["name"] == "flowlystack" and "tools" in r["capabilities"]
    assert "resultType" not in r and "_meta" not in r, "an older client gets the older shape"
    for want in ("2025-03-26", "2024-11-05", "2025-11-25"):
        assert rpc("initialize", {"protocolVersion": want})[1]["result"]["protocolVersion"] == want
    assert rpc("initialize", {"protocolVersion": "1999-01-01"})[1]["result"]["protocolVersion"] == server.LEGACY[0]
    assert rpc("initialize", {})[1]["result"]["protocolVersion"] == server.LEGACY[0]
    assert rpc("ping")[1]["result"] == {}
    step("initialize answers with the client's version when we have it (else our newest older one), no session, no extra fields")

    # --- modern (stateless) requests
    st, b = rpc("server/discover", modern())
    d = b["result"]
    assert st == 200 and d["resultType"] == "complete" and d["supportedVersions"] == list(server.SUPPORTED) and d["capabilities"] == {"tools": {}}
    assert isinstance(d["ttlMs"], int) and d["cacheScope"] == "public" and d["_meta"]["io.modelcontextprotocol/serverInfo"]["name"] == "flowlystack"
    assert server.MODERN == "2026-07-28" and server.SUPPORTED[0] == server.MODERN
    st, b = rpc("tools/list", modern(), headers={"mcp-protocol-version": "2026-07-28", "mcp-method": "tools/list"})
    r = b["result"]
    assert st == 200 and r["resultType"] == "complete" and r["ttlMs"] == 0 and r["cacheScope"] == "private" and "nextCursor" not in r
    assert "_meta" in r
    step("server/discover and a modern tools/list carry resultType, ttlMs, cacheScope (private: the list depends on the token) and serverInfo")

    st, b = rpc("tools/list", {"_meta": {**MODERN_META, "io.modelcontextprotocol/protocolVersion": "1900-01-01"}})
    assert st == 400 and b["error"]["code"] == -32022 and b["error"]["data"]["requested"] == "1900-01-01" and "2026-07-28" in b["error"]["data"]["supported"]
    st, b = rpc("tools/list", {}, headers={"mcp-protocol-version": "1900-01-01"})
    assert st == 400 and b["error"]["code"] == -32022
    st, b = rpc("tools/list", modern(), headers={"mcp-protocol-version": "2025-06-18"})
    assert st == 400 and b["error"]["code"] == -32020 and "mismatch" in b["error"]["message"].lower()
    st, b = rpc("tools/list", modern(), headers={"mcp-method": "tools/call"})
    assert st == 400 and b["error"]["code"] == -32020
    st, b = rpc("tools/call", modern({"name": "flowlystack_about", "arguments": {}}), headers={"mcp-name": "other"})
    assert st == 400 and b["error"]["code"] == -32020
    st, b = rpc("tools/call", modern({"name": "flowlystack_about", "arguments": {}}), headers={"mcp-name": "flowlystack_about", "mcp-method": "tools/call"})
    assert st == 200
    step("an unsupported version is 400 -32022 with the supported list; a header that disagrees with the body is 400 -32020")

    st, b = rpc("nope/nothing")
    assert st == 404 and b["error"]["code"] == -32601 and b["id"] == 1
    step("an unknown method is 404 -32601")

    # --- tools/list
    st, b = rpc("tools/list", {})
    names = [t["name"] for t in b["result"]["tools"]]
    assert "flowlystack_about" in names and "_t_echo" in names and "_t_write" not in names, names
    assert "resultType" not in b["result"] and "_meta" not in b["result"]
    assert "_t_write" in [t["name"] for t in rpc("tools/list", {}, ctx=WRITE)[1]["result"]["tools"]]
    assert rpc("tools/list", {"cursor": ""})[0] == 200
    st, b = rpc("tools/list", {"cursor": "abc"})
    assert b["error"]["code"] == -32602 and "cursor" in b["error"]["message"].lower()
    t = next(t for t in rpc("tools/list", {})[1]["result"]["tools"] if t["name"] == "_t_echo")
    assert set(t) == {"name", "title", "description", "inputSchema", "annotations"} and t["annotations"]["readOnlyHint"] is True
    step("a read token sees only read tools, a write token sees both; the list is one page (any real cursor is invalid); the scope is not leaked in the listing")

    # --- tools/call
    st, b = rpc("tools/call", {"name": "flowlystack_about", "arguments": {}})
    assert st == 200 and b["result"]["isError"] is False and "resultType" not in b["result"]
    out = json.loads(text_of(b))
    assert out["notice"] == server.NOTICE and out["token"] == {"name": "Claude Code", "scope": "read"} and out["app"] == "flowlystack"
    assert "flowlystack_about" in [t["name"] for t in out["tools"]] and "_t_write" not in [t["name"] for t in out["tools"]]
    out = json.loads(text_of(rpc("tools/call", {"name": "flowlystack_about"}, ctx=WRITE)[1]))
    assert "_t_write" in [t["name"] for t in out["tools"]]
    b = rpc("tools/call", modern({"name": "flowlystack_about"}))[1]
    assert b["result"]["resultType"] == "complete" and b["result"]["isError"] is False
    step("a call returns JSON text with the data notice; arguments may be left out; modern calls say resultType complete")

    st, b = rpc("tools/call", {"name": "does_not_exist", "arguments": {}})
    assert st == 200 and b["error"]["code"] == -32602 and "Unknown tool" in b["error"]["message"]
    assert rpc("tools/call", {"arguments": {}})[1]["error"]["code"] == -32602
    assert rpc("tools/call", {"name": 5})[1]["error"]["code"] == -32602
    step("an unknown tool is a -32602 error, not a crash")

    ok = rpc("tools/call", {"name": "_t_echo", "arguments": {"text": "hi", "n": 3, "flag": False, "tags": ["a"], "mode": "b"}})[1]["result"]
    assert ok["isError"] is False and json.loads(ok["content"][0]["text"])["echo"]["n"] == 3
    assert json.loads(rpc("tools/call", {"name": "_t_echo", "arguments": {"text": "hi", "n": None, "mode": None}})[1]["result"]["content"][0]["text"])["echo"] == {"text": "hi"}
    for args, needle in (({}, "missing argument 'text'"), ({"text": 5}, "must be a string"), ({"text": "x" * 11}, "wrong length"),
                         ({"text": "a", "n": "3"}, "integer"), ({"text": "a", "n": True}, "integer"), ({"text": "a", "n": 9}, "between"),
                         ({"text": "a", "flag": "yes"}, "true or false"), ({"text": "a", "tags": ["a", "b", "c"]}, "at most 2"),
                         ({"text": "a", "tags": ["toolong"]}, "short strings"), ({"text": "a", "mode": "z"}, "one of: a, b"),
                         ({"text": "a", "extra": 1}, "unknown argument 'extra'"), ("nope", "arguments must be an object")):
        res = rpc("tools/call", {"name": "_t_echo", "arguments": args})[1]["result"]
        assert res["isError"] is True and needle in res["content"][0]["text"], (args, res)
    step("arguments are checked against the schema (types, length, range, enum, list size, unknown names); nulls are dropped; a problem is a tool error the model can fix")

    res = rpc("tools/call", {"name": "_t_write", "arguments": {"v": "x"}})[1]["result"]
    assert res["isError"] is True and "only read" in res["content"][0]["text"] and "wrote" not in res["content"][0]["text"]
    res = rpc("tools/call", {"name": "_t_write", "arguments": {"v": "x"}}, ctx=WRITE)[1]["result"]
    assert res["isError"] is False and json.loads(res["content"][0]["text"])["wrote"] == "x"
    step("a read token cannot call a write tool (a clear tool error); a write token can")

    res = rpc("tools/call", {"name": "_t_fail"})[1]["result"]
    assert res["isError"] is True and res["content"][0]["text"] == "That id does not exist."
    res = rpc("tools/call", {"name": "_t_boom"})[1]["result"]
    assert res["isError"] is True and "secret" not in res["content"][0]["text"] and "/Users" not in res["content"][0]["text"]
    res = rpc("tools/call", {"name": "_t_big"})[1]["result"]
    assert res["isError"] is True and "too large" in res["content"][0]["text"] and len(res["content"][0]["text"]) < 200
    step("a ToolError reaches the model as written; any other failure is generic (no internals); an oversized result is refused")

    # --- every registered tool follows the rules
    for name, t in [(n, t) for n, t in server.TOOLS.items() if not n.startswith("_t_")]:   # (the test tools above are removed at the end)
        assert re.match(r"^[A-Za-z0-9_.-]{1,128}$", name), name
        assert len(t["description"]) >= 20 and t["scope"] in ("read", "write"), name
        s = t["inputSchema"]
        assert s["type"] == "object" and s["additionalProperties"] is False and set(s["required"]) <= set(s["properties"]), name
        assert t["annotations"]["readOnlyHint"] is (t["scope"] == "read"), name
        if t["scope"] == "write":
            assert t["annotations"]["destructiveHint"] is False, name
    step("every registered tool has a safe name, a description, a closed schema and honest read/write annotations")

    print("\nall MCP protocol checks passed")
finally:
    for n in [n for n in server.TOOLS if n.startswith("_t_")]:
        del server.TOOLS[n]
