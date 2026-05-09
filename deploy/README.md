# Deployment

Single-VPS deployment with Caddy + systemd, fronted by Cloudflare. The
chess server runs as a dedicated unprivileged `chess` user; Caddy
terminates TLS at the origin using a Cloudflare-issued Origin
Certificate; UFW restricts inbound 80/443 to Cloudflare's published
IP ranges so the origin IP is unreachable from anywhere else.

Tested end-to-end on Hetzner CX22 / Debian 13 (Trixie). Everything
should work the same on Debian 12 (Bookworm). All commands run as a
sudoer user (e.g. `apollo`).

## One-time setup

### 1. apt deps + `chess` user

```bash
sudo apt update
sudo apt install -y caddy git curl ufw \
    build-essential libssl-dev zlib1g-dev libbz2-dev libreadline-dev \
    libsqlite3-dev libncursesw5-dev xz-utils tk-dev libffi-dev liblzma-dev

sudo useradd -r -m -d /opt/chess -s /bin/bash chess
```

The `build-essential ... liblzma-dev` block is what `pyenv` needs to
compile Python from source.

#### Debian 13 binutils permission gotcha

`binutils-x86-64-linux-gnu` ships its assembler / linker / strip
binaries with mode `0750` or `0754` on Debian 13 — the `chess` user
can't execute them, so `gcc` later fails with
`cannot execute 'as': Permission denied` part-way through the pyenv
build. Fix once now (reinstalling the package does NOT help — the .deb
itself ships these perms):

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

# Smoke test:
echo 'int main(void){return 0;}' > /tmp/h.c && gcc /tmp/h.c -o /tmp/h && echo OK || echo FAIL
rm -f /tmp/h /tmp/h.c
```

### 2. Python 3.12 via pyenv (as `chess`)

`pyproject.toml` pins `>=3.12,<3.13`. Debian 12's apt repos top out at
3.11; Debian 13 ships 3.13. pyenv builds a private 3.12 for `chess`
without touching system Python.

Both blocks below set `HOME=/opt/chess` explicitly because `sudo -H`
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

# Wire pyenv into chess's .bashrc for future interactive sessions.
sudo -u chess -- tee -a /opt/chess/.bashrc > /dev/null <<'EOF'

export PYENV_ROOT="$HOME/.pyenv"
[[ -d $PYENV_ROOT/bin ]] && export PATH="$PYENV_ROOT/bin:$PATH"
eval "$(pyenv init - bash)"
EOF

# Install Python 3.12 — compiles from source, ~2 min the first time.
# We export PYENV_ROOT/PATH inline because non-interactive sudo shells
# don't source .bashrc.
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

The repo lives at `/opt/chess/repo` (NOT `/opt/chess` directly —
that's the home dir with skel files, `git clone` would refuse).

### 4. systemd unit + env file

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
sudo systemctl daemon-reload
```

Don't enable/start the service yet — Caddy needs configuring first
(step 6) and the chess server is bound to `127.0.0.1:8000` so it
won't be reachable until Caddy proxies it.

### 5. Cloudflare DNS + Origin Certificate

In the Cloudflare dashboard for your zone:

1. **DNS → Records** — add `A` (and `AAAA` if you have IPv6) for
   `chess`, pointing at the VPS public IP, **Proxy status = Proxied
   (orange cloud)**. Keep it proxied throughout — never flip to
   "DNS only", that puts the origin IP in DNS history and CT logs
   permanently.

2. **SSL/TLS → Origin Server → Create Certificate.** Default
   settings: ECC private key, hostname `chess.your-domain.com` (or
   `*.your-domain.com` if you want one cert covering future
   subdomains), 15-year validity. Click Create. **The private key
   is shown ONCE** — save both PEMs immediately.

3. **On the VPS,** paste each PEM into a file (Ctrl-X to save in
   nano):
   ```bash
   sudo nano /etc/caddy/chess-origin.crt    # paste the certificate PEM
   sudo nano /etc/caddy/chess-origin.key    # paste the private key PEM
   sudo chown root:caddy /etc/caddy/chess-origin.{crt,key}
   sudo chmod 640 /etc/caddy/chess-origin.{crt,key}
   ```

### 6. Caddy site block

Append the chess block to `/etc/caddy/Caddyfile` — Debian's default
file has a `:80` static-file block that you can leave; Caddy supports
multiple sites per file.

```bash
sudo tee -a /etc/caddy/Caddyfile > /dev/null <<'EOF'

chess.your-domain.com {
    tls /etc/caddy/chess-origin.crt /etc/caddy/chess-origin.key
    reverse_proxy localhost:8000
    encode zstd gzip
    log {
        output file /var/log/caddy/chess-access.log
        format console
    }
}
EOF

sudo sed -i 's/your-domain.com/<your-actual-domain>/' /etc/caddy/Caddyfile

sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

The explicit `tls /path/crt /path/key` line tells Caddy to use the
Origin Certificate verbatim — no Let's Encrypt, no ACME challenge,
no public CA in the chain, no chicken-and-egg.

### 7. UFW: restrict 80/443 to Cloudflare

UFW's default-deny policy means inbound 443 is blocked even after
Caddy is up — the very thing that just bit you would bite the next
operator too if undocumented. Allow Cloudflare's published ranges
only, so origin direct hits get dropped at packet level:

```bash
sudo ufw allow ssh
for cidr in $(curl -s https://www.cloudflare.com/ips-v4); do
    sudo ufw allow from "$cidr" to any port 80 proto tcp
    sudo ufw allow from "$cidr" to any port 443 proto tcp
done
for cidr in $(curl -s https://www.cloudflare.com/ips-v6); do
    sudo ufw allow from "$cidr" to any port 80 proto tcp
    sudo ufw allow from "$cidr" to any port 443 proto tcp
done
sudo ufw default deny incoming
sudo ufw enable
sudo ufw status verbose | head -50
```

Cloudflare adds new CIDRs once or twice a year — re-run the loop
when their published list changes.

### 8. Cloudflare zone settings

Still in the dashboard:

- **SSL/TLS → Overview → Encryption mode = Full (strict).** The
  Origin Certificate satisfies it.
- **SSL/TLS → Edge Certificates → Always Use HTTPS = ON.**
- **Network → WebSockets = ON** (default; verify).
- **Security → Bots → Bot Fight Mode = OFF** (zone-wide). Free Bot
  Fight Mode does not run on Cloudflare's Ruleset Engine and CANNOT
  be bypassed per-hostname — it would block `curl`, the pygame
  client, and the WebSocket handshake. For other sites on the same
  domain, use Custom Rules + Managed Rules + Rate Limiting (1 free
  rule); those DO honour per-hostname filters.
- **Configuration Rule** to relax browser-bot heuristics for the
  chess subdomain only (docs: https://developers.cloudflare.com/rules/configuration-rules/create-dashboard/):
  - When: Hostname equals `chess.your-domain.com`
  - Then: **Browser Integrity Check = Off** (this is what serves
    the "Just a moment..." JS interstitial to non-browser clients)

The app's per-uuid + per-IP rate limits and Pydantic input validation
cover abuse server-side, so the relaxed CF posture on this one
hostname is fine.

### 9. Start the chess server + verify

```bash
sudo systemctl enable --now chess-server
sudo systemctl status chess-server --no-pager
```

Should show `active (running)`. Then test **from your laptop, not
from the VPS itself** (the VPS-to-itself path bypasses some failure
modes):

```bash
curl https://chess.your-domain.com/healthz
# {"status":"ok","version":1,"rooms_active":0,"queue_depth":0,"uptime_s":...}

curl -I https://chess.your-domain.com/healthz | grep -iE 'cf-ray|server'
# server: cloudflare
# cf-ray: ...
```

Both lines confirm Cloudflare is in front. If you get HTTP `522`,
Cloudflare can't reach origin — re-check UFW (step 7) and Caddy
status. If you get a JS challenge page, Bot Fight Mode is still on
or the Configuration Rule's BIC override didn't deploy.

## Operations

Day-to-day commands:

| Action | Command |
|---|---|
| Start | `sudo systemctl start chess-server` |
| Stop | `sudo systemctl stop chess-server` |
| Restart (after env change) | `sudo systemctl restart chess-server` |
| Status | `sudo systemctl status chess-server` |
| Live logs | `sudo journalctl -u chess-server -f` |
| Last 200 lines | `sudo journalctl -u chess-server -n 200 --no-pager` |
| Live `LOG_FILE` | `sudo tail -f /var/log/chess-server.log` |
| Disable autostart | `sudo systemctl disable chess-server` |
| Re-enable autostart | `sudo systemctl enable chess-server` |
| Caddy reload | `sudo systemctl reload caddy` |
| Caddy validate | `sudo caddy validate --config /etc/caddy/Caddyfile` |
| Caddy logs | `sudo journalctl -u caddy -f` |

A clean `stop` / `restart` triggers the lifespan handler's
`server_shutdown` broadcast — connected clients see "Game cancelled
/ server shutting down". Reconnects after a restart hit the
"Server restarted — game ended" modal (because `/resume` 4xx but
`/healthz` ok) and clicking **New Search** re-pairs immediately.

## Updating

```bash
sudo -u chess -- bash -c 'export HOME=/opt/chess && cd /opt/chess/repo && git pull && .venv/bin/pip install -e .'
sudo systemctl restart chess-server
```

## Client connection

Players set in their `.env`:

```
CHESS_SERVER_ADDR=chess.your-domain.com
```

The client's `_split_addr` heuristic (`frontend/online/transport.py`)
auto-picks `wss://` for any non-localhost / non-IP / non-:8000
hostname, so the WebSocket URL becomes
`wss://chess.your-domain.com/ws/{room_id}` automatically — no port,
no client config beyond the address.

## Reference

### Endpoints

| Path | Method | Purpose |
|---|---|---|
| `/` | GET | JSON manifest of available endpoints |
| `/healthz` | GET | `{status, version, rooms_active, queue_depth, uptime_s}` |
| `/matchmake` | POST | Enqueue / pair |
| `/matchmake` | DELETE | Cancel pre-pairing |
| `/resume` | POST | Re-establish session after WS drop |
| `/reclaim` | POST | App-restart reconnect (uuid → fresh token) |
| `/ws/{room_id}` | WS | Auth handshake then game events |

### Rate limits

- `/reclaim` — 5/min per uuid (sliding 60s window) **plus** slowapi's
  120/min/IP cap.
- `/matchmake` — 60/min/IP.
- `/resume` — 60/min/IP.
- Per-WS — 30 msg/sec per session; exceeded messages get a
  `rate_limited` error reply, the connection stays open.

Cloudflare's WebSocket idle timeout is 100s — server-side
`ws_ping_interval=20` keeps the connection well under it.

### Logs

`journalctl -u chess-server -f` (or `tail -f $LOG_FILE`) shows
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

`LOG_LEVEL=DEBUG` adds one line per WS message:

```
ws dispatch room=… uuid=… type=move latency_ms=0.9 outcome=applied
ws dispatch room=… uuid=… type=draw_offer latency_ms=0.2 outcome=offered
```

UUIDs are truncated to 8 chars in every log line. Restart the service
after editing `/etc/chess-server.env`.
