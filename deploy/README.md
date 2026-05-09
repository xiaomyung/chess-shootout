# Deployment

Single-VPS deployment with Caddy + systemd. Local dev runs on
`localhost:8000` with no TLS; the VPS runs uvicorn behind Caddy on
`:443` with auto-renewed Let's Encrypt certs.

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
sudo -u chess .venv/bin/pip install -e .

# 3. Server env
sudo cp deploy/chess-server.service.example /etc/systemd/system/chess-server.service
sudo tee /etc/chess-server.env > /dev/null <<EOF
HOST=127.0.0.1
PORT=8000
LOG_LEVEL=INFO
LOG_FILE=/var/log/chess-server.log
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
# {"status":"ok","version":1,"rooms_active":0,"queue_depth":0,"uptime_s":4.12}
```

`LOG_FILE` is optional — when set, the server attaches a
`RotatingFileHandler` (5 MiB × 3 backups) to the root logger in
addition to journald. Drop the line to log only via `journalctl`.

## Updating

```bash
cd /opt/chess
sudo -u chess git pull
sudo -u chess .venv/bin/pip install -e .
sudo systemctl restart chess-server
```

The `chess-server.service` lifespan handler broadcasts a
`server_shutdown` result to all active rooms before exit, so connected
clients see "Game cancelled / server shutting down" instead of an
abrupt drop. Clients reconnecting after the restart hit the
"Server restarted — game ended" modal (because `/resume` 4xx-fatals but
`/healthz` is reachable) and can click **New Search** to immediately
re-pair.

## Client connection

Players set `CHESS_SERVER_ADDR=your-actual-domain.com` in their `.env`.
The client's scheme heuristic picks `wss://` for hostnames (anything
that isn't `localhost`/IP/port-8000), so TLS is automatic.

## Endpoints

| Path | Method | Purpose |
|---|---|---|
| `/` | GET | JSON manifest of available endpoints |
| `/healthz` | GET | `{status, version, rooms_active, queue_depth, uptime_s}` |
| `/matchmake` | POST | Enqueue / pair |
| `/matchmake` | DELETE | Cancel pre-pairing |
| `/resume` | POST | Re-establish session token after WS drop |
| `/reclaim` | POST | App-restart reconnect (uuid → fresh token) |
| `/ws/{room_id}` | WS | Auth handshake then game events |

`/reclaim` is rate-limited per-uuid (5/min sliding window) on top of
slowapi's 30/min/IP cap. Per-WS dispatch is rate-limited at 30 msg/sec
per session — exceeded messages get a `rate_limited` error reply.

## Logs

`journalctl -u chess-server -f` (or `tail -f $LOG_FILE` if set) shows
the structured key-value lines:

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

UUIDs are truncated to 8 chars in every log line.
