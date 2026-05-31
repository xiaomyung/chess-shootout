# PyInstaller build for the Chess Shootout client.
#
#   onedir build (current OS):   pyinstaller chess.spec
#   portable Windows onefile:    pyinstaller --onefile --windowed --noupx \
#                                  --name ChessShootout --icon assets/icons/icon.ico \
#                                  --add-data "assets;assets" \
#                                  --collect-data certifi --hidden-import certifi \
#                                  --exclude-module fastapi --exclude-module uvicorn \
#                                  --exclude-module starlette --exclude-module slowapi main.py
#
# Only the web stack is excluded; server.protocol (pydantic-only) stays, since the
# client imports it. macOS wraps the COLLECT output into ChessShootout.app via BUNDLE.
import os
import sys

from PyInstaller.utils.hooks import collect_data_files

CHESS_VERSION = os.environ.get("CHESS_VERSION", "0.0.0")

a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=[],
    datas=[("assets", "assets"), *collect_data_files("certifi")],
    hiddenimports=["certifi", "pygame._sdl2", "pygame._sdl2.video"],
    excludes=["fastapi", "uvicorn", "starlette", "slowapi"],
    noarchive=False,
)
# SVG sources (assets/pieces_svg) are build-time only; ship the rendered PNGs, not the sources.
a.datas = [entry for entry in a.datas if not entry[0].lower().endswith(".svg")]

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
