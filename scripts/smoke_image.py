#!/usr/bin/env python3
"""The "starts empty" proof for the Docker image: runs the image with fresh anonymous volumes (no mounts at all), waits for it,
and checks what a first visitor would meet. Stdlib only; needs the docker command.

    python3 scripts/smoke_image.py flowlystack:local

Checks: the app answers within 120 s; the first-visit state says no account exists yet; the front page is served; the app
process (PID 1) does not run as root; the prompts folder is empty; the data folder holds no login file. The container gets a random host port
on 127.0.0.1 and a throwaway name, and is removed (with its volumes) at the end, pass or fail. Exit code 0 = all good."""
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid


def docker(*args, check=True):
    r = subprocess.run(["docker"] + list(args), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
    if check and r.returncode != 0:
        raise AssertionError("docker %s failed:\n%s" % (" ".join(args), r.stdout))
    return r.stdout.strip()


def get(url, timeout=5):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.status, r.read().decode("utf-8", "replace")


def main(argv):
    if len(argv) != 1:
        sys.stderr.write(__doc__)
        return 2
    image = argv[0]
    name = "flowlystack-smoke-" + uuid.uuid4().hex[:8]
    try:
        print("image %s: %s" % (image, docker("image", "inspect", "--format", "{{.Os}}/{{.Architecture}}, {{.Size}} bytes", image)))
        # --rm removes the anonymous volumes with the container; no -v, so nothing from this computer is mounted.
        # The auth gate stays ON: the first visitor must see the sign-up state, not a bypass.
        docker("run", "-d", "--rm", "--name", name, "-p", "127.0.0.1::8372", image)
        m = re.search(r":(\d+)$", docker("port", name, "8372/tcp").splitlines()[0])
        base = "http://127.0.0.1:%s" % m.group(1)

        state = None
        deadline = time.time() + 120
        while time.time() < deadline:
            try:
                status, body = get(base + "/api/auth/state")
                if status == 200:
                    state = json.loads(body)
                    break
            except (urllib.error.URLError, ConnectionError, OSError, ValueError):
                pass
            time.sleep(2)
        assert state is not None, "the app did not answer in 120 s:\n" + docker("logs", "--tail", "30", name, check=False)
        print("ok  answers after %d s: /api/auth/state -> %s" % (120 - (deadline - time.time()), json.dumps(state)))

        # No account yet: the sign-up screen is what a first visitor must meet, with nobody signed in.
        assert state.get("needs_setup") is True and state.get("signed_in") is False, state
        print("ok  first-visit state: sign-up needed, nobody signed in")

        status, page = get(base + "/")
        assert status == 200 and "flowlystack" in page.lower(), page[:200]
        print("ok  the front page is served")

        # `docker exec` starts a new process as the container's default user; the app is PID 1 after the entrypoint drops privileges.
        uid = docker("exec", name, "sh", "-c", "awk '/^Uid:/ {print $2}' /proc/1/status")
        assert uid not in ("", "0"), "the app (PID 1) runs as root (uid %s)" % uid
        print("ok  the app process runs as uid %s, not root" % uid)

        prompts = docker("exec", name, "sh", "-c", "ls -A /app/prompts | wc -l")
        assert prompts == "0", "the prompts folder is not empty (%s entries)" % prompts
        auth = docker("exec", name, "sh", "-c", "test -e /app/data/auth.json && echo yes || echo no")
        assert auth == "no", "an auth.json exists before anyone signed up"
        print("ok  prompts folder empty, no login file")
        print("\nsmoke_image: all passed")
        return 0
    except AssertionError as e:
        print("FAIL  %s" % e)
        return 1
    finally:
        docker("rm", "-f", "-v", name, check=False)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
