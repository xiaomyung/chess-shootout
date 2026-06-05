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
        caddy container :80/:443  ── Origin Cert + Authenticated Origin Pulls (mTLS)
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

Docker's published ports **bypass UFW**, so the Cloudflare-ranges restriction
must live in the `DOCKER-USER` chain, not a plain `ufw allow`:

```bash
sudo ufw allow ssh && sudo ufw default deny incoming && sudo ufw enable

# Allow only Cloudflare ranges to the published 80/443 (IPv4 + IPv6):
for ip in $(curl -s https://www.cloudflare.com/ips-v4); do
  sudo iptables  -I DOCKER-USER -p tcp -m multiport --dports 80,443 -s "$ip" -j ACCEPT
done
for ip in $(curl -s https://www.cloudflare.com/ips-v6); do
  sudo ip6tables -I DOCKER-USER -p tcp -m multiport --dports 80,443 -s "$ip" -j ACCEPT
done
# Drop everything else aimed at 80/443:
sudo iptables  -A DOCKER-USER -p tcp -m multiport --dports 80,443 -j DROP
sudo ip6tables -A DOCKER-USER -p tcp -m multiport --dports 80,443 -j DROP
sudo apt-get install -y netfilter-persistent iptables-persistent
sudo netfilter-persistent save
```

This is **belt-and-suspenders** with Authenticated Origin Pulls (next step): the
firewall blocks non-CF IPs, AOP rejects anything that isn't Cloudflare at the TLS
layer even if the firewall is wrong.

### 6. Cloudflare: enable Authenticated Origin Pulls

Dashboard → SSL/TLS → Origin Server → **Authenticated Origin Pulls** = On
(zone-level). The Caddyfile already requires the CF client cert
(`client_auth … trust_pool file /run/secrets/cf_aop_ca`).

> **Maintenance note:** Cloudflare's AOP CA has rotated before. If origin pulls
> start failing zone-wide, refresh `secrets/cf_aop_ca.pem` from Cloudflare and
> `docker compose --profile edge restart caddy`.

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

**Normal updates** pin `IMAGE_TAG` to the version (e.g. `2.1.0`); `docker compose
pull` fetches the latest build of that tag — including the **weekly base-image
CVE rebuild**. For a guaranteed-unchanging rollback target, pin the full image
**digest** in the compose `image:` line, since the `version`/`sha` tags are
re-pushed by the weekly job.

A clean `stop`/`restart` lets the server broadcast `server_shutdown` to connected
clients (`TimeoutStopSec=30` covers the 10 s drain).
