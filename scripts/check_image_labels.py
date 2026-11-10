#!/usr/bin/env python3
"""Checks that the image description is one sentence in three places: pyproject.toml, the Dockerfile LABEL and the
metadata-action labels in .github/workflows/release.yml. Stdlib only, no server, no Docker.
    python3 scripts/check_image_labels.py
Also checks the other Dockerfile labels are present (title, licenses, source, url), that the licence is MIT like the LICENSE file,
and that the LABEL comes after the dependency install (so a label change never reinstalls the dependencies)."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    release = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")

    py_desc = re.search(r'^description\s*=\s*"([^"]+)"', pyproject, re.M).group(1)
    labels = dict(re.findall(r'(org\.opencontainers\.image\.[a-z]+)="([^"]*)"', dockerfile))
    wf = re.search(r"org\.opencontainers\.image\.description=(.+)", release)
    assert wf, "release.yml does not pin org.opencontainers.image.description"
    wf_desc = wf.group(1).strip()

    assert labels.get("org.opencontainers.image.description") == py_desc, (labels.get("org.opencontainers.image.description"), py_desc)
    assert wf_desc == py_desc, (wf_desc, py_desc)
    print("ok  one description in pyproject.toml, the Dockerfile and release.yml: %r" % py_desc)

    wf_title = re.search(r"org\.opencontainers\.image\.title=(.+)", release)
    assert wf_title and wf_title.group(1).strip() == labels.get("org.opencontainers.image.title"), "release.yml must pin the same title as the Dockerfile"
    print("ok  the title is pinned the same in the Dockerfile and release.yml: %r" % labels["org.opencontainers.image.title"])

    for key in ("title", "licenses", "source", "url"):
        assert labels.get("org.opencontainers.image." + key), "Dockerfile has no org.opencontainers.image." + key
    assert labels["org.opencontainers.image.licenses"] == "MIT" and (ROOT / "LICENSE").read_text(encoding="utf-8").startswith("MIT License")
    assert labels["org.opencontainers.image.source"].startswith("https://github.com/")
    print("ok  title, licenses (MIT), source and url are set")

    assert dockerfile.index("LABEL org.opencontainers") > dockerfile.index("uv pip install"), "LABEL must come after the dependency install"
    print("ok  the LABEL comes after the dependency install (cache stays valid)")
    print("\ncheck_image_labels: all passed")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as e:
        print("FAIL  %s" % (e,))
        sys.exit(1)
