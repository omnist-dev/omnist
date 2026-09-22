"""Unit tests for tools/conformance/vector_runner.py (issues #286, #343) --
exercises the JSON-vector envelope's own dispatch/decode/compare logic
against synthetic vectors and a monkeypatched CLI, so this suite runs
without the vendor/omnist-spec submodule needing to be checked out. The
submodule's real vectors are exercised separately by the conformance CI job.

The runner is STRICT: diagnostics compare as (path, code) sets (E-17).
Every test below that touches a diagnostic therefore has a "right code,
wrong path" and a "right path, wrong code" case somewhere -- a
code-agnostic comparison would pass one of them, and that is the mode this
runner used to run in.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tools.conformance.vector_runner as vr  # noqa: E402


@pytest.fixture
def cli(monkeypatch):
    """Replace the CLI with a fake returning ``(stdout, stderr, code)``, and
    record the argv it was called with in ``seen``."""
    seen: dict = {}
    state = {"reply": ("", "", 0)}

    def fake(args, stdin_text=None):
        seen["args"] = args
        return state["reply"]

    monkeypatch.setattr(vr.cli_runner, "_run", fake)

    def set_reply(stdout="", stderr="", code=0):
        state["reply"] = (stdout, stderr, code)
        return seen

    set_reply.seen = seen  # type: ignore[attr-defined]
    return set_reply


def failure_payload(*pairs, ok=False):
    return json.dumps({"ok": ok, "message": "m", "errors": [
        {"path": p, "code": c, "message": "m"} for p, c in pairs]})


OML_ONE = {"edges": [["a", {"scalar": {"kind": "integer", "value": 1}}]]}
SCHEMA = "record R {\n    \"a\": integer,\n}\nroot R\n"


# --------------------------------------------------------------- decoding

def test_decode_scalar_all_kinds():
    assert vr._decode_scalar(None, None) is None
    assert vr._decode_scalar("string", "x") == "x"
    assert vr._decode_scalar("boolean", True) is True
    assert vr._decode_scalar("number", 1.5) == 1.5
    assert vr._decode_scalar("integer", 3) == 3
    assert vr._decode_scalar("integer", "3") == 3
    assert vr._decode_scalar("date", "2024-01-01").isoformat() == "2024-01-01"
    assert vr._decode_scalar("time", "12:00:00").isoformat() == "12:00:00"
    assert vr._decode_scalar("datetime", "2024-01-01T12:00:00").isoformat() == \
        "2024-01-01T12:00:00"


def test_decode_scalar_number_sentinels():
    import math
    assert math.isnan(vr._decode_scalar("number", "NaN"))
    assert vr._decode_scalar("number", "Infinity") == float("inf")
    assert vr._decode_scalar("number", "-Infinity") == float("-inf")
    assert vr._decode_scalar("number", "not-a-sentinel") == "not-a-sentinel"


def test_decode_scalar_unknown_kind_raises():
    with pytest.raises(ValueError, match="unknown scalar kind"):
        vr._decode_scalar("bogus", "x")


def test_decode_document():
    assert vr.decode_document({"scalar": {"kind": "integer", "value": 1}}) == 1
    assert vr.decode_document(OML_ONE) == [("a", 1)]


# ------------------------------------------------- diagnostics comparison

def test_pairs_is_a_set_of_path_and_code():
    assert vr._pairs([{"path": "$.a", "code": "c1", "message": "x"},
                      {"path": "$.a", "code": "c1"}]) == {("$.a", "c1")}


def test_pairs_missing_fields_become_none_never_a_crash():
    assert vr._pairs([{"code": "c"}, {"path": "p"}]) == {(None, "c"), ("p", None)}


def test_pairs_can_read_a_different_path_key():
    assert vr._pairs([{"location": "R.a", "code": "c"}], "location") == {("R.a", "c")}


def test_diff_equal_sets_is_none_regardless_of_order_and_message():
    exp = [{"path": "a", "code": "c1"}, {"path": "b", "code": "c2"}]
    act = [{"path": "b", "code": "c2", "message": "zzz"}, {"path": "a", "code": "c1"}]
    assert vr._diff(exp, act) is None


def test_diff_right_path_wrong_code_fails():
    status, msg = vr._diff([{"path": "a", "code": "c1"}], [{"path": "a", "code": "c2"}])
    assert status == "fail" and "c1" in msg and "c2" in msg


def test_diff_right_code_wrong_path_fails():
    status, _ = vr._diff([{"path": "a", "code": "c1"}], [{"path": "b", "code": "c1"}])
    assert status == "fail"


def test_diff_no_partial_matching():
    exp = [{"path": "a", "code": "c1"}]
    act = [{"path": "a", "code": "c1"}, {"path": "b", "code": "c2"}]
    assert vr._diff(exp, act)[0] == "fail"       # an unexpected extra
    assert vr._diff(act, exp)[0] == "fail"       # an expected one missing


def test_diff_missing_code_never_matches_an_expected_one():
    assert vr._diff([{"path": "a", "code": "c1"}], [{"path": "a"}])[0] == "fail"


# ---------------------------------------------------------- _expect_failure

def test_expect_failure_command_succeeded():
    status, msg = vr._expect_failure({"diagnostics": []}, "", "", 0)
    assert status == "fail" and "command succeeded" in msg


def test_expect_failure_crash_without_a_json_payload_is_a_fail():
    status, msg = vr._expect_failure({"diagnostics": []}, "", "Traceback ...", 1)
    assert status == "fail" and "Traceback" in msg


def test_expect_failure_payload_must_be_an_object():
    status, msg = vr._expect_failure({"diagnostics": []}, "[1]", "", 2)
    assert status == "fail" and "--json failure payload" in msg


def test_expect_failure_ok_must_be_false():
    status, msg = vr._expect_failure({"diagnostics": []}, json.dumps({"ok": True}), "", 2)
    assert status == "fail" and "ok=false" in msg


def test_expect_failure_matches_and_mismatches():
    exp = {"diagnostics": [{"path": "1:1", "code": "parse.invalid-encoding"}]}
    good = failure_payload(("1:1", "parse.invalid-encoding"))
    assert vr._expect_failure(exp, good, "", 2) == ("pass", "ok")
    assert vr._expect_failure(exp, failure_payload(("1:1", "parse.syntax")), "", 2)[0] == "fail"
    assert vr._expect_failure(exp, failure_payload(), "", 2)[0] == "fail"


def test_expect_failure_without_a_diagnostics_key_expects_none():
    # E-17: no unexpected diagnostic may be present.
    assert vr._expect_failure({}, failure_payload(), "", 2) == ("pass", "ok")
    assert vr._expect_failure({}, failure_payload(("$", "x")), "", 2)[0] == "fail"


def test_report_diagnostics():
    assert vr._report_diagnostics({}, "not json")[0] == "fail"
    assert vr._report_diagnostics({}, '{"a": 1}')[0] == "fail"
    assert vr._report_diagnostics({}, "[]") is None
    exp = {"diagnostics": [{"path": "$.d", "code": "format.temporal-stringified"}]}
    assert vr._report_diagnostics(
        exp, json.dumps([{"path": "$.d", "code": "format.temporal-stringified"}])) is None
    assert vr._report_diagnostics(
        exp, json.dumps([{"path": "$.d", "code": "temporal.stringified"}]))[0] == "fail"
    # unexpected warnings on a vector that expects none are a mismatch too
    assert vr._report_diagnostics(
        {}, json.dumps([{"path": "$", "code": "c"}]))[0] == "fail"


# ---------------------------------------------------------------- inputs

def test_write_input_text_is_utf8(tmp_path):
    p = vr._write_input({"input": {"text": "é"}}, tmp_path, "in.json")
    assert p.read_bytes() == "é".encode()


def test_write_input_bytes_hex_is_written_unchanged_and_never_decoded(tmp_path):
    p = vr._write_input({"input": {"bytes_hex": "7b22e2"}}, tmp_path, "in.json")
    assert p.read_bytes() == b'{"\xe2'          # not valid UTF-8, and left that way


def test_write_input_empty_bytes_is_a_legal_input(tmp_path):
    assert vr._write_input({"input": {"bytes_hex": ""}}, tmp_path, "in").read_bytes() == b""


@pytest.mark.parametrize("inp", [{"text": "a", "bytes_hex": "61"}, {}])
def test_write_input_exactly_one_of_text_and_bytes_hex(tmp_path, inp):
    with pytest.raises(ValueError, match="E-27"):
        vr._write_input({"input": inp}, tmp_path, "in")


# ------------------------------------------------------------------ parse

def test_run_parse_oml_success_uses_format(tmp_path, cli):
    seen = cli("a: 1\n", "", 0)
    v = {"input": {"format": "oml", "text": "a: 1\n"}, "expect": {"ok": True, "document": OML_ONE}}
    assert vr.run_parse(v, tmp_path) == ("pass", "ok")
    assert seen["args"][0] == "format" and "--json" in seen["args"]


def test_run_parse_codec_success_asks_for_the_report(tmp_path, cli):
    seen = cli("a: 1\n", "[]", 0)
    v = {"input": {"format": "json", "text": '{"a":1}'},
         "expect": {"ok": True, "document": OML_ONE}}
    assert vr.run_parse(v, tmp_path) == ("pass", "ok")
    assert seen["args"][0] == "convert" and "--report" in seen["args"]


def test_run_parse_success_with_expected_diagnostics(tmp_path, cli):
    report = json.dumps([{"path": "$.a", "code": "format.attribute-dropped"}])
    cli('a: "1"\n', report, 0)
    doc = {"edges": [["a", {"scalar": {"kind": "string", "value": "1"}}]]}
    v = {"input": {"format": "xml", "text": '<a x="1">1</a>'},
         "expect": {"ok": True, "document": doc,
                    "diagnostics": [{"path": "$.a", "code": "format.attribute-dropped"}]}}
    assert vr.run_parse(v, tmp_path) == ("pass", "ok")
    v["expect"]["diagnostics"][0]["code"] = "format.namespace-dropped"
    assert vr.run_parse(v, tmp_path)[0] == "fail"


def test_run_parse_success_with_unexpected_warning_fails(tmp_path, cli):
    cli("a: 1\n", json.dumps([{"path": "$", "code": "format.attribute-dropped"}]), 0)
    v = {"input": {"format": "xml", "text": "<a/>"}, "expect": {"ok": True, "document": OML_ONE}}
    assert vr.run_parse(v, tmp_path)[0] == "fail"


def test_run_parse_expected_success_but_command_failed(tmp_path, cli):
    cli("", "boom", 2)
    v = {"input": {"format": "oml", "text": "x"}, "expect": {"ok": True, "document": OML_ONE}}
    status, msg = vr.run_parse(v, tmp_path)
    assert status == "fail" and "expected success" in msg


def test_run_parse_document_mismatch(tmp_path, cli):
    cli("a: 2\n", "", 0)
    v = {"input": {"format": "oml", "text": "a: 1"}, "expect": {"ok": True, "document": OML_ONE}}
    assert vr.run_parse(v, tmp_path) == ("fail", "parsed document does not match expected")


def test_run_parse_failure_compares_path_and_code(tmp_path, cli):
    v = {"input": {"format": "oml", "text": "a: 1 b: 2"},
         "expect": {"ok": False, "diagnostics": [
             {"path": "1:6", "code": "parse.trailing-content"}]}}
    cli(failure_payload(("1:6", "parse.trailing-content")), "", 2)
    assert vr.run_parse(v, tmp_path) == ("pass", "ok")
    cli(failure_payload(("1:6", "parse.unexpected-token")), "", 2)     # right path, wrong code
    assert vr.run_parse(v, tmp_path)[0] == "fail"
    cli(failure_payload(("1:7", "parse.trailing-content")), "", 2)     # right code, wrong path
    assert vr.run_parse(v, tmp_path)[0] == "fail"


def test_run_parse_syntax_failure_with_no_structured_diagnostic_is_a_fail_not_a_skip(
        tmp_path, cli):
    cli(failure_payload(), "", 2)      # what a coded-less ParseError used to look like
    v = {"input": {"format": "json", "text": "{"},
         "expect": {"ok": False, "diagnostics": [{"path": "1:2", "code": "parse.codec-syntax"}]}}
    assert vr.run_parse(v, tmp_path)[0] == "fail"


def test_run_parse_bytes_hex_goes_to_the_cli_as_raw_bytes(tmp_path, monkeypatch):
    """E-27/D-14: the bytes are handed to the CLI (the byte-oriented entry
    point) unchanged -- never decoded with replacement and run as text."""
    read = {}

    def fake(args, stdin_text=None):
        read["bytes"] = Path(args[1]).read_bytes()
        return failure_payload(("1:1", "parse.invalid-encoding")), "", 2

    monkeypatch.setattr(vr.cli_runner, "_run", fake)
    v = {"input": {"format": "json", "bytes_hex": "7b2261223a2278e282227d"},
         "expect": {"ok": False,
                    "diagnostics": [{"path": "1:1", "code": "parse.invalid-encoding"}]}}
    assert vr.run_parse(v, tmp_path) == ("pass", "ok")
    assert read["bytes"] == bytes.fromhex("7b2261223a2278e282227d")
    assert b"\xef\xbf\xbd" not in read["bytes"]      # no U+FFFD anywhere


# ----------------------------------------------------------- parse_schema

def test_run_parse_schema_success(tmp_path, cli):
    cli(SCHEMA, "", 0)
    assert vr.run_parse_schema({"input": {"text": SCHEMA}, "expect": {"ok": True}},
                               tmp_path) == ("pass", "ok")


def test_run_parse_schema_canonical_output_is_compared_byte_for_byte(tmp_path, cli):
    cli(SCHEMA, "", 0)
    v = {"input": {"text": SCHEMA}, "expect": {"ok": True, "schema": SCHEMA}}
    assert vr.run_parse_schema(v, tmp_path) == ("pass", "ok")
    v["expect"]["schema"] = SCHEMA.replace('"a"', '"b"')
    status, msg = vr.run_parse_schema(v, tmp_path)
    assert status == "fail" and "canonical" in msg


def test_run_parse_schema_expected_success_but_failed(tmp_path, cli):
    cli("", "boom", 2)
    status, msg = vr.run_parse_schema({"input": {"text": "x"}, "expect": {"ok": True}}, tmp_path)
    assert status == "fail" and "expected success" in msg


def test_run_parse_schema_failure_is_strict(tmp_path, cli):
    v = {"input": {"text": "x"},
         "expect": {"ok": False, "diagnostics": [{"path": "R.a", "code": "schema.nullable-ref"}]}}
    cli(failure_payload(("R.a", "schema.nullable-ref")), "", 2)
    assert vr.run_parse_schema(v, tmp_path) == ("pass", "ok")
    cli(failure_payload(("A", "schema.nullable-ref")), "", 2)
    assert vr.run_parse_schema(v, tmp_path)[0] == "fail"


def test_run_parse_schema_bytes_hex(tmp_path, cli):
    seen = cli(failure_payload(("1:1", "parse.invalid-encoding")), "", 2)
    v = {"input": {"bytes_hex": "80"},
         "expect": {"ok": False,
                    "diagnostics": [{"path": "1:1", "code": "parse.invalid-encoding"}]}}
    assert vr.run_parse_schema(v, tmp_path) == ("pass", "ok")
    assert seen["args"][:2] == ["schema", "format"]


# --------------------------------------------------------------- validate

def test_run_validate(tmp_path, cli):
    v = {"input": {"schema": SCHEMA, "document": OML_ONE}, "expect": {"ok": True}}
    cli(json.dumps({"ok": True}), "", 0)
    assert vr.run_validate(v, tmp_path) == ("pass", "ok")
    cli("not json", "", 2)
    assert vr.run_validate(v, tmp_path)[0] == "fail"
    cli(json.dumps({"ok": False}), "", 1)
    assert vr.run_validate(v, tmp_path)[0] == "fail"


def test_run_validate_failure_is_strict(tmp_path, cli):
    v = {"input": {"schema": SCHEMA, "document": OML_ONE},
         "expect": {"ok": False,
                    "diagnostics": [{"path": "$.a", "code": "validate.type-mismatch"}]}}
    cli(failure_payload(("$.a", "validate.type-mismatch")), "", 1)
    assert vr.run_validate(v, tmp_path) == ("pass", "ok")
    cli(failure_payload(("$.a", "validate.shape-mismatch")), "", 1)
    assert vr.run_validate(v, tmp_path)[0] == "fail"


# ------------------------------------------------------------ materialize

def test_run_materialize_success(tmp_path, cli):
    v = {"input": {"schema": SCHEMA, "document": OML_ONE},
         "expect": {"ok": True, "document": OML_ONE}}
    cli("a: 1\n", "", 0)
    assert vr.run_materialize(v, tmp_path) == ("pass", "ok")
    cli("a: 2\n", "", 0)
    assert vr.run_materialize(v, tmp_path)[0] == "fail"
    cli("", "boom", 2)
    status, msg = vr.run_materialize(v, tmp_path)
    assert status == "fail" and "expected success" in msg


def test_run_materialize_failure_is_strict(tmp_path, cli):
    v = {"input": {"schema": SCHEMA, "document": OML_ONE},
         "expect": {"ok": False, "diagnostics": [
             {"path": "$.n", "code": "materialize.inexact-conversion"}]}}
    cli(failure_payload(("$.n", "materialize.inexact-conversion")), "", 2)
    assert vr.run_materialize(v, tmp_path) == ("pass", "ok")
    cli(failure_payload(("$.n", "validate.type-mismatch")), "", 2)
    assert vr.run_materialize(v, tmp_path)[0] == "fail"
    cli("", "", 0)
    assert vr.run_materialize(v, tmp_path)[0] == "fail"


# ------------------------------------------------------------------ write

def test_run_write_codec_success_text_and_report(tmp_path, cli):
    report = json.dumps([{"path": "$.d", "code": "format.temporal-stringified"}])
    seen = cli('{"d": "2024-01-01"}\n', report, 0)
    v = {"input": {"document": OML_ONE, "format": "json"},
         "expect": {"ok": True, "text": '{"d": "2024-01-01"}', "diagnostics": [
             {"path": "$.d", "code": "format.temporal-stringified"}]}}
    assert vr.run_write(v, tmp_path) == ("pass", "ok")
    assert seen["args"][0] == "convert" and "--json" in seen["args"]
    v["expect"]["diagnostics"][0]["code"] = "temporal.stringified"     # the old spelling
    assert vr.run_write(v, tmp_path)[0] == "fail"


def test_run_write_oml_uses_format_and_passes_strict(tmp_path, cli):
    seen = cli("a: 1\n", "", 0)
    v = {"input": {"document": OML_ONE, "format": "oml", "strict": True},
         "expect": {"ok": True, "text": "a: 1"}}
    assert vr.run_write(v, tmp_path) == ("pass", "ok")
    assert seen["args"][0] == "format" and "--strict" in seen["args"]


def test_run_write_strict_flag_reaches_a_codec(tmp_path, cli):
    seen = cli("{}\n", "[]", 0)
    v = {"input": {"document": OML_ONE, "format": "json", "strict": True},
         "expect": {"ok": True, "text": "{}"}}
    vr.run_write(v, tmp_path)
    assert "--strict" in seen["args"]


def test_run_write_failure_is_strict(tmp_path, cli):
    v = {"input": {"document": OML_ONE, "format": "xml"},
         "expect": {"ok": False,
                    "diagnostics": [{"path": "$", "code": "format.multiple-roots"}]}}
    cli(failure_payload(("$", "format.multiple-roots")), "", 2)
    assert vr.run_write(v, tmp_path) == ("pass", "ok")
    cli(failure_payload(("$", "write.unsupported-value")), "", 2)
    assert vr.run_write(v, tmp_path)[0] == "fail"


def test_run_write_expected_success_but_failed_or_text_differs(tmp_path, cli):
    v = {"input": {"document": OML_ONE, "format": "json"},
         "expect": {"ok": True, "text": "{}"}}
    cli("", "boom", 2)
    assert "expected success" in vr.run_write(v, tmp_path)[1]
    cli('{"a": 1}\n', "[]", 0)
    assert vr.run_write(v, tmp_path)[0] == "fail"


def test_run_write_without_expected_text_still_checks_the_report(tmp_path, cli):
    v = {"input": {"document": OML_ONE, "format": "json"}, "expect": {"ok": True}}
    cli("{}\n", "[]", 0)
    assert vr.run_write(v, tmp_path) == ("pass", "ok")
    cli("{}\n", json.dumps([{"path": "$", "code": "format.interleaving-lost"}]), 0)
    assert vr.run_write(v, tmp_path)[0] == "fail"


def test_run_write_xml_whitespace_between_tags_is_normalised():
    assert vr._normalize_xml_whitespace("<a>\n  <b>x y</b>\n</a>") == "<a><b>x y</b></a>"


def test_run_write_xml_compares_modulo_inter_tag_whitespace(tmp_path, cli):
    cli("<a>\n  <b>x</b>\n</a>\n", "[]", 0)
    v = {"input": {"document": OML_ONE, "format": "xml"},
         "expect": {"ok": True, "text": "<a><b>x</b></a>"}}
    assert vr.run_write(v, tmp_path) == ("pass", "ok")
    v["expect"]["text"] = "<a><b>x  </b></a>"      # real text data is not touched
    assert vr.run_write(v, tmp_path)[0] == "fail"


# ------------------------------------------------- schema-producing ops

@pytest.mark.parametrize("fn", ["run_normalize", "run_prune"])
def test_run_schema_producing(tmp_path, cli, fn):
    v = {"input": {"schema": SCHEMA}, "expect": {"schema": SCHEMA}}
    cli(SCHEMA, "", 0)
    assert getattr(vr, fn)(v, tmp_path) == ("pass", "ok")
    cli("", "boom", 2)
    assert "exit 2" in getattr(vr, fn)(v, tmp_path)[1]
    cli(SCHEMA.replace("integer", "string"), "", 0)
    assert "does not match" in getattr(vr, fn)(v, tmp_path)[1]


def test_run_booleans(tmp_path, cli):
    schema = {"schema": SCHEMA}
    cli(json.dumps({"empty": False}), "", 1)
    assert vr.run_is_empty(
        {"input": schema, "expect": {"empty": False}}, tmp_path) == ("pass", "ok")
    cli(json.dumps({"compatible": True}), "", 0)
    assert vr.run_compatible_with({"input": {"a": SCHEMA, "b": SCHEMA},
                                   "expect": {"result": True}}, tmp_path) == ("pass", "ok")
    cli(json.dumps({"equivalent": False}), "", 1)
    status, msg = vr.run_equivalent({"input": {"a": SCHEMA, "b": SCHEMA},
                                     "expect": {"result": True}}, tmp_path)
    assert status == "fail" and "expected equivalent=True" in msg


def test_check_bool_non_json_and_non_object():
    assert "non-JSON" in vr._check_bool("not json", True, "empty")[1]
    assert "non-JSON" in vr._check_bool("[]", True, "empty")[1]


# ---------------------------------------------------------------- extract

def test_run_extract(tmp_path, cli):
    v = {"input": {"schema": SCHEMA, "keep": ["a"]}, "expect": {"ok": True, "schema": SCHEMA}}
    cli(SCHEMA, "", 0)
    assert vr.run_extract(v, tmp_path) == ("pass", "ok")
    cli(SCHEMA.replace("integer", "string"), "", 0)
    assert "does not match" in vr.run_extract(v, tmp_path)[1]
    cli("", "boom", 2)
    assert "expected success" in vr.run_extract(v, tmp_path)[1]


def test_run_extract_failure_is_strict(tmp_path, cli):
    v = {"input": {"schema": SCHEMA, "keep": []},
         "expect": {"ok": False, "diagnostics": [
             {"path": "R", "code": "algebra.extract-invalidates-root"}]}}
    cli(failure_payload(("R", "algebra.extract-invalidates-root")), "", 1)
    assert vr.run_extract(v, tmp_path) == ("pass", "ok")
    cli(failure_payload(("R", "schema.something")), "", 1)
    assert vr.run_extract(v, tmp_path)[0] == "fail"


# ------------------------------------------------------------------- lint

def _lint_reply(findings, ok=True):
    return json.dumps({"ok": ok, "findings": findings})


def test_run_lint(tmp_path, cli):
    v = {"input": {"schema": SCHEMA}, "expect": {"ok": True, "findings": []}}
    cli(_lint_reply([]), "", 0)
    assert vr.run_lint(v, tmp_path) == ("pass", "ok")
    cli("not json", "", 0)
    assert "non-JSON" in vr.run_lint(v, tmp_path)[1]
    cli("[]", "", 0)
    assert "non-JSON" in vr.run_lint(v, tmp_path)[1]
    cli(_lint_reply([], ok=False), "", 1)
    assert "expected ok" in vr.run_lint(v, tmp_path)[1]


def test_run_lint_findings_compare_location_and_code_never_severity(tmp_path, cli):
    v = {"input": {"schema": SCHEMA}, "expect": {"ok": False, "findings": [
        {"code": "lint.unreachable-record", "severity": "warning", "location": "Orphan"}]}}
    same = {"code": "lint.unreachable-record", "severity": "info", "location": "Orphan",
            "message": "whatever"}
    cli(_lint_reply([same], ok=False), "", 1)
    assert vr.run_lint(v, tmp_path) == ("pass", "ok")
    cli(_lint_reply([{**same, "code": "unreachable-record"}], ok=False), "", 1)   # bare code
    assert vr.run_lint(v, tmp_path)[0] == "fail"
    cli(_lint_reply([{**same, "location": "Other"}], ok=False), "", 1)
    assert vr.run_lint(v, tmp_path)[0] == "fail"


# ------------------------------------------------------------------ infer

def test_run_infer_success_and_shape():
    v = {"input": {"samples": ['tag: "a"\ntag: "b"\n', 'tag: "c"\n']},
         "expect": {"ok": True, "schema": 'record Root {\n    "tag" [0,]: string,\n}\nroot Root\n'}}
    assert vr.run_infer(v, Path(".")) == ("pass", "ok")
    v["expect"]["schema"] = 'record Root {\n    "tag": integer,\n}\nroot Root\n'
    assert "not isomorphic" in vr.run_infer(v, Path("."))[1]


def test_run_infer_with_report_and_allow_any():
    v = {"input": {"samples": ['tag: "a"\n', "tag: 1\n"], "allow_any": True},
         "expect": {"ok": True, "schema": 'record Root {\n    "tag": any,\n}\nroot Root\n'}}
    assert vr.run_infer_with_report(v, Path(".")) == ("pass", "ok")
    assert vr.run_infer(v, Path(".")) == ("pass", "ok")


def test_run_infer_failures_are_strict():
    v = {"input": {"samples": []},
         "expect": {"ok": False, "diagnostics": [
             {"path": "$", "code": "algebra.infer-no-samples"}]}}
    assert vr.run_infer(v, Path(".")) == ("pass", "ok")
    v["expect"]["diagnostics"][0]["code"] = "algebra.infer-scalar-root"     # wrong code
    assert vr.run_infer(v, Path("."))[0] == "fail"
    v["expect"]["diagnostics"] = [{"path": "Root", "code": "algebra.infer-no-samples"}]
    assert vr.run_infer(v, Path("."))[0] == "fail"                          # wrong path


def test_run_infer_a_failure_with_no_code_is_a_named_mismatch(monkeypatch):
    def boom(*a, **k):
        from omnist.errors import SchemaError
        raise SchemaError("uncoded")

    monkeypatch.setattr(vr, "_infer", boom)
    v = {"input": {"samples": ["a: 1\n"]},
         "expect": {"ok": False, "diagnostics": [
             {"path": "$", "code": "algebra.infer-no-samples"}]}}
    status, msg = vr.run_infer(v, Path("."))
    assert status == "fail" and "(None, None)" in msg


def test_run_infer_unexpected_failure_and_unexpected_success():
    v = {"input": {"samples": []}, "expect": {"ok": True, "schema": "record Root{}\nroot Root\n"}}
    assert "expected success" in vr.run_infer(v, Path("."))[1]
    v = {"input": {"samples": ['tag: "a"\n']}, "expect": {"ok": False}}
    assert "expected failure" in vr.run_infer(v, Path("."))[1]


# ---------------------------------------------------------------- skipping

def _v(operation, **inp):
    return {"name": "n", "operation": operation, "input": inp, "expect": {"ok": True}}


@pytest.mark.parametrize("op", sorted(vr._OSD_OML_OPS))
def test_the_osd_oml_operations_are_an_e20_skip_citing_the_tracking_issue(op):
    assert vr.skip_reason(_v(op, text="x")) == vr.SKIP_OSD_OML
    assert "omnist#341" in vr.SKIP_OSD_OML and vr.SKIP_OSD_OML.startswith("E-20")


@pytest.mark.parametrize("key", sorted(vr._LIMIT_KEYS))
def test_declared_limit_vectors_are_an_e20_skip(key):
    assert vr.skip_reason(_v("parse", format="oml", text="x", **{key: 3})) == vr.SKIP_LIMITS


def test_alias_expansion_key_is_skipped_citing_div3_never_run_against_the_default():
    v = _v("parse", format="yaml", text="a: 1", declared_max_alias_expansion=3)
    assert vr.skip_reason(v) == vr.SKIP_ALIAS and "DIV-3" in vr.SKIP_ALIAS
    assert vr.run_vector(v) == ("skip", vr.SKIP_ALIAS)


def test_an_ordinary_vector_is_not_skipped():
    assert vr.skip_reason(_v("parse", format="oml", text="x")) is None


def test_unknown_operation_is_a_fail_never_a_skip():
    status, msg = vr.run_vector(_v("bogus"))
    assert status == "fail" and "unknown operation 'bogus'" in msg


def test_unknown_declared_limit_key_is_a_fail_never_a_run_against_the_default():
    status, msg = vr.run_vector(_v("parse", format="oml", text="x", declared_max_widgets=1))
    assert status == "fail" and "declared_max_widgets" in msg


def test_driver_crash_is_reported_as_fail(monkeypatch):
    def boom(v, tmp):
        raise RuntimeError("kaboom")

    monkeypatch.setitem(vr.RUNNERS, "lint", boom)
    status, msg = vr.run_vector(_v("lint", schema="x"))
    assert status == "fail" and "kaboom" in msg


def test_a_vector_with_both_text_and_bytes_hex_is_a_fail(cli):
    cli("", "", 0)
    status, msg = vr.run_vector(_v("parse", format="oml", text="a", bytes_hex="61"))
    assert status == "fail" and "E-27" in msg


# --------------------------------------------------------------- main / CLI

def _write_suite(tmp_path, vectors):
    suite = tmp_path / "test-suite" / "grp"
    suite.mkdir(parents=True)
    (suite / "vecs.json").write_text(json.dumps({"vectors": vectors}), encoding="utf-8")
    return tmp_path / "test-suite"


def test_main_states_the_comparison_mode_and_tallies_skips(tmp_path, monkeypatch, cli, capsys):
    suite = _write_suite(tmp_path, [
        {"name": "ok-one", "operation": "lint", "input": {"schema": SCHEMA},
         "expect": {"ok": True, "findings": []}},
        {"name": "osd-oml-one", "operation": "parse_schema_oml", "input": {"text": "x"},
         "expect": {"ok": True}},
    ])
    monkeypatch.setattr(vr, "VECTOR_SUITE_DIR", suite)
    cli(_lint_reply([]), "", 0)
    assert vr.main([]) == 0
    out = capsys.readouterr().out
    assert "comparison mode: strict" in out and "(path, code) sets" in out
    assert "1 passed, 0 failed, 1 skipped (of 2 vectors)" in out
    assert "skips by reason:" in out and vr.SKIP_OSD_OML in out
    assert "[SKIP] osd-oml-one" in out


def test_main_exits_nonzero_and_names_the_failing_vector_on_a_wrong_code(
        tmp_path, monkeypatch, cli, capsys):
    """The runner bites: a code that differs from the vector's is a named FAIL
    and a nonzero exit -- there is no allowlist that could excuse it (E-22)."""
    suite = _write_suite(tmp_path, [
        {"name": "grp/wrong-code", "operation": "parse",
         "input": {"format": "oml", "text": "a: 1 b: 2"},
         "expect": {"ok": False,
                    "diagnostics": [{"path": "1:6", "code": "parse.trailing-content"}]}},
    ])
    monkeypatch.setattr(vr, "VECTOR_SUITE_DIR", suite)
    cli(failure_payload(("1:6", "parse.unexpected-token")), "", 2)
    assert vr.main([]) == 1
    out = capsys.readouterr().out
    assert "[FAIL] grp/wrong-code" in out and "parse.trailing-content" in out
    assert "1 failed" in out


def test_main_missing_submodule(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(vr, "VECTOR_SUITE_DIR", tmp_path / "does-not-exist")
    assert vr.main([]) == 2
    assert "submodule" in capsys.readouterr().err


def test_iter_vectors_walks_every_file(tmp_path, monkeypatch):
    monkeypatch.setattr(vr, "VECTOR_SUITE_DIR", _write_suite(
        tmp_path, [{"name": "a"}, {"name": "b"}]))
    assert [v["name"] for v in vr.iter_vectors()] == ["a", "b"]
