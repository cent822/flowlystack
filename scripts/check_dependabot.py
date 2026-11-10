#!/usr/bin/env python3
"""Checks .github/dependabot.yml against the pins it protects. Stdlib only (text checks), no server, no network.
    python3 scripts/check_dependabot.py
- Meilisearch is pinned to v1.40.x in docker-compose.yml, and dependabot.yml blocks >=1.41.0 for it (typo tolerance breaks from 1.41.0).
- The Dockerfile uses Python 3.12, and dependabot.yml blocks >=3.13 for the base image.
- All four ecosystems are watched, with a cooldown, and nothing is set to auto-merge.
- Every GitHub Action in .github/workflows is pinned to a full 40-character commit hash (Dependabot keeps the hashes current)."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    dep = (ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    for eco in ("github-actions", "pip", "docker", "docker-compose"):
        assert re.search(r"package-ecosystem:\s*%s\s*$" % re.escape(eco), dep, re.M), "dependabot.yml does not watch " + eco
    assert dep.count("cooldown:") == 4, "every ecosystem should have a cooldown"
    assert "automerge" not in dep.lower() and "auto-merge" not in dep.lower().replace("never merges", ""), "Dependabot must never auto-merge"
    print("ok  all four ecosystems watched, each with a cooldown, no auto-merge")

    pin = re.search(r"image:\s*getmeili/meilisearch:v(\d+)\.(\d+)\.(\d+)", compose)
    assert pin and (pin.group(1), pin.group(2)) == ("1", "40"), "docker-compose.yml must keep Meilisearch on v1.40.x (typo tolerance breaks from v1.41.0; re-run the incremental-add typo test before changing it)"
    block = re.search(r"dependency-name:\s*getmeili/meilisearch\s*\n\s*versions:\s*\[\"([^\"]+)\"\]", dep)
    assert block and block.group(1) == ">=1.41.0", "dependabot.yml must block Meilisearch >=1.41.0"
    print("ok  Meilisearch pinned to v1.40.x and Dependabot blocks >=1.41.0")

    assert re.search(r"^FROM python:3\.12(-|\s|$)", dockerfile, re.M), "the Dockerfile base image must be Python 3.12"
    py = re.search(r"dependency-name:\s*python\s*\n\s*versions:\s*\[\"([^\"]+)\"\]", dep)
    assert py and py.group(1) == ">=3.13", "dependabot.yml must block python >=3.13"
    print("ok  base image is Python 3.12 and Dependabot blocks >=3.13")

    uses = []
    for wf in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        for line in wf.read_text(encoding="utf-8").splitlines():
            m = re.match(r"\s*-?\s*uses:\s*(\S+)", line)
            if m and not m.group(1).startswith("./"):
                uses.append((wf.name, m.group(1)))
    assert uses, "no actions found"
    for name, ref in uses:
        assert re.fullmatch(r"[\w./-]+@[0-9a-f]{40}", ref), "%s: %s is not pinned to a full commit hash" % (name, ref)
    print("ok  all %d action references are pinned to a 40-character commit hash" % len(uses))
    print("\ncheck_dependabot: all passed")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as e:
        print("FAIL  %s" % (e,))
        sys.exit(1)
