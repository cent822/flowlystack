#!/bin/sh
# Switches the leak-check hooks ON for this clone (copies them into .git/hooks). Run it once, only when you mean to.
# Switch them off again: rm .git/hooks/pre-commit .git/hooks/pre-push
set -e
root=$(git rev-parse --show-toplevel)
for h in pre-commit pre-push; do
  cp "$root/scripts/githooks/$h" "$(git rev-parse --git-path hooks)/$h"
  chmod +x "$(git rev-parse --git-path hooks)/$h"
  echo "installed $h"
done
