# Connect an AI agent to FlowlyStack (MCP)

*Last checked: 2026-11-05, with Claude Code 2.1.309 and the Claude desktop app on a Mac (routes A and C both confirmed in the real app). These apps change quickly. If a screen looks different from what is described here, the idea is the same: FlowlyStack gives your app an address and a token, and your app needs both.*

**In one minute:** FlowlyStack can let an AI agent (such as Claude Code) look inside your own prompts, document collections and Linkshell plans, and, only if you allow it, save new prompts and plans for you. This page shows you how to switch that on, step by step. You do not need to be a programmer. If a step uses a word you do not know, it is explained right there.

**Contents**

1. [What this does (and does not do)](#1-what-this-does-and-does-not-do)
2. [Before you start](#2-before-you-start)
3. [Step 1: Switch MCP on](#3-step-1-switch-mcp-on)
4. [Step 2: Make a token](#4-step-2-make-a-token)
5. [Step 3: Connect your app](#5-step-3-connect-your-app)
   - [A. Claude Code (terminal) and the Claude desktop app's Code tab](#a-claude-code-terminal-and-the-claude-desktop-apps-code-tab) (the easy way)
   - [B. Cursor, Windsurf, VS Code, Cline and other apps](#b-cursor-windsurf-vs-code-cline-and-other-apps)
   - [C. The Claude desktop app's Connectors list (an on-off switch)](#c-the-claude-desktop-apps-connectors-list-an-on-off-switch)
6. [Step 4: Check that it works](#6-step-4-check-that-it-works)
7. [Step 5: Try it](#7-step-5-try-it)
8. [Letting an agent save things (and Undo)](#8-letting-an-agent-save-things-and-undo)
9. [Managing tokens](#9-managing-tokens)
10. [Using it from another computer (HTTPS)](#10-using-it-from-another-computer-https)
11. [Privacy and safety](#11-privacy-and-safety)
12. [Problems and fixes](#12-problems-and-fixes)
13. [All 32 tools](#13-all-32-tools)
14. [For developers](#14-for-developers)

---

## 1. What this does (and does not do)

**MCP** (Model Context Protocol) is a common way for AI apps to use other programs. Think of it as a plug: FlowlyStack has a socket, and your AI app has the plug. Once they are connected, you can talk to your AI app normally, and it can use FlowlyStack by itself when it helps.

**What an agent can do, by default (read only):**

- Search and read the prompts in your **Library** (the prompts you sent to Claude Code, Codex and so on) and your **Studio** (the prompts you wrote on purpose), including older versions.
- Search your **Collections** (the documents you imported, plus your prompts).
- Read your **Linkshell** projects: the plan, each step, and the exact text you would paste.
- Read the patterns in your **Gallery** (groups, repeated prompts).
- Ask your **Lattice** what is connected to what: which prompts, Studio prompts and documents are in the same collection, carry the same tag, or are close in meaning. An agent can also search it, follow the shortest chain between two items, and read the **entities** (people, tools, ideas) that were added to it, each with the exact quotes where it appears.

**What an agent can do only if you switch on writing for its token:**

- Save a **new** prompt in Studio (always as a *draft*), or add a **new version** to a Studio prompt.
- Create a **new** Linkshell project from a plan.
- Add **entities** (people, tools, ideas) and the links between them to your Lattice. Every link comes with a quote copied from your own item, and FlowlyStack checks that the quote is really there. One agent run is one batch, so one click undoes all of it.

**What an agent can never do:**

- Delete anything. Overwrite anything. Change a Library prompt. Open your Settings, passwords or other tokens. Send your text to any model by itself.
- Every prompt or project an agent creates is tagged **`via-mcp`**. Everything an agent saves, Lattice additions included, is listed in **Settings > MCP > Recent agent activity** and can be put back with **Undo**.

> The tools only add things. Nothing an agent does through FlowlyStack can remove your work.

## 2. Before you start

You need:

- **FlowlyStack running** on your computer. If you installed it with Docker, it is already running; check with `docker compose ps` in your `flowlystack` folder and start it with `docker compose up -d` if not. If you run it from source, start it with `./run.sh`. Then open <http://127.0.0.1:8372> in your browser. (If you changed the port, use your port everywhere below.) You must already be signed in, which means you made your account on the first visit.
- **An AI app that supports MCP.** The easiest is **Claude Code**. It must already be installed and working. If you have not installed it yet, follow Anthropic's own instructions for Claude Code first, then come back.
- **A terminal** (only for route A). A terminal is the window where you type commands. On a Mac, open the app called **Terminal**. On Windows, open **PowerShell**. On Linux, open your terminal app.

> **Tip: use one token per app.** You will make a "token" in Step 2. Make a separate one for each app you connect. Then you can cut one off without breaking the others.

## 3. Step 1: Switch MCP on

MCP is **off until you switch it on**. While it is off, FlowlyStack acts as if the feature does not exist.

1. In FlowlyStack, open **Settings**. The button is at the bottom of the left sidebar (your account button). You can also press **⌘K** (Ctrl+K on Windows and Linux) and type "MCP".
2. In the list on the left, under **Services**, click **MCP**.
3. Turn on the switch **Let agents use FlowlyStack**.

You will see a small message ("MCP is on. Make a token next."), and the heading shows **On**.

Just below the switch you will see the **Address**. It looks like `http://127.0.0.1:8372/mcp`. This is where your AI app will connect. You do not need to copy it by hand: the setup text in Step 3 already contains it.

## 4. Step 2: Make a token

A **token** is a long secret password that belongs to one app. Without it, an app cannot get in. You make it yourself, and you can cancel it at any time.

1. Still on **Settings > MCP**, press **New token**.
2. A window shows your new token. It starts with `fls_`. You can press **Copy** in that window. FlowlyStack shows the token **only once** and can never show it again.
3. Press **I saved it** to close the window. (It has no other way to close, so you cannot lose the token by accident.)
4. You do not have to paste the token anywhere yourself in route A. The setup text further down the same page now contains it, for as long as you stay on this page.

Good to know:

- The token gets a name such as **Token 1**. You can **Rename** it later.
- A new token can only **read**. It cannot save anything. You can allow writing later (see [section 8](#8-letting-an-agent-save-things-and-undo)).
- **Do not share the token and do not post it in a chat or on a website.** Treat it like a password. Anyone who has it can read your prompts through MCP. If it leaks, press **Revoke** (see [section 9](#9-managing-tokens)).
- **Do not leave Settings before you finish Step 3.** The token only appears in the setup text right after you make it. If you leave the page, press **Regen** on the token to get a fresh one (the old one stops working).

## 5. Step 3: Connect your app

On **Settings > MCP**, find **Connect a client**. There are three buttons: **Claude Code**, **Claude Desktop** and **Other apps**. Pick the one that matches your app. A grey box shows the text to copy, and the **Copy** button puts it on your clipboard.

> **Right after you make a token, the box contains your real token. After you leave the page, the box shows `YOUR_TOKEN` instead.** If you see `YOUR_TOKEN` and your app has not been connected yet, press **Regen** on your token to get a fresh one, and the box fills in again.

### A. Claude Code (terminal) and the Claude desktop app's Code tab

This is the easiest and best-tested way. The terminal version of Claude Code and the **Code tab** of the Claude desktop app share one setup, so you do this once and both work.

1. On **Settings > MCP > Connect a client**, press **Claude Code**.
2. Press **Copy**. The text is one line, and looks like this (your token is in place of the dots):

   ```bash
   claude mcp add --scope user --transport http flowlystack http://127.0.0.1:8372/mcp --header "Authorization: Bearer fls_..."
   ```

3. Open a terminal and paste the line. Press **Enter**.
4. You should see a message that the server was added. If you see "already exists", go to the [problems list](#12-problems-and-fixes).
5. **Start a new Claude Code session.** (A session that was already open does not learn about the new tools.) In the desktop app, start a new session in the Code tab.

What the parts mean, in case you wonder: `claude mcp add` adds a connection, `--scope user` makes it available in **every** folder you work in (without it, only the current folder would see it), `flowlystack` is the name, and the long text after `--header` is your token.

To see the connection later, run:

```bash
claude mcp list
```

`flowlystack` should show as **Connected**.

### B. Cursor, Windsurf, VS Code, Cline and other apps

Many apps accept an MCP **address plus a header**. They all need the same two things, but they use slightly different file names and field names. FlowlyStack gives you a ready-made example, and you adapt it to your app.

1. On **Settings > MCP > Connect a client**, press **Other apps**, then **Copy**. You get something like this:

   ```json
   {
     "mcpServers": {
       "flowlystack": {
         "type": "http",
         "url": "http://127.0.0.1:8372/mcp",
         "headers": {
           "Authorization": "Bearer fls_..."
         }
       }
     }
   }
   ```

2. Find the **MCP settings** of your app (look for "MCP", "MCP servers" or "Tools" in its settings, or check its help pages for where the file lives) and add this entry. If the app already has other MCP servers, **keep them** and add only the `flowlystack` part.
3. Small differences between apps:
   - **VS Code** keeps the same entry under `"servers"` instead of `"mcpServers"`.
   - **Windsurf** calls the address `serverUrl` instead of `url`.
   - Some apps do not need the `"type": "http"` line, and some require it. If the app complains, try with and without.
4. Restart the app (or reload its MCP settings), then check that it lists `flowlystack`.

> **Honest note:** we tested this text against FlowlyStack directly, but we have not run every one of these apps ourselves. If your app does not connect, the [problems list](#12-problems-and-fixes) has a quick way to test the address and token by hand, which tells you whether the problem is FlowlyStack or the app's setup.

> **Never put your token in a file that belongs to a project you share** (for example a `.mcp.json` in a folder under Git). It could end up on the internet. Put it in your app's own **user** settings instead.

### C. The Claude desktop app's Connectors list (an on-off switch)

*Confirmed on a Mac on 2026-11-05.* Route A already gives the Code tab the FlowlyStack tools, but the tools are always on and the app's **Connectors** list does not show them. Route C adds FlowlyStack to that list, so you get a **flowlystack** switch under **+ > Connectors** and can turn the connection on or off whenever you like, the same way you switch Claude in Chrome. You can use route A, route C, or both.

The app's own settings file cannot take an address, so it starts a tiny helper program (a "bridge") that connects to FlowlyStack for it. The bridge is already included in FlowlyStack (`backend/mcp_stdio.py`).

1. On **Settings > MCP > Connect a client**, press **Claude Desktop**. Make sure you opened FlowlyStack on **the same computer** where the Claude app runs. (If not, the file paths in the text will be wrong. Use route A or B instead.)
2. Press **Copy**. You get a block that contains two paths from your own computer, the address, and the token. (Right after you make or regenerate a token the box has the real token; later it shows `YOUR_TOKEN`, see above.)

   > **Running FlowlyStack in Docker?** The two paths in that text then point *inside the container* (`/usr/local/bin/python` and `/app/backend/mcp_stdio.py`), which the Claude app on your computer can't use. Do this instead. The bridge is one small file that needs only Python 3 (already on a Mac and on most Linux computers; Windows users install it from python.org). Copy the file out of the container into your `flowlystack` folder:
   >
   > ```bash
   > docker cp flowlystack-app:/app/backend/mcp_stdio.py ~/flowlystack/mcp_stdio.py
   > ```
   >
   > Then use `python3` as the `"command"` (on Windows: `python`) and the path to that copy as the single item in `"args"`, for example `"/path/to/home/flowlystack/mcp_stdio.py"`. Keep the address and the token from the copied text. After a FlowlyStack update, copy the file again.
3. **Quit the Claude app completely.** On a Mac press **Cmd+Q**. Closing the window is not enough. *This is important:* the app rewrites its settings file when it closes, and would erase your change. (Quitting also ends any session that is open in the app, so finish what you are doing first.)
4. Open the app's settings file:
   - **Mac:** `~/Library/Application Support/Claude/claude_desktop_config.json`
   - **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

   On a Mac the folder name has a **space** in it ("Application Support"), so in the terminal the path must be in quotes, or the command says "No such file or directory" even though the file is there:

   ```bash
   open -e "$HOME/Library/Application Support/Claude/claude_desktop_config.json"
   ```

5. Add the `flowlystack` entry inside `"mcpServers"`. If the file already has other servers, keep them and add yours next to them, with a **comma** between the entries. It should end up like this (your own paths and token, as copied in step 2):

   ```json
   {
     "mcpServers": {
       "flowlystack": {
         "command": "/path/to/flowlystack/.venv/bin/python",
         "args": ["/path/to/flowlystack/backend/mcp_stdio.py"],
         "env": {
           "FLOWLYSTACK_MCP_URL": "http://127.0.0.1:8372/mcp",
           "FLOWLYSTACK_MCP_TOKEN": "fls_..."
         }
       },
       "another-server": { "...": "..." }
     }
   }
   ```

   Save the file. A missing or extra comma makes the whole file invalid, so check the commas before you save. Do not change anything else in the file: it also holds the app's own settings.
6. Open the Claude app again, then open **+ > Connectors**. You should see **flowlystack** with a switch, next to the other connectors.

**Do not use the app's "Add custom connector" option for FlowlyStack.** That one only accepts a public `https` address and a different kind of login, so it cannot reach FlowlyStack running on your computer.

> **The token is in that file.** Keep it out of any folder under Git, and do not keep a spare copy of the file inside a project (for example in `docs/`). If a copy ever got committed, treat the token as leaked: **Regen** it on Settings > MCP and update the file.

If it does not work, check that the two paths in the file really exist, that you quit the app before editing, and that the file is still valid JSON. See also the [problems list](#12-problems-and-fixes).

## 6. Step 4: Check that it works

**In Claude Code:** start a **new** session and type:

```
/context
```

You should see a list of tools with names that start with `flowlystack`: 20 if the token can only read, 23 if it can also write. (In a terminal, `/mcp` also shows the connection.)

**Then ask your agent something simple:**

> "Call flowlystack_about."

It should answer with the FlowlyStack version, the name of the token it is using, whether it can read or write, and the tool list. If it does, **you are done.**

## 7. Step 5: Try it

You do not need special words. Say what you want, and the agent picks the right tool. Here are some ideas:

**Find things**

- "Search my FlowlyStack Library for prompts about Docker."
- "Show me my most-starred prompts."
- "What are the prompts in my Studio that are still drafts?"
- "Which prompts do I keep retyping?" (This uses the Gallery.)
- "What in my FlowlyStack is related to my *Dough plan* Studio prompt?" (This uses the Lattice. Lines marked *similar* are the app's estimate of closeness in meaning, not facts.)
- "How is my *Dough plan* prompt connected to my *Pizza notes* document?" (The Lattice again: the agent follows the shortest chain between the two.)

**Use your own material as context**

- "Look in my collections for what I wrote about deployment, and summarise it."
- "Read my Linkshell project called *Newsletter landing page* and tell me the next step."

**Improve a prompt** *(needs a token that is allowed to write)*

- "Take my Library prompt about Docker, make it clearer, show me the result, and **if I like it**, save it to my Studio."

**Plan a project** *(needs a token that is allowed to write)*

- "Help me plan a small website in three phases. When I agree, create it as a Linkshell project."

**Grow your Lattice** *(needs a token that is allowed to write)*

- "Read the documents in my *Kitchen notes* collection, find the people and tools in them, show me what you would add to my Lattice, and if I agree, add them." (Each link must carry a quote from the document, and FlowlyStack refuses it if the quote is not really there. Open the **Lattice** page afterwards and switch on **Entities** to see them.)

Afterwards, open **Studio** or **Linkshell** in FlowlyStack and look at what was made. **Reload the page if you do not see it yet**: FlowlyStack's pages do not refresh by themselves when an agent saves something.

> Agents are told to **ask you before saving**. If an agent saves without asking, tell it to ask first, and consider making the token read-only again.

## 8. Letting an agent save things (and Undo)

A new token can only read. To let one agent save prompts and plans:

1. On **Settings > MCP**, find the token and press **Allow writing**.
2. Read the confirmation, and confirm.
3. **Start a new session in your app.** A session keeps the list of tools it started with, so it will not see the five write tools until you do.

You can switch back any time with **Make read-only**. The token's secret does not change.

**What a write token can do (and only this):**

| Tool | What it does |
|---|---|
| `studio_create` | Saves a **new** prompt in Studio as a **draft**, tagged `via-mcp`. It can link back to the Library prompt it came from. |
| `studio_save_version` | Adds a **new version** to a Studio prompt. The old versions stay in its history. |
| `linkshell_create_project_from_plan` | Creates a **new** Linkshell project from a plan (phases of prompts, with optional reference texts). The Brief is left **unticked** so you read the plan first. |
| `graph_start_run` | Opens a **run** for the Lattice, so everything an agent adds in it is one batch that one click undoes. |
| `graph_add` | Adds **entities** (people, tools, ideas) and the links between them to your Lattice. Each link needs the item it came from and a quote copied exactly from that item, or the whole call is refused. It only adds: nothing is deleted or changed. |

**Undo.** **Settings > MCP > Recent agent activity** lists everything agents saved (newest first), with the token name and the time. Each line has an **Undo** button:

- A new prompt or a new project goes to the **Trash**. You can restore it from the Trash page.
- A new prompt version is replaced by the text before it (the agent's version stays in the history).
- If **you edited that prompt after the agent did**, Undo refuses, so your own work is never overwritten. Use the prompt's version history instead.
- Entities and links an agent added to the Lattice are **hidden everywhere in the Lattice**. Nothing is deleted, and you can also hide or delete a run on the Lattice page.

If you like what an agent made, just leave it there. It is yours.

## 9. Managing tokens

On **Settings > MCP > Tokens**, each token has four buttons:

| Button | What it does | When to use it |
|---|---|---|
| **Allow writing** / **Make read-only** | Lets that token save new prompts and projects, or takes the permission away. | You want an agent to save, or stop saving. |
| **Rename** | Changes the name only. | You made several and want to tell them apart. |
| **Regen** | Gives the same token a **new secret** (it asks you to confirm). The old secret stops working at once. The name and permission stay. | You lost the token, or want a fresh one. Then update your app with the new one. |
| **Revoke** | Deletes the token. Any app that uses it is turned away. | You no longer use the app, or the token leaked. |

You can have up to 20 tokens. **Switching MCP off** (the switch at the top) turns every token away at once, without deleting them.

**After Regen:** your app still has the old token. Update it. For Claude Code, run these two commands (copy the new one from the setup box):

```bash
claude mcp remove --scope user flowlystack
claude mcp add --scope user --transport http flowlystack http://127.0.0.1:8372/mcp --header "Authorization: Bearer YOUR_NEW_TOKEN"
```

**After you regenerate or revoke the token, in the Claude desktop app (route C):** the token lives in the app's settings file, so update it there. (After a Revoke, make a new token first, then copy it from the setup box.)

1. Quit Claude Desktop with **Cmd+Q**.
2. Open `claude_desktop_config.json` and replace the old `FLOWLYSTACK_MCP_TOKEN` value with the new token. (On a Mac, put the path in quotes in a terminal; see [route C](#c-the-claude-desktop-apps-connectors-list-an-on-off-switch).)
3. Save the file and reopen Claude.

**Every place you pasted the old token needs the new one.** That means the `claude mcp add` line (route A) **and** the `FLOWLYSTACK_MCP_TOKEN` line in `claude_desktop_config.json` (route C, quit the app first). A place you forget will answer **401** ("A valid MCP token is required") and its tools will not load.

### Removing FlowlyStack from an app

To disconnect FlowlyStack completely, remove it from the app that holds the connection. This does not delete any of your prompts, collections or plans, and it does not delete the token on Settings > MCP (use **Revoke** there for that).

**Claude Code (route A).** Run this in a terminal. Replace `<the_app_MCP>` with the name you gave the connection (the setup text uses `flowlystack`):

```bash
claude mcp remove --scope user <the_app_MCP>
```

Not sure of the name? `claude mcp list` shows every connection. The `--scope user` part must match how you added it (the add command also used `--scope user`); without it, the command looks only in the current folder and may say the connection does not exist.

**Claude desktop app (route C).** Quit the app with **Cmd+Q**, open `claude_desktop_config.json`, delete the whole `"flowlystack": { ... }` entry (and the comma that belonged to it, so the file stays valid), save, and reopen the app. To only pause the connection, use the **flowlystack** switch under **+ > Connectors** instead: nothing is deleted.

**Other apps (route B).** Delete the FlowlyStack entry in that app's MCP settings.

**Same name twice.** If you set up both route A and route C under the name `flowlystack`, the two entries share one name and the Claude Code one wins, so a stale token in it hides the working one. Remove one of them, or give them different names.

If you ever forget your FlowlyStack password and use the reset command (see [Forgot the password](remote-access.md#forgot-the-password)), **every token is revoked** as well. Make new ones afterwards.

## 10. Using it from another computer (HTTPS)

By default, MCP works on the computer that runs FlowlyStack. If you open FlowlyStack from elsewhere (for example through Caddy or Nginx Proxy Manager, as described in [remote-access.md](remote-access.md)), then:

1. **Always use HTTPS.** A token sent over plain `http://` across a network can be read by others. Settings shows a red warning when the address is not encrypted.
2. **Open FlowlyStack through your HTTPS address, then copy the setup text from that page.** The text uses the address of the page you are on, so it will contain your public address.
3. On the server, tell FlowlyStack it is behind a proxy (`FLOWLYSTACK_TRUST_PROXY=1`), as described in [remote-access.md](remote-access.md).
4. The MCP address (`/mcp`) skips the browser login on purpose. It **always** needs a valid token instead, even when the login is turned off. A browser session cookie is **not** accepted there, and a token is **not** accepted anywhere else in FlowlyStack.
5. Route C (the Claude chat app's helper) only works on the computer that runs FlowlyStack, unless you copy `backend/mcp_stdio.py` to the other computer and change the two paths.

## 11. Privacy and safety

- **FlowlyStack sends your text nowhere because of MCP.** It only answers when an agent asks.
- **But the agent's own AI model reads whatever the tools return.** If you connect Claude Code, Anthropic's model reads the prompts it asks for. If you connect an app that uses a model on your own computer, the text stays on your computer. **Only connect agents you trust with that, and think about which prompts you keep.**
- **Use a read-only token** unless you want the agent to save things.
- **Text from your files is treated as data, never as orders.** Every answer is marked that way, and the agents are told not to follow instructions that appear inside your prompts or documents. This helps against "prompt injection" (a stored text that tries to give the agent orders), but no safeguard is perfect, which is another reason writes only ever **add** and can be **undone**.
- **Tokens are secrets.** Only a one-way fingerprint of each token is stored in FlowlyStack. Anyone with a token can read what it is allowed to read, so keep it out of chats, screenshots and shared files. If a token ends up in your app's settings file, treat that file like a password file.
- Wrong tokens count like wrong passwords: **five wrong tries in a minute lock that address out for a minute.**

## 12. Problems and fixes

**"Connection failed", "refused" or "not reachable"**
FlowlyStack is not running, or the port is different. Start it (`docker compose up -d`, or `./run.sh` from source) and check the address in **Settings > MCP**.

**401 / "A valid MCP token is required" / "FlowlyStack refused the token"**
The token is wrong, was revoked, or was pasted with a missing or extra character. Go to **Settings > MCP**, press **Regen** on the token, and update your app with the new one (see [section 9](#9-managing-tokens)).

**404 / "MCP is turned off"**
The switch **Let agents use FlowlyStack** is off, or the address is wrong. Turn the switch on. The address must end in `/mcp`.

**429 / "too many attempts"**
Five wrong tokens in a minute. Wait a minute, then fix the token.

**403 / "Cross-site request refused"**
A web page, or a proxy that does not pass the original host, sent the request. Agents normally do not send an `Origin`, so this means something in between is changing the request. See the Problems list in [remote-access.md](remote-access.md).

**The tools do not show up in `/context`**
- You must start a **new** session after adding the connection or changing the token's permission.
- Run `claude mcp list`. If `flowlystack` is missing, run the add command again (with `--scope user`).
- If you ran the command **without** `--scope user`, the connection exists only in that one folder. Remove it and add it again with `--scope user`:

  ```bash
  claude mcp remove flowlystack
  claude mcp add --scope user --transport http flowlystack http://127.0.0.1:8372/mcp --header "Authorization: Bearer YOUR_TOKEN"
  ```

**"MCP server flowlystack already exists"**
Remove the old one first, then add it again:

```bash
claude mcp remove --scope user flowlystack
```

**I only see 27 tools, not 32**
The token can only read. Press **Allow writing** on it in **Settings > MCP**, then start a **new** session.

**An agent says a write tool is not allowed**
Same cause: the token is read-only. See above.

**Searching gives no results, though I have prompts**
Without Meilisearch (the optional search service from the README), FlowlyStack uses a simpler search. If you run Meilisearch and search suddenly finds nothing, FlowlyStack repairs the search index by itself within about half a minute. If it still finds nothing after a few minutes, stop and start FlowlyStack.

**Route C: the Connectors list does not show FlowlyStack**
- Did you **quit the app completely (Cmd+Q)** before editing the file? If not, the app erased your entry when it closed. Quit it, add the entry again, and then open the app.
- Is the file still valid JSON? A missing comma between `"flowlystack"` and the next server, or an extra comma at the end, hides every server. Paste the file into a JSON checker if unsure.
- Do the two paths in the file exist on this computer? Use the **absolute** paths that Settings gave you.
- In the terminal, was the path in quotes? `Application Support` has a space.
- The switch shows but the tools do not load, or you see **401**? The token in the file is old or was revoked. Regen it on Settings > MCP, put the new one in the file (quit the app first), and open the app again.
- The helper program prints problems in plain words (for example "FlowlyStack refused the token"); the app's log window may show them.

**Test the address and token by hand** *(for any app; needs `curl`, which Mac and Linux have by default)*
Replace `YOUR_TOKEN`, and the address if yours is different:

```bash
curl -s http://127.0.0.1:8372/mcp \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

If you get a long answer with `"tools"`, FlowlyStack and your token are fine, and the problem is in how the app was set up. If you get `{"detail":"MCP is turned off."}`, the switch is off. If you get `A valid MCP token is required`, the token is wrong.

**The Settings page looks old after an update**
FlowlyStack's pages do not reload on their own. Reload the browser page.

**I see a new item in Studio or Linkshell that I did not expect**
Open **Settings > MCP > Recent agent activity**. It shows which token saved it and when, and has **Undo**.

### I run two copies of FlowlyStack

Give each copy its own **name** in the connect command, and use each copy's own token. For example, `flowlystack` for the installed copy on port 8372 and `flowlystack-second` for a second copy on another port:

```bash
claude mcp add --scope user --transport http flowlystack-second http://127.0.0.1:9000/mcp --header "Authorization: Bearer YOUR_TOKEN"
```

The name is the word right after `--transport http`. In the Claude desktop app's `claude_desktop_config.json`, the name is the key under `"mcpServers"`. The address (`:9000`) must be the port that copy really runs on. If a connection that worked stops, check that the app is running on that port.


## 13. All 32 tools

You do not call these by name. Your agent picks them. This list shows what exists, and what a token needs.

**Read tools** (every token has these 27)

| Tool | What it does |
|---|---|
| `flowlystack_about` | Says what this token may do and lists the tools. Agents call this first. |
| `library_search` | Searches your Library prompts (typo-tolerant when Meilisearch runs). Filters: tag, agent, starred. |
| `library_get` | Reads one Library prompt in full. |
| `library_list_tags` | Lists your Library tags with counts. |
| `studio_search` | Searches your Studio prompts. Filters: tag, status (draft, refined, final). |
| `studio_get` | Reads one Studio prompt in full. |
| `studio_versions` | Lists the versions of a Studio prompt. |
| `studio_diff` | Shows what changed between two versions. |
| `collections_list` | Lists your collections (plus the built-in "My prompts"). |
| `collections_search` | Finds passages that answer a question, across documents and prompts. Shows `vector_score` (meaning similarity) and `keyword_rank` so an agent can judge relevance; optional `min_relevance` drops weak meaning-only matches. |
| `collections_get_prompt` | Reads one saved prompt (Library or Studio) by id. |
| `collections_list_by_tag` | Lists saved prompts that carry a tag. |
| `linkshell_list_projects` | Lists your Linkshell projects with progress. |
| `linkshell_get_project` | Shows one project's structure: phases, blocks and links. |
| `linkshell_get_block` | Reads one block's text and history. |
| `linkshell_assemble` | Gives the exact text you would paste for one prompt. |
| `linkshell_export_plan` | Gives a whole project as a clean, readable plan. |
| `gallery_overview` | Describes patterns in your Library (groups, top words). Never starts a rebuild. |
| `gallery_repeats` | Lists prompts you keep retyping (near duplicates). |
| `gallery_group` | Lists the prompts in one Gallery group. |
| `graph_overview` | Describes your Lattice: how many prompts, documents, collections, tags and Linkshell projects (those connected to a prompt) it holds, how they connect, the most connected items. Starts the same quick background build the page uses if there is none yet (no model is called). |
| `graph_search` | Finds items, collections, tags and entities in the Lattice by words in their title, or lists the items that connect to nothing (`unconnected`). |
| `graph_neighbors` | Lists what one item is connected to: its collection, tags, project, the prompt it was copied from, the next or same-session prompt, exact copies, the links, files and ticket ids it shares with other items, and documents it names (facts), and the items closest to it in meaning (estimates with a score). |
| `graph_path` | Shows the shortest chain of connections between two items. It can pass through entities. |
| `graph_entity` | Reads one entity (a person, tool or concept found in your material) with its evidence: every item that mentions it with the exact quote, and its links to other entities. |
| `graph_refresh` | Rebuilds the Lattice's base layer from your files now (the page's Refresh). No model is called; only the Lattice's own cache is written. |
| `graph_unprocessed` | Lists the items no entity run has covered or read yet (newest first), so an agent can work through your material in pieces. |

**Write tools** (only tokens with **Allow writing**; see [section 8](#8-letting-an-agent-save-things-and-undo))

| Tool | What it does |
|---|---|
| `studio_create` | Saves a new draft prompt in Studio. |
| `studio_save_version` | Adds a new version to a Studio prompt. |
| `linkshell_create_project_from_plan` | Creates a new Linkshell project from a plan. |
| `graph_start_run` | Opens a "run": everything an agent adds to the Lattice in that run is one batch, so one click undoes all of it. |
| `graph_add` | Adds entities (people, tools, concepts ...) and the links between them to the Lattice. Every link needs the item it came from and a quote copied exactly from that item; FlowlyStack checks the quote is really there and refuses the call otherwise. Each entity has a kind (Person, Technology, ...): use the names listed in the tool's description, which follow the kinds you set in the Lattice (Edit kinds). It can only add. |

## 14. For developers

- **Endpoint:** `POST /mcp` on the same server and port as FlowlyStack. JSON answers only (no streaming, no sessions). `GET` and `DELETE` return 405. A notification gets `202` with no body.
- **Protocol:** one endpoint serves two generations of MCP. Requests that carry `_meta["io.modelcontextprotocol/protocolVersion"]` (2026-07-28) are answered statelessly, and `server/discover` describes the server. Older clients start with `initialize` (2025-11-25, 2025-06-18, 2025-03-26, 2024-11-05) and are answered without a session. Only tools are offered (no resources or prompts).
- **Auth:** `Authorization: Bearer fls_…` on every request. A token works **only** on `/mcp`. A session cookie is never accepted there. `/mcp` needs a token even when `FLOWLYSTACK_AUTH=off`. A request whose `Origin` names another site is refused with 403. The switch is the setting `mcp.enabled` (default off, `404` while off).
- **Scopes:** `read` and `write`. `tools/list` shows a read token 27 tools and a write token 32. `tools/call` refuses a write tool for a read token. List results say `cacheScope: "private"`, because the list depends on the token.
- **Limits:** text in up to 200 KB; Linkshell plans up to 60 prompts, 80 blocks and 200 links; a result over about 400,000 characters is refused with a request to narrow the question; `library_get` and `studio_get` cut text at 100,000 characters and say `truncated: true`.
- **Every result** carries a `notice` saying the text comes from the user's files and is data, not instructions.
- **The bridge** `backend/mcp_stdio.py` is a single standard-library file: it reads one JSON-RPC message per line on stdin, `POST`s it to `FLOWLYSTACK_MCP_URL` with `FLOWLYSTACK_MCP_TOKEN`, and writes the answer to stdout. It never follows redirects and never prints the token. Run it with an absolute path.
- **Activity log:** `data/` (the settings folder) holds `mcp_activity.json`: time, token name, tool, store, id and title only. No prompt text and no secrets.
- **Checks:** `scripts/check_mcp.py`, `check_mcp_tools.py`, `check_mcp_write.py`, `check_mcp_stdio.py` and `check_mcp_api.py` (the last needs throwaway servers; see its header).

---

*Something unclear or out of date? That is a bug in this page. Please open an issue.*
