# Manual Docker install (all systems, the Windows path)

These are the same steps `install.sh` performs, written so they can be run by hand or by an agent, in bash or in PowerShell. Replace `8372` if that port is busy.

Source of the files: `https://raw.githubusercontent.com/cent822/flowlystack/main/`

## 1. Make the folders

bash:
```bash
mkdir -p ~/flowlystack/prompts ~/flowlystack/empty
```

PowerShell:
```powershell
$dir = Join-Path $HOME 'flowlystack'
New-Item -ItemType Directory -Force (Join-Path $dir 'prompts'), (Join-Path $dir 'empty') | Out-Null
```

The `empty` folder is a placeholder the compose file mounts when an agent folder is not found.

## 2. Get the compose file

bash:
```bash
cd ~/flowlystack
curl -fsSL https://raw.githubusercontent.com/cent822/flowlystack/main/docker-compose.yml | grep -v '^    build: \.$' > docker-compose.yml
```

PowerShell (written without a byte-order mark, with the developer-only `build: .` line removed):
```powershell
cd $dir
$text = (Invoke-WebRequest -UseBasicParsing https://raw.githubusercontent.com/cent822/flowlystack/main/docker-compose.yml).Content
$lines = $text -split "`r?`n" | Where-Object { $_ -ne '    build: .' }
[System.IO.File]::WriteAllText((Join-Path $dir 'docker-compose.yml'), (($lines -join "`n") + "`n"), (New-Object System.Text.UTF8Encoding($false)))
```

## 3. Write `.env` (only if it does not exist yet)

Never overwrite an existing `.env`. Use forward slashes in paths, also on Windows. Leave a line out when that folder does not exist. Check for the folders first (existence only; do not open what is inside):

- Claude Code writes to `~/.claude/projects` (Windows: the same folder under your user folder, written with forward slashes)
- Codex writes to `~/.codex/sessions` and `~/.codex/archived_sessions` (or under `CODEX_HOME`)

Example content:
```
FLOWLYSTACK_IMAGE=ghcr.io/cent822/flowlystack:latest
FLOWLYSTACK_PORT=8372
TZ=Europe/London
FLOWLYSTACK_SOURCES=claude
CLAUDE_PROJECTS_DIR=/home/you/.claude/projects
```

- `TZ` must be an IANA name such as `Europe/London`, `America/New_York`, `Asia/Bangkok` (not a Windows name such as "GMT Standard Time"). If unsure, use `UTC`; the user can change it later.
- Add `FLOWLYSTACK_SOURCES=claude,codex` plus `CODEX_SESSIONS_DIR` and `CODEX_ARCHIVED_DIR` only when the Codex folder exists.
- On Linux also add `PUID=<output of id -u>` and `PGID=<output of id -g>` so the prompts folder belongs to the user.
- On Windows write the file as UTF-8 **without** a byte-order mark (the PowerShell example above uses `UTF8Encoding($false)`; plain `Set-Content -Encoding utf8` adds one in Windows PowerShell 5.1 and breaks the first line).

## 4. Start it

```
docker compose pull
docker compose up -d
```

Run these inside the install folder. The first pull takes a minute or two.

## 5. Wait until it is ready

bash:
```bash
docker inspect -f '{{.State.Health.Status}}' flowlystack-app
```

PowerShell:
```powershell
docker inspect -f '{{.State.Health.Status}}' flowlystack-app
```

Repeat every few seconds until it prints `healthy` (up to about 90 seconds). Then the user opens `http://127.0.0.1:8372` and creates their account.

## Windows notes

- Docker Desktop must be running with the WSL 2 backend.
- Run the commands in a normal (not administrator) PowerShell.
- If a path with spaces is used in `.env`, wrap the value in double quotes.
