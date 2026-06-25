#!/usr/bin/env bash
# Update the running server and restart it.
#   ./deploy/update.sh            # update to the latest release
#   ./deploy/update.sh v2.1.5     # or roll to a specific release tag
#
# Pulls the CI-built, scanned image from GHCR and recreates the gameserver
# container; refreshes the compose file / Caddyfile from git. Falls back to sudo
# automatically when the shell is not in the docker group.
set -euo pipefail

main() {
  local ref="${1:-}" tag
  cd "$(dirname "$0")/.."

  local dc="docker"
  docker info >/dev/null 2>&1 || dc="sudo docker"

  git fetch --tags --prune origin
  if [ -n "$ref" ]; then
    git checkout --quiet "$ref" 2>/dev/null || git checkout --quiet "v${ref#v}"
    tag="${ref#v}"
  else
    git checkout --quiet master
    git pull --ff-only origin master
    tag="latest"
  fi

  if grep -q '^IMAGE_TAG=' .env 2>/dev/null; then
    sed -i "s/^IMAGE_TAG=.*/IMAGE_TAG=${tag}/" .env
  else
    printf 'IMAGE_TAG=%s\n' "$tag" >> .env
  fi

  $dc compose pull gameserver
  $dc compose --profile edge up -d

  sleep 3
  printf '>> health: '
  curl -fsS http://127.0.0.1:8000/healthz || printf '(starting...)'
  printf '\n>> now running: %s\n' "$tag"
}

main "$@"
