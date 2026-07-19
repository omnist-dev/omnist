#!/usr/bin/env python3
"""Fail CI if a PR adds or changes a fenced code block in docs/*.md without
either a `verified-by` marker (naming the test that checks its exact
literal output) or an explicit `doc-illustrative` opt-out.

This does not verify a marker is honest -- it only requires one to exist.
See issue #249 for the stronger check (confirming the named test's
captured output actually contains the doc's literal text).

Usage: python3 tools/check_doc_examples.py [--base-ref origin/master]
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

FENCE_RE = re.compile(r"^```")
MARKER_RE = re.compile(
    r"<!--\s*(verified-by:\s*\S+|doc-illustrative)\s*-->"
)


def changed_doc_files(base_ref: str) -> list[Path]:
    out = subprocess.run(
        ["git", "diff", "--name-only", f"{base_ref}...HEAD", "--", "docs/"],
        capture_output=True, text=True, check=True,
    ).stdout
    return [Path(p) for p in out.splitlines() if p.endswith(".md")]


def changed_line_numbers(path: Path, base_ref: str) -> set[int]:
    """Line numbers in the *current* file that were added or modified."""
    out = subprocess.run(
        ["git", "diff", "-U0", f"{base_ref}...HEAD", "--", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout
    changed: set[int] = set()
    hunk_re = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
    for line in out.splitlines():
        m = hunk_re.match(line)
        if m:
            start = int(m.group(1))
            count = int(m.group(2)) if m.group(2) else 1
            changed.update(range(start, start + count))
    return changed


def find_blocks(path: Path) -> list[tuple[int, int]]:
    """[(fence_open_line, fence_close_line)] -- 1-indexed, inclusive."""
    lines = path.read_text(encoding="utf-8").splitlines()
    blocks = []
    i = 0
    while i < len(lines):
        if FENCE_RE.match(lines[i]):
            start = i + 1
            j = i + 1
            while j < len(lines) and not lines[j].startswith("```"):
                j += 1
            blocks.append((start, j + 1))
            i = j + 1
        else:
            i += 1
    return blocks


def has_marker(path: Path, block_end_line: int) -> bool:
    """A marker directly before the fence or directly after it counts."""
    lines = path.read_text(encoding="utf-8").splitlines()
    for offset in (-2, -1, 0, 1):
        idx = block_end_line + offset - 1
        if 0 <= idx < len(lines) and MARKER_RE.search(lines[idx]):
            return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-ref", default="origin/master")
    args = ap.parse_args()

    problems: list[str] = []
    for path in changed_doc_files(args.base_ref):
        if not path.exists():
            continue
        changed = changed_line_numbers(path, args.base_ref)
        for start, end in find_blocks(path):
            if not changed.intersection(range(start, end + 1)):
                continue  # this block wasn't touched by the diff
            if not has_marker(path, end):
                problems.append(
                    f"{path}:{start}-{end}: new/changed code block has no "
                    f"<!-- verified-by: path::test_name --> or "
                    f"<!-- doc-illustrative --> marker"
                )

    if problems:
        print("Doc-example coverage check failed:\n")
        for p in problems:
            print(f"  {p}")
        print(
            "\nEvery code block that shows literal output needs a "
            "verified-by marker naming the test that asserts that exact "
            "text, or a doc-illustrative marker if it's a diagram/table/"
            "grammar fragment with no runnable claim. See docs/testing.md."
        )
        return 1

    print("Doc-example coverage check passed.")
    return 0


if __name__ == "__main__":  # pragma: no cover -- entry point, not importable behavior
    sys.exit(main())
