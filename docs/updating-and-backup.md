# Updating and backup

This page covers three things: how to **update** FlowlyStack, how to **back up** your work, and how to **move or remove** it. Your prompts and documents are never lost by an update.

## Where your things live

| What | Where | Back it up? |
|---|---|---|
| **Prompts, Studio prompts, documents, Linkshell projects, conversations** | The `prompts` folder inside your `flowlystack` folder: plain files you can open | **Yes. This is your work.** |
| **Your login, settings and keys** | The Docker volume `flowlystack_data` (from source: the `data` folder) | Yes, if you don't want to set it up again |
| **Search index, vectors, Dashboard and Gallery caches** | Docker volumes and the `data` folder | No. They are rebuilt from your files |

The login and settings volume also holds `secrets.json`, which stores any key you typed under **Other runtimes**. Keep your backup somewhere private.

## Update

Your prompts, settings and login stay. New versions can read the data of old ones, and the caches are rebuilt by themselves if needed. After an update, open **Settings > About > What's new** to see what changed.

### Docker (installer, agent or by hand)

In your `flowlystack` folder:

```bash
docker compose pull
docker compose up -d
```

`pull` downloads the new version and `up -d` restarts the app on it. This takes a minute. You can also run the installer again, which does the same and is safe to repeat:

```bash
bash ~/flowlystack/install.sh
```

### Choose a version: `latest` or a fixed one

The `FLOWLYSTACK_IMAGE` line in your `.env` file decides which version you get:

```
FLOWLYSTACK_IMAGE=ghcr.io/cent822/flowlystack:latest
```

- **`latest`** follows the newest release every time you pull. Good for most people.
- **A fixed version** such as `:0.1.0` never changes until you edit the line. Good if you want stability.

The installer never edits your `.env`. To switch, change that line yourself, then run the two commands above.

### From source

```bash
git pull
./run.sh
```

`run.sh` installs any new dependencies by itself, then starts the app.

## Back up

### The easy part: your prompts folder

Copy the `prompts` folder to a safe place (an external drive, a cloud folder, a Git repository). That's all your work, as plain files. It is fine to copy while the app is running.

If you already back up your computer (Time Machine, a cloud-sync folder), your `prompts` folder is covered because it is a normal folder. Your login and settings live in a Docker volume that those tools can't see, so back them up with the command below, or keep them in a normal folder with a bind-mount (advanced).

### Your login and settings (Docker)

These live in a Docker volume, so they need one command. Stopping the app first keeps the copy clean. Run this in your `flowlystack` folder:

```bash
docker compose stop
docker run --rm -v flowlystack_flowlystack_data:/data:ro -v "$PWD":/backup alpine tar czf /backup/flowlystack-data-backup.tar.gz -C /data .
docker compose start
```

This makes one file, `flowlystack-data-backup.tar.gz`, next to your compose file. On Windows PowerShell, write `${PWD}` instead of `$PWD`.

> **The volume name.** With the standard setup it is `flowlystack_flowlystack_data`. If yours differs (for example you changed the project name), run `docker volume ls` and look for the name that ends in `flowlystack_data`.

If you run from source, the same data is the `data` folder: copy it while the app is stopped.

## Restore

1. Put your `prompts` folder back in place.
2. For the login and settings, stop the app and unpack your backup into the volume:

   ```bash
   docker compose down
   docker run --rm -v flowlystack_flowlystack_data:/data -v "$PWD":/backup alpine sh -c "cd /data && tar xzf /backup/flowlystack-data-backup.tar.gz"
   docker compose up -d
   ```

3. Open the app. Search and the other caches rebuild on their own.

The Library, Studio and the rest come from the `prompts` folder, so even with only that folder restored, you get all your work back and only the login and settings need setting up again.

## Move to a new computer

1. Install FlowlyStack on the new computer ([Quick start](quick-start.md)). Don't create an account yet.
2. Stop it (`docker compose down`).
3. Copy your `prompts` folder over the new one, and restore the data backup as above if you want your login and settings too.
4. Start it (`docker compose up -d`).

## Stop, uninstall and start over

| What you want | Command (in your `flowlystack` folder) | What happens to your data |
|---|---|---|
| **Stop** the app | `docker compose down` | Nothing is deleted. `docker compose up -d` starts it again. |
| **Remove the app, keep your work** | `docker compose down`, then delete the images if you like | Your `prompts` folder and the data volume stay. |
| **Start completely fresh** | `docker compose down -v` | **Deletes the volumes: login, settings and caches.** Your `prompts` folder stays, but the app asks you to create an account again. |
| **Delete everything** | `docker compose down -v`, then delete the `flowlystack` folder | **Your prompts are gone too.** Back them up first. |

`-v` is the dangerous letter: it deletes the volumes. FlowlyStack's installer and agent skill never run it for you.

## Good to know

- **Old Claude history.** Claude Code deletes old session history after a while. If you [captured your prompts](connect-agents.md), the copies in your Library may now be the only ones.
- **Several copies.** A second install on the same computer needs another folder, another port and another container name (`FLOWLYSTACK_PORT`, `FLOWLYSTACK_CONTAINER` in its `.env`).
- **Something wrong after an update?** Set `FLOWLYSTACK_IMAGE` back to the older version, run the two update commands, and see [Troubleshooting](troubleshooting.md).
