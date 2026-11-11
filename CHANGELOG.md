# Changelog

What changed in each release, newest first. The app shows this page under **What's new**.

## [0.1.1] - 2026-11-11
A small fix release. Update with the steps in [Updating and backup](docs/updating-and-backup.md).

### Fixed
- **Codex prompts now import with current Codex.** Newer Codex versions record a typed prompt in a different way, so the Prompt Library's Codex **Import**, **Live sync** and the Dashboard's prompt count found nothing. All of them now read both the new and the older format. Files that were read before are read again once, so prompts that were missed show up by themselves.
- **A clearer message when no Claude Code history is found.** Import used to say "Imported 0, skipped 0". It now says that no history folder was found and, in Docker, which line to add to your `.env` file.
- **Docker by hand starts without a `.env` file.** The compose file now pulls the published image by default instead of one you had to build yourself.

## [0.1.0] - 2026-11-10
First release. Everything runs on your own computer; your prompts and documents stay in plain files you own.

### New
- **Dashboard:** your Claude Code usage (terminal or the desktop app's Code tab), OpenAI Codex usage and Ollama activity (read from Open WebUI), one agent at a time. Limits are estimates and are labelled that way.
- **Prompt Library:** prompts captured from Claude Code, Codex and Open WebUI, with tags, versions, search, Trash and Undo.
- **Prompt Studio:** write and refine your own prompts, with versions, compare and export, and an optional Assistant that talks to a model only when you press Send.
- **Linkshell:** plan a project as connected blocks, follow it step by step, copy it as one prompt or export it.
- **Collections:** import documents (Markdown, text, PDF, JSON), search them by meaning and keywords, and chat with them with numbered sources.
- **Gallery and Lattice:** patterns in your prompts, and a knowledge graph of how your prompts, documents and projects connect.
- **MCP server:** let Claude Code, Cursor or the Claude desktop app search your library and, with a token you allow, save new prompts. Every change an agent makes can be undone.
- **Login and profile:** one owner account with a profile picture and a name you can change, optional two-step login with an authenticator app, and a guide for reaching the app through a reverse proxy.
- **Settings:** connections to Ollama and other OpenAI-compatible runtimes, keyboard shortcuts, day and night mode.
