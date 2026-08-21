"""The server image must stay pygame-free: nothing under server/, backend/ or
skillcheck/ may import pygame or reach back into the frontend package.

AST-based rather than a raw-text regex, so prose can never trip it and a
relative import (`from ..frontend import x`) can never slip past it -- the old
line-anchored pattern only recognised the absolute spellings.

Both halves of an `import ... from` are checked: the module it resolves to AND
each name pulled out of it, because `from chessshootout import frontend` and
`from .. import frontend` resolve to the harmless parent package and carry the
forbidden half in the alias. The probes at the bottom are the negative control
that keeps the guard honest.
"""

import ast
import os

import pytest

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


def _forbidden_lines_in_source(source, source_module, filename="<probe>"):
    tree = ast.parse(source, filename=filename)
    lines = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(_is_forbidden(alias.name) for alias in node.names):
                lines.append(node.lineno)
        elif isinstance(node, ast.ImportFrom):
            resolved = _resolve(source_module, node.level or 0, node.module)
            if not resolved:
                continue
            if _is_forbidden(resolved) or any(
                    _is_forbidden(f"{resolved}.{alias.name}") for alias in node.names):
                lines.append(node.lineno)
    return lines


def _forbidden_import_lines(path):
    with open(path, encoding="utf-8") as f:
        source = f.read()
    return _forbidden_lines_in_source(source, _module_name(path), filename=path)


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


@pytest.mark.parametrize("module, source", [
    pytest.param("chessshootout.server.app", "import pygame\n", id="plain_pygame"),
    pytest.param("chessshootout.server.app", "import pygame as pg\n", id="aliased_pygame"),
    pytest.param("chessshootout.server.app", "import chessshootout.frontend.layout\n",
                 id="dotted_frontend_module"),
    pytest.param("chessshootout.server.app", "from pygame import Surface\n", id="from_pygame"),
    pytest.param("chessshootout.server.app", "from chessshootout.frontend import layout\n",
                 id="from_frontend_package"),
    pytest.param("chessshootout.server.app", "from chessshootout import frontend\n",
                 id="frontend_as_an_imported_name"),
    pytest.param("chessshootout.server.app", "from .. import frontend\n",
                 id="relative_frontend_as_an_imported_name"),
    pytest.param("chessshootout.server.moderation.detector", "from ... import frontend\n",
                 id="relative_from_a_nested_module"),
])
def test_guard_catches_every_spelling_of_a_forbidden_import(module, source):
    """The negative control. The `... import frontend` spellings are why the alias
    half exists: they resolve to `chessshootout` (harmless on its own) and hide the
    forbidden half in the imported NAME, so a module-only check waves them through
    -- which is exactly what this guard used to do."""
    assert _forbidden_lines_in_source(source, module) == [1]


@pytest.mark.parametrize("module, source", [
    pytest.param("chessshootout.server.app", "from chessshootout.backend import backend\n",
                 id="sibling_package"),
    pytest.param("chessshootout.server.app", "from . import rooms\n", id="relative_sibling"),
    pytest.param("chessshootout.server.app", "from .. import server\n",
                 id="relative_sibling_of_the_parent"),
    pytest.param("chessshootout.server.app", "import chessshootout.skillcheck.wheel\n",
                 id="dotted_sibling_module"),
    pytest.param("chessshootout.server.app", "frontend = 1\nfrom chessshootout import paths\n",
                 id="frontend_as_a_local_name"),
])
def test_guard_leaves_the_legitimate_imports_alone(module, source):
    """The other half of the control: broadening the alias check must not start
    flagging the imports the server actually makes, nor a bare name that merely
    happens to read like the forbidden package."""
    assert _forbidden_lines_in_source(source, module) == []
