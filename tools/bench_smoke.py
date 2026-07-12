#!/usr/bin/env python3
"""Lightweight, non-gating performance smoke test (issue #228).

Times `read_oml` / `write_oml` / `Schema.validate` on a handful of
synthetic document sizes and prints a plain table to stdout. This is
**observability, not a gate**: the stability policy explicitly treats
performance characteristics as a non-promise (see
``docs/stability.md#stable-surfaces``), and shared CI runners are too
noisy to threshold on. Nothing here asserts or exits non-zero on slow
numbers -- it only measures and prints, for a human (or a future trend
script) to eyeball over time.

Deliberately independent of ``paper/scripts/bench.py``-style tooling:
that script doesn't exist in this repo (checked directly -- there is no
``paper/scripts`` directory), so this is new, minimal, CI-sized tooling
rather than a reuse of nonexistent prior art. Kept under ~2 minutes total
by using small-to-moderate sizes and a single repetition per size.

Usage::

    python3 tools/bench_smoke.py
"""

from __future__ import annotations

import os
import sys
import time
from typing import Callable, List, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from omnist import Doc, parse_schema, read_oml, write_oml  # noqa: E402

# Sizes are edge counts in a flat record, small enough that even a slow
# shared runner finishes the whole table in well under two minutes.
SIZES = [10, 100, 1_000, 5_000]


def _make_oml(n: int) -> str:
    return "\n".join(f'f{i}: {i}' for i in range(n)) + "\n"


def _make_schema(n: int) -> str:
    fields = "".join(f'    "f{i}": integer,\n' for i in range(n))
    return f"record Root {{\n{fields}}}\nroot Root\n"


def _time(fn: Callable[[], object]) -> float:
    start = time.perf_counter()
    fn()
    return time.perf_counter() - start


def run() -> List[Tuple[int, float, float, float]]:
    rows: List[Tuple[int, float, float, float]] = []
    for n in SIZES:
        text = _make_oml(n)
        schema = parse_schema(_make_schema(n))

        read_s = _time(lambda: read_oml(text))
        node = read_oml(text)
        write_s = _time(lambda: write_oml(node))
        d = Doc(node)
        validate_s = _time(lambda: schema.validate(d))

        rows.append((n, read_s, write_s, validate_s))
    return rows


def main() -> int:
    rows = run()
    print(f"{'edges':>8}  {'read_oml (s)':>14}  {'write_oml (s)':>14}  {'validate (s)':>14}")
    for n, r, w, v in rows:
        print(f"{n:>8}  {r:>14.4f}  {w:>14.4f}  {v:>14.4f}")
    print()
    print("(non-gating: numbers are printed for trend-watching only, "
          "see docs/stability.md#stable-surfaces)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
