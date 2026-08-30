"""Unit tests for tools/conformance/vector_runner.py (issue #286) --
exercises the JSON-vector envelope's own dispatch/decode/compare logic
against synthetic vectors and a monkeypatched cli_runner, so this suite
runs without the vendor/omnist-spec submodule needing to be checked out.
The submodule's real 139 vectors are exercised separately by the
conformance CI job.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tools.conformance.vector_runner as vr  # noqa: E402

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
    # #293: the canonical encoding spells NaN/Infinity/-Infinity as a
    # string sentinel (JSON has no such token), never a bare JSON number.
    import math
    assert math.isnan(vr._decode_scalar("number", "NaN"))
    assert vr._decode_scalar("number", "Infinity") == float("inf")
    assert vr._decode_scalar("number", "-Infinity") == float("-inf")
    assert vr._decode_scalar("number", "not-a-sentinel") == "not-a-sentinel"


def test_decode_scalar_unknown_kind_raises():
    import pytest
    with pytest.raises(ValueError, match="unknown scalar kind"):
        vr._decode_scalar("bogus", "x")


def test_decode_document_scalar_leaf():
    assert vr.decode_document({"scalar": {"kind": "integer", "value": 1}}) == 1


def test_decode_document_edges():
    node = {"edges": [["a", {"scalar": {"kind": "string", "value": "x"}}]]}
    assert vr.decode_document(node) == [("a", "x")]


def test_paths():
    assert vr._paths([{"path": "$.a", "code": "c1"}, {"path": "$.b", "code": "c2"}]) == \
        {"$.a", "$.b"}


# ---------------------------------------------------------------- parse

def test_run_parse_skips_declared_limits(tmp_path):
    v = {"input": {"declared_max_depth": 3, "format": "oml", "text": "a: 1\n"},
         "expect": {"ok": True}}
    status, msg = vr.run_parse(v, tmp_path)
    assert status == "skip"


def test_run_parse_success_oml(tmp_path, monkeypatch):
    monkeypatch.setattr(vr.cli_runner, "_run", lambda args: ("a: 1\n", "", 0))
    v = {"input": {"format": "oml", "text": "a: 1\n"},
         "expect": {"ok": True, "document": {
             "edges": [["a", {"scalar": {"kind": "integer", "value": 1}}]]}}}
    status, msg = vr.run_parse(v, tmp_path)
    assert status == "pass"


def test_run_parse_success_non_oml_format(tmp_path, monkeypatch):
    seen = {}

    def fake_run(args):
        seen["args"] = args
        return "a: 1\n", "", 0

    monkeypatch.setattr(vr.cli_runner, "_run", fake_run)
    v = {"input": {"format": "json", "text": '{"a":1}'},
         "expect": {"ok": True, "document": {
             "edges": [["a", {"scalar": {"kind": "integer", "value": 1}}]]}}}
    status, msg = vr.run_parse(v, tmp_path)
    assert status == "pass"
    assert seen["args"][0] == "convert"


def test_run_parse_success_with_expected_diagnostics_passes(tmp_path, monkeypatch):
    # format.attribute-dropped/format.namespace-dropped (Sec8.3.8): a
    # successful parse can still carry warning-severity diagnostics, so
    # when expect.ok is true AND expect.diagnostics is present, run_parse
    # must pass --report and compare the reported paths.
    seen = {}

    def fake_run(args):
        seen["args"] = args
        return 'a: "1"\n', json.dumps([{"path": "$.a", "code": "format.attribute-dropped"}]), 0

    monkeypatch.setattr(vr.cli_runner, "_run", fake_run)
    v = {"input": {"format": "xml", "text": '<a x="1">1</a>'},
         "expect": {"ok": True,
                    "document": {"edges": [["a", {"scalar": {"kind": "string", "value": "1"}}]]},
                    "diagnostics": [{"path": "$.a", "code": "format.attribute-dropped"}]}}
    status, msg = vr.run_parse(v, tmp_path)
    assert status == "pass"
    assert "--report" in seen["args"]


def test_run_parse_success_with_diagnostics_mismatch_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(
        vr.cli_runner, "_run",
        lambda args: ('a: "1"\n', json.dumps([{"path": "$.wrong", "code": "x"}]), 0))
    v = {"input": {"format": "xml", "text": '<a x="1">1</a>'},
         "expect": {"ok": True,
                    "document": {"edges": [["a", {"scalar": {"kind": "string", "value": "1"}}]]},
                    "diagnostics": [{"path": "$.a", "code": "format.attribute-dropped"}]}}
    status, msg = vr.run_parse(v, tmp_path)
    assert status == "fail"
    assert "diagnostic paths differ" in msg


def test_run_parse_success_with_non_json_report_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(vr.cli_runner, "_run", lambda args: ('a: "1"\n', "not json", 0))
    v = {"input": {"format": "xml", "text": '<a x="1">1</a>'},
         "expect": {"ok": True,
                    "document": {"edges": [["a", {"scalar": {"kind": "string", "value": "1"}}]]},
                    "diagnostics": [{"path": "$.a", "code": "format.attribute-dropped"}]}}
    status, msg = vr.run_parse(v, tmp_path)
    assert status == "fail"
    assert "non-JSON stderr report" in msg


def test_run_parse_expected_success_but_command_failed(tmp_path, monkeypatch):
    monkeypatch.setattr(vr.cli_runner, "_run", lambda args: ("", "boom", 2))
    v = {"input": {"format": "oml", "text": "bad\n"}, "expect": {"ok": True, "document": {}}}
    status, msg = vr.run_parse(v, tmp_path)
    assert status == "fail" and "expected success" in msg


def test_run_parse_document_mismatch(tmp_path, monkeypatch):
    monkeypatch.setattr(vr.cli_runner, "_run", lambda args: ("a: 2\n", "", 0))
    v = {"input": {"format": "oml", "text": "a: 1\n"},
         "expect": {"ok": True, "document": {
             "edges": [["a", {"scalar": {"kind": "integer", "value": 1}}]]}}}
    status, msg = vr.run_parse(v, tmp_path)
    assert status == "fail" and "does not match" in msg


def test_run_parse_error_case_skips_when_diagnostics_expected(tmp_path, monkeypatch):
    monkeypatch.setattr(vr.cli_runner, "_run", lambda args: ("", "bad", 1))
    v = {"input": {"format": "oml", "text": "bad\n"},
         "expect": {"ok": False, "diagnostics": [{"path": "1:1", "code": "x"}]}}
    status, msg = vr.run_parse(v, tmp_path)
    assert status == "skip"


def test_run_parse_error_case_no_diagnostics_pass(tmp_path, monkeypatch):
    monkeypatch.setattr(vr.cli_runner, "_run", lambda args: ("", "bad", 1))
    v = {"input": {"format": "oml", "text": "bad\n"}, "expect": {"ok": False}}
    status, msg = vr.run_parse(v, tmp_path)
    assert status == "pass"


def test_run_parse_error_case_command_unexpectedly_succeeded(tmp_path, monkeypatch):
    monkeypatch.setattr(vr.cli_runner, "_run", lambda args: ("a: 1\n", "", 0))
    v = {"input": {"format": "oml", "text": "a: 1\n"}, "expect": {"ok": False}}
    status, msg = vr.run_parse(v, tmp_path)
    assert status == "fail" and "expected failure" in msg


# --------------------------------------------------------- parse_schema

def test_run_parse_schema_success(tmp_path, monkeypatch):
    monkeypatch.setattr(vr.cli_runner, "_run", lambda args: ("record R{}\nroot R\n", "", 0))
    v = {"input": {"text": "record R{}\nroot R\n"}, "expect": {"ok": True}}
    status, msg = vr.run_parse_schema(v, tmp_path)
    assert status == "pass"


def test_run_parse_schema_expected_success_failed(tmp_path, monkeypatch):
    monkeypatch.setattr(vr.cli_runner, "_run", lambda args: ("", "boom", 2))
    v = {"input": {"text": "x"}, "expect": {"ok": True}}
    status, msg = vr.run_parse_schema(v, tmp_path)
    assert status == "fail"


def test_run_parse_schema_error_case_skips_with_diagnostics(tmp_path, monkeypatch):
    monkeypatch.setattr(vr.cli_runner, "_run", lambda args: ("", "boom", 2))
    v = {"input": {"text": "x"},
         "expect": {"ok": False, "diagnostics": [{"path": "R.a", "code": "c"}]}}
    status, msg = vr.run_parse_schema(v, tmp_path)
    assert status == "skip"


def test_run_parse_schema_error_case_no_diagnostics_pass(tmp_path, monkeypatch):
    monkeypatch.setattr(vr.cli_runner, "_run", lambda args: ("", "boom", 2))
    v = {"input": {"text": "x"}, "expect": {"ok": False}}
    status, msg = vr.run_parse_schema(v, tmp_path)
    assert status == "pass"


def test_run_parse_schema_error_case_command_unexpectedly_succeeded(tmp_path, monkeypatch):
    monkeypatch.setattr(vr.cli_runner, "_run", lambda args: ("ok", "", 0))
    v = {"input": {"text": "x"}, "expect": {"ok": False}}
    status, msg = vr.run_parse_schema(v, tmp_path)
    assert status == "fail"


# --------------------------------------------------------------- validate

def test_run_validate_ok_matches(tmp_path, monkeypatch):
    monkeypatch.setattr(vr.cli_runner, "validate",
                        lambda doc, schema: (json.dumps({"ok": True}), "", 0))
    v = {"input": {"schema": "record R{}\nroot R\n", "document": {"edges": []}},
         "expect": {"ok": True}}
    status, msg = vr.run_validate(v, tmp_path)
    assert status == "pass"


def test_run_validate_non_json_stdout(tmp_path, monkeypatch):
    monkeypatch.setattr(vr.cli_runner, "validate", lambda doc, schema: ("not json", "", 0))
    v = {"input": {"schema": "record R{}\nroot R\n", "document": {"edges": []}},
         "expect": {"ok": True}}
    status, msg = vr.run_validate(v, tmp_path)
    assert status == "fail" and "non-JSON" in msg


def test_run_validate_ok_mismatch(tmp_path, monkeypatch):
    monkeypatch.setattr(vr.cli_runner, "validate",
                        lambda doc, schema: (json.dumps({"ok": False}), "", 0))
    v = {"input": {"schema": "record R{}\nroot R\n", "document": {"edges": []}},
         "expect": {"ok": True}}
    status, msg = vr.run_validate(v, tmp_path)
    assert status == "fail" and "expected ok" in msg


def test_run_validate_diagnostics_paths_match(tmp_path, monkeypatch):
    monkeypatch.setattr(
        vr.cli_runner, "validate",
        lambda doc, schema: (json.dumps(
            {"ok": False, "errors": [{"path": "$.a", "code": "type-mismatch"}]}), "", 0))
    v = {"input": {"schema": "record R{}\nroot R\n", "document": {"edges": []}},
         "expect": {"ok": False,
                    "diagnostics": [{"path": "$.a", "code": "validate.type-mismatch"}]}}
    status, msg = vr.run_validate(v, tmp_path)
    assert status == "pass"


def test_run_validate_diagnostics_paths_differ(tmp_path, monkeypatch):
    monkeypatch.setattr(
        vr.cli_runner, "validate",
        lambda doc, schema: (json.dumps(
            {"ok": False, "errors": [{"path": "$.b", "code": "type-mismatch"}]}), "", 0))
    v = {"input": {"schema": "record R{}\nroot R\n", "document": {"edges": []}},
         "expect": {"ok": False, "diagnostics": [{"path": "$.a", "code": "x"}]}}
    status, msg = vr.run_validate(v, tmp_path)
    assert status == "fail" and "diagnostic paths differ" in msg


# ------------------------------------------------------------ materialize

def test_run_materialize_ok(tmp_path, monkeypatch):
    monkeypatch.setattr(vr.cli_runner, "materialize", lambda doc, schema: ("a: 1\n", "", 0))
    v = {"input": {"schema": "record R{}\nroot R\n", "document": {"edges": []}},
         "expect": {"ok": True, "document": {
             "edges": [["a", {"scalar": {"kind": "integer", "value": 1}}]]}}}
    status, msg = vr.run_materialize(v, tmp_path)
    assert status == "pass"


def test_run_materialize_ok_expected_but_failed(tmp_path, monkeypatch):
    monkeypatch.setattr(vr.cli_runner, "materialize", lambda doc, schema: ("", "boom", 2))
    v = {"input": {"schema": "record R{}\nroot R\n", "document": {"edges": []}},
         "expect": {"ok": True, "document": {}}}
    status, msg = vr.run_materialize(v, tmp_path)
    assert status == "fail" and "expected success" in msg


def test_run_materialize_document_mismatch(tmp_path, monkeypatch):
    monkeypatch.setattr(vr.cli_runner, "materialize", lambda doc, schema: ("a: 2\n", "", 0))
    v = {"input": {"schema": "record R{}\nroot R\n", "document": {"edges": []}},
         "expect": {"ok": True, "document": {
             "edges": [["a", {"scalar": {"kind": "integer", "value": 1}}]]}}}
    status, msg = vr.run_materialize(v, tmp_path)
    assert status == "fail" and "does not match" in msg


def test_run_materialize_fail_expected_but_succeeded(tmp_path, monkeypatch):
    monkeypatch.setattr(vr.cli_runner, "materialize", lambda doc, schema: ("a: 1\n", "", 0))
    v = {"input": {"schema": "record R{}\nroot R\n", "document": {"edges": []}},
         "expect": {"ok": False}}
    status, msg = vr.run_materialize(v, tmp_path)
    assert status == "fail" and "expected failure" in msg


def test_run_materialize_fail_no_diagnostics_pass(tmp_path, monkeypatch):
    monkeypatch.setattr(vr.cli_runner, "materialize", lambda doc, schema: ("", "boom", 2))
    v = {"input": {"schema": "record R{}\nroot R\n", "document": {"edges": []}},
         "expect": {"ok": False}}
    status, msg = vr.run_materialize(v, tmp_path)
    assert status == "pass"


def test_run_materialize_fail_diagnostics_non_json(tmp_path, monkeypatch):
    monkeypatch.setattr(vr.cli_runner, "materialize", lambda doc, schema: ("not json", "boom", 2))
    v = {"input": {"schema": "record R{}\nroot R\n", "document": {"edges": []}},
         "expect": {"ok": False, "diagnostics": [{"path": "$.a", "code": "x"}]}}
    status, msg = vr.run_materialize(v, tmp_path)
    assert status == "fail" and "non-JSON" in msg


def test_run_materialize_fail_diagnostics_match(tmp_path, monkeypatch):
    monkeypatch.setattr(
        vr.cli_runner, "materialize",
        lambda doc, schema: (json.dumps({"errors": [{"path": "$.a", "code": "c"}]}), "boom", 2))
    v = {"input": {"schema": "record R{}\nroot R\n", "document": {"edges": []}},
         "expect": {"ok": False, "diagnostics": [{"path": "$.a", "code": "x"}]}}
    status, msg = vr.run_materialize(v, tmp_path)
    assert status == "pass"


def test_run_materialize_fail_diagnostics_differ(tmp_path, monkeypatch):
    monkeypatch.setattr(
        vr.cli_runner, "materialize",
        lambda doc, schema: (json.dumps({"errors": [{"path": "$.b", "code": "c"}]}), "boom", 2))
    v = {"input": {"schema": "record R{}\nroot R\n", "document": {"edges": []}},
         "expect": {"ok": False, "diagnostics": [{"path": "$.a", "code": "x"}]}}
    status, msg = vr.run_materialize(v, tmp_path)
    assert status == "fail" and "diagnostic paths differ" in msg


# ------------------------------------------------------------------ write

def test_run_write_ok_text_and_diagnostics_match(tmp_path, monkeypatch):
    monkeypatch.setattr(vr.cli_runner, "_run",
                        lambda args: ('{"d": "2024-01-01"}',
                                      json.dumps([{"path": "$.d", "code": "temporal.stringified"}]),
                                      0))
    v = {"input": {"format": "json", "document": {
             "edges": [["d", {"scalar": {"kind": "date", "value": "2024-01-01"}}]]}},
         "expect": {"ok": True, "text": '{"d": "2024-01-01"}',
                    "diagnostics": [{"path": "$.d", "code": "format.temporal-stringified"}]}}
    status, msg = vr.run_write(v, tmp_path)
    assert status == "pass"


def test_run_write_oml_target_uses_format_not_convert(tmp_path, monkeypatch):
    # #293: `convert --from oml --to oml` is refused by the CLI; write must
    # special-case fmt=="oml" the same way run_parse already does.
    seen = {}

    def fake_run(args):
        seen["args"] = args
        return 'd: "2024-01-01"\n', "", 0

    monkeypatch.setattr(vr.cli_runner, "_run", fake_run)
    v = {"input": {"format": "oml", "document": {
             "edges": [["d", {"scalar": {"kind": "string", "value": "2024-01-01"}}]]}},
         "expect": {"ok": True, "text": 'd: "2024-01-01"\n'}}
    status, msg = vr.run_write(v, tmp_path)
    assert status == "pass"
    assert seen["args"][0] == "format"
    assert "convert" not in seen["args"]


def test_run_write_oml_target_strict_flag_passed(tmp_path, monkeypatch):
    seen = {}

    def fake_run(args):
        seen["args"] = args
        return "", "", 2

    monkeypatch.setattr(vr.cli_runner, "_run", fake_run)
    v = {"input": {"format": "oml", "document": {"edges": []}, "strict": True},
         "expect": {"ok": False}}
    status, msg = vr.run_write(v, tmp_path)
    assert status == "pass"
    assert seen["args"][0] == "format"
    assert "--strict" in seen["args"]


def test_run_write_strict_flag_passed(tmp_path, monkeypatch):
    seen = {}

    def fake_run(args):
        seen["args"] = args
        return "", "[]", 1

    monkeypatch.setattr(vr.cli_runner, "_run", fake_run)
    v = {"input": {"format": "toml", "document": {"edges": []}, "strict": True},
         "expect": {"ok": False,
                    "diagnostics": [{"path": "$.n", "code": "write.unsupported-value"}]}}
    status, msg = vr.run_write(v, tmp_path)
    assert status == "pass"
    assert "--strict" in seen["args"]


def test_run_write_fail_expected_but_succeeded(tmp_path, monkeypatch):
    monkeypatch.setattr(vr.cli_runner, "_run", lambda args: ("out", "[]", 0))
    v = {"input": {"format": "toml", "document": {"edges": []}},
         "expect": {"ok": False}}
    status, msg = vr.run_write(v, tmp_path)
    assert status == "fail" and "expected failure" in msg


def test_run_write_ok_expected_but_failed(tmp_path, monkeypatch):
    monkeypatch.setattr(vr.cli_runner, "_run", lambda args: ("", "boom", 2))
    v = {"input": {"format": "toml", "document": {"edges": []}},
         "expect": {"ok": True}}
    status, msg = vr.run_write(v, tmp_path)
    assert status == "fail" and "expected success" in msg


def test_run_write_text_mismatch(tmp_path, monkeypatch):
    monkeypatch.setattr(vr.cli_runner, "_run", lambda args: ('{"m": [2]}', "[]", 0))
    v = {"input": {"format": "json", "document": {"edges": []}},
         "expect": {"ok": True, "text": '{"m": [1]}'}}
    status, msg = vr.run_write(v, tmp_path)
    assert status == "fail" and "expected text" in msg


def test_run_write_xml_whitespace_normalized_passes(tmp_path, monkeypatch):
    # Sec8.5.3: indented vs. compact XML output must compare equal once
    # insignificant inter-tag whitespace is stripped from both sides.
    monkeypatch.setattr(vr.cli_runner, "_run",
                        lambda args: ("<root>\n  <x>a&#13;b</x>\n</root>\n", "[]", 0))
    v = {"input": {"format": "xml", "document": {"edges": []}},
         "expect": {"ok": True, "text": "<root><x>a&#13;b</x></root>"}}
    status, msg = vr.run_write(v, tmp_path)
    assert status == "pass"


def test_run_write_xml_genuine_mismatch_still_fails(tmp_path, monkeypatch):
    # Normalizing whitespace must not mask a real content difference.
    monkeypatch.setattr(vr.cli_runner, "_run",
                        lambda args: ("<root><x>wrong</x></root>", "[]", 0))
    v = {"input": {"format": "xml", "document": {"edges": []}},
         "expect": {"ok": True, "text": "<root><x>a&#13;b</x></root>"}}
    status, msg = vr.run_write(v, tmp_path)
    assert status == "fail" and "expected text" in msg


def test_run_write_diagnostics_non_json_stderr(tmp_path, monkeypatch):
    monkeypatch.setattr(vr.cli_runner, "_run", lambda args: ("out", "not json", 0))
    v = {"input": {"format": "json", "document": {"edges": []}},
         "expect": {"ok": True, "diagnostics": [{"path": "$.a", "code": "x"}]}}
    status, msg = vr.run_write(v, tmp_path)
    assert status == "fail" and "non-JSON stderr" in msg


def test_run_write_diagnostics_differ(tmp_path, monkeypatch):
    monkeypatch.setattr(vr.cli_runner, "_run",
                        lambda args: ("out", json.dumps([{"path": "$.b", "code": "x"}]), 0))
    v = {"input": {"format": "json", "document": {"edges": []}},
         "expect": {"ok": True, "diagnostics": [{"path": "$.a", "code": "x"}]}}
    status, msg = vr.run_write(v, tmp_path)
    assert status == "fail" and "diagnostic paths differ" in msg


# ------------------------------------------------------- schema-producing

def test_run_normalize_pass(tmp_path, monkeypatch):
    monkeypatch.setattr(vr.cli_runner, "normalize",
                        lambda schema: ("record R{}\nroot R\n", "", 0))
    v = {"input": {"schema": "record R{}\nroot R\n"}, "expect": {"schema": "record R{}\nroot R\n"}}
    status, msg = vr.run_normalize(v, tmp_path)
    assert status == "pass"


def test_run_normalize_cli_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(vr.cli_runner, "normalize", lambda schema: ("", "boom", 2))
    v = {"input": {"schema": "record R{}\nroot R\n"}, "expect": {"schema": "record R{}\nroot R\n"}}
    status, msg = vr.run_normalize(v, tmp_path)
    assert status == "fail" and "exit 2" in msg


def test_run_normalize_mismatch(tmp_path, monkeypatch):
    monkeypatch.setattr(vr.cli_runner, "normalize",
                        lambda schema: ('record R{"x": integer}\nroot R\n', "", 0))
    v = {"input": {"schema": "record R{}\nroot R\n"}, "expect": {"schema": "record R{}\nroot R\n"}}
    status, msg = vr.run_normalize(v, tmp_path)
    assert status == "fail" and "does not match" in msg


def test_run_prune_pass(tmp_path, monkeypatch):
    monkeypatch.setattr(vr.cli_runner, "prune", lambda schema: ("record R{}\nroot R\n", "", 0))
    v = {"input": {"schema": "record R{}\nroot R\n"}, "expect": {"schema": "record R{}\nroot R\n"}}
    status, msg = vr.run_prune(v, tmp_path)
    assert status == "pass"


# ------------------------------------------------------------- booleans

def test_run_is_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(vr.cli_runner, "is_empty",
                        lambda schema: (json.dumps({"empty": False}), "", 0))
    v = {"input": {"schema": "record R{}\nroot R\n"}, "expect": {"empty": False}}
    assert vr.run_is_empty(v, tmp_path) == ("pass", "ok")


def test_run_compatible_with(tmp_path, monkeypatch):
    monkeypatch.setattr(vr.cli_runner, "compatible_with",
                        lambda a, b: (json.dumps({"compatible": True}), "", 0))
    v = {"input": {"a": "record R{}\nroot R\n", "b": "record R{}\nroot R\n"},
         "expect": {"result": True}}
    assert vr.run_compatible_with(v, tmp_path) == ("pass", "ok")


def test_run_equivalent(tmp_path, monkeypatch):
    monkeypatch.setattr(vr.cli_runner, "equivalent",
                        lambda a, b: (json.dumps({"equivalent": False}), "", 0))
    v = {"input": {"a": "record R{}\nroot R\n", "b": "record R{}\nroot R\n"},
         "expect": {"result": True}}
    status, msg = vr.run_equivalent(v, tmp_path)
    assert status == "fail" and "expected" in msg


def test_check_bool_non_json():
    status, msg = vr._check_bool("not json", True, "empty")
    assert status == "fail" and "non-JSON" in msg


# --------------------------------------------------------------- extract

def test_run_extract_ok(tmp_path, monkeypatch):
    monkeypatch.setattr(vr.cli_runner, "extract",
                        lambda schema, keep: ("record R{}\nroot R\n", "", 0))
    v = {"input": {"schema": "record R{}\nroot R\n", "keep": ["a"]},
         "expect": {"ok": True, "schema": "record R{}\nroot R\n"}}
    status, msg = vr.run_extract(v, tmp_path)
    assert status == "pass"


def test_run_extract_ok_expected_but_failed(tmp_path, monkeypatch):
    monkeypatch.setattr(vr.cli_runner, "extract", lambda schema, keep: ("", "boom", 2))
    v = {"input": {"schema": "record R{}\nroot R\n", "keep": ["a"]},
         "expect": {"ok": True, "schema": ""}}
    status, msg = vr.run_extract(v, tmp_path)
    assert status == "fail" and "expected success" in msg


def test_run_extract_mismatch(tmp_path, monkeypatch):
    monkeypatch.setattr(vr.cli_runner, "extract",
                        lambda schema, keep: ('record R{"x": integer}\nroot R\n', "", 0))
    v = {"input": {"schema": "record R{}\nroot R\n", "keep": ["a"]},
         "expect": {"ok": True, "schema": "record R{}\nroot R\n"}}
    status, msg = vr.run_extract(v, tmp_path)
    assert status == "fail" and "does not match" in msg


def test_run_extract_fail_expected_but_succeeded(tmp_path, monkeypatch):
    monkeypatch.setattr(vr.cli_runner, "extract",
                        lambda schema, keep: ("record R{}\nroot R\n", "", 0))
    v = {"input": {"schema": "record R{}\nroot R\n", "keep": ["a"]}, "expect": {"ok": False}}
    status, msg = vr.run_extract(v, tmp_path)
    assert status == "fail" and "expected failure" in msg


def test_run_extract_fail_pass(tmp_path, monkeypatch):
    monkeypatch.setattr(vr.cli_runner, "extract", lambda schema, keep: ("", "boom", 2))
    v = {"input": {"schema": "record R{}\nroot R\n", "keep": ["a"]}, "expect": {"ok": False}}
    status, msg = vr.run_extract(v, tmp_path)
    assert status == "pass"


# ------------------------------------------------------------------ lint

def test_run_lint_pass(tmp_path, monkeypatch):
    monkeypatch.setattr(vr.cli_runner, "lint",
                        lambda schema: (json.dumps({"ok": True, "findings": []}), "", 0))
    v = {"input": {"schema": "record R{}\nroot R\n"}, "expect": {"ok": True, "findings": []}}
    status, msg = vr.run_lint(v, tmp_path)
    assert status == "pass"


def test_run_lint_non_json(tmp_path, monkeypatch):
    monkeypatch.setattr(vr.cli_runner, "lint", lambda schema: ("not json", "", 0))
    v = {"input": {"schema": "record R{}\nroot R\n"}, "expect": {"ok": True, "findings": []}}
    status, msg = vr.run_lint(v, tmp_path)
    assert status == "fail" and "non-JSON" in msg


def test_run_lint_ok_mismatch(tmp_path, monkeypatch):
    monkeypatch.setattr(vr.cli_runner, "lint",
                        lambda schema: (json.dumps({"ok": False, "findings": []}), "", 0))
    v = {"input": {"schema": "record R{}\nroot R\n"}, "expect": {"ok": True, "findings": []}}
    status, msg = vr.run_lint(v, tmp_path)
    assert status == "fail" and "expected ok" in msg


def test_run_lint_findings_differ(tmp_path, monkeypatch):
    monkeypatch.setattr(
        vr.cli_runner, "lint",
        lambda schema: (json.dumps(
            {"ok": True,
             "findings": [{"code": "c", "severity": "warning", "location": "R.b"}]}), "", 0))
    v = {"input": {"schema": "record R{}\nroot R\n"},
         "expect": {"ok": True, "findings": [{"code": "c", "location": "R.a"}]}}
    status, msg = vr.run_lint(v, tmp_path)
    assert status == "fail" and "finding locations differ" in msg


# ----------------------------------------------------------------- infer

def test_run_infer_pass():
    v = {"input": {"samples": ['tag: "a"\ntag: "b"\n', 'tag: "c"\n']},
         "expect": {"ok": True, "schema": 'record Root {\n    "tag" [0,]: string,\n}\nroot Root\n'}}
    status, msg = vr.run_infer(v, Path("."))
    assert status == "pass"


def test_run_infer_with_report_pass():
    v = {"input": {"samples": ['tag: "a"\n']},
         "expect": {"ok": True, "schema": 'record Root {\n    "tag": string,\n}\nroot Root\n'}}
    status, msg = vr.run_infer_with_report(v, Path("."))
    assert status == "pass"


def test_run_infer_zero_samples_is_an_error():
    v = {"input": {"samples": []}, "expect": {"ok": False}}
    status, msg = vr.run_infer(v, Path("."))
    assert status == "pass"


def test_run_infer_zero_samples_unexpected_success_would_fail():
    v = {"input": {"samples": []}, "expect": {"ok": True, "schema": "record Root{}\nroot Root\n"}}
    status, msg = vr.run_infer(v, Path("."))
    assert status == "fail" and "expected success" in msg


def test_run_infer_expected_failure_but_succeeded():
    v = {"input": {"samples": ['tag: "a"\n']}, "expect": {"ok": False}}
    status, msg = vr.run_infer(v, Path("."))
    assert status == "fail" and "expected failure" in msg


def test_run_infer_not_isomorphic():
    v = {"input": {"samples": ['tag: "a"\n']},
         "expect": {"ok": True, "schema": 'record Root {\n    "tag": integer,\n}\nroot Root\n'}}
    status, msg = vr.run_infer(v, Path("."))
    assert status == "fail" and "not isomorphic" in msg


def test_run_infer_allow_any_flag_used():
    v = {"input": {"samples": ['tag: "a"\n', 'tag: 1\n'], "allow_any": True},
         "expect": {"ok": True, "schema": 'record Root {\n    "tag": any,\n}\nroot Root\n'}}
    status, msg = vr.run_infer(v, Path("."))
    assert status == "pass"


# ------------------------------------------------------------- dispatch

def test_run_vector_unknown_operation():
    status, msg = vr.run_vector({"operation": "bogus", "name": "x"})
    assert status == "skip" and "no driver" in msg


def test_run_vector_driver_crash_is_reported_as_fail():
    def boom(v, tmp):
        raise RuntimeError("kaboom")

    orig = vr.RUNNERS["lint"]
    vr.RUNNERS["lint"] = boom
    try:
        status, msg = vr.run_vector({"operation": "lint", "name": "x"})
    finally:
        vr.RUNNERS["lint"] = orig
    assert status == "fail" and "kaboom" in msg


def test_iter_vectors_and_main(tmp_path, monkeypatch):
    suite = tmp_path / "test-suite" / "lint"
    suite.mkdir(parents=True)
    (suite / "vecs.json").write_text(json.dumps({"vectors": [
        {"name": "a", "operation": "lint",
         "input": {"schema": "record R{}\nroot R\n"},
         "expect": {"ok": True, "findings": []}},
        {"name": "b", "operation": "bogus"},
    ]}), encoding="utf-8")
    monkeypatch.setattr(vr, "VECTOR_SUITE_DIR", tmp_path / "test-suite")
    monkeypatch.setattr(vr.cli_runner, "lint",
                        lambda schema: (json.dumps({"ok": True, "findings": []}), "", 0))
    assert list(vr.iter_vectors())
    assert vr.main([]) == 0


def test_main_missing_submodule(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(vr, "VECTOR_SUITE_DIR", tmp_path / "does-not-exist")
    assert vr.main([]) == 2
    assert "submodule" in capsys.readouterr().err


def test_main_reports_failures(tmp_path, monkeypatch):
    suite = tmp_path / "test-suite" / "lint"
    suite.mkdir(parents=True)
    (suite / "vecs.json").write_text(json.dumps({"vectors": [
        {"name": "a", "operation": "lint",
         "input": {"schema": "record R{}\nroot R\n"},
         "expect": {"ok": True, "findings": []}},
    ]}), encoding="utf-8")
    monkeypatch.setattr(vr, "VECTOR_SUITE_DIR", tmp_path / "test-suite")
    monkeypatch.setattr(vr.cli_runner, "lint",
                        lambda schema: (json.dumps({"ok": False, "findings": []}), "", 0))
    assert vr.main([]) == 1
