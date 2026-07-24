# Deploying the server (containerized)

The server runs as a single hardened `gameserver` container (uvicorn) managed by
`docker compose`. TLS termination and the public `:80/:443` surface live in a
**standalone edge proxy stack** (Caddy) that ships from its own private repo and runs
separately on the VPS. This repo's compose file joins that stack's external `edge`
docker network under the alias `chess-gameserver`, and the edge proxy reverse-proxies
to it.

```
Player ──wss:443──▶ Cloudflare (orange cloud, Full strict)
                         ▼
        edge proxy stack (Caddy, separate repo)  :80/:443, terminates TLS
                         │  reverse_proxy chess-gameserver:8000  (external `edge` network)
                         ▼
        gameserver container  (uvicorn; 127.0.0.1:8000 published for the healthcheck)
```

The server is **stateless** (in-memory rooms, no DB) — a restart loses in-flight
games. TLS, the Cloudflare origin certificate, and the "only Cloudflare reaches the
origin" firewall are all owned by the edge stack and documented in its own repo — none
of that lives here anymore. This repo ships only the gameserver; the `127.0.0.1:8000`
publish is for the local healthcheck only.

## Prerequisites

- A Debian VPS with Docker installed, running the standalone **edge proxy stack**. That
  stack creates and owns the external `edge` docker network (bridge) and terminates TLS
  in front of this container; deploy it first.
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

### 3. Config files

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

`HOST=0.0.0.0` lets the edge proxy reach the app over the shared `edge` network. Do not
set `LOG_FILE` (logs go to stdout). `TRUSTED_PROXIES` is set in `docker-compose.yml`
(the edge proxy's IP on the `edge` network), not here. Optional tunables you can add to
`gameserver.env`: `GRACE_SECONDS=60`, `HEARTBEAT_INTERVAL_SECONDS=2`,
`HEARTBEAT_MISS_LIMIT=3`.

### 4. Start

The external `edge` network must already exist (created by the edge proxy stack). Then:

```bash
docker compose up -d
docker compose ps
curl -s http://127.0.0.1:8000/healthz
```

The compose file attaches the container to the external `edge` network with the alias
`chess-gameserver`, which is how the proxy reaches it. `restart: unless-stopped` brings
the container back automatically after a reboot. For systemd integration (so
`systemctl stop` triggers the graceful client drain), you can optionally install the
bundled unit:

```bash
sudo cp deploy/gameserver-compose.service.example /etc/systemd/system/gameserver-compose.service
sudo systemctl daemon-reload
sudo systemctl enable --now gameserver-compose
```

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
the compose file from git, recreates the `gameserver` container with the graceful
`server_shutdown` drain, and reports the installed version before and after
(`was <ver>@<digest> -> now <ver>@<digest>`, read from `/healthz`). Each run is appended
to `deploy/update.log` (UTC, gitignored). It falls back to `sudo` automatically when
your shell isn't in the `docker` group.

## Operations

Run these from `/srv/chess-shootout`.

Status:

```bash
docker compose ps
```

Live logs:

```bash
docker compose logs -f
```

Restart:

```bash
docker compose restart
```

Stop:

```bash
docker compose down
```

A clean stop, restart, or update lets the server broadcast `server_shutdown` to
connected clients; the compose `stop_grace_period` covers the 10 s drain.
