"""Runs real (non-self-test) fixtures under vendor/omnist-spec's
conformance/fixtures/<operation>/ against the omnist CLI, per
omnist-spec's docs/conformance-harness.md Sec3's fixture format and
Sec2's verified CLI contract. Sec8.5.5's reporting discipline: pass,
fail, or skip -- skip is first-class, never folded into pass.

Ported from omnist-spec's conformance/orchestrator/runner.py (issue
#283) with no change to the comparison logic -- only FIXTURES_DIR now
points at the pinned submodule instead of a sibling directory.

Usage: python3 -m tools.conformance.runner [operation ...]
  (with no arguments, runs every operation directory that has fixtures)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

from . import cli_runner
from .referee import compare_document, compare_schema

FIXTURES_DIR = (
    Path(__file__).resolve().parent.parent.parent
    / "vendor" / "omnist-spec" / "conformance" / "fixtures"
)

ALL_OPERATIONS = {"write", "validate", "materialize", "normalize", "prune",
                  "extract", "is_empty", "compatible_with", "equivalent",
                  "infer", "lint"}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _purpose(case_dir: Path) -> str:
    p = case_dir / "purpose.txt"
    return _read(p).splitlines()[0] if p.exists() else ""


def run_write(case_dir: Path) -> Tuple[str, str]:
    stdout, stderr, code = cli_runner.write(case_dir / "input.oml")
    if code != 0:
        return "fail", f"exit {code}: {stderr.strip()}"
    expected = _read(case_dir / "expected.oml")
    if compare_document(stdout, expected):
        return "pass", "ok"
    return "fail", "output does not match expected (structural comparison)"


def run_validate(case_dir: Path) -> Tuple[str, str]:
    stdout, stderr, code = cli_runner.validate(case_dir / "input.oml", case_dir / "schema.osd")
    expect_ok = _read(case_dir / "expected" / "ok.txt").strip() == "true"
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return "fail", f"non-JSON stdout: {stdout!r}"
    if payload.get("ok") != expect_ok:
        return "fail", f"expected ok={expect_ok}, got {payload.get('ok')}"
    return "pass", "ok"


def run_materialize(case_dir: Path) -> Tuple[str, str]:
    stdout, stderr, code = cli_runner.materialize(case_dir / "input.oml", case_dir / "schema.osd")
    expect_ok = _read(case_dir / "expected" / "ok.txt").strip() == "true"
    if expect_ok:
        if code != 0:
            return "fail", f"expected success, got exit {code}: {stderr.strip()}"
        expected = _read(case_dir / "expected" / "output.oml")
        if compare_document(stdout, expected):
            return "pass", "ok"
        return "fail", "materialized output does not match expected"
    else:
        if code == 0:
            return "fail", "expected failure, command succeeded"
        return "pass", "ok"


def _run_schema_producing(case_dir: Path, cli_fn: Any) -> Tuple[str, str]:
    stdout, stderr, code = cli_fn(case_dir / "input.osd")
    if code != 0:
        return "fail", f"exit {code}: {stderr.strip()}"
    expected = _read(case_dir / "expected.osd")
    if compare_schema(stdout, expected, mode="exact"):
        return "pass", "ok"
    return "fail", "output schema does not match expected (exact structural comparison)"


def run_normalize(case_dir: Path) -> Tuple[str, str]:
    return _run_schema_producing(case_dir, cli_runner.normalize)


def run_prune(case_dir: Path) -> Tuple[str, str]:
    return _run_schema_producing(case_dir, cli_runner.prune)


def _run_boolean(case_dir: Path, cli_fn: Any, key: str, *, two_input: bool) -> Tuple[str, str]:
    if two_input:
        stdout, stderr, code = cli_fn(case_dir / "a.osd", case_dir / "b.osd")
    else:
        stdout, stderr, code = cli_fn(case_dir / "input.osd")
    expect = _read(case_dir / "expected.txt").strip() == "true"
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return "fail", f"non-JSON stdout: {stdout!r}"
    if payload.get(key) != expect:
        return "fail", f"expected {key}={expect}, got {payload.get(key)}"
    return "pass", "ok"


def run_is_empty(case_dir: Path) -> Tuple[str, str]:
    return _run_boolean(case_dir, cli_runner.is_empty, "empty", two_input=False)


def run_compatible_with(case_dir: Path) -> Tuple[str, str]:
    return _run_boolean(case_dir, cli_runner.compatible_with, "compatible", two_input=True)


def run_equivalent(case_dir: Path) -> Tuple[str, str]:
    return _run_boolean(case_dir, cli_runner.equivalent, "equivalent", two_input=True)


def run_extract(case_dir: Path) -> Tuple[str, str]:
    keep = [lbl for lbl in _read(case_dir / "keep.txt").strip().split(",") if lbl]
    stdout, stderr, code = cli_runner.extract(case_dir / "schema.osd", keep)
    expect_ok = _read(case_dir / "expected" / "ok.txt").strip() == "true"
    if expect_ok:
        if code != 0:
            return "fail", f"expected success, got exit {code}: {stderr.strip()}"
        expected = _read(case_dir / "expected" / "output.osd")
        if compare_schema(stdout, expected, mode="exact"):
            return "pass", "ok"
        return "fail", "extracted schema does not match expected"
    else:
        if code == 0:
            return "fail", "expected failure (keep set invalidates root), command succeeded"
        return "pass", "ok"


def run_infer(case_dir: Path) -> Tuple[str, str]:
    samples_dir = case_dir / "samples"
    sample_files = sorted(samples_dir.iterdir())
    allow_any_file = case_dir / "allow_any.txt"
    allow_any = allow_any_file.exists() and _read(allow_any_file).strip() == "true"

    stdout, stderr, code = cli_runner.infer(sample_files, allow_any=allow_any)
    expect_ok = _read(case_dir / "expected" / "ok.txt").strip() == "true"
    if expect_ok:
        if code != 0:
            return "fail", f"expected success, got exit {code}: {stderr.strip()}"
        expected = _read(case_dir / "expected" / "output.osd")
        # isomorphic, not exact: Sec6.10 -- infer's generated record names
        # are implementation-derived, never canonical.
        if compare_schema(stdout, expected, mode="isomorphic"):
            return "pass", "ok"
        return "fail", "inferred schema is not isomorphic to expected"
    else:
        if code == 0:
            return "fail", "expected failure (ambiguous type, no --allow-any), command succeeded"
        return "pass", "ok"


def _drop_messages(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Message text is never compared (Sec8.5's own matching rule 1) --
    strip it so a fixture's expected.json doesn't have to pin exact
    wording, only code/severity/location."""
    return {
        "ok": payload["ok"],
        "findings": [
            {k: f[k] for k in ("code", "severity", "location")}
            for f in payload["findings"]
        ],
    }


def run_lint(case_dir: Path) -> Tuple[str, str]:
    stdout, stderr, code = cli_runner.lint(case_dir / "input.osd")
    try:
        actual = json.loads(stdout)
    except json.JSONDecodeError:
        return "fail", f"non-JSON stdout: {stdout!r}"
    expected = json.loads(_read(case_dir / "expected.json"))
    # Findings MUST already be sorted deterministically by (code, location)
    # per Sec6.11 -- a direct list-equality comparison (not set/unordered)
    # is itself a conformance check, not just convenient.
    if _drop_messages(actual) == _drop_messages(expected):
        return "pass", "ok"
    return "fail", f"expected {expected!r}, got {actual!r}"


RUNNERS = {
    "write": run_write,
    "validate": run_validate,
    "materialize": run_materialize,
    "normalize": run_normalize,
    "prune": run_prune,
    "is_empty": run_is_empty,
    "compatible_with": run_compatible_with,
    "equivalent": run_equivalent,
    "extract": run_extract,
    "infer": run_infer,
    "lint": run_lint,
}


def run_operation(operation: str) -> Tuple[int, int, int]:
    """Returns (passed, failed, skipped) counts for one operation directory."""
    op_dir = FIXTURES_DIR / operation
    if not op_dir.is_dir():
        return 0, 0, 0
    cases = sorted(p for p in op_dir.iterdir() if p.is_dir())
    if not cases:
        return 0, 0, 0

    runner_fn = RUNNERS.get(operation)
    passed = failed = skipped = 0
    for case_dir in cases:
        purpose = _purpose(case_dir)
        if runner_fn is None:
            print(f"[SKIP] {operation}/{case_dir.name} ({purpose}): "
                  f"no runner wired up yet for this operation")
            skipped += 1
            continue
        status, message = runner_fn(case_dir)
        print(f"[{status.upper()}] {operation}/{case_dir.name} ({purpose}): {message}")
        if status == "pass":
            passed += 1
        else:
            failed += 1
    return passed, failed, skipped


def main(argv: List[str]) -> int:
    if not FIXTURES_DIR.is_dir():
        print(
            f"no fixtures found at {FIXTURES_DIR} -- has the vendor/omnist-spec "
            "submodule been checked out? (git submodule update --init)",
            file=sys.stderr)
        return 2

    operations = argv or sorted(ALL_OPERATIONS)
    total_pass = total_fail = total_skip = 0
    for op in operations:
        p, f, s = run_operation(op)
        total_pass += p
        total_fail += f
        total_skip += s

    print(f"\n{total_pass} passed, {total_fail} failed, {total_skip} skipped "
          f"(across {len(operations)} operation(s))")
    return 1 if total_fail else 0


if __name__ == "__main__":  # pragma: no cover -- entry point, not importable behavior
    raise SystemExit(main(sys.argv[1:]))
