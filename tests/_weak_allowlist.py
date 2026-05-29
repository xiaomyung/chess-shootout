"""Tests grandfathered past the weak-test guard while the suite was strengthened.

This list has drained to empty: every test now exercises real behavior. If a new
entry is ever needed, the test should be strengthened instead — the guard
(test_no_weak_tests.py) fails on stale entries, so this never silently grows.
"""

WEAK_ALLOWLIST = {}
