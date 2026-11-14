# Remote access and login

FlowlyStack asks for a login. The first time you open it, it shows **Create your account**: choose a username and a password (at least 8 characters). That account is the **owner** and the only one: sign-up closes for good once it exists, and every visit after that shows **Log in**, also on `localhost`. Nothing in the app (pages, the API, the live stream) opens without a session.

This page is for people who run FlowlyStack on a computer or server and open it from elsewhere through a reverse proxy (Caddy, Nginx Proxy Manager).

## How the login works

- One owner account, stored in `data/auth.json` (owner-only permissions, never committed): the username and a scrypt hash of the password. A password is never stored or logged.
- A successful log-in sets a session cookie (named `flowlystack_session_` plus a short code that is different for every install, so two copies of FlowlyStack on one computer never log each other out: HttpOnly, SameSite=Lax, `Secure` over HTTPS). It is a session cookie: the browser drops it when it quits, and the server ends a session left unused for 30 days. On top of that, **every browser tab signs in for itself**: a tab you open later asks for the password again, even if another tab is still signed in; reloading a tab keeps it signed in. Only a hash of the cookie's token is stored.
- Five wrong passwords in a minute lock that address out for a minute.
- A write request whose `Origin` names another site is refused (protection against cross-site requests).
- **Settings > Account** has a profile picture, Name (the name you log in with; changing it asks for your password and keeps you signed in), Change password (it signs every other browser out) and Sign out; the account menu (bottom-left) has Sign out too. The picture is a file next to `auth.json` in `data/` and never leaves the computer.
- Optional two-step login (below). No email and no second account.
- A server restart does not log you out; the lockout, which is only in memory, resets.

## Two-step login (authenticator app)

Turn it on in **Settings > Account > Two-step login > Set up**: type your password, scan the QR code with an authenticator app (Google Authenticator, Microsoft Authenticator, 1Password, Authy and others), type the first 6-digit code, and save the **8 backup codes** it then shows once (Copy or Download). From then on every new log-in asks for the 6-digit code after the password; **Use a backup code instead** takes one of the saved codes, each of which works once. The code is asked at each log-in, which now happens in every new tab or browser session; a reload in the same tab does not ask again.

- **New backup codes** and **Turn off** (same row) ask for your password and a current code (a backup code works too), and sign every other browser out. So does turning it on.
- A code works once, and a phone clock one step (30 seconds) off is tolerated; more than that fails with "Check that the clock on your phone is right". Five wrong codes lock that address for a minute, like wrong passwords.
- The setup key is stored in `data/auth.json` (it has to be readable to check codes; the file is owner-only). Backup codes are stored only as hashes. Do not copy that file to a shared place.
- **Lost the phone and the backup codes:** on the computer that runs FlowlyStack, run the reset command described under [Forgot the password](#forgot-the-password) with `reset-2fa` at the end. It turns two-step off and signs every browser out; you log in with the password and can set it up again.

**MCP (letting an AI agent use FlowlyStack)** has its own tokens and does not use this login: `/mcp` needs a valid token and never accepts the session cookie. If you reach it through a proxy, use HTTPS and the settings below, then follow [mcp-setup.md](mcp-setup.md). Resetting the password also revokes every MCP token.

## Before you expose it

1. **Create the account on the server itself**, at `http://127.0.0.1:8372` (or your port). A sign-up that arrives through a proxy is refused ("Create the account first on the server itself"), so nobody can claim a server you just put online.
2. **Always use HTTPS** on the public side (Caddy does this by itself; in Nginx Proxy Manager turn on Force SSL). A password sent over plain `http://` can be read on the way.
3. Keep FlowlyStack listening on `127.0.0.1` and let the proxy on the same computer reach it. This is the default both for `./run.sh` and for the Docker install (its port is published to `127.0.0.1` only). Do not open the port in a firewall.

## Tell FlowlyStack it is behind a proxy

Set `FLOWLYSTACK_TRUST_PROXY=1`.

- **Docker:** add the line `FLOWLYSTACK_TRUST_PROXY=1` to the `.env` file in your `flowlystack` folder, then run `docker compose up -d`.
- **From source:**

  ```bash
  FLOWLYSTACK_TRUST_PROXY=1 ./run.sh
  ```

With this on, FlowlyStack believes the proxy's `X-Forwarded-For` (the real client address for the lockout), `X-Forwarded-Proto` (so the cookie gets `Secure`) and `X-Forwarded-Host`. Turn it on **only** when the proxy is the only way in; otherwise a visitor could invent those headers. Without it the headers are ignored.

## Caddy

```
flowly.example.com {
    reverse_proxy 127.0.0.1:8372 {
        flush_interval -1
    }
}
```

Caddy gets the certificate, passes the original `Host`, and sets the `X-Forwarded-*` headers. `flush_interval -1` sends the live-update stream (`/api/stream`, server-sent events) at once instead of buffering it.

## Nginx Proxy Manager

1. **Proxy Hosts > Add Proxy Host.** Domain: `flowly.example.com`. Scheme `http`, Forward Hostname `127.0.0.1`, Forward Port `8372`. Leave Websockets off (not needed).
2. **SSL tab:** request a Let's Encrypt certificate and turn on **Force SSL**.
3. **Advanced tab** (custom Nginx configuration), for the live stream:

   ```
   proxy_buffering off;
   proxy_read_timeout 1h;
   ```

If Nginx Proxy Manager itself runs in Docker, `127.0.0.1` points at its own container, not your computer, so it can't reach a port that FlowlyStack publishes to `127.0.0.1` only. The simplest fix is to run the proxy **on the host** (Caddy, or Nginx installed directly). If you want to keep Nginx Proxy Manager in a container, put it on the same Docker network as FlowlyStack and forward to `flowlystack-app` on port `8372`, or change the `ports` line of FlowlyStack's compose file to publish on your computer's LAN address (and let a firewall allow only the proxy). The login still protects the app, but a published port is reachable from that network, so do not skip the firewall.

## Plain Nginx

```
location / {
    proxy_pass http://127.0.0.1:8372;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_buffering off;
    proxy_read_timeout 1h;
}
```

`Host $host` matters: with the default Nginx setting FlowlyStack sees its own address as the host and refuses every save as "Cross-site request refused".

## Problems

- **"Cross-site request refused" when saving:** the proxy does not pass the original `Host` (or, with `FLOWLYSTACK_TRUST_PROXY=1`, `X-Forwarded-Host`). Fix the proxy as above.
- **You log in but are sent back to the login page:** with `FLOWLYSTACK_TRUST_PROXY=1` the cookie is marked `Secure` when the proxy says the request was HTTPS, and a browser drops a `Secure` cookie on a plain `http://` page. Open the site over `https://`.
- **Page updates arrive late or never:** the proxy buffers the live stream; see the settings above.
- **Locked out:** wait a minute (five wrong passwords or codes), or restart FlowlyStack (the lockout is in memory only).
- **"Wrong code" with the right app:** the clock on the phone or on the server is off by more than 30 seconds. Set both to automatic time.

## Forgot the password

There is no email reset. Run this on the computer that runs FlowlyStack.

**Docker:**

```bash
docker exec -it flowlystack-app /usr/local/bin/entrypoint.sh python -m backend.auth reset-password
```

**From source**, in the app folder:

```bash
python3 -m backend.auth reset-password
```

It asks for a new password and signs every browser out. (Two-step stays on; to turn that off, run the same command with `reset-2fa` instead.) Resetting the password also revokes every MCP token.

To start over completely (sign-up opens again), delete the login file. In Docker: `docker exec flowlystack-app rm /app/data/auth.json`. From source: quit FlowlyStack and delete `data/auth.json`.

## Turn the login off

If you run FlowlyStack from source, only on your own computer, and do not want a login:

```bash
FLOWLYSTACK_AUTH=off ./run.sh
```

The Docker install does not offer this switch. Keep the login on there.

Do **not** turn the login off on a server that others can reach. The test scripts in `scripts/` that call a running server (`check_*_api.py`) also need this setting on their throwaway server.
