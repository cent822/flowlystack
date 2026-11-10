"""The owner's profile picture (standard library only). One file, `avatar.png`, next to `auth.json` (tests use FLOWLYSTACK_SETTINGS_DIR).

The browser shrinks and re-encodes whatever the user picks into a PNG of at most 512 pixels a side before sending it, so this module
accepts nothing else: a PNG signature, a real IHDR with sane sizes, the closing IEND chunk, and a size limit. No image library, no SVG
(it can carry script), no metadata from the original photo. The picture stays on this computer; nothing sends it anywhere and MCP agents
never see it. Written atomically, owner-only.
"""
from __future__ import annotations

import os
import struct
import tempfile
from pathlib import Path

from .config import SETTINGS_DIR

MAX_BYTES = 400_000
MIN_PX, MAX_PX = 32, 512
_SIG = b"\x89PNG\r\n\x1a\n"
_IEND = b"IEND\xaeB`\x82"


class ProfileError(Exception):
    pass


def _path() -> Path:
    return SETTINGS_DIR / "avatar.png"


def check_png(data) -> None:
    if not isinstance(data, (bytes, bytearray)) or not data:
        raise ProfileError("No picture was sent.")
    if len(data) > MAX_BYTES:
        raise ProfileError("That picture is too large.")
    if data[:8] != _SIG or data[12:16] != b"IHDR" or struct.unpack(">I", data[8:12])[0] != 13 or not bytes(data).endswith(_IEND):
        raise ProfileError("The picture must be a PNG made by the app.")
    w, h = struct.unpack(">II", data[16:24])
    if not (MIN_PX <= w <= MAX_PX and MIN_PX <= h <= MAX_PX):
        raise ProfileError(f"The picture must be between {MIN_PX} and {MAX_PX} pixels on each side.")


def save(data) -> int:
    """Store the picture (replacing any earlier one) and return its version."""
    check_png(data)
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix="avatar.png.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, p)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return version()


def remove() -> None:
    _path().unlink(missing_ok=True)


def read() -> bytes | None:
    try:
        return _path().read_bytes()
    except OSError:
        return None


def version() -> int | None:
    """A number that changes whenever the picture does (the browser asks for `?v=<version>`), or None when there is none."""
    try:
        return _path().stat().st_mtime_ns // 1000   # microseconds: small enough to stay exact as a JSON number in the browser
    except OSError:
        return None
