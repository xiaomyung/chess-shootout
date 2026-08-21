"""Static architecture guards for the screen split (step 7 of the
screen-architecture refactor).

All AST-based, path-walked from chessshootout.__file__ (same pattern as the
transport-import guard in tests/online/test_server_transport.py and the
pygame/frontend guard in tests/infra/test_server_no_pygame.py, just walking
`chessshootout/frontend` instead of `chessshootout/server`+`backend`):

1. No chessshootout.frontend.screens.{menu,game,history,review} module imports
   a SIBLING screen module. screens.base is exempt (Nav/Screen are the shared
   contract every screen and the coordinator legitimately depend on).
2. online_coordinator.py imports nothing from chessshootout.frontend.screens
   except screens.base.
3. chessshootout.frontend has no import cycles at all (module-level, via the
   real import graph -- not just the screens subpackage).
4. input_router.py never references a game-specific identifier (board,
   right_menu, result_menu, skillcheck, focus_) -- it dispatches through the
   Screen contract only, never reaches into a screen's internals by name.
5. Every production `Nav(` construction site lives in a module that imports
   Nav from screens.base -- no ad-hoc Nav-like duck type can bypass
   assert_plain_payload. (A literal-payload-shape AST check was considered
   and rejected: OnlineCoordinator builds its payload as a `nav_payload = {...}`
   variable a few lines above the `Nav("game", nav_payload)` call, which is
   exactly the kind of legitimate pattern a "must be a dict literal at the
   call site" check would misflag. Runtime purity is already end-to-end
   tested in test_screens_skeleton.py.)
"""

import ast
import os
import re

import chessshootout

from tests.helpers import read_source_without_docstrings


PACKAGE_ROOT = os.path.dirname(os.path.abspath(chessshootout.__file__))
REPO_ROOT = os.path.dirname(PACKAGE_ROOT)
FRONTEND_ROOT = os.path.join(PACKAGE_ROOT, "frontend")
SCREENS_ROOT = os.path.join(FRONTEND_ROOT, "screens")


def _iter_py_files(root):
    for dirpath, _, filenames in os.walk(root):
        if "__pycache__" in dirpath:
            continue
        for name in sorted(filenames):
            if name.endswith(".py"):
                yield os.path.join(dirpath, name)


def _discover_concrete_screens():
    """Read the screen list off disk, not off a literal: a hardcoded set means a
    fifth screen silently opts out of every guard below."""
    return {os.path.basename(path)[:-3] for path in _iter_py_files(SCREENS_ROOT)
            if os.path.basename(path)[:-3] not in ("__init__", "base")}


CONCRETE_SCREENS = _discover_concrete_screens()


def _module_name(path):
    rel = os.path.relpath(path, os.path.dirname(PACKAGE_ROOT))
    dotted = rel[:-3].replace(os.sep, ".")
    if dotted.endswith(".__init__"):
        dotted = dotted[:-len(".__init__")]
    return dotted


def _parse(path):
    with open(path, encoding="utf-8") as f:
        return ast.parse(f.read(), filename=path)


def _import_targets(tree):
    """Dotted module strings named by every `import X` / `from X import Y`
    (level-0 only) statement in tree. For ImportFrom this is node.module
    itself -- exactly the real submodule/package path when the statement
    names a concrete file (`from a.b.c import D`), or the enclosing package
    when it names a symbol re-exported from an __init__ (`from a.b import D`).
    Relative (`from . import X`) imports are skipped -- no caller needs them."""
    targets = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                targets.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                continue
            if node.module:
                targets.add(node.module)
    return targets


def test_no_screen_module_imports_a_sibling_screen_module():
    files = [p for p in _iter_py_files(SCREENS_ROOT) if not p.endswith("__init__.py")]
    assert len(files) >= 4, f"only found {len(files)} screen files, guard root is likely wrong"
    offenders = []
    for path in files:
        stem = os.path.splitext(os.path.basename(path))[0]
        if stem not in CONCRETE_SCREENS:
            continue
        targets = _import_targets(_parse(path))
        for module in targets:
            if not module.startswith("chessshootout.frontend.screens."):
                continue
            sibling = module[len("chessshootout.frontend.screens."):].split(".")[0]
            if sibling in CONCRETE_SCREENS and sibling != stem:
                offenders.append(f"{stem}.py imports {module}")
    assert offenders == [], f"screens must not import sibling screens: {offenders}"


def test_online_coordinator_only_imports_screens_base():
    path = os.path.join(FRONTEND_ROOT, "online_coordinator.py")
    assert os.path.isfile(path), f"expected {path} to exist"
    targets = _import_targets(_parse(path))
    offenders = [
        m for m in targets
        if m.startswith("chessshootout.frontend.screens")
        and m != "chessshootout.frontend.screens.base"
    ]
    assert offenders == [], (
        f"online_coordinator.py may only import chessshootout.frontend.screens.base "
        f"(Nav is legitimately shared): {offenders}"
    )


def _resolve(module_dotted, level, target):
    if level == 0:
        return target
    parts = module_dotted.split(".")
    base = parts[:-level]
    if target:
        base = base + [target]
    return ".".join(base)


def _build_frontend_import_graph(files):
    nodes = {_module_name(p) for p in files}
    graph = {node: set() for node in nodes}
    for path in files:
        source_module = _module_name(path)
        tree = _parse(path)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in nodes:
                        graph[source_module].add(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.level and node.level > 0:
                    resolved = _resolve(source_module, node.level, node.module)
                else:
                    resolved = node.module
                if resolved in nodes:
                    graph[source_module].add(resolved)
    return graph


def _find_cycle(graph):
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {node: WHITE for node in graph}
    stack = []

    def visit(node):
        color[node] = GRAY
        stack.append(node)
        for neighbor in graph[node]:
            if color[neighbor] == GRAY:
                start = stack.index(neighbor)
                return stack[start:] + [neighbor]
            if color[neighbor] == WHITE:
                found = visit(neighbor)
                if found is not None:
                    return found
        stack.pop()
        color[node] = BLACK
        return None

    for node in sorted(graph):
        if color[node] == WHITE:
            found = visit(node)
            if found is not None:
                return found
    return None


def test_chessshootout_frontend_has_no_import_cycles():
    files = list(_iter_py_files(FRONTEND_ROOT))
    assert len(files) >= 25, f"only scanned {len(files)} frontend files, guard root is likely wrong"
    graph = _build_frontend_import_graph(files)
    cycle = _find_cycle(graph)
    assert cycle is None, f"import cycle detected: {' -> '.join(cycle)}"


INPUT_ROUTER_FORBIDDEN_TOKENS = ("board", "right_menu", "result_menu", "skillcheck", "focus_")


def _forbidden_token_pattern(token):
    """Identifier-boundary match, not a bare substring: `keyboard` must not read as
    `board`. Only letters and digits block a match -- underscores deliberately do
    not, so `board_rect`, `self.board` and `right_menu` still count as reaching
    into a screen's internals. A token spelled with a trailing underscore
    (`focus_`) stays a prefix match, since that is how the family is named."""
    tail = "" if token.endswith("_") else r"(?![A-Za-z0-9])"
    return re.compile(r"(?<![A-Za-z0-9])" + re.escape(token) + tail)


def test_input_router_has_no_game_specific_identifiers():
    path = os.path.join(FRONTEND_ROOT, "input_router.py")
    assert os.path.isfile(path), f"expected {path} to exist"
    source = read_source_without_docstrings(path)
    offenders = []
    for token in INPUT_ROUTER_FORBIDDEN_TOKENS:
        match = _forbidden_token_pattern(token).search(source)
        if match is not None:
            line_no = source.count("\n", 0, match.start()) + 1
            offenders.append(f"{token} (line {line_no})")
    assert offenders == [], (
        f"input_router.py must dispatch through the Screen contract only, "
        f"never reach into a screen's internals by name: found {offenders}"
    )


def test_every_nav_construction_site_imports_nav_from_screens_base():
    offenders = []
    scanned = 0
    for path in _iter_py_files(PACKAGE_ROOT):
        if "tests" in path.split(os.sep):
            continue
        scanned += 1
        with open(path, encoding="utf-8") as f:
            source = f.read()
        tree = ast.parse(source, filename=path)
        calls_nav = any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "Nav"
            for node in ast.walk(tree)
        )
        if not calls_nav:
            continue
        imports_canonical_nav = any(
            isinstance(node, ast.ImportFrom)
            and node.module == "chessshootout.frontend.screens.base"
            and any(alias.name == "Nav" for alias in node.names)
            for node in ast.walk(tree)
        )
        if not imports_canonical_nav:
            offenders.append(os.path.relpath(path, REPO_ROOT))
    assert scanned > 50, f"only scanned {scanned} files, guard root is likely wrong"
    assert offenders == [], (
        f"every Nav(...) construction site must import the canonical Nav from "
        f"screens.base -- no ad-hoc Nav-like duck types: {offenders}"
    )
