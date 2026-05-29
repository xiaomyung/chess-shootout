"""Guard against tests that cannot fail.

Statically scans every tests/test_*.py and flags a test function as weak when
it exercises no real behavior: no non-trivial assertion, no pytest.raises/warns,
and no call to an assertion helper (named assert_* / expect_*, or a known helper
such as play_moves). Tests whose only assertion is `assert True`, `assert <lit>`,
or `assert X == X` count as weak.

The WEAK_ALLOWLIST in _weak_allowlist.py records the tests grandfathered in while
the suite is cleaned up; it self-prunes — a name that is no longer weak fails the
allowlist test, forcing its removal. The goal is an empty allowlist.
"""

import ast
from pathlib import Path

from tests._weak_allowlist import WEAK_ALLOWLIST

TESTS_DIR = Path(__file__).resolve().parent
SKIP_FILES = {
    "__init__.py", "conftest.py", "helpers.py",
    "test_no_weak_tests.py", "_weak_allowlist.py",
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
    tree = ast.parse(path.read_text(), filename=str(path))
    weak = {}
    for fn in _iter_test_funcs(tree):
        real, banned = _classify_asserts(fn)
        if real or _uses_raises(fn) or _calls_assertion_helper(fn):
            continue
        weak[fn.name] = banned or "no assertion / does not exercise behavior"
    return weak


def _collect_weak():
    found = {}
    for path in sorted(TESTS_DIR.glob("test_*.py")):
        if path.name in SKIP_FILES:
            continue
        weak = _scan_file(path)
        if weak:
            found[path.name] = weak
    return found


def test_no_unexpected_weak_tests():
    found = _collect_weak()
    reasons = {(f, n): r for f, w in found.items() for n, r in w.items()}
    allow = {(f, n) for f, names in WEAK_ALLOWLIST.items() for n in names}
    unexpected = sorted(k for k in reasons if k not in allow)
    detail = "\n".join(f"  {f}::{n} — {reasons[(f, n)]}" for f, n in unexpected)
    assert not unexpected, (
        "Weak tests not in the allowlist — strengthen them to exercise real "
        f"behavior (or fix/delete):\n{detail}"
    )


def test_weak_allowlist_has_no_dead_entries():
    found = _collect_weak()
    flat = {(f, n) for f, w in found.items() for n in w}
    allow = {(f, n) for f, names in WEAK_ALLOWLIST.items() for n in names}
    dead = sorted(allow - flat)
    detail = "\n".join(f"  {f}::{n}" for f, n in dead)
    assert not dead, (
        "Allowlist entries that are no longer weak — remove them from "
        f"_weak_allowlist.py:\n{detail}"
    )
