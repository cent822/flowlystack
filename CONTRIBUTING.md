# Contributing to FlowlyStack

**You are warmly welcome here.** Whether you found a typo, hit a bug, have an idea, or want to write code, we are glad you came. Every contribution helps, big or small, and you do not need to be an expert to take part.

FlowlyStack is a private workspace on your own computer: it keeps your AI prompts, shows how they connect, and lets you plan a project as a canvas of prompts. Please keep that in mind when you suggest changes. It stays **local** (no cloud, no tracking), it stays **simple** (plain files, no build step, no framework), and it never sends your text to a model unless you press Send.

## Report a bug or suggest an idea

- Open an issue from the **Issues** tab and pick the template that fits. Search the existing issues first; someone may have asked already.
- For a bug, tell us what you did, what you expected, what happened, and your setup (how you run it: Docker or from source, your system, your browser). A screenshot helps.
- **Never paste your prompts, tokens, passwords or personal data into an issue.** Remove them first.
- Found a security problem? Please do **not** open a public issue. Follow [SECURITY.md](SECURITY.md).

## Run it on your own computer

```bash
./run.sh
```

This creates a Python environment on the first run and starts the app at <http://127.0.0.1:8372>. To use another port: `PORT=9000 ./run.sh`. The backend reloads when you change a file in `backend/`; for the frontend, refresh the browser.

The app reads and writes your real prompts folder. When you are trying changes, **use a throwaway prompts folder** so your own data is never touched (see the next section).

## Ground rules for code

- **Frontend:** plain JavaScript modules loaded from `index.html`. No build step, no bundler, no framework. D3 is bundled in `frontend/vendor/`, and fonts are self-hosted (no requests to outside servers; please keep it that way).
- **Backend:** Python with FastAPI. Several modules are deliberately standard-library only; if a file has no third-party imports today, do not add one.
- **Day and night mode:** every screen must work in both. Colours come from the CSS variables in `frontend/css/tokens.css` (see `DESIGN.md`); do not hard-code colours.
- **Look and feel:** reuse what exists. New buttons use the Glow button style, Copy buttons use the shared copy helper, and dialogs must fit the window at any zoom. `DESIGN.md` describes each pattern.
- **Privacy:** nothing is sent anywhere or to any model unless the user presses a button that says so and the app shows what goes. Do not read other tools' credentials. Do not add analytics or tracking of any kind.
- **Keep changes small and focused.** One topic per change is much easier to review.

## Run the checks

The checks are plain scripts in `scripts/` named `check_*.py`; they use simple asserts and need no test framework. Most run with plain `python3`; the ones that import numpy, LanceDB or pypdf need the project's environment (`.venv/bin/python`).

Checks that talk to the API create and delete prompts, so run them against a **test server** with a temporary prompts folder, never your real one:

```bash
T=$(mktemp -d)
FLOWLYSTACK_AUTH=off FLOWLYSTACK_PROMPTS_DIR=$T RELOAD=0 PORT=8799 ./run.sh &
FLOWLYSTACK_PROMPTS_DIR=$T BASE=http://127.0.0.1:8799 python3 scripts/check_studio_api.py
```

Each script explains in its first lines what it needs. Please run the checks that touch the area you changed, and add or extend a check when you fix a bug or add a feature.

## Send a pull request

1. Fork the repository and make your change on a branch.
2. Keep it focused, and describe **what** you changed and **why**.
3. Say which checks you ran, and what you looked at by hand (screenshots help for visual changes, in both day and night mode).
4. Be kind in discussions. We will do the same. Reviews may ask for changes; that is normal, and it is how we learn from each other.

## Licence

FlowlyStack is released under the [MIT licence](LICENSE). By contributing, you agree that your contribution is released under the same licence.

Thank you for helping make FlowlyStack better.
