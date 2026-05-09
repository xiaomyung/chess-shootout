# Deployment

Single-VPS deployment with Caddy + systemd. Local dev runs on `localhost:8000`
with no TLS; the VPS runs uvicorn behind Caddy on `:443` with auto-renewed
Let's Encrypt certs.

## Server VPS setup

```bash
# 1. System packages
sudo apt update
sudo apt install -y python3.12 python3.12-venv caddy git

# 2. App user + checkout
sudo useradd -r -m -d /opt/chess chess
sudo -u chess git clone https://github.com/xiaomyung/chess-pygame /opt/chess
cd /opt/chess
sudo -u chess python3.12 -m venv .venv
sudo -u chess .venv/bin/pip install -r requirements.txt

# 3. Server env
sudo cp deploy/chess-server.service.example /etc/systemd/system/chess-server.service
sudo tee /etc/chess-server.env > /dev/null <<EOF
HOST=127.0.0.1
PORT=8000
LOG_LEVEL=INFO
MAX_ROOMS=100
EOF

# 4. Caddy
sudo cp deploy/Caddyfile.example /etc/caddy/Caddyfile
sudo sed -i 's/chess.example.com/your-actual-domain.com/' /etc/caddy/Caddyfile

# 5. Start
sudo systemctl daemon-reload
sudo systemctl enable --now chess-server caddy

# 6. Verify
curl https://your-actual-domain.com/healthz
# {"status":"ok","rooms_active":0}
```

## Updating

```bash
cd /opt/chess
sudo -u chess git pull
sudo -u chess .venv/bin/pip install -r requirements.txt
sudo systemctl restart chess-server
```

The `chess-server.service` lifespan handler broadcasts a `server_shutdown`
result to all active rooms before exit, so connected clients see "Game
cancelled / server shutting down" instead of an abrupt drop.

## Client connection

Players set `CHESS_SERVER_ADDR=your-actual-domain.com` in their `.env`. The
client's scheme heuristic picks `wss://` for hostnames (anything that isn't
`localhost`/IP/port-8000), so TLS is automatic.

## Logs

`journalctl -u chess-server -f` tails the structured logs:

```
matchmake nickname=… uuid=… tc=…
ws auth ok room=… uuid=… …
game_start broadcast room=… sent_to=[…]
move applied room=… mover=… san=…
draw offered/accepted/declined/mutual room=…
takeback requested/accepted/declined room=…
rematch requested/accepted/declined/mutual room=…
abandonment / aborted / drop room=…
```

## Out of scope (v1)

- Docker / k8s
- Multi-instance scaling (in-memory rooms don't shard)
- Persistent game-history database
- Metrics scraping (Prometheus)
- Centralized log shipping
