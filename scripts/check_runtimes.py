#!/usr/bin/env python3
"""Checks for backend/assistant/openai_compat.py against a fake OpenAI-compatible server. Plain asserts, standard library only.

    python3 scripts/check_runtimes.py
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backend.assistant.base import ProviderError   # noqa: E402
from backend.assistant.openai_compat import OpenAICompatProvider as P   # noqa: E402
from fake_openai import FakeOpenAI, MODELS   # noqa: E402


def step(msg):
    print("ok  ", msg)


def raises(fn, needle):
    try:
        fn()
    except ProviderError as e:
        assert needle.lower() in str(e).lower(), (needle, str(e))
        return str(e)
    raise AssertionError(f"expected ProviderError containing {needle!r}")


def text(p, model="ok"):
    return "".join(p.stream([{"role": "user", "content": "hi"}], {"model": model, "temperature": 0.4, "num_ctx": 4096}))


# ---- no key
s = FakeOpenAI()
p = P("rt-aaaaaaaa", "Fake", s.url)
assert p.status() == {"reachable": True, "version": "", "error": ""}
assert p.models() == MODELS
assert text(p) == "Hello there"
assert s.last_body["stream"] is True and s.last_body["temperature"] == 0.4 and "num_ctx" not in s.last_body and "max_tokens" not in s.last_body
assert all(a == "" for _, _, a in s.seen)   # no key: no Authorization header
step("models, status and a streamed answer; no num_ctx, no max_tokens, no header without a key")

# ---- error shapes, empty and unfinished streams
raises(lambda: text(p, "err-obj"), "model 'x' is not loaded")
raises(lambda: text(p, "err-text"), "plain error text")
raises(lambda: text(p, "err-detail"), "detail text")
assert text(p, "nodone") == "Hello there"   # a stream that ends without [DONE] still gives its text
assert text(p, "empty") == ""               # the route layer turns this into "The model sent an empty answer"
step("three error shapes name the connection; missing [DONE] and empty answers behave")

# ---- wrong address and unreadable answers
bad = P("rt-aaaaaaaa", "Fake", s.url.replace("/v1", ""))
raises(bad.models, "no such route")
assert bad.status()["reachable"] is False
odd = P("rt-aaaaaaaa", "Fake", s.url + "/not")
raises(odd.models, "no such route")
raises(lambda: P("rt-aaaaaaaa", "Fake", s.url.replace("/models", "")).embed("m", ["x"]), "not used for embeddings")
step("a wrong path is a clear error; embeddings are refused")

# ---- stop mid-stream closes the connection
it = P("rt-aaaaaaaa", "Fake", s.url).stream([{"role": "user", "content": "hi"}], {"model": "slow"})
assert next(it) == "a"
it.close()
time.sleep(0.6)
assert s.dropped, "the server should notice the closed connection"
step("closing the generator stops the model call")
s.close()

# ---- key required
k = FakeOpenAI(key="s3cret")
assert P("rt-bbbbbbbb", "Locked", k.url).status()["reachable"] is False
raises(P("rt-bbbbbbbb", "Locked", k.url).models, "refused the key")
raises(P("rt-bbbbbbbb", "Locked", k.url, key="wrong").models, "refused the key")
q = P("rt-bbbbbbbb", "Locked", k.url, key="s3cret")
assert q.models() == MODELS and text(q) == "Hello there"
assert k.seen[-1][2] == "Bearer s3cret"
step("a key is required, rejected when wrong, sent as a Bearer header when right")

# ---- a redirect is refused and the key never reaches the other host
other = FakeOpenAI()
r = FakeOpenAI(redirect_to=other.url.replace("/v1", ""))
raises(P("rt-cccccccc", "Moved", r.url, key="s3cret").models, "redirected")
assert other.seen == [], other.seen
step("redirects are refused and the key is not forwarded")
for x in (k, other, r):
    x.close()

# ---- unreachable
raises(P("rt-dddddddd", "Down", "http://127.0.0.1:1/v1").models, "Cannot reach Down")
assert P("rt-dddddddd", "Down", "http://127.0.0.1:1/v1").status()["reachable"] is False
step("an unreachable server is a readable error")
print("all runtime adapter checks passed")
