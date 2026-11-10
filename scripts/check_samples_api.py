#!/usr/bin/env python3
"""Checks /api/samples against a TEST server (empty temp prompts and settings folders, FLOWLYSTACK_AUTH=off), see CONTRIBUTING.md. Standard library only.

    BASE=http://127.0.0.1:8799 python3 scripts/check_samples_api.py
"""
import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("BASE", "http://127.0.0.1:8799")


def call(method, path, body=None):
    req = urllib.request.Request(BASE + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"null")
    except OSError as e:
        sys.exit(f"Cannot reach {BASE}: {e}. Start a test server first (see CONTRIBUTING.md).")


def counts():
    return {"studio": call("GET", "/api/studio")[1]["total"], "linkshell": call("GET", "/api/linkshell")[1]["total"],
            "library": call("GET", "/api/prompts")[1]["total"],
            "collections": len([c for c in call("GET", "/api/collections")[1]["items"] if not c.get("builtin")])}


assert counts() == {"studio": 0, "linkshell": 0, "library": 0, "collections": 0}, "run this against an EMPTY test server: " + str(counts())

c, s = call("GET", "/api/samples")
assert c == 200 and s["state"] == "offered" and s["can_offer"] is True and s["will_add"]["studio"] == 4, s

c, r = call("POST", "/api/samples/add")
assert c == 200 and r["added"] is True and r["present"] == {"studio": 4, "linkshell": 1, "collections": 1} and r["can_offer"] is False, r
assert counts() == {"studio": 4, "linkshell": 1, "library": 0, "collections": 1}, counts()   # the Library gets nothing
studio = call("GET", "/api/studio")[1]
assert all(i["meta"]["tags"] == ["Sample"] for i in studio["items"])
assert call("GET", "/api/linkshell")[1]["items"][0]["tags"] == ["Sample"]

c, r = call("POST", "/api/samples/add")   # again: nothing more
assert c == 200 and r["added"] is False and counts()["studio"] == 4

c, r = call("POST", "/api/samples/dismiss")   # after adding it changes nothing
assert c == 200 and r["state"] == "added"

c, r = call("POST", "/api/samples/remove")
assert c == 200 and r["removed"] == {"studio": 4, "linkshell": 1, "collections": 1} and r["kept"] == 0 and r["state"] == "removed", r
assert counts() == {"studio": 0, "linkshell": 0, "library": 0, "collections": 0}, counts()
assert call("GET", "/api/samples")[1]["can_offer"] is False   # not offered again, but can be added again

c, r = call("POST", "/api/samples/add")
assert c == 200 and r["added"] is True and counts()["studio"] == 4
call("POST", "/api/samples/remove")

print("all samples API checks passed")
