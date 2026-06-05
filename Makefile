.PHONY: build up up-edge down logs loadtest

# Build the server image via compose.
build:
	docker compose build

# Local app-only container (no TLS/Caddy), published on 127.0.0.1:8000.
up:
	docker compose up -d chess-server

# Full edge stack (needs ./secrets/*.pem + ./chess-server.env).
up-edge:
	docker compose --profile edge up -d

# Tear down the whole stack (keeps named volumes).
down:
	docker compose --profile edge down

logs:
	docker compose --profile edge logs -f

# Drive synthetic games at a local/throwaway server. Pass args via ARGS, e.g.
#   make loadtest ARGS="--addr localhost:8000 --rooms 200 --hold 60"
loadtest:
	.venv/bin/python tools/loadtest_server.py $(ARGS)
