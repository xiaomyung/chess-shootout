#!/usr/bin/env bash
# Assemble an AppImage from a PyInstaller onedir build.
#   DIST_DIR    PyInstaller onedir output     (default: dist/ChessShootout)
#   BUILD_ROOT  where AppDir + appimagetool + the .AppImage go (default: repo root)
# CI uses the defaults; build_local.sh points both at local_build/.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
DIST_DIR="${DIST_DIR:-dist/ChessShootout}"
BUILD_ROOT="${BUILD_ROOT:-$ROOT}"

if [ ! -d "$DIST_DIR" ]; then
    echo "$DIST_DIR not found - run pyinstaller first" >&2
    exit 1
fi

APPDIR="$BUILD_ROOT/AppDir"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin"
cp -r "$DIST_DIR/." "$APPDIR/usr/bin/"
cp packaging/AppRun "$APPDIR/AppRun"
chmod +x "$APPDIR/AppRun"
cp packaging/chess.desktop "$APPDIR/chess-shootout.desktop"
cp assets/icons/icon.png "$APPDIR/chess-shootout.png"

TOOL="$BUILD_ROOT/appimagetool-x86_64.AppImage"
if [ ! -x "$TOOL" ]; then
    curl -fsSL -o "$TOOL" \
        https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage
    chmod +x "$TOOL"
fi

# --appimage-extract-and-run avoids needing libfuse2 to run the tool itself.
ARCH=x86_64 "$TOOL" --appimage-extract-and-run "$APPDIR" "$BUILD_ROOT/ChessShootout-x86_64.AppImage"
echo "built $BUILD_ROOT/ChessShootout-x86_64.AppImage"
