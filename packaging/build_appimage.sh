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

# The tool is downloaded and executed, so it is pinned to a release and checked
# against a recorded digest - never a rolling build, never an unverified binary.
APPIMAGETOOL_VERSION="1.9.1"
APPIMAGETOOL_SHA256="ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0"
APPIMAGETOOL_URL="https://github.com/AppImage/appimagetool/releases/download/${APPIMAGETOOL_VERSION}/appimagetool-x86_64.AppImage"
TOOL="$BUILD_ROOT/appimagetool-${APPIMAGETOOL_VERSION}-x86_64.AppImage"

tool_verified() {
    [ -f "$TOOL" ] && printf '%s  %s\n' "$APPIMAGETOOL_SHA256" "$TOOL" \
        | sha256sum --check --status
}

if ! tool_verified; then
    rm -f "$TOOL"
    curl -fsSL -o "$TOOL" "$APPIMAGETOOL_URL"
    if ! tool_verified; then
        echo "appimagetool $APPIMAGETOOL_VERSION failed checksum - refusing to run it" >&2
        rm -f "$TOOL"
        exit 1
    fi
fi
chmod +x "$TOOL"

# --appimage-extract-and-run avoids needing libfuse2 to run the tool itself.
ARCH=x86_64 "$TOOL" --appimage-extract-and-run "$APPDIR" "$BUILD_ROOT/ChessShootout-x86_64.AppImage"
echo "built $BUILD_ROOT/ChessShootout-x86_64.AppImage"
