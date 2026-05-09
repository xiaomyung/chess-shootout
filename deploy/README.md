# Deployment

Single-VPS deployment with Caddy + systemd. Local dev runs on
`localhost:8000` with no TLS; the VPS runs uvicorn behind Caddy on
`:443` with auto-renewed Let's Encrypt certs.

Tested on Debian 12 (Bookworm) and Debian 13 (Trixie). All commands
below run as a sudoer user (e.g. `apollo`); the actual chess process
runs as a dedicated unprivileged `chess` system user.

## One-time setup

### 1. System packages and the `chess` user

```bash
sudo apt update
sudo apt install -y caddy git curl \
    build-essential libssl-dev zlib1g-dev libbz2-dev libreadline-dev \
    libsqlite3-dev libncursesw5-dev xz-utils tk-dev libffi-dev liblzma-dev

sudo useradd -r -m -d /opt/chess -s /bin/bash chess
```

The `build-essential ... liblzma-dev` block is what `pyenv` needs to
compile Python from source; skip it if you already have a working 3.12
on the system.

#### Debian 13 (Trixie) binutils gotcha

On Debian 13 the `binutils-x86-64-linux-gnu` package ships its
binaries (`as`, `ld`, ...) with mode `0750` or `0754`, so the chess
user can't execute them. `gcc` will fail with
`cannot execute 'as': posix_spawnp: Permission denied` part-way through
the pyenv build. Fix once after the apt install:

```bash
sudo chmod 0755 \
    /usr/bin/x86_64-linux-gnu-as \
    /usr/bin/x86_64-linux-gnu-ld \
    /usr/bin/x86_64-linux-gnu-ld.bfd \
    /usr/bin/x86_64-linux-gnu-ld.gold \
    /usr/bin/x86_64-linux-gnu-objcopy \
    /usr/bin/x86_64-linux-gnu-objdump \
    /usr/bin/x86_64-linux-gnu-strip \
    /usr/bin/x86_64-linux-gnu-ar \
    /usr/bin/x86_64-linux-gnu-ranlib \
    /usr/bin/x86_64-linux-gnu-nm 2>/dev/null
```

Reinstalling `binutils-x86-64-linux-gnu` does not help — the .deb
itself ships with these perms. Verified on Hetzner's Debian 13 image
and on a separate Debian 13 homelab.

Quick verify:

```bash
echo 'int main(void){return 0;}' > /tmp/h.c && gcc /tmp/h.c -o /tmp/h && echo OK || echo FAIL
rm -f /tmp/h /tmp/h.c
```

### 2. Python 3.12 via pyenv (under the `chess` user)

Debian 12's main repos top out at 3.11; Debian 13 ships 3.13 — neither
matches our `requires-python = ">=3.12,<3.13"` pin. pyenv builds a
local 3.12 for the `chess` user without touching system Python.

Every block below sets `HOME=/opt/chess` explicitly because `sudo -H`
is not honoured uniformly across Debian sudoers configs (Hetzner's
default image leaks the invoking user's HOME into the chess shell,
which pyenv then can't `cd` into).

```bash
# Install pyenv into /opt/chess/.pyenv.
sudo -u chess -- bash -c '
    export HOME=/opt/chess
    cd $HOME
    curl -fsSL https://pyenv.run | bash
'

# Add pyenv to chess's .bashrc for future interactive sessions.
sudo -u chess -- tee -a /opt/chess/.bashrc > /dev/null <<'EOF'

export PYENV_ROOT="$HOME/.pyenv"
[[ -d $PYENV_ROOT/bin ]] && export PATH="$PYENV_ROOT/bin:$PATH"
eval "$(pyenv init - bash)"
EOF

# Install Python 3.12 — compiles from source, ~2 min the first time.
# We export PYENV_ROOT/PATH inline because non-interactive sudo
# shells don't source .bashrc.
sudo -u chess -- bash -c '
    export HOME=/opt/chess
    cd $HOME
    export PYENV_ROOT="$HOME/.pyenv"
    export PATH="$PYENV_ROOT/bin:$PATH"
    eval "$(pyenv init - bash)"
    pyenv install 3.12
    pyenv global 3.12
    python --version
'
# Expect: Python 3.12.x
```

(If you already have a working `python3.12` from `bookworm-backports`,
skip this and have the venv in step 3 use `/usr/bin/python3.12` instead.)

### 3. Clone, venv, install

```bash
sudo -u chess -- bash -c '
    export HOME=/opt/chess
    cd $HOME
    export PYENV_ROOT="$HOME/.pyenv"
    export PATH="$PYENV_ROOT/bin:$PATH"
    eval "$(pyenv init - bash)"
    git clone https://github.com/xiaomyung/chess-pygame /opt/chess/repo
    cd /opt/chess/repo
    python -m venv .venv
    .venv/bin/pip install -U pip
    .venv/bin/pip install -e .
'
```

### 4. systemd unit + env

```bash
sudo cp /opt/chess/repo/deploy/chess-server.service.example /etc/systemd/system/chess-server.service

sudo tee /etc/chess-server.env > /dev/null <<'EOF'
HOST=127.0.0.1
PORT=8000
LOG_LEVEL=INFO
LOG_FILE=/var/log/chess-server.log
MAX_ROOMS=100
EOF

sudo touch /var/log/chess-server.log
sudo chown chess:chess /var/log/chess-server.log
```

### 5. Caddy + DNS

Point an `A` (and optionally `AAAA`) record for your hostname at the
VPS, then **append** the chess site block to your existing
`/etc/caddy/Caddyfile` (don't overwrite — Debian's default already has
a `:80` static-file block you may want to keep, and Caddy supports
multiple site blocks in one file):

```bash
sudo tee -a /etc/caddy/Caddyfile < /opt/chess/repo/deploy/Caddyfile.example > /dev/null
sudo sed -i 's/chess.example.com/your-actual-domain.com/' /etc/caddy/Caddyfile
```

If you don't want the default `:80` static-file site, comment that
block out manually after appending — Caddy will just not serve it.

#### Cloudflare proxied (recommended for security)

If your DNS is on Cloudflare, putting `chess.your-domain.com` behind
the orange cloud (proxied) is the recommended setup — origin IP
hidden, edge DDoS mitigation, free WAF rules, plus the app-level
caps. Steps in the Cloudflare dashboard for your zone:

1. **DNS → Records** — add `A` (and optionally `AAAA`) for `chess`,
   pointing at the VPS, **proxy status = Proxied** (orange cloud).
2. **SSL/TLS → Overview → Encryption Mode = Full (strict).** Anything
   weaker (Flexible, Full) makes the edge↔origin link spoofable. Caddy
   serves a Let's Encrypt cert that satisfies (strict).
3. **SSL/TLS → Edge Certificates → Always Use HTTPS = ON.**
4. **Network → WebSockets = ON** (default; verify).
5. **Security → Bots → Bot Fight Mode = ON** (free).

Cloudflare's WebSocket idle timeout is 100 seconds — our server already
sends ping frames every 20s (`ws_ping_interval=20` in
`server/app.py`), well under the cap.

Optionally restrict origin firewall to Cloudflare IP ranges only so
attackers can't bypass the proxy by hitting your VPS IP directly:

```bash
# Make sure SSH is allowed BEFORE enabling the firewall.
sudo ufw allow ssh

# Allow 80/443 only from Cloudflare's published IPv4 ranges.
for cidr in $(curl -s https://www.cloudflare.com/ips-v4); do
    sudo ufw allow from "$cidr" to any port 80 proto tcp
    sudo ufw allow from "$cidr" to any port 443 proto tcp
done

sudo ufw default deny incoming
sudo ufw enable
```

(Cloudflare's IPv4 ranges change rarely — once or twice a year. If
you want to be tidy, re-run the loop on update; otherwise current
rules keep working.)

### 6. Start everything

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now chess-server caddy
```

### 7. Verify

```bash
curl https://your-actual-domain.com/healthz
# {"status":"ok","version":1,"rooms_active":0,"queue_depth":0,"uptime_s":4.12}
```

## Operations

Day-to-day commands. All require `sudo` unless noted.

| Action | Command |
|---|---|
| Start | `sudo systemctl start chess-server` |
| Stop | `sudo systemctl stop chess-server` |
| Restart (e.g. after env change) | `sudo systemctl restart chess-server` |
| Status (running? recent logs?) | `sudo systemctl status chess-server` |
| Live logs | `sudo journalctl -u chess-server -f` |
| Logs since boot | `sudo journalctl -u chess-server -b` |
| Last 200 lines | `sudo journalctl -u chess-server -n 200 --no-pager` |
| Live `LOG_FILE` (if set) | `sudo tail -f /var/log/chess-server.log` |
| Disable autostart | `sudo systemctl disable chess-server` |
| Re-enable autostart | `sudo systemctl enable chess-server` |
| Caddy reload (config change) | `sudo systemctl reload caddy` |
| Caddy logs | `sudo journalctl -u caddy -f` |

The `chess-server.service` lifespan handler broadcasts a
`server_shutdown` result to all active rooms before exit, so a clean
`stop` / `restart` shows connected clients
"Game cancelled / server shutting down" instead of an abrupt drop.
After a restart, clients reconnecting hit the
"Server restarted — game ended" modal (`/resume` 4xx + `/healthz` ok)
and can click **New Search** to immediately re-pair.

## Updating

```bash
sudo -u chess -- bash -c 'export HOME=/opt/chess && cd /opt/chess/repo && git pull && .venv/bin/pip install -e .'
sudo systemctl restart chess-server
```

## Client connection

Players set `CHESS_SERVER_ADDR=your-actual-domain.com` in their `.env`.
The client's scheme heuristic picks `wss://` for hostnames (anything
that isn't `localhost`/IP/port-8000), so TLS is automatic — no
configuration on the client.

## Reference

### Endpoints

| Path | Method | Purpose |
|---|---|---|
| `/` | GET | JSON manifest of available endpoints |
| `/healthz` | GET | `{status, version, rooms_active, queue_depth, uptime_s}` |
| `/matchmake` | POST | Enqueue / pair |
| `/matchmake` | DELETE | Cancel pre-pairing |
| `/resume` | POST | Re-establish session token after WS drop |
| `/reclaim` | POST | App-restart reconnect (uuid → fresh token) |
| `/ws/{room_id}` | WS | Auth handshake then game events |

### Rate limits

- `/reclaim` — 5/min per uuid (sliding 60s window) on top of slowapi's
  120/min/IP cap.
- `/matchmake` — 60/min/IP.
- `/resume` — 60/min/IP.
- Per-WS — 30 msg/sec per session; exceeded messages get a
  `rate_limited` error reply but the connection stays open.

### Logs

`journalctl -u chess-server -f` (or `tail -f $LOG_FILE`) shows the
structured key-value lines:

```
matchmake nickname=… uuid=… tc=…
matchmake ok room=… paired=…
ws auth ok room=… uuid=… tentative_color=… paired=… has_both=…
game_start broadcast room=… sent_to=[white, black]
move applied room=… mover=… san=…
draw offered/accepted/declined/mutual room=…
takeback requested/accepted/declined room=…
rematch requested/accepted/declined/mutual room=…
abandonment / aborted / drop room=…
ws disconnected room=… color=…
```

`LOG_LEVEL=DEBUG` in `/etc/chess-server.env` adds one line per WS
message:

```
ws dispatch room=… uuid=… type=move latency_ms=0.9 outcome=applied
ws dispatch room=… uuid=… type=draw_offer latency_ms=0.2 outcome=offered
```

UUIDs are truncated to 8 chars in every log line. Restart the service
after changing `LOG_LEVEL`.
