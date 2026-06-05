# Deploying the server

Single-VPS setup: the server listens directly on a public TCP port and
players connect by typing the VPS IP into the game's start menu — no TLS,
no DNS, no reverse proxy.

Verified end-to-end on Hetzner CX22 / Debian 13 (Trixie); Debian 12
(Bookworm) works the same. Run everything as a sudoer (e.g. `apollo`).

## One-time setup

### 1. Packages + `chess` user

```bash
sudo apt update
sudo apt install -y git curl ufw \
    build-essential libssl-dev zlib1g-dev libbz2-dev libreadline-dev \
    libsqlite3-dev libncursesw5-dev xz-utils tk-dev libffi-dev liblzma-dev

sudo useradd -r -m -d /opt/chess -s /bin/bash chess
```

The `build-essential … liblzma-dev` block is what pyenv needs to compile
Python from source.

<details>
<summary><strong>Debian 13 only</strong> — fix <code>binutils</code> permissions first</summary>

`binutils-x86-64-linux-gnu` ships its assembler / linker / strip binaries as
mode `0750`/`0754` on Debian 13, so the `chess` user can't execute them and
the pyenv build later fails with `cannot execute 'as': Permission denied`.
Reinstalling the package does **not** help — the `.deb` itself carries these
perms. Fix once:

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

# smoke test
echo 'int main(void){return 0;}' > /tmp/h.c && gcc /tmp/h.c -o /tmp/h && echo OK || echo FAIL
rm -f /tmp/h /tmp/h.c
```

</details>

### 2. Python 3.12 via pyenv (as `chess`)

`pyproject.toml` pins `>=3.12,<3.13`; Debian 12 tops out at 3.11 and Debian 13
ships 3.13, so pyenv builds a private 3.12 for the `chess` user without
touching system Python.

Both blocks set `HOME=/opt/chess` explicitly because `sudo -H` is not honoured
uniformly across Debian sudoers configs — Hetzner's default image leaks the
invoking user's HOME into the chess shell, which pyenv then can't `cd` into.

```bash
# install pyenv into /opt/chess/.pyenv
sudo -u chess -- bash -c '
    export HOME=/opt/chess
    cd $HOME
    curl -fsSL https://pyenv.run | bash
'

# wire pyenv into chess's .bashrc for future interactive sessions
sudo -u chess -- tee -a /opt/chess/.bashrc > /dev/null <<'EOF'

export PYENV_ROOT="$HOME/.pyenv"
[[ -d $PYENV_ROOT/bin ]] && export PATH="$PYENV_ROOT/bin:$PATH"
eval "$(pyenv init - bash)"
EOF

# build 3.12 (~2 min first time). PYENV_ROOT/PATH are set inline because
# non-interactive sudo shells don't source .bashrc.
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
# expect: Python 3.12.x
```

### 3. Clone + install

```bash
sudo -u chess -- bash -c '
    export HOME=/opt/chess
    cd $HOME
    export PYENV_ROOT="$HOME/.pyenv"
    export PATH="$PYENV_ROOT/bin:$PATH"
    eval "$(pyenv init - bash)"
    git clone https://github.com/xiaomyung/chess-shootout /opt/chess/repo
    cd /opt/chess/repo
    python -m venv .venv
    .venv/bin/pip install -U pip
    .venv/bin/pip install -e ".[server]"
'
```

The repo lives at `/opt/chess/repo`, not `/opt/chess` directly — the home dir
has skel files and `git clone` would refuse it.

### 4. systemd unit + env file

```bash
sudo cp /opt/chess/repo/deploy/chess-server.service.example /etc/systemd/system/chess-server.service

sudo tee /etc/chess-server.env > /dev/null <<'EOF'
HOST=0.0.0.0
PORT=8000
LOG_LEVEL=INFO
LOG_FILE=/var/log/chess-server.log
MAX_ROOMS=100
# Online-lifecycle tuning (optional; defaults shown):
# GRACE_SECONDS=60                # reconnect window before a drop is resolved
# HEARTBEAT_INTERVAL_SECONDS=2    # how often a client pings while in a game
# HEARTBEAT_MISS_LIMIT=3          # missed pings before a player is marked gone
EOF

sudo touch /var/log/chess-server.log
sudo chown chess:chess /var/log/chess-server.log
sudo systemctl daemon-reload
```

`HOST=0.0.0.0` binds every interface — required for clients on other machines
to reach it. (Use `127.0.0.1` only if you front it with your own reverse proxy.)

### 5. Firewall (UFW)

```bash
sudo ufw allow ssh
sudo ufw allow 8000/tcp
sudo ufw default deny incoming
sudo ufw enable
sudo ufw status verbose
```

Change the `8000/tcp` rule to match if you change `PORT`.

### 6. Start + verify

```bash
sudo systemctl enable --now chess-server
sudo systemctl status chess-server --no-pager     # expect: active (running)
```

Then from any other machine:

```bash
curl http://<vps-ip>:8000/healthz
# {"status":"ok","version":1,"rooms_active":0,"queue_depth":0,"uptime_s":...}
```

## Connecting from the game

In the start menu's **Server address** field, two forms are accepted:

- `<ip>` — uses the default port 8000 (e.g. `203.0.113.5`).
- `<ip>:<port>` — uses the typed port (e.g. `203.0.113.5:9999`).

The client picks plaintext WebSocket (`ws://…`) automatically for any IP and
persists what you typed to your local `.env` as `CHESS_SERVER_ADDR`. If you
change the server's `PORT`, players must include the matching `:<port>` (and
you must open it in UFW — step 5).

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

A clean `stop` / `restart` fires the lifespan handler's `server_shutdown`
broadcast — connected clients see "Game cancelled / server shutting down".
Reconnects after a restart hit the "Server restarted — game ended" modal
(`/resume` 4xx but `/healthz` ok); clicking **New Search** re-pairs immediately.

## Updating

```bash
sudo -u chess -- bash -c 'export HOME=/opt/chess && cd /opt/chess/repo && git pull && .venv/bin/pip install -e ".[server]"'
sudo systemctl restart chess-server
```
