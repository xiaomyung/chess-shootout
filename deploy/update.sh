#!/usr/bin/env bash
# Update the running server and restart it.
#   ./deploy/update.sh            # update to the latest release
#   ./deploy/update.sh v2.1.5     # or roll to a specific release tag
#
# Pulls the CI-built image from GHCR and recreates the gameserver container;
# refreshes the compose file from git. A failed pull aborts - the deploy never
# falls back to building from local sources. Falls back to sudo automatically
# when the shell is not in the docker group. Reports the installed version
# before and after, and appends a UTC-timestamped record to deploy/update.log.
set -euo pipefail

HEALTH_URL="http://127.0.0.1:8000/healthz"
LOG_FILE="deploy/update.log"

dc="docker"

now_utc() { date -u '+%Y-%m-%d %H:%M:%S UTC'; }

health_version() {
  curl -fsS "$HEALTH_URL" 2>/dev/null \
    | sed -n 's/.*"app_version":"\([^"]*\)".*/\1/p' || true
}

running_image_id() {
  local cid
  cid="$($dc compose ps -q gameserver 2>/dev/null || true)"
  [ -n "$cid" ] || return 0
  $dc inspect --format '{{.Image}}' "$cid" 2>/dev/null \
    | sed 's/^sha256://' | cut -c1-12 || true
}

main() {
  local ref="${1:-}" tag
  cd "$(dirname "$0")/.."

  docker info >/dev/null 2>&1 || dc="sudo docker"

  local old_ver old_digest
  old_ver="$(health_version)"; : "${old_ver:=unknown}"
  old_digest="$(running_image_id)"; : "${old_digest:=none}"

  git fetch --tags --prune origin
  if [ -n "$ref" ]; then
    git checkout --quiet "$ref" 2>/dev/null || git checkout --quiet "v${ref#v}"
    tag="${ref#v}"
  else
    git checkout --quiet master
    git pull --ff-only origin master
    tag="latest"
  fi

  local old_tag=""
  if grep -q '^IMAGE_TAG=' .env 2>/dev/null; then
    old_tag="$(sed -n 's/^IMAGE_TAG=//p' .env | head -1)"
    sed -i "s/^IMAGE_TAG=.*/IMAGE_TAG=${tag}/" .env
  else
    printf 'IMAGE_TAG=%s\n' "$tag" >> .env
  fi

  # A failed pull must abort: `up` would otherwise fall back to the compose
  # file's `build:` and put an unreviewed local build into production. Roll
  # IMAGE_TAG back so a later bare `docker compose up` can't do it either.
  if ! $dc compose pull gameserver; then
    if [ -n "$old_tag" ]; then
      sed -i "s/^IMAGE_TAG=.*/IMAGE_TAG=${old_tag}/" .env
    fi
    local failure="pull of ${tag} failed - aborted, still running ${old_ver}@${old_digest}"
    printf '>> %s\n' "$failure" >&2
    printf '%s | %-5s | %s\n' "$(now_utc)" "fail" "$failure" >> "$LOG_FILE"
    exit 1
  fi
  $dc compose up -d --no-build

  sleep 3
  local health new_ver new_digest
  if curl -fsS "$HEALTH_URL" >/dev/null 2>&1; then
    health="ok"
  else
    health="unreachable"
  fi
  new_ver="$(health_version)"; : "${new_ver:=unknown}"
  new_digest="$(running_image_id)"; : "${new_digest:=none}"

  local outcome="ok"
  [ "$health" = "ok" ] || outcome="check"

  local summary
  summary="was ${old_ver}@${old_digest} -> now ${new_ver}@${new_digest}"
  summary="${summary} (tag=${tag} health=${health})"
  printf '>> %s\n' "$summary"
  printf '%s | %-5s | %s\n' "$(now_utc)" "$outcome" "$summary" >> "$LOG_FILE"
}

main "$@"
