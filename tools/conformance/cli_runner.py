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
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple

CLI = os.environ.get("OMNIST_CLI", "omnist")


def _cli_module_file() -> Optional[str]:
    """The ``omnist/__init__.py`` the CLI's own interpreter imports, or None
    when that cannot be determined (the CLI is not a ``#!`` script, e.g. a
    Windows launcher).  Read from the console script's shebang interpreter, so
    it reflects the install the CLI really runs, not the runner's."""
    exe = shutil.which(CLI)
    if exe is None:
        return None
    try:
        with open(exe, "rb") as fh:
            first = fh.readline().decode("utf-8", "replace").strip()
    except OSError:
        return None
    if not first.startswith("#!"):
        return None
    argv = first[2:].split()
    if not argv:
        return None
    try:
        proc = subprocess.run(
            [*argv, "-c", "import omnist; print(omnist.__file__)"],
            capture_output=True, text=True, encoding="utf-8")
    except OSError:
        return None
    return proc.stdout.strip() if proc.returncode == 0 else None


def check_version() -> Optional[str]:
    """None when the CLI under test is this checkout's build, else a message.

    The CLI is resolved from PATH (or OMNIST_CLI), so a stale or global
    ``omnist`` would silently be measured instead of this tree (omnist#350).
    Compares ``omnist --version`` with ``omnist.__version__`` and, where the
    CLI is a ``#!`` script, the module file its interpreter imports with this
    checkout's (the same version number can come from another install)."""
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
    theirs = _cli_module_file()
    if theirs is not None and os.path.realpath(theirs) != os.path.realpath(omnist.__file__):
        return (f"the CLI {CLI!r} imports omnist from {theirs!r}, not this "
                f"checkout's {omnist.__file__!r}: it is not this checkout's build "
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
    # plain materialized OML on stdout. Safe to always pass.  --report with
    # --result-format json prints the success-path diagnostics (a JSON list)
    # on stderr, which the vector runner compares (omnist#350).
    return _run(["convert", str(input_file), "--from", "oml", "--to", "oml",
                 "--schema", str(schema_file), "--json",
                 "--report", "--result-format", "json"])


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
