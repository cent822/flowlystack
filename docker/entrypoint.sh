#!/bin/sh
# Starts FlowlyStack. As root it first makes sure the two folders the app writes (/app/data and /app/prompts) belong to PUID:PGID
# (default 1000:1000), because Docker creates a missing bind-mounted folder as root, then drops to that user. As any other user it just runs.
set -e

# Meilisearch (the second service) needs a master key. Nobody types one: the first start makes a random key in a small volume shared with it
# (the Meilisearch service waits for that file), and the app reads it here. An existing key is never replaced.
if [ -n "$FLOWLYSTACK_SEARCH_KEY_FILE" ]; then
  if [ ! -s "$FLOWLYSTACK_SEARCH_KEY_FILE" ]; then
    mkdir -p "$(dirname "$FLOWLYSTACK_SEARCH_KEY_FILE")" 2>/dev/null || true
    head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n' > "$FLOWLYSTACK_SEARCH_KEY_FILE.tmp" 2>/dev/null && mv "$FLOWLYSTACK_SEARCH_KEY_FILE.tmp" "$FLOWLYSTACK_SEARCH_KEY_FILE" || echo "flowlystack: could not make the search key; search falls back to plain matching" >&2
  fi
  if [ -s "$FLOWLYSTACK_SEARCH_KEY_FILE" ]; then FLOWLYSTACK_MEILI_KEY="$(cat "$FLOWLYSTACK_SEARCH_KEY_FILE")"; export FLOWLYSTACK_MEILI_KEY; fi
fi

if [ "$(id -u)" = "0" ]; then
  PUID="${PUID:-1000}"; PGID="${PGID:-1000}"
  mkdir -p /app/data /app/prompts
  for d in /app/data /app/prompts; do
    # only when the top folder has another owner (a first start, or a changed PUID): re-owning a big folder on every start would be slow
    if [ "$(stat -c %u "$d")" != "$PUID" ]; then chown -R "$PUID:$PGID" "$d" 2>/dev/null || echo "flowlystack: could not change the owner of $d (a mounted folder that refuses it); continuing" >&2; fi
  done
  exec setpriv --reuid="$PUID" --regid="$PGID" --clear-groups "$@"
fi
exec "$@"
