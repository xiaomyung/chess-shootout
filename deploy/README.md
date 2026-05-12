# Deployment

Single-VPS deployment: the chess server listens directly on a public TCP
port. Players connect by entering the VPS IP into the game's start menu —
no TLS, no DNS, no reverse proxy.

Tested end-to-end on Hetzner CX22 / Debian 13 (Trixie). Everything should
work the same on Debian 12 (Bookworm). All commands run as a sudoer user
(e.g. `apollo`).

## One-time setup

### 1. apt deps + `chess` user

```bash
sudo apt update
sudo apt install -y git curl ufw \
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
HOST=0.0.0.0
PORT=8000
LOG_LEVEL=INFO
LOG_FILE=/var/log/chess-server.log
MAX_ROOMS=100
EOF

sudo touch /var/log/chess-server.log
sudo chown chess:chess /var/log/chess-server.log
sudo systemctl daemon-reload
```

`HOST=0.0.0.0` binds the server to every interface — required for
clients on other machines to reach it. (Use `127.0.0.1` if you're
fronting it with your own reverse proxy.)

### 5. UFW: open SSH + the chess port

```bash
sudo ufw allow ssh
sudo ufw allow 8000/tcp
sudo ufw default deny incoming
sudo ufw enable
sudo ufw status verbose
```

If you change `PORT` in the env file, update the UFW rule to match.

### 6. Start the server + verify

```bash
sudo systemctl enable --now chess-server
sudo systemctl status chess-server --no-pager
```

Should show `active (running)`. Then from any other machine:

```bash
curl http://<vps-ip>:8000/healthz
# {"status":"ok","version":1,"rooms_active":0,"queue_depth":0,"uptime_s":...}
```

## Connecting from the game

In the game's start menu, open the **Server address** field and type
the VPS IP — for example `203.0.113.5`. The client auto-picks
`ws://203.0.113.5:8000` (any IP address, or any host on port 8000, gets
plaintext WS) and persists the address to your local `.env` as
`CHESS_SERVER_ADDR`.

That's it — match-make and play.

## Operations

| Action | Command |
|---|---|
| Start | `sudo systemctl start chess-server` |
| Stop | `sudo systemctl stop chess-server` |
| Restart (after env change) | `sudo systemctl restart chess-server` |
| Status | `sudo systemctl status chess-server` |
| Live logs | `sudo journalctl -u chess-server -f` |
| Last 200 lines | `sudo journalctl -u chess-server -n 200 --no-pager` |
| Live `LOG_FILE` | `sudo tail -f /var/log/chess-server.log` |

A clean `stop` / `restart` triggers the lifespan handler's
`server_shutdown` broadcast — connected clients see "Game cancelled /
server shutting down". Reconnects after a restart hit the
"Server restarted — game ended" modal (because `/resume` 4xx but
`/healthz` ok) and clicking **New Search** re-pairs immediately.

## Updating

```bash
sudo -u chess -- bash -c 'export HOME=/opt/chess && cd /opt/chess/repo && git pull && .venv/bin/pip install -e .'
sudo systemctl restart chess-server
```
