#!/usr/bin/env python3
"""Checks how Open WebUI's webui.db is opened for reading (backend/sources/ollama/db.py `open_webui`), including a cleanly stopped Open WebUI
(a WAL database with no -shm file) on a folder that cannot be written, which is what a read-only Docker mount looks like.
Temp folder only, no server, no Docker.    .venv/bin/python scripts/check_webui_readonly.py"""
import os
import sqlite3
import stat
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.sources.ollama.db import open_webui  # noqa: E402

root = Path(tempfile.mkdtemp())
dbp = root / "webui.db"
c = sqlite3.connect(dbp)
c.execute("PRAGMA journal_mode=WAL")
c.execute("CREATE TABLE t(x)")
c.execute("INSERT INTO t VALUES (1),(2)")
c.commit()
c.close()
assert sorted(os.listdir(root)) == ["webui.db"], "a clean close leaves no -wal or -shm"

# 1. writable folder: the normal mode=ro path
assert open_webui(dbp).execute("SELECT count(*) FROM t").fetchone()[0] == 2

# 2. read-only folder and file, no -shm: plain mode=ro may fail, open_webui falls back and reads
os.chmod(dbp, stat.S_IREAD)
os.chmod(root, stat.S_IREAD | stat.S_IEXEC)
try:
    if os.access(root, os.W_OK):
        print("skipped the read-only folder case (running as a user that can write anywhere)")
    else:
        try:
            sqlite3.connect(f"file:{dbp}?mode=ro", uri=True).execute("SELECT count(*) FROM t")
            print("note: plain mode=ro worked here, so the fallback was not needed on this system")
        except sqlite3.OperationalError:
            pass
        assert open_webui(dbp).execute("SELECT count(*) FROM t").fetchone()[0] == 2, "falls back and reads"
finally:
    os.chmod(root, stat.S_IRWXU)
    os.chmod(dbp, stat.S_IRUSR | stat.S_IWUSR)
    for f in root.iterdir():
        f.unlink()
    root.rmdir()
print("all Open WebUI read-only checks passed")
