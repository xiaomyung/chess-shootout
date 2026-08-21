"""Static architecture guards for the menu sub-view split (v2.9.0 shell).

Mirrors the screen guards in test_screen_guards.py, one directory down:

1. No concrete menu view module (play_view/history_host/options_view/profile_view/stubs)
   imports a SIBLING view module -- views never reach across to each other. The shared MenuView
   base lives in menu/view.py (a leaf), which every view legitimately imports.
2. menu/shell.py::build_views is the SINGLE registration point: shell is the only
   frontend module that imports the concrete view modules. MenuScreen therefore
   cannot depend on a concrete view -- it routes purely by name through the dict
   build_views hands it.
3. MenuScreen (screens/menu.py) builds its views via build_views and never imports
   a concrete view module.
"""

import ast
import os

import chessshootout


PACKAGE_ROOT = os.path.dirname(os.path.abspath(chessshootout.__file__))
FRONTEND_ROOT = os.path.join(PACKAGE_ROOT, "frontend")
MENU_ROOT = os.path.join(FRONTEND_ROOT, "menu")
MENU_SCREEN = os.path.join(FRONTEND_ROOT, "screens", "menu.py")

VIEW_MODULES = ("play_view", "history_host", "options_view", "profile_view", "stubs")


def _view_module(name):
    return "chessshootout.frontend.menu." + name


def _parse(path):
    with open(path, encoding="utf-8") as f:
        return ast.parse(f.read(), filename=path)


def _import_targets(tree):
    targets = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                targets.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if not (node.level and node.level > 0) and node.module:
                targets.add(node.module)
    return targets


def _iter_py_files(root):
    for dirpath, _, filenames in os.walk(root):
        if "__pycache__" in dirpath:
            continue
        for name in sorted(filenames):
            if name.endswith(".py"):
                yield os.path.join(dirpath, name)


def test_no_view_module_imports_a_sibling_view_module():
    offenders = []
    for module in VIEW_MODULES:
        path = os.path.join(MENU_ROOT, module + ".py")
        assert os.path.isfile(path), f"expected {path} to exist"
        targets = _import_targets(_parse(path))
        for sibling in VIEW_MODULES:
            if sibling != module and _view_module(sibling) in targets:
                offenders.append(f"{module}.py imports {sibling}")
    assert offenders == [], f"menu views must not import sibling views: {offenders}"


def test_shell_is_the_single_registration_point_for_the_view_modules():
    shell_targets = _import_targets(_parse(os.path.join(MENU_ROOT, "shell.py")))
    for module in VIEW_MODULES:
        assert _view_module(module) in shell_targets, f"shell must register {module}"

    offenders = []
    scanned = 0
    for path in _iter_py_files(FRONTEND_ROOT):
        if os.path.basename(path) == "shell.py":
            continue
        scanned += 1
        targets = _import_targets(_parse(path))
        for module in VIEW_MODULES:
            if _view_module(module) in targets:
                offenders.append(f"{os.path.relpath(path, PACKAGE_ROOT)} imports {module}")
    assert scanned > 25, f"only scanned {scanned} frontend files, guard root is likely wrong"
    assert offenders == [], (
        f"only menu/shell.py (build_views) may import the concrete view modules: {offenders}")


def test_menuscreen_builds_views_and_routes_by_name():
    with open(MENU_SCREEN, encoding="utf-8") as f:
        source = f.read()
    assert "build_views" in source, "MenuScreen must build its views via build_views"
    targets = _import_targets(ast.parse(source, filename=MENU_SCREEN))
    offenders = [m for m in VIEW_MODULES if _view_module(m) in targets]
    assert offenders == [], (
        f"MenuScreen must route by name, never import a concrete view module: {offenders}")
