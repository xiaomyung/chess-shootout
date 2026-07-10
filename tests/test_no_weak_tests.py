"""Guard against tests that cannot fail.

Statically scans every tests/test_*.py and flags a test function as weak when
it exercises no real behavior: no non-trivial assertion, no pytest.raises/warns,
and no call to an assertion helper (named assert_* / expect_*, or a known helper
such as play_moves). Tests whose only assertion is `assert True`, `assert <lit>`,
or `assert X == X` count as weak. Every test must exercise real behavior — there
is no allowlist; strengthen a flagged test rather than grandfathering it.
"""

import ast
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SKIP_FILES = {
    "__init__.py", "conftest.py", "helpers.py", "test_no_weak_tests.py",
}
KNOWN_ASSERTION_HELPERS = {"play_moves", "play_sans", "assert_moves_legal"}
ASSERTION_HELPER_PREFIXES = ("assert", "expect", "verify", "check", "ensure")
RAISES_ATTRS = {"raises", "warns", "deprecated_call"}


def _is_test_func(node):
    return (
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_")
    )


def _iter_test_funcs(tree):
    for node in tree.body:
        if _is_test_func(node):
            yield node
        elif isinstance(node, ast.ClassDef):
            for sub in node.body:
                if _is_test_func(sub):
                    yield sub


def _assert_is_banned(test):
    if isinstance(test, ast.Constant) and bool(test.value):
        return "asserts a constant literal (assert True / assert <lit>)"
    if (
        isinstance(test, ast.Compare)
        and len(test.ops) == 1
        and isinstance(test.ops[0], ast.Eq)
        and ast.dump(test.left) == ast.dump(test.comparators[0])
    ):
        return "asserts X == X (identical operands)"
    return None


def _classify_asserts(node):
    real, banned = 0, None
    for n in ast.walk(node):
        if isinstance(n, ast.Assert):
            reason = _assert_is_banned(n.test)
            if reason:
                banned = banned or reason
            else:
                real += 1
    return real, banned


def _uses_raises(node):
    for n in ast.walk(node):
        if isinstance(n, (ast.With, ast.AsyncWith)):
            for item in n.items:
                call = item.context_expr
                if isinstance(call, ast.Call):
                    f = call.func
                    attr = getattr(f, "attr", None) or getattr(f, "id", None)
                    if attr in RAISES_ATTRS:
                        return True
    return False


def _calls_assertion_helper(node):
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            f = n.func
            name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)
            if not name:
                continue
            if name in KNOWN_ASSERTION_HELPERS:
                return True
            if name.lstrip("_").startswith(ASSERTION_HELPER_PREFIXES):
                return True
            if name == "fail" and isinstance(f, ast.Attribute):
                return True
    return False


def _scan_file(path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    weak = {}
    for fn in _iter_test_funcs(tree):
        real, banned = _classify_asserts(fn)
        if real or _uses_raises(fn) or _calls_assertion_helper(fn):
            continue
        weak[fn.name] = banned or "no assertion / does not exercise behavior"
    return weak


def _collect_weak():
    found = {}
    for path in sorted(TESTS_DIR.rglob("test_*.py")):
        if path.name in SKIP_FILES:
            continue
        weak = _scan_file(path)
        if weak:
            found[str(path.relative_to(TESTS_DIR))] = weak
    return found


def test_no_weak_tests():
    found = _collect_weak()
    reasons = {(f, n): r for f, w in found.items() for n, r in w.items()}
    offenders = sorted(reasons)
    detail = "\n".join(f"  {f}::{n} — {reasons[(f, n)]}" for f, n in offenders)
    assert not offenders, (
        "These tests do not exercise real behavior — strengthen each to assert a "
        f"real outcome (or fix/delete):\n{detail}"
    )
