#!/bin/bash
# Start flowlystack locally: http://127.0.0.1:8372
cd "$(dirname "$0")"
# A leftover server (for example one that hung during a reload) would make the new one fail with a cryptic
# "address already in use" and the browser would keep spinning, so say who holds the port.
OLD=$(lsof -nP -iTCP:"${PORT:-8372}" -sTCP:LISTEN -t 2>/dev/null | head -1)
[ -n "$OLD" ] && { echo "Port ${PORT:-8372} is already in use by process $OLD. Stop it first:  kill $OLD" >&2; exit 1; }
# pyproject.toml is the one dependency list. Installing from it on every start costs a fraction of a second when
# nothing changed, and keeps an existing .venv in step after a pull.
[ -d .venv ] || uv venv --python 3.12 .venv || exit 1
uv pip install --quiet --python .venv/bin/python -r pyproject.toml || { echo "Could not install the dependencies from pyproject.toml (see the message above)." >&2; exit 1; }
# Auto-restarts when files under backend/ change (RELOAD=0 ./run.sh to turn off).
# --timeout-graceful-shutdown: the live-update stream (/api/stream) never ends on its own, so without a limit
# every reload waited forever for any open browser tab and the server stayed down until it was restarted by hand.
RELOAD_ARGS=(--reload --reload-dir backend)
[ "${RELOAD:-1}" = "0" ] && RELOAD_ARGS=()
exec .venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port "${PORT:-8372}" --timeout-graceful-shutdown 1 "${RELOAD_ARGS[@]}"
