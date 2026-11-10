#!/usr/bin/env python3
"""Checks for the stdio bridge (backend/mcp_stdio.py). Plain asserts, standard library only. No FlowlyStack server: a tiny fake endpoint stands in.

    python3 scripts/check_mcp_stdio.py
"""
import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BRIDGE = str(Path(__file__).resolve().parent.parent / "backend" / "mcp_stdio.py")
TOKEN = "fls_" + "T" * 43
SEEN = []            # every request the fake endpoint received: (path, headers, body)
PLAN = {}            # path -> (status, headers, body bytes)


class Fake(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        SEEN.append((self.path, {k.lower(): v for k, v in self.headers.items()}, body))
        if "id" not in json.loads(body) and self.path not in PLAN:   # like FlowlyStack: a notification is accepted with nothing to say
            status, headers, out = 202, {}, b""
        else:
            status, headers, out = PLAN.get(self.path) or (200, {}, json.dumps({"jsonrpc": "2.0", "id": json.loads(body).get("id"), "result": {"echo": json.loads(body)}}).encode())
        self.send_response(status)
        for k, v in headers.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)


srv = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{srv.server_address[1]}"


def step(msg):
    print("ok  ", msg)


def run(lines, url=None, token=TOKEN, env_extra=None, py=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith("FLOWLYSTACK_")}
    if url is not None:
        env["FLOWLYSTACK_MCP_URL"] = url
    if token is not None:
        env["FLOWLYSTACK_MCP_TOKEN"] = token
    env.update(env_extra or {})
    p = subprocess.run([py or sys.executable, BRIDGE], input="\n".join(lines) + ("\n" if lines else ""), capture_output=True, text=True, encoding="utf-8", env=env, timeout=60)
    outs = [json.loads(x) for x in p.stdout.splitlines() if x.strip()]
    assert TOKEN not in p.stdout and TOKEN not in p.stderr, "the token must never be printed"
    return p.returncode, outs, p.stderr


def msg(id_, method, params=None):
    return json.dumps({"jsonrpc": "2.0", "id": id_, "method": method, **({"params": params} if params is not None else {})}, ensure_ascii=False)


try:
    # --- relay
    SEEN.clear()
    rc, outs, err = run([msg(1, "tools/list", {})], BASE + "/mcp")
    assert rc == 0 and len(outs) == 1 and outs[0]["id"] == 1 and outs[0]["result"]["echo"]["method"] == "tools/list"
    path, h, body = SEEN[0]
    assert path == "/mcp" and h["authorization"] == f"Bearer {TOKEN}" and h["content-type"] == "application/json" and "text/event-stream" in h["accept"]
    assert json.loads(body)["method"] == "tools/list" and "mcp-protocol-version" not in h
    step("a line on stdin is POSTed with the bearer token and the answer comes back as one line on stdout")

    SEEN.clear()
    rc, outs, err = run([msg(1, "ping"), json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}), "", msg(2, "ping")], BASE + "/mcp")
    assert [o["id"] for o in outs] == [1, 2] and len(SEEN) == 3
    PLAN["/mcp"] = (202, {}, b"")
    SEEN.clear()
    rc, outs, err = run([json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}), msg(5, "ping")], BASE + "/mcp")
    assert outs == [] and len(SEEN) == 2, "a 202 produces no output line, and the next request still goes through"
    PLAN.clear()
    step("a notification (202, no body) and blank lines print nothing; order is kept")

    SEEN.clear()
    rc, outs, err = run([msg("é-1", "tools/call", {"name": "library_search", "arguments": {"query": "naïve café 日本語 🚀"}})], BASE + "/mcp")
    assert outs[0]["id"] == "é-1" and outs[0]["result"]["echo"]["params"]["arguments"]["query"] == "naïve café 日本語 🚀"
    big = "x" * 200_000
    rc, outs, err = run([msg(3, "tools/call", {"name": "a", "arguments": {"q": big}})], BASE + "/mcp")
    assert len(outs[0]["result"]["echo"]["params"]["arguments"]["q"]) == 200_000
    step("UTF-8 survives both ways and a long message is fine")

    SEEN.clear()
    meta = {"io.modelcontextprotocol/protocolVersion": "2026-07-28", "io.modelcontextprotocol/clientCapabilities": {}}
    run([msg(1, "tools/call", {"name": "flowlystack_about", "arguments": {}, "_meta": meta})], BASE + "/mcp")
    h = SEEN[0][1]
    assert h["mcp-protocol-version"] == "2026-07-28" and h["mcp-method"] == "tools/call" and h["mcp-name"] == "flowlystack_about"
    step("a message in the newer protocol also gets the MCP-Protocol-Version, Mcp-Method and Mcp-Name headers")

    # --- under every Python we can find (the app's own .venv Python 3.12 tripped over backend/collections.py shadowing the standard library once)
    VENV = Path(BRIDGE).resolve().parent.parent / ".venv" / "bin" / "python"
    pythons = [sys.executable] + ([str(VENV)] if VENV.exists() else [])
    for py in pythons:
        SEEN.clear()
        rc, outs, err = run([msg(1, "ping")], BASE + "/mcp", py=py)
        assert rc == 0 and len(outs) == 1 and outs[0]["id"] == 1 and "Traceback" not in err, (py, rc, err[-300:])
        rc, outs, err = run([msg(1, "ping")], None, None, py=py)
        assert rc == 1 and "FLOWLYSTACK_MCP_URL" in err and "Traceback" not in err, (py, err[-300:])
    step(f"the bridge starts and relays under {len(pythons)} Python{'s' if len(pythons) > 1 else ''} ({'the system one and the project .venv' if len(pythons) > 1 else 'the system one; no .venv here'}): its own folder never shadows the standard library")

    # --- the server's own JSON-RPC errors pass through
    PLAN["/mcp"] = (404, {}, json.dumps({"jsonrpc": "2.0", "id": 9, "error": {"code": -32601, "message": "Method not found: x"}}).encode())
    rc, outs, err = run([msg(9, "x")], BASE + "/mcp")
    assert outs[0]["error"]["code"] == -32601 and outs[0]["id"] == 9
    PLAN["/mcp"] = (400, {}, json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Batches"}}).encode())
    rc, outs, err = run([msg(4, "x")], BASE + "/mcp")
    assert outs[0]["error"]["code"] == -32600 and outs[0]["id"] == 4, "an error without an id gets the request's id"
    step("a JSON-RPC error from FlowlyStack is passed on (and tied to the request id when it had none)")

    # --- plain HTTP failures become readable JSON-RPC errors
    for status, body, needle in ((401, {"error": {"code": -32600, "message": "A valid MCP token is required."}}, "refused the token"),
                                 (404, {"detail": "MCP is turned off."}, "turned off"), (429, {"error": {"code": -32600, "message": "Too many attempts."}}, "too many"),
                                 (403, {"detail": "Cross-site request refused."}, "refused the request"), (500, {"detail": "boom"}, "HTTP 500")):
        PLAN["/mcp"] = (status, {}, json.dumps(body).encode())
        rc, outs, err = run([msg(7, "ping")], BASE + "/mcp")
        assert len(outs) == 1 and outs[0]["id"] == 7 and needle.lower() in outs[0]["error"]["message"].lower(), (status, outs)
        assert outs[0]["error"]["message"] in err, "the same words go to stderr"
    PLAN["/mcp"] = (401, {}, json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "A valid MCP token is required."}}).encode())
    rc, outs, err = run([msg(7, "ping")], BASE + "/mcp")
    assert outs[0]["id"] == 7 and "refused the token" in outs[0]["error"]["message"], "FlowlyStack's own 401 is explained too"
    PLAN["/mcp"] = (200, {}, b"<html>proxy page</html>")
    rc, outs, err = run([msg(7, "ping")], BASE + "/mcp")
    assert outs[0]["error"]["message"].startswith("FlowlyStack answered HTTP 200")
    PLAN.clear()
    step("401, 404, 429, 403, 500 and a non-JSON page become an error with the request's id and words the user can act on")

    # --- redirects are never followed
    SEEN.clear()
    PLAN["/mcp"] = (302, {"Location": BASE + "/elsewhere"}, b"")
    rc, outs, err = run([msg(8, "ping")], BASE + "/mcp")
    assert outs[0]["id"] == 8 and "redirect" in outs[0]["error"]["message"].lower(), outs
    assert [p for p, _, _ in SEEN] == ["/mcp"], "the redirect target must never receive the token"
    PLAN.clear()
    step("a redirect is not followed (the token would travel with it)")

    # --- the app is not running / bad input / bad setup
    rc, outs, err = run([msg(1, "ping"), msg(2, "ping")], "http://127.0.0.1:9/mcp")
    assert rc == 0 and [o["id"] for o in outs] == [1, 2] and "not reachable" in outs[0]["error"]["message"] and "Is the app running" in outs[0]["error"]["message"]
    rc, outs, err = run([json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})], "http://127.0.0.1:9/mcp")
    assert rc == 0 and outs == [] and "not reachable" in err
    step("when FlowlyStack is not running each request gets a clear error (a notification only logs), and the bridge keeps going")

    SEEN.clear()
    rc, outs, err = run(["{not json", msg(1, "ping")], BASE + "/mcp")
    assert outs[0]["error"]["code"] == -32700 and outs[0]["id"] is None and outs[1]["id"] == 1 and len(SEEN) == 1
    step("a line that is not JSON gets a parse error without calling FlowlyStack")

    for url, token, needle in ((None, TOKEN, "FLOWLYSTACK_MCP_URL"), (BASE + "/mcp", None, "FLOWLYSTACK_MCP_TOKEN"), ("ftp://x/mcp", TOKEN, "http://")):
        SEEN.clear()
        rc, outs, err = run([msg(1, "ping")], url, token)
        assert rc == 1 and outs == [] and needle in err and not SEEN, (url, token, rc, err)
    step("without both settings (or with a non-http address) it exits at once with one line on stderr and nothing on stdout")

    print("\nall MCP stdio bridge checks passed")
finally:
    srv.shutdown()
