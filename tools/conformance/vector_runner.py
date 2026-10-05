"""Runs omnist-spec's ``test-suite/`` JSON-vector suite (envelope
``name``/``spec``/``operation``/``purpose``/``input``/``expect`` -- see
``vendor/omnist-spec/test-suite/README.md`` and
``docs/08-conformance-and-errors.md`` Sec8.5) against this repo's own
omnist. This is the *second* runner alongside ``runner.py``'s
directory-per-fixture format (issue #286) -- the two vector shapes don't
share a natural code path, so they stay separate, sharing only
``referee.py``/``cli_runner.py``.

**Diagnostics matching mode: STRICT.** Every diagnostic list is compared as
a *set* of ``(path, code)`` pairs (Sec8.5.2, rule E-17 -- message text and
severity are never compared, no partial matching). This is the reference
implementation, so it does not use E-17 rule 4's code-agnostic escape hatch;
an earlier version of this runner did (compared ``ok`` plus the set of
paths only, and skipped any expected diagnostic that had no structured
path), which is how the reference came to pass vectors it did not satisfy
(``docs/09-divergence-ledger.md`` DIV-4). The mode is printed on every run.
There is deliberately **no runner-side "known failing" list** (E-22: a
nonzero fail count fails the build).

**Every skip is an E-20/E-21 skip with a true reason** and is tallied by
category in the run's summary:

* *E-20, not yet implemented*: the OSD-OML extension operations
  (``omnist#341``) and the safety-limit vectors (this omnist hardcodes
  ``_MAX_DEPTH`` etc. as module constants, Sec2.4 only says an
  implementation MAY expose them). The YAML alias limits are NOT skipped any
  more: ``max_alias_expansion`` (D-18) and ``max_expanded_slots`` (D-22) are
  options of ``read_yaml``, so a vector declaring ``declared_max_alias_expansion``
  or ``declared_max_expanded_slots`` runs through the library with exactly that
  value (the CLI has no flag for them) -- never against the default, which
  would be a false result. declared_max_input_bytes (D-23) is the same
  for the max_input_bytes option of every reader (any format).
* E-21 (documented divergence) is used for nothing today.

An unknown ``operation`` is a **fail**, never a skip; so is an unknown
``declared_*`` limit key (running it against this omnist's own default is
the one outcome the key exists to prevent).

**``bytes_hex`` (E-27)** vectors are presented to this implementation
through its byte-oriented entry point, the CLI (which reads the file it is
handed as bytes and decodes strictly, D-14), *never* by decoding with
replacement and running the vector as text.

Drivers (unchanged in kind): everything but ``infer`` goes through the real
CLI in ``--json`` mode; ``infer``/``infer_with_report`` drive the library
directly because the CLI's ``infer`` positional is ``nargs='+'`` and could
never reach ``infer/errors/zero-samples-is-an-error``.

Usage: python3 -m tools.conformance.vector_runner
"""
from __future__ import annotations

import collections
import datetime as _dt
import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from omnist import Doc, get_format, parse_schema, write_oml
from omnist import infer as _infer
from omnist import infer_with_report as _infer_with_report
from omnist.errors import OmnistError

from . import cli_runner
from .referee import compare_document

VECTOR_SUITE_DIR = (
    Path(__file__).resolve().parent.parent.parent / "vendor" / "omnist-spec" / "test-suite"
)

COMPARISON_MODE = "strict: diagnostics compared as (path, code) sets, Sec8.5.2 E-17"

# The three universal limits (Sec2.4) are module constants here, not
# runtime-configurable: a vector declaring one cannot be run against the
# value it declares.
_LIMIT_KEYS = {"declared_max_depth", "declared_max_nodes", "declared_max_int_digits"}
# D-18's and D-22's keys: configurable (read_yaml's max_alias_expansion and
# max_expanded_slots), so a vector carrying one runs, with that value.
_ALIAS_KEYS = {"declared_max_alias_expansion": "max_alias_expansion",
               "declared_max_expanded_slots": "max_expanded_slots"}
# D-23's key: configurable (the ``max_input_bytes`` option of every reader),
# for any format. E-20a: a key this runner does not know FAILS the vector.
_INPUT_SIZE_KEYS = {"declared_max_input_bytes": "max_input_bytes"}
_LIBRARY_KEYS = {**_ALIAS_KEYS, **_INPUT_SIZE_KEYS}

# OSD-OML extension operations (extensions/osd-oml.md Sec E.11): nothing
# implements them yet here (omnist#341).
_OSD_OML_OPS = {"parse_schema_oml", "write_schema_oml", "schema_from_document",
                "schema_to_document"}

Result = Tuple[str, str]
Pair = Tuple[Optional[str], Optional[str]]

SKIP_OSD_OML = "E-20 not yet implemented: OSD-OML extension (omnist#341)"
SKIP_LIMITS = ("E-20 not yet implemented: safety limits are module constants, "
               "not runtime-configurable (Sec2.4 MAY)")


# ---------------------------------------------------------------------------
# Canonical document encoding (Sec8.5.4) -> a raw omnist Document node
# ---------------------------------------------------------------------------

_NUMBER_SENTINELS = {"NaN": float("nan"), "Infinity": float("inf"), "-Infinity": float("-inf")}


def _decode_scalar(kind: Optional[str], value: Any) -> Any:
    if kind is None:
        return None
    if kind == "number":
        # test-suite/README.md's canonical encoding: JSON has no NaN/Infinity
        # token, so these three special values are spelled as a string
        # sentinel, not a bare JSON number -- issue #293.
        if isinstance(value, str) and value in _NUMBER_SENTINELS:
            return _NUMBER_SENTINELS[value]
        return value
    if kind in ("string", "boolean"):
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


# ---------------------------------------------------------------------------
# Diagnostics comparison (E-17)
# ---------------------------------------------------------------------------

def _pairs(diagnostics: Iterable[Dict[str, Any]], path_key: str = "path") -> Set[Pair]:
    """The set of ``(path, code)`` pairs of a diagnostic list. A diagnostic
    missing either field contributes ``None`` there, so it can never equal
    an expected pair -- it is a named mismatch, not a crash or a skip."""
    return {(d.get(path_key), d.get("code")) for d in diagnostics}


# E-32: the one path that is not compared byte for byte.
PLACEHOLDER_PATH = "line:col"
CODEC_SYNTAX = "parse.codec-syntax"
_TEXT_POSITION = re.compile(r"[1-9][0-9]*:[1-9][0-9]*")


def _apply_placeholder(exp: Set[Pair], act: Set[Pair]) -> Set[Pair]:
    """E-32: an expected ``("line:col", "parse.codec-syntax")`` is satisfied by
    a reported ``parse.codec-syntax`` whose path is a well-formed text position
    (``^[1-9][0-9]*:[1-9][0-9]*$``, so ``0:0``, a sign, a leading zero or a
    missing path all fail); nothing closer is compared. Returns ``act`` with
    that reported pair rewritten to the placeholder, so the usual set
    comparison (E-17: none missing, none extra) then decides. Applies only when
    the placeholder is the vector's only diagnostic (E-32a); anywhere else it
    is a literal string no real path equals."""
    if exp != {(PLACEHOLDER_PATH, CODEC_SYNTAX)} or len(act) != 1:
        return act      # a second diagnostic is an extra one (E-17 rule 3): never rewritten
    ((path, code),) = act
    if code == CODEC_SYNTAX and isinstance(path, str) and _TEXT_POSITION.fullmatch(path):
        return {(PLACEHOLDER_PATH, CODEC_SYNTAX)}
    # the literal string "line:col" is not a position, so it must not satisfy itself
    return {(f"!{path}", code)}


def _diff(expected: Iterable[Dict[str, Any]], actual: Iterable[Dict[str, Any]],
          path_key: str = "path") -> Optional[Result]:
    """``None`` when the two lists are equal as (path, code) sets, else a
    ``fail`` result naming both sets."""
    exp, act = _pairs(expected, path_key), _pairs(actual, path_key)
    act = _apply_placeholder(exp, act)
    if exp == act:
        return None
    return "fail", (f"diagnostics differ as (path, code) sets: expected {sorted(exp, key=str)}, "
                    f"got {sorted(act, key=str)}")


def _json_or_none(text: str) -> Optional[Any]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _expect_failure(expect: Dict[str, Any], stdout: str, stderr: str, code: int) -> Result:
    """A vector expecting ``ok: false``: the command must fail AND report
    (in ``--json`` mode, on stdout) exactly the expected (path, code) set."""
    if code == 0:
        return "fail", "expected failure, command succeeded"
    payload = _json_or_none(stdout)
    if not isinstance(payload, dict):
        return "fail", (f"expected a --json failure payload, got exit {code}, "
                        f"stdout {stdout!r}, stderr {stderr.strip()!r}")
    if payload.get("ok") is not False:
        return "fail", f"expected ok=false, got {payload.get('ok')!r}"
    mismatch = _diff(expect.get("diagnostics", []), payload.get("errors", []))
    return mismatch or ("pass", "ok")


def _report_diagnostics(expect: Dict[str, Any], stderr: Optional[str]) -> Optional[Result]:
    """Success-path diagnostics (warnings) come from the ``--report`` JSON on
    stderr. Compared strictly: absent ``expect.diagnostics`` means none.

    ``stderr=None`` is an operation whose CLI has no success-path diagnostics
    channel: it reports none, so a vector that expects some fails rather than
    going unchecked (omnist#350). Every ``ok: true`` driver ends here."""
    if stderr is None:
        return _diff(expect.get("diagnostics", []), [])
    report = _json_or_none(stderr)
    if not isinstance(report, list):
        return "fail", f"non-JSON stderr report: {stderr!r}"
    return _diff(expect.get("diagnostics", []), report)


# ---------------------------------------------------------------------------
# Input presentation
# ---------------------------------------------------------------------------

def _write_tmp(dir_: Path, name: str, text: str) -> Path:
    p = dir_ / name
    p.write_text(text, encoding="utf-8")
    return p


def _write_input(v: Dict[str, Any], dir_: Path, name: str) -> Path:
    """Materialise a read-side vector's source (``text`` xor ``bytes_hex``,
    E-27) as a file the CLI will read. ``bytes_hex`` is decoded to raw bytes
    and written unchanged: no decoding, no replacement, no normalisation."""
    inp = v["input"]
    if ("text" in inp) == ("bytes_hex" in inp):
        raise ValueError("E-27: exactly one of `text` and `bytes_hex` must be present")
    p = dir_ / name
    if "bytes_hex" in inp:
        p.write_bytes(bytes.fromhex(inp["bytes_hex"]))
    else:
        p.write_bytes(inp["text"].encode("utf-8"))
    return p


# ---------------------------------------------------------------------------
# Operation drivers -- one function per operation, each (vector, tmp_dir) -> Result
# ---------------------------------------------------------------------------

def _run_parse_library_limits(v: Dict[str, Any]) -> Result:
    """A vector declaring ``declared_max_alias_expansion`` and/or
    ``declared_max_expanded_slots`` (D-18, D-22: YAML text) or
    ``declared_max_input_bytes`` (D-23: any format): driven through the
    library with exactly the declared maxima, because the CLI has no flag for
    them. An undeclared one keeps its default."""
    inp, expect = v["input"], v["expect"]
    if "text" not in inp:
        raise ValueError("a library-limit vector is text")
    if _ALIAS_KEYS.keys() & inp.keys() and inp["format"] != "yaml":
        raise ValueError("an alias-limit vector is YAML text")
    options = {opt: inp[key] for key, opt in _LIBRARY_KEYS.items() if key in inp}
    try:
        node = get_format(inp["format"]).read(inp["text"], **options)
    except OmnistError as exc:
        if expect["ok"]:
            return "fail", f"expected success, got {exc}"
        actual = [{"path": getattr(exc, "path", None), "code": getattr(exc, "code", None)}]
        return _diff(expect.get("diagnostics", []), actual) or ("pass", "ok")
    if not expect["ok"]:
        return "fail", "expected failure, the read succeeded"
    if not compare_document(write_oml(node), write_oml(decode_document(expect["document"]))):
        return "fail", "parsed document does not match expected"
    return "pass", "ok"


def run_parse(v: Dict[str, Any], tmp: Path) -> Result:
    inp = v["input"]
    expect = v["expect"]
    fmt = inp["format"]
    if _LIBRARY_KEYS.keys() & inp.keys():
        return _run_parse_library_limits(v)
    src = _write_input(v, tmp, "in." + fmt)
    if fmt == "oml":
        args = ["format", str(src), "--json"]
    else:
        args = ["convert", str(src), "--from", fmt, "--to", "oml", "--json"]
        if expect["ok"]:
            # format.attribute-dropped / format.namespace-dropped (Sec8.3.8):
            # a *successful* parse can still carry warning-severity
            # diagnostics -- --report surfaces them on stderr as JSON.
            args += ["--report", "--result-format", "json"]
    stdout, stderr, code = cli_runner._run(args)
    if not expect["ok"]:
        return _expect_failure(expect, stdout, stderr, code)
    if code != 0:
        return "fail", f"expected success, got exit {code}: {stderr.strip()}"
    if not compare_document(stdout, write_oml(decode_document(expect["document"]))):
        return "fail", "parsed document does not match expected"
    return _report_diagnostics(expect, stderr if fmt != "oml" else None) or ("pass", "ok")


def run_parse_schema(v: Dict[str, Any], tmp: Path) -> Result:
    expect = v["expect"]
    src = _write_input(v, tmp, "in.osd")
    stdout, stderr, code = cli_runner._run(["schema", "format", str(src), "--json"])
    if not expect["ok"]:
        return _expect_failure(expect, stdout, stderr, code)
    if code != 0:
        return "fail", f"expected success, got exit {code}: {stderr.strip()}"
    if "schema" in expect and not _canonical_equal(stdout, expect["schema"]):
        return "fail", f"expected canonical {expect['schema']!r}, got {stdout!r}"
    return _report_diagnostics(expect, None) or ("pass", "ok")


def run_validate(v: Dict[str, Any], tmp: Path) -> Result:
    inp = v["input"]
    expect = v["expect"]
    schema_f = _write_tmp(tmp, "s.osd", inp["schema"])
    doc_f = _write_tmp(tmp, "d.oml", write_oml(decode_document(inp["document"])))
    stdout, stderr, code = cli_runner.validate(doc_f, schema_f)
    if not expect["ok"]:
        return _expect_failure(expect, stdout, stderr, code)
    payload = _json_or_none(stdout)
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        return "fail", f"expected ok=true, got exit {code}, stdout {stdout!r}"
    return _report_diagnostics(expect, None) or ("pass", "ok")


def run_materialize(v: Dict[str, Any], tmp: Path) -> Result:
    inp = v["input"]
    expect = v["expect"]
    schema_f = _write_tmp(tmp, "s.osd", inp["schema"])
    doc_f = _write_tmp(tmp, "d.oml", write_oml(decode_document(inp["document"])))
    stdout, stderr, code = cli_runner.materialize(doc_f, schema_f)
    if not expect["ok"]:
        return _expect_failure(expect, stdout, stderr, code)
    if code != 0:
        return "fail", f"expected success, got exit {code}: {stderr.strip()}"
    if not compare_document(stdout, write_oml(decode_document(expect["document"]))):
        return "fail", "materialized document does not match expected"
    return _report_diagnostics(expect, stderr) or ("pass", "ok")


def _normalize_xml_whitespace(text: str) -> str:
    """Sec8.5.3 (E-18): strip whitespace strictly between '>' and '<' before
    comparing a write vector's expected/actual text for XML. Safe because an
    omnist writer never produces mixed-content XML (Document model Sec2: a
    node has either child edges or one scalar value, never both), so this
    whitespace can only ever be inter-tag formatting, never real text data.
    """
    return re.sub(r">\s+<", "><", text)


def run_write(v: Dict[str, Any], tmp: Path) -> Result:
    inp = v["input"]
    expect = v["expect"]
    doc_f = _write_tmp(tmp, "d.oml", write_oml(decode_document(inp["document"])))
    fmt = inp["format"]
    if fmt == "oml":
        # mirrors run_parse's own oml special-case: the CLI explicitly
        # refuses `convert --from oml --to oml` ("use omnist format
        # instead") -- issue #293.
        args = ["format", str(doc_f), "--json"]
    else:
        args = ["convert", str(doc_f), "--from", "oml", "--to", fmt, "--json",
                "--report", "--result-format", "json"]
    if inp.get("strict"):
        args.append("--strict")
    stdout, stderr, code = cli_runner._run(args)
    if not expect["ok"]:
        return _expect_failure(expect, stdout, stderr, code)
    if code != 0:
        return "fail", f"expected success, got exit {code}: {stderr.strip()}"
    if "text" in expect:
        got, want = stdout.strip(), expect["text"].strip()
        if fmt == "xml":
            got, want = _normalize_xml_whitespace(got), _normalize_xml_whitespace(want)
        if got != want:
            return "fail", f"expected text {expect['text']!r}, got {stdout.strip()!r}"
    return _report_diagnostics(expect, stderr if fmt != "oml" else None) or ("pass", "ok")


def _canonical_equal(actual: str, expected: str) -> bool:
    """``canonical`` (Sec8.5.3, 3.3/5.9): the implementation's canonical output
    text against the expected text, byte for byte, no re-parse and no
    whitespace normalised -- the trailing newline is part of the text."""
    return actual == expected


def _run_schema_producing(v: Dict[str, Any], tmp: Path, cli_fn: Any) -> Result:
    schema_f = _write_tmp(tmp, "s.osd", v["input"]["schema"])
    stdout, stderr, code = cli_fn(schema_f)
    if code != 0:
        return "fail", f"exit {code}: {stderr.strip()}"
    if _canonical_equal(stdout, v["expect"]["schema"]):
        return "pass", "ok"
    return "fail", "output schema does not match expected canonical text"


def run_normalize(v: Dict[str, Any], tmp: Path) -> Result:
    return _run_schema_producing(v, tmp, cli_runner.normalize)


def run_prune(v: Dict[str, Any], tmp: Path) -> Result:
    return _run_schema_producing(v, tmp, cli_runner.prune)


def _check_bool(stdout: str, expect_val: bool, key: str) -> Result:
    payload = _json_or_none(stdout)
    if not isinstance(payload, dict):
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
    if not expect["ok"]:
        return _expect_failure(expect, stdout, stderr, code)
    if code != 0:
        return "fail", f"expected success, got exit {code}: {stderr.strip()}"
    if not _canonical_equal(stdout, expect["schema"]):
        return "fail", "extracted schema does not match expected canonical text"
    return _report_diagnostics(expect, None) or ("pass", "ok")


def run_lint(v: Dict[str, Any], tmp: Path) -> Result:
    schema_f = _write_tmp(tmp, "s.osd", v["input"]["schema"])
    stdout, stderr, code = cli_runner.lint(schema_f)
    payload = _json_or_none(stdout)
    if not isinstance(payload, dict):
        return "fail", f"non-JSON stdout: {stdout!r}"
    expect = v["expect"]
    if payload.get("ok") != expect["ok"]:
        return "fail", f"expected ok={expect['ok']}, got {payload.get('ok')}"
    # findings carry (code, location) where diagnostics carry (code, path);
    # severity is never compared (E-17).
    mismatch = _diff(expect["findings"], payload.get("findings", []), path_key="location")
    return mismatch or ("pass", "ok")


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
        actual = [{"path": getattr(exc, "path", None), "code": getattr(exc, "code", None)}]
        mismatch = _diff(expect.get("diagnostics", []), actual)
        return mismatch or ("pass", "ok")
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


def skip_reason(v: Dict[str, Any]) -> Optional[str]:
    """The E-20/E-21 reason this vector cannot be run, or ``None``. Every
    reason is true of *every* vector it is returned for: the OSD-OML
    operations are unimplemented, and a vector declaring a limit cannot be
    run against a value this omnist cannot be configured to."""
    if v["operation"] in _OSD_OML_OPS:
        return SKIP_OSD_OML
    declared = {k for k in v["input"] if k.startswith("declared_")}
    if declared & _LIMIT_KEYS:
        return SKIP_LIMITS
    return None


def run_vector(v: Dict[str, Any]) -> Result:
    op = v["operation"]
    unknown = {k for k in v["input"]
               if k.startswith("declared_") and k not in _LIMIT_KEYS | _LIBRARY_KEYS.keys()}
    if unknown:
        return "fail", (f"unknown declared-limit key(s) {sorted(unknown)}: teach the runner "
                        "(running against this omnist's default would be a false result)")
    ignored = sorted(_LIBRARY_KEYS.keys() & v["input"].keys()) if op != "parse" else []
    if ignored:
        # E-20a: only the `parse` driver passes these to a reader; any other
        # operation would silently run against the default and could pass.
        return "fail", (f"declared-limit key(s) {ignored} on operation {op!r}, whose driver "
                        "does not honour them: teach the runner (E-20a)")
    reason = skip_reason(v)
    if reason is not None:
        return "skip", reason
    fn = RUNNERS.get(op)
    if fn is None:
        return "fail", f"unknown operation {op!r}: no driver (a skip would hide it)"
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

    mismatch = cli_runner.check_version()
    if mismatch:
        print(mismatch, file=sys.stderr)
        return 2

    print(f"comparison mode: {COMPARISON_MODE}")
    passed = failed = skipped = 0
    skip_tally: "collections.Counter[str]" = collections.Counter()
    for v in iter_vectors():
        status, message = run_vector(v)
        print(f"[{status.upper()}] {v['name']}: {message}")
        if status == "pass":
            passed += 1
        elif status == "skip":
            skipped += 1
            skip_tally[message] += 1
        else:
            failed += 1

    total = passed + failed + skipped
    print("\nskips by reason:")
    for reason, n in sorted(skip_tally.items()):
        print(f"  {n:3d}  {reason}")
    print(f"\n{passed} passed, {failed} failed, {skipped} skipped (of {total} vectors) "
          f"-- comparison mode: {COMPARISON_MODE}")
    return 1 if failed else 0


if __name__ == "__main__":  # pragma: no cover -- entry point, not importable behavior
    raise SystemExit(main(sys.argv[1:]))
