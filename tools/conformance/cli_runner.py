"""Invokes the omnist CLI per omnist-spec's docs/conformance-harness.md
Sec2's verified contract. One function per operation. Each returns
(stdout, stderr, exit_code).

The CLI name is resolved from PATH (not hardcoded to a location) via
subprocess's normal lookup -- pass a different name via OMNIST_CLI to test
a different build (e.g. a specific venv's console script). Ported from
omnist-spec's conformance/orchestrator/cli_runner.py (issue #283) with no
change to the CLI contract itself.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple

CLI = os.environ.get("OMNIST_CLI", "omnist")


def check_version() -> Optional[str]:
    """None when the CLI under test is this checkout's build, else a message.

    The CLI is resolved from PATH (or OMNIST_CLI), so a stale or global
    ``omnist`` would silently be measured instead of this tree (omnist#350).
    Compares ``omnist --version`` with ``omnist.__version__``."""
    import omnist

    try:
        out, err, code = _run(["--version"])
    except OSError as exc:
        return f"cannot run the CLI {CLI!r}: {exc}"
    expected = f"omnist {omnist.__version__}"
    if code != 0 or out.strip() != expected:
        return (f"the CLI {CLI!r} reports {out.strip() or err.strip()!r} "
                f"(exit {code}), not {expected!r}: it is not this checkout's build "
                "(activate the worktree's venv or set OMNIST_CLI)")
    return None


def _run(args: List[str], stdin_text: Optional[str] = None) -> Tuple[str, str, int]:
    proc = subprocess.run(
        [CLI, *args],
        input=stdin_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return proc.stdout, proc.stderr, proc.returncode


def write(input_file: Path) -> Tuple[str, str, int]:
    return _run(["format", str(input_file)])


def validate(input_file: Path, schema_file: Path) -> Tuple[str, str, int]:
    return _run(["validate", str(input_file), "--from", "oml",
                 "--schema", str(schema_file), "--json"])


def materialize(input_file: Path, schema_file: Path) -> Tuple[str, str, int]:
    # --json only changes the failure-path output shape (structured JSON on
    # stdout instead of plain text); the success path is unaffected -- still
    # plain materialized OML on stdout. Safe to always pass.
    return _run(["convert", str(input_file), "--from", "oml", "--to", "oml",
                 "--schema", str(schema_file), "--json"])


def normalize(schema_file: Path) -> Tuple[str, str, int]:
    return _run(["schema", "normalize", str(schema_file)])


def prune(schema_file: Path) -> Tuple[str, str, int]:
    return _run(["schema", "prune", str(schema_file)])


def extract(schema_file: Path, keep: List[str]) -> Tuple[str, str, int]:
    return _run(["schema", "extract", str(schema_file), "--keep", ",".join(keep),
                 "--json"])


def is_empty(schema_file: Path) -> Tuple[str, str, int]:
    return _run(["schema", "is-empty", str(schema_file), "--result-format", "json"])


def compatible_with(a_file: Path, b_file: Path) -> Tuple[str, str, int]:
    return _run(["schema", "compatible-with", str(a_file), str(b_file),
                 "--result-format", "json"])


def equivalent(a_file: Path, b_file: Path) -> Tuple[str, str, int]:
    return _run(["schema", "equivalent", str(a_file), str(b_file),
                 "--result-format", "json"])


def infer(sample_files: List[Path], allow_any: bool = False) -> Tuple[str, str, int]:
    args = ["infer", *[str(f) for f in sample_files], "--from", "oml"]
    if allow_any:
        args.append("--allow-any")
    return _run(args)


def lint(schema_file: Path) -> Tuple[str, str, int]:
    return _run(["schema", "lint", str(schema_file), "--json"])
