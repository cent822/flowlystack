# Troubleshooting

Find your symptom below. Each answer says what is going on and what to try. Nothing here needs `sudo` or deletes your prompts.

**First, three quick checks that solve many problems** (run them in your `flowlystack` folder):

```bash
docker compose ps                    # is the app "running" and "healthy"?
docker compose logs --tail 80        # what did it say last?
docker compose up -d                 # start it again if it is stopped
```

If you run FlowlyStack from source, look at the terminal window where `./run.sh` is running instead.

## Install and start

**`docker: command not found`, or "Cannot connect to the Docker daemon".**
Docker is not installed or not running. Install and **open** Docker Desktop (Mac, Windows) and wait until it says it is running. On Linux, install Docker Engine. See the [Quick start](quick-start.md).

**`docker compose` is not a command.**
The compose plugin is missing. Update Docker Desktop. On Linux, install the compose plugin from Docker's site.

**Linux: "permission denied" on the Docker socket.**
Your user is not allowed to use Docker. That's your choice to change with your own administrator rights (adding yourself to the `docker` group). FlowlyStack's installer never does this for you.

**"Port is already in use".**
Another program uses port 8372. Run the installer with another port (`bash install.sh --port 8373`), or change `FLOWLYSTACK_PORT` in your `.env` file and run `docker compose up -d`. To see which program holds the port: `lsof -iTCP:8372 -sTCP:LISTEN` on Mac and Linux, or `Get-NetTCPConnection -LocalPort 8372 -State Listen` in PowerShell.

**I used `--port`, but nothing changed.**
If your folder already has a `.env`, the installer keeps it and the port in that file wins. Edit the `FLOWLYSTACK_PORT=` line in `.env`, then run `docker compose up -d`.

**"pull access denied" or "not found" while downloading.**
The version name is wrong, that version is not published, or there is no internet. Try `latest` in your `.env` (`FLOWLYSTACK_IMAGE=ghcr.io/cent822/flowlystack:latest`). Nothing was started.

**The app is not "healthy" after two minutes.**
Run `docker compose logs --tail 80`. The first start can be slow on a slow disk, so wait a little longer. Other common causes are low memory, or a folder Docker is not allowed to read. Don't delete volumes to fix it.

**The browser page doesn't open.**
Use exactly `http://127.0.0.1:8372` on the same computer, with your own port if you changed it. Check that `docker ps` shows the container up.

## Login

**"Create the account first on the server itself" (the first sign-up is refused).**
The first account can only be created on the computer that runs FlowlyStack, at `http://127.0.0.1:8372`. A sign-up through a web proxy, a tunnel or another device is refused on purpose. Open that address directly.

**I forgot my password.**
There's no email reset. Run this on the computer that runs FlowlyStack. In Docker:

```bash
docker exec -it flowlystack-app /usr/local/bin/entrypoint.sh python -m backend.auth reset-password
```

From source, in the project folder: `python3 -m backend.auth reset-password`. It asks for a new password and signs every browser out.

**I lost my phone and my backup codes (two-step login).**
Same command with `reset-2fa` at the end instead of `reset-password`. It turns two-step off, and you log in with your password and can set it up again.

**"Wrong code" even though my app is right.**
The clock on your phone or computer is off by more than 30 seconds. Set both to automatic time.

**I'm locked out.**
Five wrong passwords or codes in a minute lock that address for a minute. Wait, or restart the app.

More about login, proxies and HTTPS: [Login and remote access](remote-access.md).

## The Dashboard

**It's empty.**
FlowlyStack couldn't find your AI tools' history folders, or the tool hasn't been used yet. Check that your `.env` has `CLAUDE_PROJECTS_DIR` (and the Codex lines) pointing to folders that exist, then run `docker compose up -d`. On a Mac, Docker Desktop must be allowed to share your home folder (the default). See [Connect Claude Code and Codex](connect-agents.md).

**The Ollama view is missing.**
FlowlyStack needs to be told where Open WebUI keeps its `webui.db`. In Docker, set `OPENWEBUI_DATA_DIR` in your `.env` (or use the volume block in the compose file) and run `docker compose up -d`. From source, set `FLOWLYSTACK_WEBUI_DIR`. See [Connect Claude Code and Codex](connect-agents.md#ollama-and-open-webui).

**Cost shows $0.00 or N/A.**
Cost comes from what the tool itself records. Some sessions record none. See the [Dashboard](dashboard.md).

**"Today" is the wrong day.**
Set `TZ` in `.env` to your time zone name, such as `Europe/London` or `Asia/Bangkok`, then `docker compose up -d`.

## Prompts and capture

**My prompts aren't being saved in the Library.**
- In Docker, the hook runs inside the app's container. **FlowlyStack must be running** when you send the prompt. Check `docker ps`.
- Start a **new** Claude Code session after setting up capture. An old session doesn't know about the new hook.
- Check the hook is there: **Prompt Library > Capture setup**, or the `hooks` part of `~/.claude/settings.json`.
- Press **Import** in Capture setup to catch up on prompts that were missed.

**Codex prompts don't appear.**
You must trust the hook with `/hooks` in Codex after adding it, or use **Live sync**. See [Connect Claude Code and Codex](connect-agents.md).

**Search has no typo tolerance.**
The search service isn't running, so search falls back to plain matching. Everything still works. In Docker, check `docker compose ps` for the `meilisearch` service. From source, search is plain matching unless you set the service up.

## Collections and models

**Documents say "Waiting for a model".**
No embedding model is chosen yet. Pick one on the Collections page or in **Settings > Knowledge**. See [Collections](collections.md).

**"Is Ollama running?" or the check fails.**
- Start Ollama on your computer, and install a model: `ollama pull embeddinggemma`.
- In Docker, FlowlyStack reaches Ollama at `http://host.docker.internal:11434`. Check **Settings > Connections > Check connection**.
- On Linux, Ollama may listen only on the computer itself. If the check fails, set Ollama to listen on all addresses (its `OLLAMA_HOST` setting) and restart it.

**A PDF shows an error.**
A scanned or encrypted PDF can't be read as text. It's kept with the reason shown and doesn't stop the other files.

## Gallery and Lattice

**The Gallery says "No prompts yet".**
It shows only prompts captured from your tools, and the sample content isn't part of that on purpose. Switch to **Documents** to see sample documents.

**The Lattice says it needs more items.**
It needs at least 10 items (prompts, Studio prompts and documents together).

## Other

**"Cross-site request refused" when saving.**
Your web proxy doesn't pass the original `Host` header. See [Login and remote access](remote-access.md).

**Pages update late or never behind a proxy.**
The proxy buffers the live stream. Settings are in [Login and remote access](remote-access.md).

**I run two copies of FlowlyStack on the same computer** (for example the installed one and a copy you develop). Give each its own port. Each copy has its own login and its own data, and one no longer logs the other out. If you connect both to an AI agent over MCP, give each connection its own name, such as `flowlystack` and `flowlystack-second`, and use each copy's own token. Never point two copies at the same `prompts` folder.

**I added the sample content and want it gone.**
**Settings > General > Sample content > Remove sample content.** It moves them to the Trash, so you can still get them back.

## Still stuck?

Open an issue on the project page on GitHub, and include:
- your operating system, and whether you use Docker or run from source;
- the version (**Settings > About**);
- the last lines of `docker compose logs --tail 80`;
- what you expected and what happened.

**Remove anything private first.** Never post your `.env` if it holds paths you'd rather not share, your tokens (they start with `fls_`), passwords or the content of your prompts.
