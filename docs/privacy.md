# Privacy: what FlowlyStack contacts

**The short answer.** FlowlyStack runs on your computer and keeps your data there. It has no account with us, no analytics, no tracking and no ads. The only times your text leaves the app are the ones listed below, and each one goes to a model **you** chose.

## What stays on your computer

| What | Where |
|---|---|
| Prompts, Studio prompts, documents, Linkshell projects, conversations | Plain files in your `prompts` folder |
| Login, settings, keys you typed | Your `data` folder (Docker: a volume on your computer) |
| Dashboard numbers, search index, vectors, Gallery and Lattice caches | The same `data` folder, as rebuildable caches |
| Your profile picture | A file next to your login, never sent anywhere |

Your password is stored only as a salted hash, and MCP tokens only as hashes. A key for another model service is stored only in `data/secrets.json`. It is never shown again, never exported and never put into a saved chat.

## When your text goes to a model

FlowlyStack never writes to a model on its own initiative. There are four situations, and each uses the model or address you chose in **Settings**.

1. **You press Send** in the Studio **Assistant** or a **Collections** chat. The text of your message goes to the model you picked, and, when it applies, the prompt or the passages from your documents go with it as part of your message. The panel shows a **Local** or **Remote** badge, and the line under the chat box says what was sent. Nothing is sent when you open a page, save, or wait.
2. **Your documents are indexed.** To search by meaning, the text of your documents and prompts is cut into passages and sent to your **embedding model** (Ollama on your computer unless you changed the address). This happens when you add a document and **Index automatically** is on, or when you press **Index now**. Turn it off in **Settings > Knowledge**, or use **Turn off auto-indexing** on the built-in "My prompts" collection. With a remote Ollama address, that text goes there, and the model picker marks it **Remote**.
3. **You press Start on a Lattice "local model" run.** A dialog first shows what will be sent. Nothing happens until you press Start.
4. **You let an AI agent use FlowlyStack (MCP).** This is off until you switch it on. An agent with your token can read what its tools return, and *its own* model sees that text. FlowlyStack sends nothing to the agent; the agent comes and reads. Only connect agents you trust, and see [Connect an AI agent](mcp-setup.md).

**Keeping everything on your computer:** use Ollama on your own machine (the default) and don't add remote runtimes. Then no text leaves your computer at all.

## What FlowlyStack never does

- **No telemetry, analytics or crash reports.** Nothing about you or your use is collected. The bundled search service has its analytics switched off too.
- **No outside files in the page.** The fonts and charts are bundled, so the page makes no requests to other websites.
- **No reading of your login files.** For your AI tools, FlowlyStack reads only their history folders. It never opens `auth.json`, `config.toml` or your Codex hooks file. In Docker, only those history folders are shared with it, read-only.
- **No unprompted writes** to another tool's settings. The capture hook is added only when you press a button or run `--setup-capture`, after you have seen the exact change, and a backup is made first.

## What it reads, and when

| Source | What is read | When |
|---|---|---|
| Claude Code and Codex history folders | Token counts, dates, models, project names, for the Dashboard | Continuously, read-only |
| Open WebUI chat database | Counts, dates, model names and chat titles for the Dashboard, never message text | Continuously, read-only |
| Claude Code and Codex history, Open WebUI chats | The text of your prompts, to save them in the Library | Only after you press **Import** or switch **Live sync** on (or the capture hook runs) |

## Network, in plain terms

- **While running:** the app listens on your own computer only (`127.0.0.1`). In Docker, the port is published to your own computer only. It's reachable from other devices only if **you** put a web proxy in front of it ([Login and remote access](remote-access.md)). Everything is behind your login.
- **At install and update time:** the installer downloads one script and the compose file from GitHub, and Docker downloads the app image (from GitHub's container registry) and the search service image. Those downloads don't carry anything about you or your data.
- **There is no update check in this version.** The app does not phone home to see whether a newer version exists. You update when you choose to ([Updating and backup](updating-and-backup.md)).

## Sample content

Adding the sample content only creates a few files on your computer. If you then index them for search, their text goes to your embedding model like any other document (see point 2 above).

## Check it yourself

FlowlyStack is open source, so you don't have to take this page on trust. The places that make network calls are few: the model connections (`backend/assistant/`), the search service connection (`backend/search.py`) and the local MCP helper. If you want proof for your own setup, disconnect from the internet: everything except a remote model you added keeps working.
