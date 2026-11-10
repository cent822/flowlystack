"""A fake OpenAI-compatible server for the checks (standard library only). Never a real runtime.

    srv = FakeOpenAI(key="secret")      # key=None: no key needed
    srv.url                              # http://127.0.0.1:<port>/v1
    srv.seen                             # [(method, path, authorization header or "")]

The model name in a chat request picks the behaviour: ok (streams "Hello there"), err-obj / err-text / err-detail (HTTP 400 in
each of the three error shapes), nodone (no [DONE] line), empty (no content), slow (one piece every 0.2 s, for Stop).
`redirect_to` makes every path answer 302 to that address.
`extra_models=[...]` adds model names to /models. The names extract, extract-bad, extract-junk and extract-slow answer the Lattice "Build with a
local model" request: they read the text between the dashed lines of the last user message and reply with JSON (entities = capitalised word pairs, each
with a quote copied from the text; extract-bad quotes things that are not there; extract-junk answers in prose; extract-slow takes a while, for Stop).
"""
import re
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODELS = ["ok", "err-obj", "err-text", "err-detail", "nodone", "empty", "slow", "text-embedding-nomic-embed-text-v1.5"]


class FakeOpenAI:
    def __init__(self, key=None, redirect_to=None, prefix="/v1", extra_models=()):
        outer = self
        self.key, self.redirect_to, self.seen, self.prefix, self.extra = key, redirect_to, [], prefix, list(extra_models)

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, obj=None, raw=None, ctype="application/json"):
                body = raw if raw is not None else json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("content-type", ctype)
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _gate(self):
                outer.seen.append((self.command, self.path, self.headers.get("authorization", "")))
                if outer.redirect_to:
                    self.send_response(302)
                    self.send_header("location", outer.redirect_to + self.path)
                    self.send_header("content-length", "0")
                    self.end_headers()
                    return False
                if outer.key and self.headers.get("authorization") != "Bearer " + outer.key:
                    self._send(401, {"error": {"message": "bad key"}})
                    return False
                return True

            def do_GET(self):
                if not self._gate():
                    return
                if self.path == outer.prefix + "/models":
                    self._send(200, {"object": "list", "data": [{"id": m, "object": "model"} for m in MODELS + outer.extra]})
                elif self.path == outer.prefix + "/notmodels":
                    self._send(200, {"hello": 1})
                else:
                    self._send(404, {"error": {"message": "no such route"}})

            def do_POST(self):
                if not self._gate():
                    return
                n = int(self.headers.get("content-length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}")
                outer.last_body = body
                if self.path != outer.prefix + "/chat/completions":
                    self._send(404, {"error": {"message": "no such route"}})
                    return
                m = body.get("model")
                if m == "err-obj":
                    return self._send(400, {"error": {"message": "model 'x' is not loaded"}})
                if m == "err-text":
                    return self._send(400, {"error": "plain error text"})
                if m == "err-detail":
                    return self._send(422, {"detail": "detail text"})
                self.send_response(200)
                self.send_header("content-type", "text/event-stream")
                self.end_headers()
                if m.startswith("extract"):
                    text = body["messages"][-1]["content"].strip("-\n")
                    names = list(dict.fromkeys(re.findall(r"\b([A-Z][a-z]+ [A-Z][a-z]+)\b", text)))[:3]
                    ents = [{"name": n, "kind": "person"} for n in names]
                    edges = [{"type": "mentions", "to": n, "quote": "this quote is not in the text at all" if m == "extract-bad" else text[text.index(n):text.index(n) + len(n) + 14]} for n in names]
                    answer = "I would rather talk about something else." if m == "extract-junk" else json.dumps({"entities": ents, "edges": edges})
                    pieces = [answer[i:i + 40] for i in range(0, len(answer), 40)]
                else:
                    pieces = [] if m == "empty" else ["Hello", " there"] if m != "slow" else ["a"] * 30
                try:
                    for p in pieces:
                        self.wfile.write(b"data: " + json.dumps({"choices": [{"delta": {"content": p}}]}).encode() + b"\n\n")
                        self.wfile.flush()
                        if m == "slow":
                            time.sleep(0.2)
                        if m == "extract-slow":
                            time.sleep(0.4)
                    self.wfile.write(b"data: " + json.dumps({"choices": [{"delta": {"reasoning_content": "ignored"}}]}).encode() + b"\n\n")
                    if m != "nodone":
                        self.wfile.write(b"data: [DONE]\n\n")
                    self.wfile.flush()
                except OSError:
                    outer.dropped = True

        self.last_body, self.dropped = None, False
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.httpd.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}{prefix}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()
