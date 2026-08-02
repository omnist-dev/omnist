"""Runs vendor/omnist-spec's conformance/fixtures/_referee-self-test/ --
proves the referee's own comparison logic is trustworthy before it
judges any real implementation output. Sec6 of omnist-spec's
docs/conformance-harness.md.

Ported from omnist-spec's conformance/orchestrator/self_test.py (issue
#283) with no change to the comparison logic -- only FIXTURES_DIR now
points at the pinned submodule instead of a sibling directory.

Usage: python3 -m tools.conformance.self_test
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Tuple

from .referee import compare_document, compare_schema

FIXTURES_DIR = (
    Path(__file__).resolve().parent.parent.parent
    / "vendor" / "omnist-spec" / "conformance" / "fixtures" / "_referee-self-test"
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def run_case(case_dir: Path) -> Tuple[bool, str]:
    """Returns (passed, message)."""
    kind = _read(case_dir / "kind.txt").strip()
    expect = _read(case_dir / "expect.txt").strip()
    if expect not in ("equal", "not-equal"):
        return False, f"bad expect.txt value {expect!r}"
    expect_equal = expect == "equal"

    if kind == "document":
        a = _read(case_dir / "a.oml")
        b = _read(case_dir / "b.oml")
        actual_equal = compare_document(a, b)
    elif kind == "schema":
        mode = _read(case_dir / "mode.txt").strip()
        a = _read(case_dir / "a.osd")
        b = _read(case_dir / "b.osd")
        actual_equal = compare_schema(a, b, mode)
    else:
        return False, f"bad kind.txt value {kind!r}"

    if actual_equal == expect_equal:
        return True, "ok"
    return False, (f"expected {'equal' if expect_equal else 'not-equal'}, "
                   f"got {'equal' if actual_equal else 'not-equal'}")


def main() -> int:
    if not FIXTURES_DIR.is_dir():
        print(f"no self-test fixtures found at {FIXTURES_DIR}", file=sys.stderr)
        return 2

    cases = sorted(p for p in FIXTURES_DIR.iterdir() if p.is_dir())
    if not cases:
        print(f"no self-test fixtures found at {FIXTURES_DIR}", file=sys.stderr)
        return 2

    failures = 0
    for case_dir in cases:
        purpose_file = case_dir / "purpose.txt"
        purpose = _read(purpose_file).splitlines()[0] if purpose_file.exists() else ""
        passed, message = run_case(case_dir)
        status = "PASS" if passed else "FAIL"
        print(f"[{status}] {case_dir.name} ({purpose}): {message}")
        if not passed:
            failures += 1

    print(f"\n{len(cases) - failures}/{len(cases)} self-test cases passed")
    return 1 if failures else 0


if __name__ == "__main__":  # pragma: no cover -- entry point, not importable behavior
    raise SystemExit(main())
