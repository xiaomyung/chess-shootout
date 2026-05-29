# PyInstaller build for the Chess Shootout client.
#
#   onedir build (current OS):   pyinstaller chess.spec
#   portable Windows onefile:    pyinstaller --onefile --windowed --noupx \
#                                  --name ChessShootout --icon assets/icons/icon.ico \
#                                  --add-data "assets;assets" \
#                                  --exclude-module fastapi --exclude-module uvicorn \
#                                  --exclude-module starlette --exclude-module slowapi main.py
#
# Only the web stack is excluded; server.protocol (pydantic-only) stays, since the
# client imports it. macOS wraps the COLLECT output into ChessShootout.app via BUNDLE.
import os
import sys

CHESS_VERSION = os.environ.get("CHESS_VERSION", "0.0.0")

a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=[],
    datas=[("assets", "assets")],
    hiddenimports=[],
    excludes=["fastapi", "uvicorn", "starlette", "slowapi"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ChessShootout",
    console=False,
    upx=False,
    icon="assets/icons/icon.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    upx=False,
    name="ChessShootout",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="ChessShootout.app",
        icon="assets/icons/icon.icns",
        bundle_identifier="dev.xiaomyung.chess-shootout",
        version=CHESS_VERSION,
        info_plist={
            "CFBundleShortVersionString": CHESS_VERSION,
            "CFBundleVersion": CHESS_VERSION,
        },
    )
