import argparse
import os

import uvicorn

from chessshootout.server import logging_setup
from chessshootout.server.app import create_app


def _main():
    parser = argparse.ArgumentParser(description="chess multiplayer server")
    parser.add_argument("--host", default=os.environ.get("HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    parser.add_argument("--reload", action="store_true",
                        help="dev: auto-restart on source change")
    parser.add_argument("--max-rooms", type=int,
                        default=int(os.environ.get("MAX_ROOMS", "100")))
    args = parser.parse_args()
    logging_setup.configure()
    if args.reload:
        os.environ.setdefault("CHESS_MAX_ROOMS", str(args.max_rooms))
        uvicorn.run("chessshootout.server.__main__:_app_factory", host=args.host, port=args.port,
                    reload=True, factory=True,
                    ws_ping_interval=None)
    else:
        app = create_app(max_rooms=args.max_rooms)
        uvicorn.run(app, host=args.host, port=args.port,
                    ws_ping_interval=None)


def _app_factory():
    return create_app(max_rooms=int(os.environ.get("CHESS_MAX_ROOMS", "100")))


if __name__ == "__main__":
    _main()
