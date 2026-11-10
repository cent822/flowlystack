#!/usr/bin/env python3
"""Checks skills/flowlystack-install (the agent skill that only installs FlowlyStack): front matter, size, referenced files, no private
text, no sudo instruction, every installer flag it names exists, and its facts (URLs, container name, port) match the repository.
Standard library only; needs bash for `install.sh --help`."""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SK = ROOT / "skills" / "flowlystack-install"
SKILL = SK / "SKILL.md"
assert SKILL.exists(), "skills/flowlystack-install/SKILL.md is missing"

text = SKILL.read_text(encoding="utf-8")
m = re.match(r"---\n(.*?)\n---\n", text, re.S)
assert m, "SKILL.md must start with front matter"
fm = {}
for line in m.group(1).splitlines():
    k, _, v = line.partition(":")
    fm[k.strip()] = v.strip()
assert set(fm) == {"name", "description"}, f"front matter must hold only name and description, found {sorted(fm)}"
assert fm["name"] == SK.name and re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", fm["name"]), fm["name"]
assert 40 <= len(fm["description"]) <= 500, len(fm["description"])
assert "install" in fm["description"].lower() and "only" in fm["description"].lower()
assert len(text.splitlines()) < 200, f"SKILL.md has {len(text.splitlines())} lines"

files = sorted(p for p in SK.rglob("*") if p.is_file() and p.name != ".DS_Store")
assert {p.relative_to(SK).as_posix() for p in files} == {"SKILL.md", "references/manual-docker.md", "references/troubleshooting.md"}, [p.relative_to(SK).as_posix() for p in files]
for p in files:   # every reference file is named in SKILL.md, and every name points at a file
    rel = p.relative_to(SK).as_posix()
    if rel != "SKILL.md":
        assert f"`{rel}`" in text, f"SKILL.md does not mention {rel}"
for ref in set(re.findall(r"`(references/[\w.-]+)`", text)):
    assert (SK / ref).exists(), ref

alltext = "\n".join(p.read_text(encoding="utf-8") for p in files)

# nothing private, nothing risky
for bad in (r"(?<![:\w])/Users/", r"C:[/\\]Users[/\\](?!<name>)", r"[\w.+-]+@[\w-]+\.[\w.]+", r"docs/[\w-]*(plan|buildplan)\.md", r"docs/reference-", r"CLAUDE\.md", r"devlog"):
    hit = re.search(bad, alltext, re.I)
    assert not hit, f"private text in the skill: {hit.group(0)!r}"
# The owner's own private words (name, e-mail ...) live in a local rule file outside the repository (scripts/leak_check.py); no such file, no extra check.
sys.path.insert(0, str(ROOT / "scripts"))
import leak_check  # noqa: E402
for rx in leak_check.private_patterns(ROOT):
    assert not rx.search(alltext), "a private word from the local rule file is in the skill (not printed here)"
assert not re.search(r"\|\s*(ba)?sh\b", alltext), "a download must never be piped into a shell"
for span in re.findall(r"`([^`\n]+)`", alltext) + re.findall(r"```[a-z]*\n(.*?)```", alltext, re.S):
    assert not re.match(r"\s*sudo\s+\S", span), f"the skill must not tell anyone to run sudo: {span!r}"
assert "sudo" in text and "No `sudo`" in text   # the rule itself is there

# the installer flags it names exist
helptext = subprocess.run(["/bin/bash", str(ROOT / "install.sh"), "--help"], capture_output=True, text=True).stdout
flags = {w for w in re.findall(r"--[a-z][a-z-]*", helptext)}
assert {"--dry-run", "--port", "--setup-capture", "--undo-capture", "--dir"} <= flags, flags
for line in alltext.splitlines():
    if "install.sh" in line or "bash <file>" in line or "installer" in line.lower() and "--" in line:
        for fl in re.findall(r"(?<![\w-])--[a-z][a-z-]*", line):
            assert fl in flags, f"the skill names {fl}, which install.sh does not have: {line.strip()}"
assert "--yes" in flags and "do not add `--yes`" in text   # the agent must not answer the capture question for the user

# facts match the repository
raw = "https://raw.githubusercontent.com/cent822/flowlystack/main/"
for url in re.findall(r"https://raw\.githubusercontent\.com/[^\s`)'\"]+", alltext):
    assert url.startswith(raw), f"unexpected source URL: {url}"
    assert (ROOT / url[len(raw):]).exists(), f"{url} points at a file that does not exist in the repository"
for url in re.findall(r"https?://[^\s`)'\"]+", alltext):
    assert url.startswith((raw, "https://www.docker.com/", "https://docs.docker.com/", "http://127.0.0.1")), f"unexpected URL: {url}"
assert (ROOT / "docs" / "mcp-setup.md").exists() and "docs/mcp-setup.md" in text
compose = (ROOT / "docker-compose.yml").read_text()
assert "flowlystack-app" in compose and "flowlystack-app" in text
assert "FLOWLYSTACK_PORT:-8372" in compose and "8372" in text
assert "8372" in (ROOT / "install.sh").read_text()
assert "    build: ." in compose and "build: ." in alltext   # the line both install paths remove

print("all skill checks passed")
