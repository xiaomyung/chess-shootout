#!/usr/bin/env bash
# One-command local build. Everything lands under local_build/ (gitignored):
#   local_build/dist/ChessShootout/ChessShootout     the onedir binary
#   local_build/ChessShootout-x86_64.AppImage        the AppImage
# Run from anywhere: packaging/build_local.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
OUT="$ROOT/local_build"

PYINSTALLER="$ROOT/.venv/bin/pyinstaller"
[ -x "$PYINSTALLER" ] || PYINSTALLER="pyinstaller"

rm -rf "$OUT"
mkdir -p "$OUT"
"$PYINSTALLER" --noconfirm \
    --distpath "$OUT/dist" --workpath "$OUT/build" \
    chess.spec
BUILD_ROOT="$OUT" DIST_DIR="$OUT/dist/ChessShootout" "$ROOT/packaging/build_appimage.sh"

echo
echo "local build complete under $OUT"
echo "  binary:   $OUT/dist/ChessShootout/ChessShootout"
echo "  appimage: $OUT/ChessShootout-x86_64.AppImage"
