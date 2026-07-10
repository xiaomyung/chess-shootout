import os
import re

import chessshootout

IMPORT_PATTERN = re.compile(
    r"^\s*(import\s+pygame|from\s+pygame|"
    r"import\s+chessshootout\.frontend|from\s+chessshootout\.frontend)",
    re.MULTILINE,
)


def test_server_and_backend_never_import_pygame_or_frontend():
    package_root = os.path.dirname(os.path.abspath(chessshootout.__file__))
    offenders = []
    scanned = 0
    for pkg in ("server", "backend"):
        pkg_dir = os.path.join(package_root, pkg)
        assert os.path.isdir(pkg_dir), f"expected a walkable package dir at {pkg_dir}"
        for root, _, files in os.walk(pkg_dir):
            for name in files:
                if not name.endswith(".py"):
                    continue
                path = os.path.join(root, name)
                scanned += 1
                with open(path, encoding="utf-8") as f:
                    if IMPORT_PATTERN.search(f.read()):
                        offenders.append(path)
    assert scanned > 10, f"only scanned {scanned} files, guard root is likely wrong"
    assert offenders == [], (
        f"server image must stay pygame-free (no pygame/frontend imports): {offenders}"
    )
