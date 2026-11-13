# Settings and keyboard shortcuts

Open **Settings** from the account button at the bottom of the left sidebar, or press **⌘K** (Ctrl+K on Windows and Linux) and type "Settings". The list on the left groups the pages. Most settings save right away; a few have a **Save** button.

> **Mac and Windows keys.** In this guide **⌘** means the Command key on a Mac and **Ctrl** on Windows and Linux. **⌥** means Option on a Mac and **Alt** elsewhere. **⇧** is Shift.

## The Settings pages

### Basics

| Page | What is on it |
|---|---|
| **General** | **Theme**: *System* (follows your computer), *Day* or *Night*. It applies at once. **Sample content**: add or remove the example prompts, project plan and documents (see the [Quick start](quick-start.md)). |
| **Account** | Your **profile picture**, your **name** (the one you log in with; changing it asks for your password), your **password**, optional **two-step login** and **Sign out**. Details in [Login and remote access](remote-access.md). If you turned login off, this page says so. |
| **About** | The version you are running, a link to **What's new** (the release notes, which open without a connection) and the credits. |
| **Updates** | One switch, **Tell me about new versions** (on by default). When you are online, FlowlyStack asks GitHub for the latest release, at most once a day, and shows a notice after login if a newer one exists. Nothing about you is sent, and it never updates the app by itself. Off means no request at all. Details in [Privacy](privacy.md). |
| **Keyboard** | Every shortcut, with a button to change each one (see below). |

### Services

| Page | What is on it |
|---|---|
| **Connections** | The address of your **Ollama**, a **Check connection** button, and **Other runtimes**: LM Studio, llama.cpp, vLLM, Jan, LocalAI or any service that speaks the OpenAI style of API (one you host, Hugging Face, OpenAI and others). You type the address and, if needed, a key. A key is stored only on your computer and is never shown again, exported or put into a chat. Opening a page that lists models asks each connection for its model names, using the key but never your text. |
| **MCP** | Let AI agents use FlowlyStack: the on and off switch, the address, tokens, ready-made connect commands and a list of what agents saved, with Undo. A step-by-step guide is in [Connect an AI agent (MCP)](mcp-setup.md). |

### Knowledge and Assistant

| Page | What is on it |
|---|---|
| **Knowledge** | Settings for [Collections](collections.md) and the Gallery: the embedding model, index automatically, save conversations, passages per answer, relevance cutoff, context size, your instructions for collection chats, and **Gallery: words to ignore**. |
| **Assistant** | Settings for the [Prompt Studio Assistant](prompt-studio.md#the-assistant-chat-with-a-model-about-your-prompt): the default model, **your instructions**, how many earlier exchanges are sent with each message, context size, **temperature** (lower is steadier, higher is freer) and whether to save conversations. |

Both of these pages have a **Your instructions** box. Leave it empty to use the built-in text, or press **Reset to default** to go back to it.

## Keyboard shortcuts

A shortcut is **⌘ plus a letter or digit**. You can also use **⌘⌥** or **⌘⇧⌥** with a letter or digit. They work from any field of a prompt page, so your cursor can stay in the text.

### Change a shortcut

Open **Settings > Keyboard**, press the button that shows a shortcut, then press the keys you want. **Esc** cancels. **Reset** goes back to the original. FlowlyStack refuses keys that the browser or text editing already use (⌘N, ⌘C and similar), keys that are already taken, and ⌘K, which is fixed.

### The default shortcuts

**Everywhere**

| What | Shortcut |
|---|---|
| Open the command palette (jump to any page or action) | ⌘K |
| Search: put the cursor in the search box of any page that has one | ⌘⇧S |
| New: a new Studio prompt, or the New project dialog on the Linkshell list | ⌘⌥N |
| Tags: the Tags box of an open prompt, or the Tags filter on a list | ⌘⌥T |
| Done: press the Done button of an open panel | ⌘⌥O |

**Prompt pages**

| What | Shortcut |
|---|---|
| Save the open Studio prompt (it asks what changed) | ⌘S |
| + Note: open the note of a Library prompt | ⌘⇧E |
| Properties of the open Studio prompt | ⌘⇧D |
| Assistant: open or close the panel | ⌘⇧A |

**Linkshell**

| What | Shortcut |
|---|---|
| Add prompt block | ⌘⌥P |
| Add reference block | ⌘⌥R |
| Add sticky note | ⌘⌥S |
| Add frame (phase) | ⌘⌥F |
| Tidy up the canvas | ⌘⌥L |
| Copy the current prompt with its context (Follow view and the block panel) | ⌘⇧C |
| Mark done (Follow view): marks the prompt done and moves to the next one | ⌘↵ |

**Collections**

| What | Shortcut |
|---|---|
| Focus the question box | ⌘⌥K |
| Send the question | ⌘⌥E |
| New chat | ⌘⌥H |
| Show or hide Sources | ⌘⌥G |
| Go to the Documents tab | ⌘⌥D |

### Keys that are not in the list

- **Esc** lets go of whatever field or button has the focus. If a dialog, a menu or a shortcut recording is open, Esc closes that first.
- **Arrow keys and Enter** move through lists (the Library, Studio and Linkshell lists) and open the highlighted item.
- **← and →** move between the Gallery slides.
- **Linkshell canvas keys** (such as Delete for a selected block or link, and Enter to open a block's panel) are fixed and can't be changed.

## The command palette

Press **⌘K** from anywhere. Type to find a page (Dashboard, Library, Studio, Linkshell, Collections, Gallery, Lattice, Trash, Settings) or an action ("New prompt", "Add sample content" and others) and press Enter. It searches the names of pages and actions, not the content of your prompts. For that, use the search box on each page.
