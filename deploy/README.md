# Deploying the server (containerized)

The server runs as a `docker compose` **edge stack**: a hardened `gameserver`
container (uvicorn) plus a `caddy` container that terminates TLS and reverse-proxies
to it, all behind Cloudflare.

```
Player ──wss:443──▶ Cloudflare (orange cloud, Full strict)
                         │  adds CF-Connecting-IP
                         ▼
        DOCKER-USER firewall: only Cloudflare ranges reach :80/:443
                         ▼
        caddy container :80/:443  ── Origin Cert (Authenticated Origin Pulls optional)
                         │  reverse_proxy gameserver:8000  (compose network)
                         ▼
        gameserver container  (uvicorn; 127.0.0.1:8000 published for debug only)
```

The server is **stateless** (in-memory rooms, no DB) — a restart loses in-flight
games. The public surface is Caddy on `:80/:443`; the `127.0.0.1:8000` publish is for
the local healthcheck only.

## Prerequisites

- A Debian VPS and a domain proxied through Cloudflare (orange cloud).
- Cloudflare **SSL/TLS mode = Full (strict)** with a **Cloudflare Origin Certificate**
  for the host (Dashboard → SSL/TLS → Origin Server → Create Certificate).
- Read access to the image at `ghcr.io/xiaomyung/chess-shootout-gameserver`: make the GHCR
  package **Public** (repo → Packages → Package settings), or `docker login ghcr.io`
  once on the box.

## One-time setup

### 1. Install Docker

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian $(. /etc/os-release && echo $VERSION_CODENAME) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

Add yourself to the `docker` group, then log out and back in so it takes effect:

```bash
sudo usermod -aG docker $USER
```

### 2. Clone the project

```bash
sudo mkdir -p /srv/chess-shootout
sudo chown "$USER:$USER" /srv/chess-shootout
git clone https://github.com/xiaomyung/chess-shootout.git /srv/chess-shootout
cd /srv/chess-shootout
```

### 3. Secrets

The Caddy container reads three PEM files from `./secrets/` (mounted as compose
secrets). Replace the two `origin` paths with your Cloudflare Origin Certificate and
key.

```bash
mkdir -p secrets
install -m 600 /path/to/origin.crt secrets/cf_origin_cert.pem
install -m 600 /path/to/origin.key secrets/cf_origin_key.pem
curl -fsSL https://developers.cloudflare.com/ssl/static/authenticated_origin_pull_ca.pem -o secrets/cf_aop_ca.pem
chmod 600 secrets/cf_aop_ca.pem
```

### 4. Config files

Create `.env` in the project dir — it selects which image runs:

```bash
echo "IMAGE_TAG=latest" > .env
```

Create `gameserver.env` — it is injected into the container:

```bash
cat > gameserver.env <<'EOF'
HOST=0.0.0.0
PORT=8000
LOG_LEVEL=INFO
MAX_ROOMS=100
EOF
```

`HOST=0.0.0.0` lets Caddy reach the app over the compose network. Do not set
`LOG_FILE` (logs go to stdout). `TRUSTED_PROXIES` is set in `docker-compose.yml`, not
here. Optional tunables you can add to `gameserver.env`: `GRACE_SECONDS=60`,
`HEARTBEAT_INTERVAL_SECONDS=2`, `HEARTBEAT_MISS_LIMIT=3`.

### 5. Firewall: only Cloudflare may reach the origin

Docker's published ports **bypass UFW**, and Docker **recreates the `DOCKER-USER`
chain on every boot and daemon restart** — so the Cloudflare-only rules can't live in
`ufw` or `netfilter-persistent` (Docker would wipe them). A small systemd unit
re-applies them after Docker.

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
reboots and Docker restarts. The container publishes IPv4; if you enable Docker IPv6
publishing, add matching `ip6tables` rules with Cloudflare's IPv6 ranges.

### 6. Start

```bash
docker compose --profile edge up -d
docker compose --profile edge ps
curl -s http://127.0.0.1:8000/healthz
```

`restart: unless-stopped` brings the stack back automatically after a reboot. For
systemd integration (so `systemctl stop` triggers the graceful client drain), you can
optionally install the bundled unit:

```bash
sudo cp deploy/gameserver-compose.service.example /etc/systemd/system/gameserver-compose.service
sudo systemctl daemon-reload
sudo systemctl enable --now gameserver-compose
```

### 7. (Optional) Authenticated Origin Pulls

The shipped Caddyfile uses the Origin Certificate only — a standard Full-strict setup.
The `DOCKER-USER` firewall already limits the origin to Cloudflare ranges. To add mTLS
on top (so the origin also *verifies* the client is Cloudflare), enable **SSL/TLS →
Origin Server → Authenticated Origin Pulls** (zone-level) in Cloudflare, then wrap the
Caddyfile's `tls` directive with a `client_auth` block:

```
tls /run/secrets/cf_origin_cert /run/secrets/cf_origin_key {
    client_auth {
        mode require_and_verify
        trust_pool file /run/secrets/cf_aop_ca
    }
}
```

Apply it with:

```bash
docker compose --profile edge restart caddy
```

Cloudflare's AOP CA has rotated before; if origin pulls fail zone-wide after enabling,
refresh `secrets/cf_aop_ca.pem` from Cloudflare and restart caddy.

## Updating

A version-bumped PR merging to master auto-publishes the new image to GHCR
(`docker.yml`). Update to the latest release with one command on the box:

```bash
cd /srv/chess-shootout
./deploy/update.sh
```

To pin a specific version, or to roll back, pass its release tag:

```bash
cd /srv/chess-shootout
./deploy/update.sh v2.1.5
```

The script pulls the matching CI-built (and trivy-scanned) image from GHCR, refreshes
the compose file / Caddyfile from git, recreates only `gameserver` (Caddy untouched)
with the graceful `server_shutdown` drain, and prints the running version. It falls
back to `sudo` automatically when your shell isn't in the `docker` group.

## Operations

Run these from `/srv/chess-shootout`.

Status:

```bash
docker compose --profile edge ps
```

Live logs:

```bash
docker compose --profile edge logs -f
```

Restart:

```bash
docker compose --profile edge restart
```

Stop:

```bash
docker compose --profile edge down
```

A clean stop, restart, or update lets the server broadcast `server_shutdown` to
connected clients; the compose `stop_grace_period` covers the 10 s drain.
