# Troubleshooting the install

Show the user the exact error text first. Never use `sudo` or delete anything to fix a problem; explain and let the user decide.

## Docker is not installed, not running, or not reachable
- `docker: command not found`: Docker is not installed. Link: https://www.docker.com/products/docker-desktop/ (Mac, Windows) or https://docs.docker.com/engine/install/ (Linux).
- `Cannot connect to the Docker daemon` or `docker info` fails: start Docker Desktop and wait until it says it is running.
- Linux, `permission denied` on the Docker socket: the user may need to be in the `docker` group (their choice, with their own administrator rights). Do not run `sudo` yourself.
- Windows: Docker Desktop needs the WSL 2 backend; if it asks to enable it, the user does that.
- Inside an AI agent's sandbox (Codex, for example), `docker info` can fail with `permission denied` on a Docker socket path (Docker Desktop's or OrbStack's) while Docker is running fine. That is the sandbox, not the user's Docker. Ask the user to approve running that one check outside the sandbox: a one-time permission, no `sudo`, and it changes nothing in Docker. If they decline, ask them to run `docker info` themselves and tell you what it says.

## `docker compose` is not a command
The compose plugin is missing. Docker Desktop includes it; update Docker Desktop. On Linux see https://docs.docker.com/compose/install/linux/ .

## Port already in use
The installer says so before starting. Run again with another port: `bash install.sh --port 8373` (manual install: change `FLOWLYSTACK_PORT` in `.env`, then `docker compose up -d`). To see who holds the port: Mac/Linux `lsof -iTCP:8372 -sTCP:LISTEN`; PowerShell `Get-NetTCPConnection -LocalPort 8372 -State Listen`. Do not stop the other program for the user.

## `--port` seems to be ignored
If the install folder already has a `.env`, the installer keeps it and the port in it wins (it says so). Change the `FLOWLYSTACK_PORT=` line in that `.env`, then run the installer again (or `docker compose up -d`). Editing that one line is fine: it is inside the install folder; tell the user.

## "pull access denied" or "not found" when downloading the image
The image name or version is wrong, the version is not published yet, or there is no internet connection. Check the version the user asked for; try `latest`. Nothing was started.

## Not healthy after two minutes
In the install folder: `docker compose ps` and `docker compose logs --tail 80`. Show the user the last lines. Common causes: a very slow first start on a slow disk (wait a little longer), a folder that Docker cannot read, or low memory. Do not delete volumes.

## The browser page does not open
Use exactly `http://127.0.0.1:<port>` on the same computer. If the port was changed, use that port. Check `docker ps` shows the container up.

## First sign-up is refused (403) or asks to create the account on the server
The first account can only be created on the same computer at `http://127.0.0.1:<port>`, not through a proxy, a tunnel or another device. Open that address directly.

## The Dashboard is empty
The app starts empty when it cannot find the agent folders. Check `.env` has `CLAUDE_PROJECTS_DIR` (and the Codex lines) pointing at folders that exist, then `docker compose up -d` again. On Mac, Docker Desktop must be allowed to share the home folder (the default). It also stays empty until the agent has been used at least once.

## Prompts are not saved after the capture setup
The capture hook runs `docker exec` into the running container, so FlowlyStack must be running when the user sends a prompt in Claude Code. On Windows this assumes Claude Code runs hooks in Git Bash. Check `docker ps` first.

## Time zone looks wrong
Set `TZ` in `.env` to an IANA name such as `Europe/London`, then `docker compose up -d`.

## Still stuck
Show the user the exact error and the relevant log lines, and ask what they want to do. Do not guess at destructive fixes.
