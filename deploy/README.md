# Deploying the server (containerized)

The server ships as a Docker image and runs as a `docker compose` **edge stack**:
a hardened `chess-server` container (uvicorn) plus a `caddy` container that
terminates TLS and reverse-proxies to it, all behind Cloudflare.

```
Player ──wss:443──▶ Cloudflare (orange cloud, Full strict)
                         │  CF-Connecting-IP added
                         ▼
        UFW + DOCKER-USER: only Cloudflare ranges may reach :80/:443
                         │
                         ▼
        caddy container :80/:443  ── Origin Cert (Authenticated Origin Pulls optional)
                         │  reverse_proxy chess-server:8000  (compose network)
                         ▼
        chess-server container  (uvicorn; 127.0.0.1:8000 host-published for debug only)
```

The server is **stateless** (in-memory rooms, no DB) — a restart loses in-flight
games. The published `127.0.0.1:8000` is for the healthcheck/debug only; the
public surface is Caddy on `:80/:443`.

## Prerequisites

- A Debian VPS and a domain proxied through Cloudflare (orange cloud).
- Cloudflare **SSL/TLS mode = Full (strict)** and a **Cloudflare Origin Certificate**
  for the host (Dashboard → SSL/TLS → Origin Server → Create Certificate).
- The image is public at `ghcr.io/xiaomyung/chess-shootout-server` — no login needed.

## One-time setup

### 1. Install Docker (official apt repo)

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
  https://download.docker.com/linux/debian $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

### 2. Project directory + files

```bash
sudo mkdir -p /srv/chess-shootout/secrets /srv/chess-shootout/deploy
cd /srv/chess-shootout
sudo curl -fsSL https://raw.githubusercontent.com/xiaomyung/chess-shootout/master/docker-compose.yml -o docker-compose.yml
sudo curl -fsSL https://raw.githubusercontent.com/xiaomyung/chess-shootout/master/deploy/Caddyfile -o deploy/Caddyfile
```

### 3. Secrets

The Caddy container reads three PEM files as compose secrets (mounted at
`/run/secrets/...`). Put them in `./secrets/` at mode `0600`:

```bash
# Cloudflare Origin Certificate + key (from the CF dashboard):
sudo install -m 600 /path/to/origin.crt secrets/cf_origin_cert.pem
sudo install -m 600 /path/to/origin.key secrets/cf_origin_key.pem
# Cloudflare Authenticated-Origin-Pulls CA (static, published by Cloudflare):
sudo curl -fsSL https://developers.cloudflare.com/ssl/static/authenticated_origin_pull_ca.pem \
  | sudo tee secrets/cf_aop_ca.pem > /dev/null
sudo chmod 600 secrets/cf_aop_ca.pem
```

### 4. Config: the two env files

`docker compose` reads two separate files in the project dir:

- **`.env`** — compose interpolation only. Pins which image runs:
  ```
  IMAGE_TAG=2.1.0
  ```
- **`chess-server.env`** — injected into the `chess-server` container:
  ```
  HOST=0.0.0.0
  PORT=8000
  LOG_LEVEL=INFO
  MAX_ROOMS=100
  # GRACE_SECONDS=60
  # HEARTBEAT_INTERVAL_SECONDS=2
  # HEARTBEAT_MISS_LIMIT=3
  ```
  `HOST=0.0.0.0` so Caddy can reach the app over the compose network. **Do not
  set `LOG_FILE`** (logs go to stdout → the json-file driver). `TRUSTED_PROXIES`
  is set in `docker-compose.yml` (the pinned Caddy subnet) — leave it out here.

### 5. Firewall: only Cloudflare may reach the origin

Docker's published ports **bypass UFW**, and Docker **recreates the `DOCKER-USER`
chain on every boot and daemon restart** — so the Cloudflare-only rules can't live
in `ufw` or `netfilter-persistent` (Docker would wipe them). Put them in a small
systemd unit that re-applies them *after* Docker:

```bash
sudo ufw allow ssh && sudo ufw default deny incoming && sudo ufw enable

sudo tee /usr/local/sbin/cf-docker-firewall.sh >/dev/null <<'EOF'
#!/usr/bin/env bash
iptables -F DOCKER-USER
for ip in $(curl -fsS --retry 3 https://www.cloudflare.com/ips-v4 || true); do
  iptables -A DOCKER-USER -p tcp -m multiport --dports 80,443 -s "$ip" -j ACCEPT
done
iptables -A DOCKER-USER -p tcp -m multiport --dports 80,443 -j DROP
iptables -A DOCKER-USER -j RETURN
EOF
sudo chmod 755 /usr/local/sbin/cf-docker-firewall.sh

sudo tee /etc/systemd/system/cf-docker-firewall.service >/dev/null <<'EOF'
[Unit]
Description=Restrict published 80/443 to Cloudflare ranges
After=docker.service network-online.target
Wants=network-online.target
Requires=docker.service
PartOf=docker.service

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/cf-docker-firewall.sh
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload && sudo systemctl enable --now cf-docker-firewall.service
```

This is the primary "only Cloudflare reaches the origin" control, and it survives
reboots and Docker restarts. (The container publishes IPv4; if you enable Docker
IPv6 publishing, add matching `ip6tables` rules with Cloudflare's IPv6 ranges.)

### 6. (Optional) Authenticated Origin Pulls

The shipped Caddyfile uses the Origin Certificate only — a standard Full-strict
setup, same as a plain host Caddy. The `DOCKER-USER` firewall above already limits
the origin to Cloudflare ranges. To add mTLS on top (so the origin also *verifies*
that the client is Cloudflare):

1. Enable **SSL/TLS → Origin Server → Authenticated Origin Pulls** (zone-level) in
   Cloudflare.
2. Wrap the Caddyfile's `tls` directive with a `client_auth` block:
   ```
   tls /run/secrets/cf_origin_cert /run/secrets/cf_origin_key {
       client_auth {
           mode require_and_verify
           trust_pool file /run/secrets/cf_aop_ca
       }
   }
   ```
   then `docker compose --profile edge restart caddy`.

> Cloudflare's AOP CA has rotated before; if origin pulls fail zone-wide after
> enabling, refresh `secrets/cf_aop_ca.pem` from Cloudflare and restart caddy.

### 7. systemd unit + start

```bash
sudo cp deploy/chess-server-compose.service.example \
        /etc/systemd/system/chess-server-compose.service
sudo systemctl daemon-reload
sudo systemctl enable --now chess-server-compose
curl -s https://chess.xiaomyung.com/healthz
```

## Operations

| Action | Command (in `/srv/chess-shootout`) |
|---|---|
| Status | `docker compose --profile edge ps` |
| Live logs | `docker compose --profile edge logs -f` |
| Restart | `sudo systemctl restart chess-server-compose` |
| Stop | `sudo systemctl stop chess-server-compose` |
| Update | set `IMAGE_TAG` in `.env`, then `docker compose pull && sudo systemctl restart chess-server-compose` |
| Rollback | pin a prior version (or image digest) in `.env`, `pull`, restart |

A clean `stop`/`restart` (or `up -d` onto a new image) lets the server broadcast
`server_shutdown` to connected clients (`stop_grace_period` / `TimeoutStopSec=30`
covers the 10 s drain).

## Updating to a new version

A version-bumped PR merging to master auto-publishes the new image to GHCR
(`docker.yml`). Updating is one command on the box:

```bash
cd /srv/chess-shootout
./deploy/update.sh            # update to the latest release
./deploy/update.sh v2.1.5     # or roll to a specific release tag
```

It pulls the matching CI-built (and trivy-scanned) image from GHCR, refreshes the
compose file / Caddyfile from git, recreates **only `chess-server`** (Caddy is
untouched) with the graceful `server_shutdown` drain, and prints the running
version. It falls back to `sudo` automatically when your shell isn't in the
`docker` group, so there's nothing to fiddle with.

**Rollback** is the same command with an earlier tag (`./deploy/update.sh v2.1.0`).

> Pulling requires read access to the GHCR package — either make it **Public**
> (repo → Packages → Package settings) or `docker login ghcr.io` once on the box.
