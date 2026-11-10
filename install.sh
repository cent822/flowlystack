#!/usr/bin/env bash
# FlowlyStack installer for Mac and Linux. It installs nothing on your computer except Docker containers and one folder.
#
#   curl -fsSL https://raw.githubusercontent.com/cent822/flowlystack/main/install.sh | bash
#
# or download it, read it, then run it:   bash install.sh --help
#
# What it does: checks that Docker works, makes an install folder (default ~/flowlystack) with your prompts folder inside,
# writes a small .env (port, time zone, the Claude Code / Codex folders it finds), fetches docker-compose.yml, starts the app
# and prints the address. It never asks questions, never uses sudo, never deletes anything, and is safe to run again.
# It only checks that your Claude Code and Codex folders exist; it never opens what is inside them.
#
# Optional, only when you ask:  --setup-capture  adds the prompt-capture hook to ~/.claude/settings.json after showing you the
# exact change and asking for a typed "yes" (a backup is made first);  --undo-capture  takes that hook out again.

# Everything runs from main(), called on the last line, so a download cut short can never run half a script.
main() {
  set -eu

  REPO="cent822/flowlystack"
  DIR="${HOME}/flowlystack"
  PORT="8372"
  VERSION="latest"
  NO_START=0
  DRY=0
  SETUP_CAPTURE=0
  UNDO_CAPTURE=0
  ASSUME_YES=0
  VERSION_GIVEN=0
  PORT_GIVEN=0
  WORK_DIR=""
  # Hidden settings, for tests and second installs: FLOWLYSTACK_RAW_BASE (where the files are fetched from), FLOWLYSTACK_IMAGE,
  # FLOWLYSTACK_PROJECT (compose project name), FLOWLYSTACK_CONTAINER, FLOWLYSTACK_NO_PULL=1, FLOWLYSTACK_TTY, CLAUDE_SETTINGS.
  PROJECT="${FLOWLYSTACK_PROJECT:-}"
  NAME="${FLOWLYSTACK_CONTAINER:-flowlystack-app}"
  TTY_FILE="${FLOWLYSTACK_TTY:-/dev/tty}"
  SETTINGS="${CLAUDE_SETTINGS:-${HOME}/.claude/settings.json}"

  say()  { printf '%s\n' "$*"; }
  note() { printf '  %s\n' "$*"; }
  warn() { printf 'Note: %s\n' "$*" >&2; }
  die()  { printf 'Error: %s\n' "$*" >&2; exit 1; }

  usage() {
    cat <<'EOF'
FlowlyStack installer (Mac and Linux)

  bash install.sh [options]

  --dir <path>       install folder (default: ~/flowlystack)
  --port <number>    port on this computer (default: 8372)
  --version <tag>    FlowlyStack version, for example 0.1.0 (default: latest)
  --no-start         write the files but do not pull or start anything
  --dry-run          show what would happen and write nothing
  --setup-capture    add the prompt-capture hook to ~/.claude/settings.json (shows the change, asks for "yes", makes a backup)
  --undo-capture     take that hook out of ~/.claude/settings.json again
  --yes              answer "yes" to the one capture question (for scripts)
  --help             this text

Needs Docker (Docker Desktop on Mac, Docker Engine on Linux) with the compose plugin.
EOF
  }

  # ---- options -------------------------------------------------------------------------------------------------------------
  while [ $# -gt 0 ]; do
    case "$1" in
      --dir)           [ $# -ge 2 ] || die "--dir needs a folder"; DIR="$2"; shift 2 ;;
      --port)          [ $# -ge 2 ] || die "--port needs a number"; PORT="$2"; PORT_GIVEN=1; shift 2 ;;
      --version)       [ $# -ge 2 ] || die "--version needs a tag"; VERSION="$2"; VERSION_GIVEN=1; shift 2 ;;
      --no-start)      NO_START=1; shift ;;
      --dry-run)       DRY=1; shift ;;
      --setup-capture) SETUP_CAPTURE=1; shift ;;
      --undo-capture)  UNDO_CAPTURE=1; shift ;;
      --yes)           ASSUME_YES=1; shift ;;
      --help|-h)       usage; return 0 ;;
      *)               usage >&2; die "unknown option: $1" ;;
    esac
  done
  case "$PORT" in ''|*[!0-9]*) die "--port must be a number" ;; esac
  case "$VERSION" in *[!A-Za-z0-9._-]*|'') die "--version must be a tag such as 0.1.0 or latest" ;; esac
  [ "$(id -u)" != "0" ] || die "run this as your normal user, not as root or with sudo (it only needs Docker access)."
  case "$DIR" in "~"|"~/"*) DIR="${HOME}${DIR#"~"}" ;; esac
  [ "$SETUP_CAPTURE" = 1 ] && [ "$UNDO_CAPTURE" = 1 ] && die "use --setup-capture or --undo-capture, not both"
  real_path() { (cd "$1" 2>/dev/null && pwd -P) || printf '%s' "$1"; }
  if [ "$(real_path "$DIR")" = "$(real_path "$HOME")" ] || [ "$(real_path "$DIR")" = "/" ]; then
    die "--dir must be a folder of its own (for example ~/flowlystack), not your home folder or the root: the installer writes .env and docker-compose.yml into it."
  fi
  check_name() {   # the container name ends up in a command that Claude Code runs later, so only Docker's own characters are allowed
    case "$NAME" in ''|[!A-Za-z0-9]*|*[!A-Za-z0-9_.-]*) die "the container name '$NAME' is not valid (letters, digits, _ . - only, starting with a letter or digit)." ;; esac
  }
  check_name

  # a temporary copy of your settings file lives in WORK_DIR while the capture change is prepared; it is removed on every way out
  drop_work() { if [ -n "$WORK_DIR" ]; then rm -rf "$WORK_DIR"; fi; WORK_DIR=""; }
  trap drop_work EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM

  dc() {
    if [ -n "$PROJECT" ]; then docker compose --project-directory "$DIR" -p "$PROJECT" "$@"; else docker compose --project-directory "$DIR" "$@"; fi
  }

  # ---- docker --------------------------------------------------------------------------------------------------------------
  check_docker() {
    if ! command -v docker >/dev/null 2>&1; then
      say "Docker is not installed."
      note "Install Docker Desktop (Mac) from https://www.docker.com/products/docker-desktop/ or Docker Engine (Linux) from https://docs.docker.com/engine/install/ , then run this again."
      return 1
    fi
    if ! docker compose version >/dev/null 2>&1; then
      say "Docker is installed but the compose plugin is missing (the 'docker compose' command)."
      note "Docker Desktop includes it. On Linux see https://docs.docker.com/compose/install/linux/ , then run this again."
      return 1
    fi
    if ! docker info >/dev/null 2>&1; then
      say "Docker is installed but not answering."
      note "Start Docker Desktop (or the Docker service) and wait until it says it is running. On Linux your user may need to be in the 'docker' group."
      return 1
    fi
  }

  # ---- detection (existence only; nothing inside these folders is opened) ---------------------------------------------------
  detect_tz() {
    local l
    l="$(readlink /etc/localtime 2>/dev/null || true)"
    case "$l" in *zoneinfo/*) printf '%s' "${l#*zoneinfo/}"; return 0 ;; esac
    if [ -r /etc/timezone ]; then head -n 1 /etc/timezone; return 0; fi
    printf ''
  }

  fetch() {   # fetch <url> <dest>: to a temp name first, so a failed download never leaves a broken file
    local url="$1" dest="$2" tmp
    tmp="${dest}.part"
    if command -v curl >/dev/null 2>&1; then curl -fsSL "$url" -o "$tmp" || { rm -f "$tmp"; return 1; }
    elif command -v wget >/dev/null 2>&1; then wget -q "$url" -O "$tmp" || { rm -f "$tmp"; return 1; }
    else die "neither curl nor wget is installed."; fi
    mv "$tmp" "$dest"
  }

  env_quote() { case "$1" in *[!A-Za-z0-9._/:@+=,-]*) printf '"%s"' "$1" ;; *) printf '%s' "$1" ;; esac; }
  env_get() { [ -f "$DIR/.env" ] && sed -n "s/^$1=//p" "$DIR/.env" | tail -n 1 | sed 's/^"//; s/"$//' || true; }

  # ---- capture hook (opt-in) -----------------------------------------------------------------------------------------------
  confirm() {   # confirm <question>: a typed "yes", read from the terminal (also works under curl | bash)
    [ "$ASSUME_YES" = 1 ] && return 0
    if { : <"$TTY_FILE"; } 2>/dev/null; then
      local ans=""
      printf '%s ' "$1" >&2
      read -r ans <"$TTY_FILE" || ans=""
      [ "$ans" = "yes" ] && return 0
      return 1
    fi
    say "No terminal to ask on. Run it again from a terminal, or add --yes."
    return 1
  }

  hook_command() { printf 'docker exec -i %s /usr/local/bin/entrypoint.sh python hooks/%s >/dev/null 2>&1 || true' "$NAME" "$1"; }

  merge_hook() {   # merge_hook add|remove <workdir>: runs the merge helper from the app's image on a copy of the settings file
    local action="$1" work="$2" img
    img="$(docker inspect -f '{{.Config.Image}}' "$NAME" 2>/dev/null || true)"
    [ -n "$img" ] || die "the FlowlyStack container ($NAME) is not running. Start it first (run this installer without --setup-capture)."
    docker run --rm --user "$(id -u):$(id -g)" --entrypoint python -v "$work":/w "$img" /app/docker/merge_hooks.py "$action" /w/settings.json "$(hook_command capture_prompt.py)"
  }

  capture() {   # capture add|remove
    local action="$1" status ts backup
    if [ "$DRY" = 1 ]; then
      if [ "$action" = add ]; then say "Would add the capture hook to $SETTINGS (after showing the change, asking for \"yes\" and making a backup)."
      else say "Would take the capture hook out of $SETTINGS (after showing the change and asking for \"yes\")."; fi
      return 0
    fi
    WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/flowlystack.XXXXXX")"   # the template form works the same on Mac and Linux and honours TMPDIR
    if [ -f "$SETTINGS" ]; then cp "$SETTINGS" "$WORK_DIR/settings.json"; fi
    status="$(merge_hook "$action" "$WORK_DIR")" || { drop_work; die "could not prepare the change (is $SETTINGS valid JSON? nothing was changed)."; }
    case "$status" in
      already) say "The capture hook is already in $SETTINGS. Nothing to do."; drop_work; return 0 ;;
      absent)  say "The capture hook is not in $SETTINGS. Nothing to do."; drop_work; return 0 ;;
    esac
    say "This is the change to $SETTINGS:"
    if [ -f "$SETTINGS" ]; then diff -u "$SETTINGS" "$WORK_DIR/settings.json" | sed '1,2d' || true
    else say "(the file does not exist yet; it would be created with this content)"; cat "$WORK_DIR/settings.json"; fi
    say ""
    if ! confirm "Type yes to apply it (anything else cancels):"; then say "Cancelled. Nothing was changed."; drop_work; return 0; fi
    if [ -f "$SETTINGS" ]; then
      ts="$(date +%Y%m%d-%H%M%S)"; backup="${SETTINGS}.flowlystack-backup-${ts}"
      cp -p "$SETTINGS" "$backup"
      say "Backup saved: $backup"
    else
      mkdir -p "$(dirname "$SETTINGS")"
    fi
    cp "$WORK_DIR/settings.json" "${SETTINGS}.flowlystack-tmp" && mv "${SETTINGS}.flowlystack-tmp" "$SETTINGS"
    drop_work
    if [ "$action" = add ]; then
      say "Done. Claude Code now saves each prompt you send into ${DIR}/prompts (while FlowlyStack is running)."
      note "Undo: bash \"${DIR}/install.sh\" --undo-capture   (it removes exactly this hook and leaves your other settings alone)"
    else
      say "Done. The capture hook is removed."
    fi
  }

  # ---- 1. docker -----------------------------------------------------------------------------------------------------------
  if ! check_docker; then
    if [ "$DRY" = 1 ]; then warn "Docker is not ready; a real run would stop here."; else exit 1; fi
  fi

  # an install with its own container name (FLOWLYSTACK_CONTAINER in .env) is found again by --setup-capture and --undo-capture
  if [ -z "${FLOWLYSTACK_CONTAINER:-}" ] && [ -n "$(env_get FLOWLYSTACK_CONTAINER)" ]; then NAME="$(env_get FLOWLYSTACK_CONTAINER)"; check_name; fi

  if [ "$UNDO_CAPTURE" = 1 ]; then capture remove; return 0; fi

  # ---- what to install -----------------------------------------------------------------------------------------------------
  if [ "$VERSION" = "latest" ]; then REF="main"; else REF="v${VERSION#v}"; fi
  RAW_BASE="${FLOWLYSTACK_RAW_BASE:-https://raw.githubusercontent.com/${REPO}/${REF}}"
  IMAGE="${FLOWLYSTACK_IMAGE:-ghcr.io/${REPO}:${VERSION#v}}"

  CLAUDE_DIR="${HOME}/.claude/projects"
  CODEX_BASE="${CODEX_HOME:-${HOME}/.codex}"
  FOUND_CLAUDE=0; FOUND_CODEX=0
  [ -d "$CLAUDE_DIR" ] && FOUND_CLAUDE=1
  [ -d "$CODEX_BASE/sessions" ] && FOUND_CODEX=1

  # --setup-capture on an install that is already running only adds the hook; it does not touch the install
  if [ "$SETUP_CAPTURE" = 1 ] && [ "$DRY" = 0 ] && [ "$(docker inspect -f '{{.State.Running}}' "$NAME" 2>/dev/null || true)" = "true" ]; then
    capture add; return 0
  fi

  # ---- port check, before anything is written, so a busy port leaves nothing behind and a second run can simply use another port ----
  EFFECTIVE_PORT="$PORT"
  ENV_PORT="$(env_get FLOWLYSTACK_PORT)"
  [ -z "$ENV_PORT" ] || EFFECTIVE_PORT="$ENV_PORT"
  APP_RUNNING=0
  if [ "$(docker inspect -f '{{.State.Running}}' "$NAME" 2>/dev/null || true)" = "true" ]; then APP_RUNNING=1; fi
  if [ "$NO_START" = 0 ] && [ "$APP_RUNNING" = 0 ] && (exec 3<>"/dev/tcp/127.0.0.1/${EFFECTIVE_PORT}") 2>/dev/null; then
    if [ -f "$DIR/.env" ] && [ -n "$ENV_PORT" ]; then
      BUSY_MSG="port ${EFFECTIVE_PORT} (set in your $DIR/.env) is already in use. Change FLOWLYSTACK_PORT in that file (for example to 8373), then run this again."
    else
      BUSY_MSG="port ${EFFECTIVE_PORT} on this computer is already in use. Nothing was written. Run again with another port, for example:  bash install.sh --port 8373"
    fi
    if [ "$DRY" = 1 ]; then warn "$BUSY_MSG"; else die "$BUSY_MSG"; fi
  fi

  say "FlowlyStack installer"
  note "install folder: $DIR"
  note "address:        http://127.0.0.1:${PORT}"
  note "version:        ${VERSION}"
  [ "$DRY" = 1 ] && note "(dry run: nothing will be written or started)"

  # ---- 2. folders ----------------------------------------------------------------------------------------------------------
  if [ "$DRY" = 1 ]; then
    note "would create: $DIR, $DIR/prompts, $DIR/empty"
  else
    mkdir -p "$DIR/prompts" "$DIR/empty"
  fi

  # ---- 3. .env -------------------------------------------------------------------------------------------------------------
  TZ_VALUE="${TZ:-}"
  [ -n "$TZ_VALUE" ] || TZ_VALUE="$(detect_tz)"
  TZ_NOTE=""
  if [ -z "$TZ_VALUE" ]; then TZ_VALUE="UTC"; TZ_NOTE="time zone not detected, using UTC: set TZ in $DIR/.env (for example Europe/London)"; fi

  build_env() {
    printf '# Written by the FlowlyStack installer. Edit freely; the installer never overwrites this file.\n'
    printf 'FLOWLYSTACK_IMAGE=%s\n' "$(env_quote "$IMAGE")"
    printf 'FLOWLYSTACK_PORT=%s\n' "$PORT"
    printf 'TZ=%s\n' "$(env_quote "$TZ_VALUE")"
    [ "$NAME" = "flowlystack-app" ] || printf 'FLOWLYSTACK_CONTAINER=%s\n' "$(env_quote "$NAME")"
    if [ "$(uname -s)" = "Linux" ]; then printf 'PUID=%s\nPGID=%s\n' "$(id -u)" "$(id -g)"; fi
    if [ "$FOUND_CODEX" = 1 ]; then printf 'FLOWLYSTACK_SOURCES=claude,codex\n'; else printf 'FLOWLYSTACK_SOURCES=claude\n'; fi
    [ "$FOUND_CLAUDE" = 1 ] && printf 'CLAUDE_PROJECTS_DIR=%s\n' "$(env_quote "$CLAUDE_DIR")"
    if [ "$FOUND_CODEX" = 1 ]; then
      printf 'CODEX_SESSIONS_DIR=%s\n' "$(env_quote "$CODEX_BASE/sessions")"
      [ -d "$CODEX_BASE/archived_sessions" ] && printf 'CODEX_ARCHIVED_DIR=%s\n' "$(env_quote "$CODEX_BASE/archived_sessions")"
    fi
    return 0
  }

  if [ -f "$DIR/.env" ]; then
    say "Kept your existing $DIR/.env (the installer never overwrites it)."
    OLD_PORT="$PORT"
    PORT="$(env_get FLOWLYSTACK_PORT)"; PORT="${PORT:-8372}"
    if [ "$PORT_GIVEN" = 1 ] && [ "$OLD_PORT" != "$PORT" ]; then
      note "--port $OLD_PORT is ignored because your .env already sets FLOWLYSTACK_PORT=$PORT. Change it in that file to use another port."
    fi
    [ -z "$(env_get FLOWLYSTACK_CONTAINER)" ] || { NAME="$(env_get FLOWLYSTACK_CONTAINER)"; check_name; }
    OLD_IMAGE="$(env_get FLOWLYSTACK_IMAGE)"
    if [ "$VERSION_GIVEN" = 1 ] && [ -n "$OLD_IMAGE" ] && [ "$OLD_IMAGE" != "$IMAGE" ]; then
      note "Your .env uses the image $OLD_IMAGE, but --version asks for $IMAGE. The installer never edits your .env: change FLOWLYSTACK_IMAGE there to switch."
    fi
  elif [ "$DRY" = 1 ]; then
    say "Would write $DIR/.env:"
    build_env | sed 's/^/    /'
  else
    build_env > "$DIR/.env"
    say "Wrote $DIR/.env"
  fi
  [ -z "$TZ_NOTE" ] || warn "$TZ_NOTE"

  # ---- 4. compose file -----------------------------------------------------------------------------------------------------
  if [ "$DRY" = 1 ]; then
    note "would fetch: ${RAW_BASE}/docker-compose.yml"
  else
    NEWC="$DIR/docker-compose.yml.new"
    fetch "${RAW_BASE}/docker-compose.yml" "$NEWC" || die "could not download ${RAW_BASE}/docker-compose.yml (check your internet connection and the version)."
    # the repository file also has a 'build: .' line for developers; an install has no source to build from
    grep -v '^    build: \.$' "$NEWC" > "$NEWC.clean" && mv "$NEWC.clean" "$NEWC"
    if [ -f "$DIR/docker-compose.yml" ] && ! cmp -s "$NEWC" "$DIR/docker-compose.yml"; then
      cp -p "$DIR/docker-compose.yml" "$DIR/docker-compose.yml.previous"
      note "the compose file changed; the old one is saved as docker-compose.yml.previous"
    fi
    mv "$NEWC" "$DIR/docker-compose.yml"
    say "Wrote $DIR/docker-compose.yml"
    # a copy of this installer (same version) next to it, so --setup-capture and --undo-capture work later, also after curl | bash
    if fetch "${RAW_BASE}/install.sh" "$DIR/install.sh"; then note "saved the installer as $DIR/install.sh"; else warn "could not save a copy of the installer (not needed to run FlowlyStack)."; fi
  fi

  # ---- 5. start ------------------------------------------------------------------------------------------------------------
  if [ "$DRY" = 1 ] || [ "$NO_START" = 1 ]; then
    [ "$DRY" = 1 ] && note "would also save the installer as $DIR/install.sh"
    [ "$DRY" = 1 ] && note "would run: docker compose pull, then docker compose up -d, then wait for the app to answer"
  else
    RUNNING="$APP_RUNNING"
    if [ "${FLOWLYSTACK_NO_PULL:-0}" != "1" ]; then
      say "Downloading the FlowlyStack image (the first time takes a minute or two)..."
      dc pull || die "could not download the image ${IMAGE}. Check your internet connection. If this version is not published yet, nothing was started."
    fi
    say "Starting FlowlyStack..."
    dc up -d || die "docker compose could not start it (see the message above)."
    waited=0; state=""
    while [ "$waited" -lt 90 ]; do
      state="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$NAME" 2>/dev/null || true)"
      case "$state" in healthy|running) break ;; esac
      sleep 2; waited=$((waited + 2))
    done
    case "$state" in
      healthy|running) : ;;
      *) die "FlowlyStack did not become ready in 90 seconds (state: ${state:-unknown}). Look at the log with:  cd \"$DIR\" && docker compose logs" ;;
    esac
    [ "$RUNNING" = 1 ] && note "(it was already running; it has been updated and restarted if a newer image was found)"
  fi

  # ---- 6. summary ----------------------------------------------------------------------------------------------------------
  CL="not found"; CX="not found"
  [ "$FOUND_CLAUDE" = 1 ] && CL="found"
  [ "$FOUND_CODEX" = 1 ] && CX="found"
  say ""
  say "Claude Code: ${CL}. Codex: ${CX}."
  if [ "$DRY" = 0 ] && [ "$NO_START" = 0 ]; then
    say "FlowlyStack is running: open http://127.0.0.1:${PORT} and create your account (the first visit asks for a username and password)."
  fi
  note "Your prompts and documents: $DIR/prompts (plain files). Login, settings and caches: a Docker volume."
  note "Stop:   cd \"$DIR\" && docker compose down"
  note "Update: run this installer again, or  cd \"$DIR\" && docker compose pull && docker compose up -d"
  [ "$FOUND_CLAUDE" = 1 ] || note "Claude Code folder not found at $CLAUDE_DIR : the Dashboard starts empty until it exists."
  [ "$SETUP_CAPTURE" = 1 ] || note "Save every prompt you send in Claude Code: bash \"$DIR/install.sh\" --setup-capture"

  # ---- 7. capture (opt-in) -------------------------------------------------------------------------------------------------
  if [ "$SETUP_CAPTURE" = 1 ]; then
    say ""
    if [ "$NO_START" = 1 ]; then warn "capture setup needs the app running; start it, then run:  bash \"$DIR/install.sh\" --setup-capture"
    else capture add; fi
  fi
  if [ "$FOUND_CODEX" = 1 ]; then
    say ""
    say "Codex prompts: the installer does not edit Codex files. To capture them, add this to ~/.codex/hooks.json (merge it with any hooks"
    say "already there), then run /hooks inside Codex and review and enable it:"
    say ""
    say "  {\"hooks\": {\"UserPromptSubmit\": [{\"hooks\": [{\"type\": \"command\", \"command\": \"$(hook_command capture_codex_prompt.py)\"}]}]}}"
  fi
}

main "$@"
