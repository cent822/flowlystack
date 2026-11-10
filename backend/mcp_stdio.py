#!/usr/bin/env python3
"""A bridge from MCP over stdio to FlowlyStack's /mcp endpoint. Standard library only, one standalone file.

Claude Desktop starts local programs and talks to them over stdin and stdout; FlowlyStack answers over HTTP with a bearer token. This program
sits between them: each line on stdin (one JSON-RPC message) is POSTed to the endpoint, and each answer is written to stdout as one line.

    FLOWLYSTACK_MCP_URL    the endpoint, for example http://127.0.0.1:8372/mcp
    FLOWLYSTACK_MCP_TOKEN  a token made in FlowlyStack Settings > MCP (kept in the environment, never in a command line or a log)

Rules: stdout carries only protocol lines (everything else goes to stderr); a redirect is never followed (the token would travel with it); the
token is never printed; a problem comes back to the client as a JSON-RPC error with the request's id, in words the user can act on.
"""
import os
import sys

# This file lives in `backend/`, which holds modules named like the standard library (collections.py, config.py, ...). Python puts a script's own
# folder first on the import path, so under some versions `import json` would load OUR collections.py and crash. Leave that folder off the path.
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:] = [p for p in sys.path if os.path.abspath(p or os.getcwd()) != _HERE]

import json  # noqa: E402
import urllib.error  # noqa: E402
import urllib.request  # noqa: E402

TIMEOUT = 120


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


OPENER = urllib.request.build_opener(_NoRedirect)


def log(msg):
    print(f"flowlystack-mcp: {msg}", file=sys.stderr, flush=True)


def out(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def rpc_error(id_, message, code=-32000):
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}


def headers_for(msg, token):
    h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream", "Authorization": f"Bearer {token}"}
    params = msg.get("params") if isinstance(msg, dict) else None
    meta = params.get("_meta") if isinstance(params, dict) else None
    version = meta.get("io.modelcontextprotocol/protocolVersion") if isinstance(meta, dict) else None
    if isinstance(version, str):   # the newer protocol also wants these as headers
        h["MCP-Protocol-Version"] = version
        if isinstance(msg.get("method"), str):
            h["Mcp-Method"] = msg["method"]
        name = params.get("name")
        if msg.get("method") == "tools/call" and isinstance(name, str) and name.isascii() and name.isprintable():
            h["Mcp-Name"] = name
    return h


def explain(status, body):
    """What to tell the user for an HTTP answer that is not a JSON-RPC message."""
    detail = ""
    try:
        d = json.loads(body)
        detail = (d.get("detail") or (d.get("error") or {}).get("message") or "") if isinstance(d, dict) else ""
    except ValueError:
        pass
    if status == 401:
        return "FlowlyStack refused the token. It may have been revoked or mistyped: make a new one in FlowlyStack Settings > MCP and update this client."
    if status == 404:
        return "MCP is turned off in FlowlyStack (Settings > MCP) or the address is wrong."
    if status == 429:
        return "FlowlyStack says there were too many attempts with a wrong token. Wait a minute, then check the token."
    if status == 403:
        return f"FlowlyStack refused the request ({detail or 'forbidden'})."
    if status in (301, 302, 303, 307, 308):
        return "The address redirects somewhere else. Use the final address (for example https://) in FLOWLYSTACK_MCP_URL."
    return f"FlowlyStack answered HTTP {status}{': ' + detail if detail else ''}."


def relay(line, url, token):
    try:
        msg = json.loads(line)
    except ValueError:
        out(rpc_error(None, "That was not valid JSON.", -32700))
        return
    id_ = msg.get("id") if isinstance(msg, dict) else None
    req = urllib.request.Request(url, data=line.encode("utf-8"), method="POST", headers=headers_for(msg, token))
    try:
        r = OPENER.open(req, timeout=TIMEOUT)
        status, body = r.status, r.read()
    except urllib.error.HTTPError as e:
        status, body = e.code, e.read()
    except (urllib.error.URLError, OSError) as e:
        why = f"FlowlyStack is not reachable at {url}. Is the app running? ({type(getattr(e, 'reason', e)).__name__})"
        log(why)
        if id_ is not None:
            out(rpc_error(id_, why))
        return
    if status == 202 or (status < 300 and not body.strip() and id_ is None):
        return                                   # a notification was accepted: nothing to send back (a request is never left unanswered)
    try:
        answer = json.loads(body)
    except ValueError:
        answer = None
    if status in (401, 403, 429):                # about the connection, not the message: say what to do about it
        answer = None
    if isinstance(answer, dict) and answer.get("jsonrpc") == "2.0" and ("result" in answer or "error" in answer):
        if answer.get("error") and answer.get("id") is None and id_ is not None:
            answer["id"] = id_                   # an error the server could not tie to a request
        out(answer)
        return
    why = explain(status, body)
    log(why)
    if id_ is not None:
        out(rpc_error(id_, why))


def main():
    url, token = os.environ.get("FLOWLYSTACK_MCP_URL", "").strip(), os.environ.get("FLOWLYSTACK_MCP_TOKEN", "").strip()
    if not url or not token:
        log("set FLOWLYSTACK_MCP_URL and FLOWLYSTACK_MCP_TOKEN (copy the setup from FlowlyStack Settings > MCP).")
        return 1
    if not url.lower().startswith(("http://", "https://")):
        log("FLOWLYSTACK_MCP_URL must start with http:// or https://.")
        return 1
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stdin.reconfigure(encoding="utf-8")
    for line in sys.stdin:
        line = line.strip()
        if line:
            relay(line, url, token)
    return 0


if __name__ == "__main__":
    sys.exit(main())
