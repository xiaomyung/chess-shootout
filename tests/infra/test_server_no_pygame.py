"""The server image must stay pygame-free: nothing under server/, backend/ or
skillcheck/ may import pygame or reach back into the frontend package.

AST-based rather than a raw-text regex, so prose can never trip it and a
relative import (`from ..frontend import x`) can never slip past it -- the old
line-anchored pattern only recognised the absolute spellings.
"""

import ast
import os

import chessshootout

PACKAGE_ROOT = os.path.dirname(os.path.abspath(chessshootout.__file__))
REPO_ROOT = os.path.dirname(PACKAGE_ROOT)

FORBIDDEN_ROOTS = ("pygame", "chessshootout.frontend")


def _module_name(path):
    rel = os.path.relpath(path, REPO_ROOT)
    dotted = rel[:-3].replace(os.sep, ".")
    if dotted.endswith(".__init__"):
        dotted = dotted[:-len(".__init__")]
    return dotted


def _resolve(module_dotted, level, target):
    if level == 0:
        return target
    parts = module_dotted.split(".")
    base = parts[:-level]
    if target:
        base = base + [target]
    return ".".join(base)


def _is_forbidden(module):
    return any(module == root or module.startswith(root + ".") for root in FORBIDDEN_ROOTS)


def _forbidden_import_lines(path):
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=path)
    source_module = _module_name(path)
    lines = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(_is_forbidden(alias.name) for alias in node.names):
                lines.append(node.lineno)
        elif isinstance(node, ast.ImportFrom):
            resolved = _resolve(source_module, node.level or 0, node.module)
            if resolved and _is_forbidden(resolved):
                lines.append(node.lineno)
    return lines


def test_server_and_backend_never_import_pygame_or_frontend():
    offenders = []
    scanned = 0
    for pkg in ("server", "backend", "skillcheck"):
        pkg_dir = os.path.join(PACKAGE_ROOT, pkg)
        assert os.path.isdir(pkg_dir), f"expected a walkable package dir at {pkg_dir}"
        for root, _, files in os.walk(pkg_dir):
            for name in files:
                if not name.endswith(".py"):
                    continue
                path = os.path.join(root, name)
                scanned += 1
                rel = os.path.relpath(path, REPO_ROOT)
                offenders += [f"{rel}:{lineno}" for lineno in _forbidden_import_lines(path)]
    assert scanned > 25, f"only scanned {scanned} files, guard root is likely wrong"
    assert offenders == [], (
        f"server image must stay pygame-free (no pygame/frontend imports): {offenders}"
    )
