"""Runs omnist-spec's ``test-suite/`` JSON-vector suite (139 vectors,
envelope ``name``/``spec``/``operation``/``purpose``/``input``/``expect`` --
see ``vendor/omnist-spec/test-suite/README.md`` and
``docs/08-conformance-and-errors.md`` Sec8.5) against this repo's own
omnist. This is a *second* runner alongside ``runner.py``'s
directory-per-fixture format (issue #286) -- the two vector shapes don't
share a natural code path, so they stay separate, sharing only
``referee.py``/``cli_runner.py``.

**Diagnostics matching mode.** Sec8.5.2 lists four normative rules; rule 4
permits "code-agnostic mode" (compare only ``ok`` plus the *set* of
``path``s, never ``code``) for implementations that have not adopted the
Sec8.3 code taxonomy. omnist has not: its diagnostic codes (``type-mismatch``,
``temporal.stringified``, ...) predate Sec8.3 and were never renamed to
match it -- confirmed directly against several vectors' expected codes
(e.g. a real ``validate`` run reports ``type-mismatch``, the vector expects
``validate.type-mismatch``). This runner therefore always compares in
code-agnostic mode. Message text is never compared either way (rule 1).

**Two more decisions, made explicit rather than silently applied
(per the issue's instruction not to silently drop anything):**

* ``document-model/limits.json``'s 6 vectors assume a runtime-configurable
  safety limit (``declared_max_depth`` etc. in ``input``) that this omnist
  hardcodes as module constants (``docs/02-document-model.md`` Sec2.4, and
  ``omnist/document.py``'s ``_MAX_DEPTH``/``_MAX_NODES``/``_MAX_INT_DIGITS``)
  with no runtime-configuration surface. These SKIP.
* ``infer``/``infer_with_report`` are driven directly through the library
  (``omnist.infer``/``infer_with_report``), not through ``cli_runner``,
  because the CLI's ``infer`` positional argument is ``nargs='+'`` and can
  never be invoked with zero sample files -- which would make
  ``infer/errors/zero-samples-is-an-error`` permanently unreachable through
  a CLI-only driver. Driving the library directly instead means that vector
  actually runs (and passes), rather than being skipped.
* A third case surfaced during implementation: some ``oml-grammar``/
  ``osd-grammar`` vectors expect specific diagnostics on a syntax-level
  parse failure. ``ParseError.errors`` is empty for syntax failures by
  design (``omnist/errors.py``: only schema-conformance failures from
  ``materialize`` carry a structured list) -- no ``path`` is obtainable for
  these through the public API at all. Vectors expecting only ``ok`` (a
  successful parse, or a bare failure with no diagnostics to check) still
  run normally; only the ones asserting specific diagnostics on a syntax
  failure SKIP.
* ``formats-xml/basic/interleaved-elements-preserve-order`` (issue #286)
  used to SKIP as a reported divergence: ``read_xml`` inferred scalar kind
  from element-text shape (``"1"`` read back as the integer ``1``),
  contradicting the vector's expectation that XML text always decodes to
  the Document ``string`` kind. Resolved by issue #288 in the vector's
  favor -- ``read_xml`` no longer infers a scalar kind from text shape, so
  this vector now runs for real and passes, and the skip is gone.

Usage: python3 -m tools.conformance.vector_runner
"""
from __future__ import annotations

import datetime as _dt
import json
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from omnist import Doc, parse_schema, write_oml
from omnist import infer as _infer
from omnist import infer_with_report as _infer_with_report
from omnist.errors import OmnistError

from . import cli_runner
from .referee import compare_document, compare_schema

VECTOR_SUITE_DIR = (
    Path(__file__).resolve().parent.parent.parent / "vendor" / "omnist-spec" / "test-suite"
)

_LIMIT_KEYS = {"declared_max_depth", "declared_max_nodes", "declared_max_int_digits"}

Result = Tuple[str, str]


# ---------------------------------------------------------------------------
# Canonical document encoding (Sec8.5.4) -> a raw omnist Document node
# ---------------------------------------------------------------------------

def _decode_scalar(kind: Optional[str], value: Any) -> Any:
    if kind is None:
        return None
    if kind in ("string", "boolean", "number"):
        return value
    if kind == "integer":
        return int(value) if isinstance(value, str) else value
    if kind == "date":
        return _dt.date.fromisoformat(value)
    if kind == "time":
        return _dt.time.fromisoformat(value)
    if kind == "datetime":
        return _dt.datetime.fromisoformat(value)
    raise ValueError(f"unknown scalar kind {kind!r}")


def decode_document(node: Dict[str, Any]) -> Any:
    if "scalar" in node:
        s = node["scalar"]
        return _decode_scalar(s["kind"], s["value"])
    return [(label, decode_document(child)) for label, child in node["edges"]]


def _paths(diagnostics: List[Dict[str, Any]]) -> Set[str]:
    return {d["path"] for d in diagnostics}


def _write_tmp(dir_: Path, name: str, text: str) -> Path:
    p = dir_ / name
    p.write_text(text, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Operation drivers -- one function per operation, each (vector, tmp_dir) -> Result
# ---------------------------------------------------------------------------

def run_parse(v: Dict[str, Any], tmp: Path) -> Result:
    inp = v["input"]
    if _LIMIT_KEYS & inp.keys():
        return "skip", "runtime-configurable safety limit not exposed by this omnist"
    expect = v["expect"]
    fmt = inp["format"]
    src = _write_tmp(tmp, "in." + fmt, inp["text"])
    if fmt == "oml":
        stdout, stderr, code = cli_runner._run(["format", str(src), "--json"])
    else:
        stdout, stderr, code = cli_runner._run(
            ["convert", str(src), "--from", fmt, "--to", "oml", "--json"])
    if expect["ok"]:
        if code != 0:
            return "fail", f"expected success, got exit {code}: {stderr.strip()}"
        expected_oml = write_oml(decode_document(expect["document"]))
        if compare_document(stdout, expected_oml):
            return "pass", "ok"
        return "fail", "parsed document does not match expected"
    if "diagnostics" in expect:
        return "skip", "syntax-level ParseError carries no structured path/code"
    if code == 0:
        return "fail", "expected failure, command succeeded"
    return "pass", "ok"


def run_parse_schema(v: Dict[str, Any], tmp: Path) -> Result:
    expect = v["expect"]
    src = _write_tmp(tmp, "in.osd", v["input"]["text"])
    stdout, stderr, code = cli_runner._run(["schema", "format", str(src), "--json"])
    if expect["ok"]:
        if code != 0:
            return "fail", f"expected success, got exit {code}: {stderr.strip()}"
        return "pass", "ok"
    if "diagnostics" in expect:
        return "skip", "syntax-level errors carry no structured path/code"
    if code == 0:
        return "fail", "expected failure, command succeeded"
    return "pass", "ok"


def run_validate(v: Dict[str, Any], tmp: Path) -> Result:
    inp = v["input"]
    expect = v["expect"]
    schema_f = _write_tmp(tmp, "s.osd", inp["schema"])
    doc_f = _write_tmp(tmp, "d.oml", write_oml(decode_document(inp["document"])))
    stdout, stderr, code = cli_runner.validate(doc_f, schema_f)
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return "fail", f"non-JSON stdout: {stdout!r}"
    if payload.get("ok") != expect["ok"]:
        return "fail", f"expected ok={expect['ok']}, got {payload.get('ok')}"
    if not expect["ok"]:
        exp_paths = _paths(expect["diagnostics"])
        act_paths = _paths(payload.get("errors", []))
        if exp_paths != act_paths:
            return "fail", f"diagnostic paths differ: expected {exp_paths}, got {act_paths}"
    return "pass", "ok"


def run_materialize(v: Dict[str, Any], tmp: Path) -> Result:
    inp = v["input"]
    expect = v["expect"]
    schema_f = _write_tmp(tmp, "s.osd", inp["schema"])
    doc_f = _write_tmp(tmp, "d.oml", write_oml(decode_document(inp["document"])))
    stdout, stderr, code = cli_runner.materialize(doc_f, schema_f)
    if expect["ok"]:
        if code != 0:
            return "fail", f"expected success, got exit {code}: {stderr.strip()}"
        expected_oml = write_oml(decode_document(expect["document"]))
        if compare_document(stdout, expected_oml):
            return "pass", "ok"
        return "fail", "materialized document does not match expected"
    if code == 0:
        return "fail", "expected failure, command succeeded"
    if "diagnostics" in expect:
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError:
            return "fail", f"non-JSON stdout on failure: {stdout!r}"
        exp_paths = _paths(expect["diagnostics"])
        act_paths = _paths(payload.get("errors", []))
        if exp_paths != act_paths:
            return "fail", f"diagnostic paths differ: expected {exp_paths}, got {act_paths}"
    return "pass", "ok"


def run_write(v: Dict[str, Any], tmp: Path) -> Result:
    inp = v["input"]
    expect = v["expect"]
    doc_f = _write_tmp(tmp, "d.oml", write_oml(decode_document(inp["document"])))
    fmt = inp["format"]
    args = ["convert", str(doc_f), "--from", "oml", "--to", fmt,
            "--report", "--result-format", "json"]
    if inp.get("strict"):
        args.append("--strict")
    stdout, stderr, code = cli_runner._run(args)
    if not expect["ok"]:
        if code == 0:
            return "fail", "expected failure, command succeeded"
        return "pass", "ok"
    if code != 0:
        return "fail", f"expected success, got exit {code}: {stderr.strip()}"
    if "text" in expect and stdout.strip() != expect["text"].strip():
        return "fail", f"expected text {expect['text']!r}, got {stdout.strip()!r}"
    if "diagnostics" in expect:
        try:
            report = json.loads(stderr)
        except json.JSONDecodeError:
            return "fail", f"non-JSON stderr report: {stderr!r}"
        exp_paths = _paths(expect["diagnostics"])
        act_paths = _paths(report)
        if exp_paths != act_paths:
            return "fail", f"diagnostic paths differ: expected {exp_paths}, got {act_paths}"
    return "pass", "ok"


def _run_schema_producing(v: Dict[str, Any], tmp: Path, cli_fn: Any) -> Result:
    schema_f = _write_tmp(tmp, "s.osd", v["input"]["schema"])
    stdout, stderr, code = cli_fn(schema_f)
    if code != 0:
        return "fail", f"exit {code}: {stderr.strip()}"
    if compare_schema(stdout, v["expect"]["schema"], mode="exact"):
        return "pass", "ok"
    return "fail", "output schema does not match expected"


def run_normalize(v: Dict[str, Any], tmp: Path) -> Result:
    return _run_schema_producing(v, tmp, cli_runner.normalize)


def run_prune(v: Dict[str, Any], tmp: Path) -> Result:
    return _run_schema_producing(v, tmp, cli_runner.prune)


def _check_bool(stdout: str, expect_val: bool, key: str) -> Result:
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return "fail", f"non-JSON stdout: {stdout!r}"
    if payload.get(key) != expect_val:
        return "fail", f"expected {key}={expect_val}, got {payload.get(key)}"
    return "pass", "ok"


def run_is_empty(v: Dict[str, Any], tmp: Path) -> Result:
    schema_f = _write_tmp(tmp, "s.osd", v["input"]["schema"])
    stdout, stderr, code = cli_runner.is_empty(schema_f)
    return _check_bool(stdout, v["expect"]["empty"], "empty")


def run_compatible_with(v: Dict[str, Any], tmp: Path) -> Result:
    a = _write_tmp(tmp, "a.osd", v["input"]["a"])
    b = _write_tmp(tmp, "b.osd", v["input"]["b"])
    stdout, stderr, code = cli_runner.compatible_with(a, b)
    return _check_bool(stdout, v["expect"]["result"], "compatible")


def run_equivalent(v: Dict[str, Any], tmp: Path) -> Result:
    a = _write_tmp(tmp, "a.osd", v["input"]["a"])
    b = _write_tmp(tmp, "b.osd", v["input"]["b"])
    stdout, stderr, code = cli_runner.equivalent(a, b)
    return _check_bool(stdout, v["expect"]["result"], "equivalent")


def run_extract(v: Dict[str, Any], tmp: Path) -> Result:
    inp = v["input"]
    expect = v["expect"]
    schema_f = _write_tmp(tmp, "s.osd", inp["schema"])
    stdout, stderr, code = cli_runner.extract(schema_f, inp["keep"])
    if expect["ok"]:
        if code != 0:
            return "fail", f"expected success, got exit {code}: {stderr.strip()}"
        if compare_schema(stdout, expect["schema"], mode="exact"):
            return "pass", "ok"
        return "fail", "extracted schema does not match expected"
    if code == 0:
        return "fail", "expected failure, command succeeded"
    return "pass", "ok"


def run_lint(v: Dict[str, Any], tmp: Path) -> Result:
    schema_f = _write_tmp(tmp, "s.osd", v["input"]["schema"])
    stdout, stderr, code = cli_runner.lint(schema_f)
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return "fail", f"non-JSON stdout: {stdout!r}"
    expect = v["expect"]
    if payload.get("ok") != expect["ok"]:
        return "fail", f"expected ok={expect['ok']}, got {payload.get('ok')}"
    exp_locs = {f["location"] for f in expect["findings"]}
    act_locs = {f["location"] for f in payload.get("findings", [])}
    if exp_locs != act_locs:
        return "fail", f"finding locations differ: expected {exp_locs}, got {act_locs}"
    return "pass", "ok"


def _run_infer(v: Dict[str, Any], with_report: bool) -> Result:
    inp = v["input"]
    expect = v["expect"]
    samples = [Doc.from_oml(s) for s in inp["samples"]]
    allow_any = bool(inp.get("allow_any", False))
    try:
        if with_report:
            schema, _fallbacks = _infer_with_report(samples, allow_any=allow_any)
        else:
            schema = _infer(samples, allow_any=allow_any)
    except OmnistError as exc:
        if expect["ok"]:
            return "fail", f"expected success, got {exc}"
        return "pass", "ok"
    if not expect["ok"]:
        return "fail", "expected failure, inference succeeded"
    expected_schema = parse_schema(expect["schema"])
    # isomorphic, not exact: infer's generated record names are
    # implementation-derived, never canonical (mirrors runner.py's run_infer).
    if schema.isomorphic_to(expected_schema):
        return "pass", "ok"
    return "fail", "inferred schema is not isomorphic to expected"


def run_infer(v: Dict[str, Any], tmp: Path) -> Result:
    return _run_infer(v, with_report=False)


def run_infer_with_report(v: Dict[str, Any], tmp: Path) -> Result:
    return _run_infer(v, with_report=True)


RUNNERS = {
    "parse": run_parse,
    "parse_schema": run_parse_schema,
    "validate": run_validate,
    "materialize": run_materialize,
    "write": run_write,
    "normalize": run_normalize,
    "prune": run_prune,
    "is_empty": run_is_empty,
    "compatible_with": run_compatible_with,
    "equivalent": run_equivalent,
    "extract": run_extract,
    "infer": run_infer,
    "infer_with_report": run_infer_with_report,
    "lint": run_lint,
}


def iter_vectors() -> Any:
    for path in sorted(VECTOR_SUITE_DIR.rglob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for vector in data.get("vectors", []):
            yield vector


def run_vector(v: Dict[str, Any]) -> Result:
    fn = RUNNERS.get(v["operation"])
    if fn is None:
        return "skip", f"no driver wired up yet for operation {v['operation']!r}"
    with tempfile.TemporaryDirectory() as d:
        try:
            return fn(v, Path(d))
        except Exception as exc:  # a driver crash is a fail, never silently swallowed
            return "fail", f"driver raised {exc!r}"


def main(argv: List[str]) -> int:
    if not VECTOR_SUITE_DIR.is_dir():
        print(
            f"no test-suite vectors found at {VECTOR_SUITE_DIR} -- has the "
            "vendor/omnist-spec submodule been checked out? "
            "(git submodule update --init)", file=sys.stderr)
        return 2

    passed = failed = skipped = 0
    for v in iter_vectors():
        status, message = run_vector(v)
        print(f"[{status.upper()}] {v['name']}: {message}")
        if status == "pass":
            passed += 1
        elif status == "skip":
            skipped += 1
        else:
            failed += 1

    total = passed + failed + skipped
    print(f"\n{passed} passed, {failed} failed, {skipped} skipped (of {total} vectors) "
          "-- diagnostics compared in code-agnostic mode (Sec8.5.2 rule 4)")
    return 1 if failed else 0


if __name__ == "__main__":  # pragma: no cover -- entry point, not importable behavior
    raise SystemExit(main(sys.argv[1:]))
