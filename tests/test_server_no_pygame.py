import os
import re

IMPORT_PATTERN = re.compile(
    r"^\s*(import\s+pygame|from\s+pygame|"
    r"import\s+chessshootout\.frontend|from\s+chessshootout\.frontend)",
    re.MULTILINE,
)


def test_server_and_backend_never_import_pygame_or_frontend():
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    offenders = []
    for pkg in ("server", "backend"):
        for root, _, files in os.walk(os.path.join(root_dir, "chessshootout", pkg)):
            for name in files:
                if not name.endswith(".py"):
                    continue
                path = os.path.join(root, name)
                with open(path, encoding="utf-8") as f:
                    if IMPORT_PATTERN.search(f.read()):
                        offenders.append(path)
    assert offenders == [], (
        f"server image must stay pygame-free (no pygame/frontend imports): {offenders}"
    )
