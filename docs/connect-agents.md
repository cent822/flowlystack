# Connect Claude Code and Codex

FlowlyStack can do two different things with your AI tools. They are separate, and both are optional:

| | What it does | What you do |
|---|---|---|
| **A. The Dashboard** | Shows your usage: tokens, busiest days, models, projects | Nothing in most cases (the installer finds the folders), or one line in a settings file |
| **B. Prompt capture** | Saves every prompt you send as a file in your Prompt Library | Switch it on once, with a button that shows you the change first |

FlowlyStack never changes a settings file of another tool without showing you the exact change first and asking you.

## A. The Dashboard: show your real usage

Claude Code and Codex write a history of your sessions to a folder on your computer. FlowlyStack reads that history, read-only, and draws charts from it.

| Tool | Folder it writes to |
|---|---|
| Claude Code (terminal) and the Claude desktop app's Code tab | `~/.claude/projects` |
| OpenAI Codex | `~/.codex/sessions` and `~/.codex/archived_sessions` (or the folder named in `CODEX_HOME`) |

> **Not counted:** ordinary chats in the Claude desktop app and Cowork. Only Claude Code (terminal or Code tab) and Codex are read.

FlowlyStack reads **only** these folders. It never opens your login files (`auth.json`), your `config.toml` or any other part of `~/.claude` or `~/.codex`. In Docker, only these folders are shared with the app, and they are shared read-only.

### If you used the installer or your AI agent

Nothing to do. The installer checks that these folders exist (never what is inside them), writes their paths into the `.env` file in your `flowlystack` folder, and the Dashboard finds your history. Open the Dashboard and, if you use more than one tool, pick one in the drop-down in the top bar.

If a folder was not found, the Dashboard starts empty and says which folder it looked for.

### If you set up Docker by hand

The folders point at an empty placeholder until you tell the app where yours are. Open the `.env` file next to `docker-compose.yml` (create it if it does not exist) and add the lines that fit. Use forward slashes, also on Windows. Leave a line out when you do not use that tool.

```
CLAUDE_PROJECTS_DIR=/path/to/home/.claude/projects
CODEX_SESSIONS_DIR=/path/to/home/.codex/sessions
CODEX_ARCHIVED_DIR=/path/to/home/.codex/archived_sessions
FLOWLYSTACK_SOURCES=claude,codex
```

Replace `/path/to/home` with the full path of your own home folder (run `echo ~` in a terminal to see it; on Windows write it with forward slashes). Then restart the app:

```bash
docker compose up -d
```

### If you run it from source

Nothing to do for Claude Code: it reads `~/.claude` directly. Codex is read from `~/.codex`, or from the folder named in `CODEX_HOME`. To choose which tools the Dashboard offers, set `FLOWLYSTACK_SOURCES=claude,codex` or `"sources": ["claude", "codex"]` in `flowlystack.config.json`. Open WebUI (the Ollama view) is the one exception: it is offered by itself as soon as its `webui.db` is found (see below), even if this list does not name it.

### Ollama and Open WebUI

Ollama keeps no usage history of its own. The Dashboard can read the chat database of **Open WebUI** instead (read-only; only counts, dates, model names and chat titles, never message text). Open WebUI keeps it in a file called `webui.db`.

- **From source:** point FlowlyStack at the folder that holds `webui.db` with `FLOWLYSTACK_WEBUI_DIR=/path/to/openwebui-data`, or `"ollama": {"webui_dir": "/path/to/openwebui-data"}` in `flowlystack.config.json`.
- **Docker, Open WebUI keeps its data in a folder on your computer** (for example you started it with `-v ./openwebui:/app/backend/data`): add one line to your `.env` file, then restart:

  ```
  OPENWEBUI_DATA_DIR=/path/to/openwebui-data
  ```

  ```bash
  docker compose up -d
  ```

- **Docker, Open WebUI keeps its data in a Docker volume** (the standard quick-start command does this, with a volume usually called `open-webui`; check with `docker volume ls`): the compose file has a commented block at the bottom that explains the two small edits. Keep a copy of your edited compose file, because the installer replaces it when it updates.

Until you set it, the Ollama view simply isn't offered; once you set it and restart, it appears by itself, with no change to `FLOWLYSTACK_SOURCES`. FlowlyStack opens the file read-only, and it works whether Open WebUI is running or stopped. The Projects and Tools cards become **Models** and **Speed by model**; cost, cache, limits, context and running state show N/A. Chats you later delete in Open WebUI stay in FlowlyStack's cache until you delete it.

## B. Prompt capture: save every prompt you send

The **Prompt Library** keeps a copy of every prompt you send, as a plain file, with search, tags, notes and versions. Claude Code does this through a small **hook**: a line in its settings file that says "after the user sends a prompt, also run this command". The command saves the prompt and stays silent.

### Claude Code: one command

If you used the installer, run it again with one extra word. It shows you the exact change, asks you to type `yes`, and makes a backup first:

```bash
bash ~/flowlystack/install.sh --setup-capture
```

What it does to `~/.claude/settings.json`:

- **Adds** one hook. It keeps every other setting and every other hook you have.
- **Shows** you a before-and-after comparison and waits for you to type `yes`.
- **Backs up** your original file next to it, as `settings.json.flowlystack-backup-<date and time>`.

To take the hook out again later (it removes only this hook and leaves everything else alone):

```bash
bash ~/flowlystack/install.sh --undo-capture
```

Then **start a new Claude Code session**. A session that was already open does not learn about the new hook.

### Claude Code: by hand

Open **Prompt Library** in the sidebar, then **Capture setup**. It shows the exact text for your setup (it differs between Docker and running from source). Copy it into `~/.claude/settings.json`, merging it with any hooks that are already there.

### Import the prompts you already sent

Claude Code deletes old session history after a while. **Capture setup** has an **Import** button that reads your existing history and saves those prompts too. Press it as often as you like; anything already imported is skipped. A prompt you trash or delete is not imported again.

### Codex

Codex hooks must be reviewed by you, so the installer never edits the Codex file. In the Prompt Library, **Capture setup** has an **Other agents** row for Codex:

1. Copy the shown text into `~/.codex/hooks.json` (merge it with any hooks already there).
2. In Codex, type `/hooks` and **trust** the new hook.

Alongside the hook there are two buttons: **Import** (imports what is new) and a **Live sync** switch (keeps picking up new prompts every few seconds while it is on). Live sync works for every Codex client, including the Codex app and VS Code. Nothing is imported until you press Import or switch Live sync on.

### Open WebUI

When Open WebUI is available (see above), the same **Other agents** row has **Import** and **Live sync** for it. Both are read-only.

## Good to know

- **In Docker, the hook runs inside the app's container.** If the app is stopped when you send a prompt, that prompt is not captured. Start the app again and use **Import** for Claude Code or Codex to catch up.
- **Windows:** the same hook line is used. Claude Code runs hooks in Git Bash on Windows, so this should work, but it has had little testing. The installer script for Windows (`install.ps1`) is marked experimental for the same reason.
- **The Claude desktop app's Code tab** shares its setup with the terminal version of Claude Code, so the hook and the Dashboard should work for both. If you see a difference on your system, please tell us.
- **Where do captured prompts live?** In the `prompts` folder inside your `flowlystack` folder, as plain files you can open, back up and move.
- **Not working?** See [Troubleshooting](troubleshooting.md).
