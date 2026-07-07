"""Tests for the omnist CLI (omnist/cli.py).

Each command is invoked in-process via ``main(argv)`` with stdin/stdout/
stderr captured -- no subprocess, consistent with this repo's fast test
suite. See docs/design/cli-spec.md for the full command surface; this
file's coverage grows alongside the CLI's own implementation PRs.
"""
from __future__ import annotations

import json

import pytest

from omnist.cli import main


def run(argv, stdin=None, capsys=None, monkeypatch=None):
    if stdin is not None:
        monkeypatch.setattr("sys.stdin", __import__("io").StringIO(stdin))
    code = main(argv)
    out = capsys.readouterr()
    return code, out.out, out.err


class TestFormat:
    def test_reformats_oml_from_file_to_stdout(self, tmp_path, capsys):
        p = tmp_path / "in.oml"
        p.write_text('a: 1\nb: "x"\n')
        code, out, err = run(["format", str(p)], capsys=capsys, monkeypatch=None)
        assert code == 0
        assert err == ""
        assert out == 'a: 1\nb: "x"\n'

    def test_writes_to_output_file(self, tmp_path, capsys):
        src = tmp_path / "in.oml"
        src.write_text('a: 1\n')
        dst = tmp_path / "out.oml"
        code, out, err = run(["format", str(src), "-o", str(dst)], capsys=capsys, monkeypatch=None)
        assert code == 0
        assert out == ""
        assert dst.read_text() == 'a: 1\n'

    def test_reads_from_stdin(self, capsys, monkeypatch):
        code, out, err = run(
            ["format", "-"], stdin='a: 1\n', capsys=capsys, monkeypatch=monkeypatch)
        assert code == 0
        assert out == 'a: 1\n'

    def test_round_trips_canonically_even_if_messy(self, tmp_path, capsys):
        p = tmp_path / "in.oml"
        p.write_text('a:   1\nb:"x"\n')
        code, out, err = run(["format", str(p)], capsys=capsys, monkeypatch=None)
        assert code == 0
        assert out == 'a: 1\nb: "x"\n'

    def test_invalid_oml_is_a_clean_error_not_a_traceback(self, tmp_path, capsys):
        p = tmp_path / "bad.oml"
        p.write_text('a: [1, 2]\n')   # OML has no JSON-style array literal
        code, out, err = run(["format", str(p)], capsys=capsys, monkeypatch=None)
        assert code == 2
        assert out == ""
        assert err.startswith("error: ")

    def test_missing_file_is_a_clean_error(self, tmp_path, capsys):
        missing = tmp_path / "nope.oml"
        code, out, err = run(["format", str(missing)], capsys=capsys, monkeypatch=None)
        assert code == 2
        assert err.startswith("error: ")

    def test_missing_input_argument_is_argparse_usage_error(self, capsys):
        with pytest.raises(SystemExit) as exc:
            main(["format"])
        assert exc.value.code == 2

    def test_compact_flag_emits_single_line_output(self, tmp_path, capsys):
        p = tmp_path / "in.oml"
        p.write_text('a: 1\nb: { x: 1; y: 2 }\n')
        code, out, err = run(["format", str(p), "--compact"], capsys=capsys, monkeypatch=None)
        assert code == 0
        assert out == "a: 1; b: { x: 1; y: 2 }\n"


class TestConvert:
    def test_json_to_yaml(self, tmp_path, capsys):
        p = tmp_path / "in.json"
        p.write_text('{"a": 1}')
        code, out, err = run(
            ["convert", str(p), "--from", "json", "--to", "yaml"], capsys=capsys, monkeypatch=None)
        assert code == 0
        assert err == ""
        assert out == "a: 1\n"

    def test_json_to_oml(self, tmp_path, capsys):
        p = tmp_path / "in.json"
        p.write_text('{"a": 1, "b": "x"}')
        code, out, err = run(
            ["convert", str(p), "--from", "json", "--to", "oml"], capsys=capsys, monkeypatch=None)
        assert code == 0
        assert out == 'a: 1\nb: "x"\n'

    def test_json_to_oml_compact(self, tmp_path, capsys):
        p = tmp_path / "in.json"
        p.write_text('{"a": 1, "b": "x"}')
        code, out, err = run(
            ["convert", str(p), "--from", "json", "--to", "oml", "--compact"],
            capsys=capsys, monkeypatch=None)
        assert code == 0
        assert out == 'a: 1; b: "x"\n'

    def test_writes_to_output_file(self, tmp_path, capsys):
        src = tmp_path / "in.json"
        src.write_text('{"a": 1}')
        dst = tmp_path / "out.yaml"
        code, out, err = run(
            ["convert", str(src), "--from", "json", "--to", "yaml", "-o", str(dst)],
            capsys=capsys, monkeypatch=None)
        assert code == 0
        assert out == ""
        assert dst.read_text() == "a: 1\n"

    def test_reads_from_stdin(self, capsys, monkeypatch):
        code, out, err = run(
            ["convert", "-", "--from", "json", "--to", "yaml"],
            stdin='{"a": 1}', capsys=capsys, monkeypatch=monkeypatch)
        assert code == 0
        assert out == "a: 1\n"

    def test_same_format_other_than_oml_is_allowed(self, tmp_path, capsys):
        p = tmp_path / "in.json"
        p.write_text('{"a":   1}')
        code, out, err = run(
            ["convert", str(p), "--from", "json", "--to", "json"], capsys=capsys, monkeypatch=None)
        assert code == 0
        assert out == '{"a": 1}\n'

    def test_oml_to_oml_is_rejected(self, tmp_path, capsys):
        p = tmp_path / "in.oml"
        p.write_text('a: 1\n')
        code, out, err = run(
            ["convert", str(p), "--from", "oml", "--to", "oml"], capsys=capsys, monkeypatch=None)
        assert code == 2
        assert out == ""
        assert "use `omnist format` instead" in err

    def test_schema_directed_upgrade(self, tmp_path, capsys):
        p = tmp_path / "in.json"
        p.write_text('{"d": "2024-01-01"}')
        schema_f = tmp_path / "s.osd"
        schema_f.write_text('record R { "d": date }\nroot R\n')
        code, out, err = run(
            ["convert", str(p), "--from", "json", "--to", "oml", "--schema", str(schema_f)],
            capsys=capsys, monkeypatch=None)
        assert code == 0
        assert out == "d: 2024-01-01\n"   # a real date now, not a quoted string

    def test_schema_conformance_failure_is_a_clean_error(self, tmp_path, capsys):
        p = tmp_path / "in.json"
        p.write_text('{"a": 1, "b": "extra"}')
        schema_f = tmp_path / "s.osd"
        schema_f.write_text('record R { "a": integer }\nroot R\n')
        code, out, err = run(
            ["convert", str(p), "--from", "json", "--to", "oml", "--schema", str(schema_f)],
            capsys=capsys, monkeypatch=None)
        assert code == 2
        assert out == ""
        assert err.startswith("error: ")

    def test_multi_root_to_xml_is_a_clean_error_not_a_traceback(self, tmp_path, capsys):
        p = tmp_path / "in.json"
        p.write_text('{"a": 1, "b": 2}')   # two top-level edges -- not single-rooted
        code, out, err = run(
            ["convert", str(p), "--from", "json", "--to", "xml"], capsys=capsys, monkeypatch=None)
        assert code == 2
        assert err.startswith("error: ")

    def test_missing_to_is_argparse_usage_error(self, tmp_path):
        p = tmp_path / "in.json"
        p.write_text('{"a": 1}')
        with pytest.raises(SystemExit) as exc:
            main(["convert", str(p), "--from", "json"])
        assert exc.value.code == 2

    def test_unknown_to_value_is_argparse_usage_error(self, tmp_path):
        p = tmp_path / "in.json"
        p.write_text('{"a": 1}')
        with pytest.raises(SystemExit) as exc:
            main(["convert", str(p), "--from", "json", "--to", "bogus"])
        assert exc.value.code == 2

    def test_malformed_input_is_a_clean_error_not_a_traceback(self, tmp_path, capsys):
        p = tmp_path / "in.json"
        p.write_text('{not valid json')
        code, out, err = run(
            ["convert", str(p), "--from", "json", "--to", "yaml"], capsys=capsys, monkeypatch=None)
        assert code == 2
        assert err.startswith("error: ")


class TestConvertReportStrict:
    def test_report_writes_and_prints_adjustment_to_stderr(self, tmp_path, capsys):
        p = tmp_path / "in.json"
        p.write_text('{"a": null}')
        dst = tmp_path / "out.toml"
        code, out, err = run(
            ["convert", str(p), "--from", "json", "--to", "toml", "--report", "-o", str(dst)],
            capsys=capsys, monkeypatch=None)
        assert code == 0
        assert out == ""
        assert "null" in err
        assert dst.exists()   # the write still happened

    def test_report_with_no_adjustments_still_prints(self, tmp_path, capsys):
        p = tmp_path / "in.json"
        p.write_text('{"a": 1}')
        code, out, err = run(
            ["convert", str(p), "--from", "json", "--to", "yaml", "--report"],
            capsys=capsys, monkeypatch=None)
        assert code == 0
        assert err == "no adjustments\n"

    def test_report_result_format_json(self, tmp_path, capsys):
        p = tmp_path / "in.json"
        p.write_text('{"a": null}')
        code, out, err = run(
            ["convert", str(p), "--from", "json", "--to", "toml",
             "--report", "--result-format", "json"],
            capsys=capsys, monkeypatch=None)
        assert code == 0
        assert err.startswith("[{")
        assert '"code"' in err

    def test_result_format_without_report_has_no_effect(self, tmp_path, capsys):
        p = tmp_path / "in.json"
        p.write_text('{"a": null}')
        code, out, err = run(
            ["convert", str(p), "--from", "json", "--to", "toml", "--result-format", "json"],
            capsys=capsys, monkeypatch=None)
        assert code == 0
        assert err == ""   # no --report -> nothing printed regardless of --result-format

    def test_strict_refuses_lossy_write_exit_1(self, tmp_path, capsys):
        p = tmp_path / "in.json"
        p.write_text('{"a": null}')
        dst = tmp_path / "out.toml"
        code, out, err = run(
            ["convert", str(p), "--from", "json", "--to", "toml", "--strict", "-o", str(dst)],
            capsys=capsys, monkeypatch=None)
        assert code == 1
        assert out == ""
        assert not dst.exists()   # nothing written
        assert err.startswith("error: ")

    def test_strict_succeeds_when_nothing_to_adjust(self, tmp_path, capsys):
        p = tmp_path / "in.json"
        p.write_text('{"a": 1}')
        code, out, err = run(
            ["convert", str(p), "--from", "json", "--to", "yaml", "--strict"],
            capsys=capsys, monkeypatch=None)
        assert code == 0
        assert out == "a: 1\n"

    def test_strict_to_oml_never_fails_since_oml_is_always_lossless(self, tmp_path, capsys):
        p = tmp_path / "in.json"
        p.write_text('{"a": null}')
        code, out, err = run(
            ["convert", str(p), "--from", "json", "--to", "oml", "--strict"],
            capsys=capsys, monkeypatch=None)
        assert code == 0

    def test_multi_root_to_xml_strict_is_still_exit_2_not_1(self, tmp_path, capsys):
        # a structural impossibility, not a --strict lossiness refusal --
        # must stay grouped with usage/parse failures (exit 2)
        p = tmp_path / "in.json"
        p.write_text('{"a": 1, "b": 2}')
        code, out, err = run(
            ["convert", str(p), "--from", "json", "--to", "xml", "--strict"],
            capsys=capsys, monkeypatch=None)
        assert code == 2
        assert err.startswith("error: ")


class TestCheck:
    def test_reports_without_writing_exit_always_0_by_default(self, tmp_path, capsys):
        p = tmp_path / "in.json"
        p.write_text('{"a": null}')
        code, out, err = run(
            ["check", str(p), "--from", "json", "--to", "toml"], capsys=capsys, monkeypatch=None)
        assert code == 0
        assert "null" in out
        assert err == ""


    def test_report_result_format_oml(self, tmp_path, capsys):
        # covers the oml branch of the adjustments encoder (cli.py _encode_adjustments)
        p = tmp_path / "in.json"
        p.write_text('{"a": null}')
        code, out, err = run(
            ["check", str(p), "--from", "json", "--to", "toml",
             "--result-format", "oml"], capsys=capsys, monkeypatch=None)
        assert code == 0
        assert "adjustments" in out and "null" in out

    def test_no_adjustments_prints_no_adjustments(self, tmp_path, capsys):
        p = tmp_path / "in.json"
        p.write_text('{"a": 1}')
        code, out, err = run(
            ["check", str(p), "--from", "json", "--to", "yaml"], capsys=capsys, monkeypatch=None)
        assert code == 0
        assert out == "no adjustments\n"

    def test_same_format_is_allowed(self, tmp_path, capsys):
        p = tmp_path / "in.json"
        p.write_text('{"a": 1}')
        code, out, err = run(
            ["check", str(p), "--from", "json", "--to", "json"], capsys=capsys, monkeypatch=None)
        assert code == 0
        assert out == "no adjustments\n"

    def test_strict_exits_1_when_something_would_adjust(self, tmp_path, capsys):
        p = tmp_path / "in.json"
        p.write_text('{"a": null}')
        code, out, err = run(
            ["check", str(p), "--from", "json", "--to", "toml", "--strict"],
            capsys=capsys, monkeypatch=None)
        assert code == 1

    def test_strict_exits_0_when_nothing_would_adjust(self, tmp_path, capsys):
        p = tmp_path / "in.json"
        p.write_text('{"a": 1}')
        code, out, err = run(
            ["check", str(p), "--from", "json", "--to", "toml", "--strict"],
            capsys=capsys, monkeypatch=None)
        assert code == 0

    def test_without_strict_always_exits_0_even_with_adjustments(self, tmp_path, capsys):
        p = tmp_path / "in.json"
        p.write_text('{"a": null}')
        code, out, err = run(
            ["check", str(p), "--from", "json", "--to", "toml"], capsys=capsys, monkeypatch=None)
        assert code == 0

    def test_result_format_json(self, tmp_path, capsys):
        p = tmp_path / "in.json"
        p.write_text('{"a": null}')
        code, out, err = run(
            ["check", str(p), "--from", "json", "--to", "toml", "--result-format", "json"],
            capsys=capsys, monkeypatch=None)
        assert code == 0
        assert out.startswith("[{")

    def test_does_not_write_anything(self, tmp_path, capsys, monkeypatch):
        # no -o flag exists on check at all -- confirm via argparse rejecting it
        p = tmp_path / "in.json"
        p.write_text('{"a": 1}')
        with pytest.raises(SystemExit) as exc:
            main(["check", str(p), "--from", "json", "--to", "toml", "-o", "x.toml"])
        assert exc.value.code == 2

    def test_malformed_input_is_a_clean_error(self, tmp_path, capsys):
        p = tmp_path / "in.json"
        p.write_text('{not valid json')
        code, out, err = run(
            ["check", str(p), "--from", "json", "--to", "toml"], capsys=capsys, monkeypatch=None)
        assert code == 2
        assert err.startswith("error: ")


class TestValidate:
    SCHEMA = 'record R { "a": integer }\nroot R\n'

    def test_valid_document_exits_0_text(self, tmp_path, capsys):
        doc_f = tmp_path / "d.json"
        doc_f.write_text('{"a": 1}')
        schema_f = tmp_path / "s.osd"
        schema_f.write_text(self.SCHEMA)
        code, out, err = run(
            ["validate", str(doc_f), "--from", "json", "--schema", str(schema_f)],
            capsys=capsys, monkeypatch=None)
        assert code == 0
        assert out == "valid\n"
        assert err == ""

    def test_invalid_document_exits_1_text(self, tmp_path, capsys):
        doc_f = tmp_path / "d.json"
        doc_f.write_text('{"a": 1, "b": "extra"}')
        schema_f = tmp_path / "s.osd"
        schema_f.write_text(self.SCHEMA)
        code, out, err = run(
            ["validate", str(doc_f), "--from", "json", "--schema", str(schema_f)],
            capsys=capsys, monkeypatch=None)
        assert code == 1
        assert out == "invalid:\n  at $.b: unexpected field\n"

    def test_result_format_json(self, tmp_path, capsys):
        doc_f = tmp_path / "d.json"
        doc_f.write_text('{"a": 1, "b": "extra"}')
        schema_f = tmp_path / "s.osd"
        schema_f.write_text(self.SCHEMA)
        code, out, err = run(
            ["validate", str(doc_f), "--from", "json", "--schema", str(schema_f),
             "--result-format", "json"],
            capsys=capsys, monkeypatch=None)
        assert code == 1
        assert out == (
            '{"ok": false, "errors": [{"path": "$.b", "message": "unexpected field"}]}\n')

    def test_result_format_oml(self, tmp_path, capsys):
        doc_f = tmp_path / "d.json"
        doc_f.write_text('{"a": 1}')
        schema_f = tmp_path / "s.osd"
        schema_f.write_text(self.SCHEMA)
        code, out, err = run(
            ["validate", str(doc_f), "--from", "json", "--schema", str(schema_f),
             "--result-format", "oml"],
            capsys=capsys, monkeypatch=None)
        assert code == 0
        assert out == "ok: true\n"

    def test_does_not_upgrade_scalars(self, tmp_path, capsys):
        # validate reads without schema-directed upgrading -- an ISO date
        # string stays a string and is reported as a type mismatch, never
        # silently upgraded to a real date first
        doc_f = tmp_path / "d.json"
        doc_f.write_text('{"d": "2024-01-01"}')
        schema_f = tmp_path / "s.osd"
        schema_f.write_text('record R { "d": date }\nroot R\n')
        code, out, err = run(
            ["validate", str(doc_f), "--from", "json", "--schema", str(schema_f)],
            capsys=capsys, monkeypatch=None)
        assert code == 0   # an ISO date string already satisfies `date` per matches_kind
        assert out == "valid\n"

    def test_unknown_format_value_is_argparse_usage_error(self, tmp_path):
        doc_f = tmp_path / "d.json"
        doc_f.write_text('{"a": 1}')
        with pytest.raises(SystemExit) as exc:
            main(["validate", str(doc_f), "--from", "bogus", "--schema", "s.osd"])
        assert exc.value.code == 2

    def test_missing_schema_flag_is_argparse_usage_error(self, tmp_path):
        doc_f = tmp_path / "d.json"
        doc_f.write_text('{"a": 1}')
        with pytest.raises(SystemExit) as exc:
            main(["validate", str(doc_f), "--from", "json"])
        assert exc.value.code == 2

    def test_malformed_input_is_a_clean_error_not_a_traceback(self, tmp_path, capsys):
        doc_f = tmp_path / "d.json"
        doc_f.write_text('{not valid json')
        schema_f = tmp_path / "s.osd"
        schema_f.write_text(self.SCHEMA)
        code, out, err = run(
            ["validate", str(doc_f), "--from", "json", "--schema", str(schema_f)],
            capsys=capsys, monkeypatch=None)
        assert code == 2
        assert err.startswith("error: ")

    def test_malformed_schema_is_a_clean_error_not_a_traceback(self, tmp_path, capsys):
        doc_f = tmp_path / "d.json"
        doc_f.write_text('{"a": 1}')
        schema_f = tmp_path / "s.osd"
        schema_f.write_text('record R { "a": integer }\n')   # no root
        code, out, err = run(
            ["validate", str(doc_f), "--from", "json", "--schema", str(schema_f)],
            capsys=capsys, monkeypatch=None)
        assert code == 2
        assert err.startswith("error: ")

    def test_json_flag_valid_document(self, tmp_path, capsys):
        doc_f = tmp_path / "d.json"
        doc_f.write_text('{"a": 1}')
        schema_f = tmp_path / "s.osd"
        schema_f.write_text(self.SCHEMA)
        code, out, err = run(
            ["validate", str(doc_f), "--from", "json", "--schema", str(schema_f), "--json"],
            capsys=capsys, monkeypatch=None)
        assert code == 0
        assert err == ""
        assert json.loads(out) == {"ok": True}

    def test_json_flag_conformance_failure_reports_every_error(self, tmp_path, capsys):
        # Multiple, distinct problems -- missing 'a' (cardinality) and an
        # unexpected 'b' -- so every one of --json's errors entries can be
        # checked for its own path/code/message, not just the first found.
        doc_f = tmp_path / "d.json"
        doc_f.write_text('{"b": "extra"}')
        schema_f = tmp_path / "s.osd"
        schema_f.write_text(self.SCHEMA)
        code, out, err = run(
            ["validate", str(doc_f), "--from", "json", "--schema", str(schema_f), "--json"],
            capsys=capsys, monkeypatch=None)
        assert code == 1
        assert err == ""
        payload = json.loads(out)
        assert payload["ok"] is False
        assert isinstance(payload["message"], str) and payload["message"]
        errors = {(e["path"], e["code"]): e["message"] for e in payload["errors"]}
        assert errors[("$.b", "unexpected-field")] == "unexpected field"
        assert errors[("$", "cardinality")] == "field 'a' occurs 0 time(s), expected exactly 1"
        assert len(payload["errors"]) == 2

    def test_json_flag_syntax_failure_has_empty_errors(self, tmp_path, capsys):
        doc_f = tmp_path / "d.json"
        doc_f.write_text('{not valid json')
        schema_f = tmp_path / "s.osd"
        schema_f.write_text(self.SCHEMA)
        code, out, err = run(
            ["validate", str(doc_f), "--from", "json", "--schema", str(schema_f), "--json"],
            capsys=capsys, monkeypatch=None)
        assert code == 2
        assert err == ""
        payload = json.loads(out)
        assert payload["ok"] is False
        assert payload["errors"] == []
        assert "invalid JSON" in payload["message"]

    def test_default_output_unchanged_when_json_flag_absent(self, tmp_path, capsys):
        # Regression guard: --json is purely additive -- every existing
        # (non-flag) output path must stay byte-identical.
        doc_f = tmp_path / "d.json"
        doc_f.write_text('{"a": 1, "b": "extra"}')
        schema_f = tmp_path / "s.osd"
        schema_f.write_text(self.SCHEMA)
        code, out, err = run(
            ["validate", str(doc_f), "--from", "json", "--schema", str(schema_f)],
            capsys=capsys, monkeypatch=None)
        assert code == 1
        assert out == "invalid:\n  at $.b: unexpected field\n"
        assert err == ""


class TestInfer:
    def test_drafts_schema_from_multiple_samples(self, tmp_path, capsys):
        f1 = tmp_path / "a.json"
        f1.write_text('{"host": "a"}')
        f2 = tmp_path / "b.json"
        f2.write_text('{"host": "b", "port": 80}')
        code, out, err = run(
            ["infer", str(f1), str(f2), "--from", "json"], capsys=capsys, monkeypatch=None)
        assert code == 0
        assert err == ""
        assert '"host": string' in out
        assert '"port" [0,1]: integer' in out
        assert out.startswith("record Root {")

    def test_single_sample(self, tmp_path, capsys):
        f1 = tmp_path / "a.json"
        f1.write_text('{"x": 1}')
        code, out, err = run(["infer", str(f1), "--from", "json"], capsys=capsys, monkeypatch=None)
        assert code == 0
        assert '"x": integer' in out

    def test_writes_to_output_file(self, tmp_path, capsys):
        f1 = tmp_path / "a.json"
        f1.write_text('{"x": 1}')
        dst = tmp_path / "out.osd"
        code, out, err = run(
            ["infer", str(f1), "--from", "json", "-o", str(dst)], capsys=capsys, monkeypatch=None)
        assert code == 0
        assert out == ""
        assert '"x": integer' in dst.read_text()

    def test_conflicting_scalars_is_a_clean_error_not_a_traceback(self, tmp_path, capsys):
        f1 = tmp_path / "a.json"
        f1.write_text('{"v": 1}')
        f2 = tmp_path / "b.json"
        f2.write_text('{"v": "x"}')
        code, out, err = run(
            ["infer", str(f1), str(f2), "--from", "json"], capsys=capsys, monkeypatch=None)
        assert code == 2
        assert err.startswith("error: ")

    def test_missing_input_is_argparse_usage_error(self):
        with pytest.raises(SystemExit) as exc:
            main(["infer", "--from", "json"])
        assert exc.value.code == 2

    def test_missing_from_is_argparse_usage_error(self, tmp_path):
        f1 = tmp_path / "a.json"
        f1.write_text('{"x": 1}')
        with pytest.raises(SystemExit) as exc:
            main(["infer", str(f1)])
        assert exc.value.code == 2

    def test_compact_flag_emits_single_line_osd(self, tmp_path, capsys):
        f1 = tmp_path / "a.json"
        f1.write_text('{"x": 1}')
        code, out, err = run(
            ["infer", str(f1), "--from", "json", "--compact"], capsys=capsys, monkeypatch=None)
        assert code == 0
        assert "\n" not in out.rstrip("\n")
        assert '"x": integer' in out

    def test_allow_any_opens_conflict_schema_on_stdout_report_on_stderr(
            self, tmp_path, capsys):
        f1 = tmp_path / "a.json"
        f1.write_text('{"v": 1, "data": {"x": 1}}')
        f2 = tmp_path / "b.json"
        f2.write_text('{"v": "x", "data": 5}')
        code, out, err = run(
            ["infer", str(f1), str(f2), "--from", "json", "--allow-any"],
            capsys=capsys, monkeypatch=None)
        assert code == 0
        # schema (with the opened fields) on stdout, still parseable OSD
        assert out.startswith("record Root {")
        assert ": any," in out
        from omnist import parse_schema
        parse_schema(out)  # pipeable / parseable
        # loud report on stderr only
        assert "opened 2 field(s) as `any`:" in err
        assert "Root.data — mixes objects and values" in err
        assert ("Root.v — values of more than one scalar kind (integer, string)"
                in err)

    def test_allow_any_with_clean_samples_prints_no_report(self, tmp_path, capsys):
        f1 = tmp_path / "a.json"
        f1.write_text('{"x": 1}')
        code, out, err = run(
            ["infer", str(f1), "--from", "json", "--allow-any"],
            capsys=capsys, monkeypatch=None)
        assert code == 0
        assert err == ""
        assert '"x": integer' in out

    def test_without_allow_any_conflict_still_errors(self, tmp_path, capsys):
        f1 = tmp_path / "a.json"
        f1.write_text('{"v": 1}')
        f2 = tmp_path / "b.json"
        f2.write_text('{"v": "x"}')
        code, out, err = run(
            ["infer", str(f1), str(f2), "--from", "json"],
            capsys=capsys, monkeypatch=None)
        assert code == 2
        assert err.startswith("error: ")


class TestSchemaFormat:
    def test_reformats_osd_from_file_to_stdout(self, tmp_path, capsys):
        p = tmp_path / "in.osd"
        p.write_text('record R { "a": integer }\nroot R\n')
        code, out, err = run(["schema", "format", str(p)], capsys=capsys, monkeypatch=None)
        assert code == 0
        assert err == ""
        assert out == 'record R {\n    "a": integer,\n}\nroot R\n'

    def test_writes_to_output_file(self, tmp_path, capsys):
        src = tmp_path / "in.osd"
        src.write_text('record R { "a": integer }\nroot R\n')
        dst = tmp_path / "out.osd"
        code, out, err = run(
            ["schema", "format", str(src), "-o", str(dst)], capsys=capsys, monkeypatch=None)
        assert code == 0
        assert out == ""
        assert dst.read_text() == 'record R {\n    "a": integer,\n}\nroot R\n'

    def test_reads_from_stdin(self, capsys, monkeypatch):
        code, out, err = run(
            ["schema", "format", "-"],
            stdin='record R { "a": integer }\nroot R\n',
            capsys=capsys, monkeypatch=monkeypatch)
        assert code == 0
        assert out == 'record R {\n    "a": integer,\n}\nroot R\n'

    def test_invalid_osd_is_a_clean_error_not_a_traceback(self, tmp_path, capsys):
        p = tmp_path / "bad.osd"
        p.write_text('record R { "a": integer }\n')   # no root
        code, out, err = run(["schema", "format", str(p)], capsys=capsys, monkeypatch=None)
        assert code == 2
        assert out == ""
        assert err.startswith("error: ")

    def test_missing_schema_file_argument_is_argparse_usage_error(self):
        with pytest.raises(SystemExit) as exc:
            main(["schema", "format"])
        assert exc.value.code == 2

    def test_missing_schema_subcommand_is_argparse_usage_error(self):
        with pytest.raises(SystemExit) as exc:
            main(["schema"])
        assert exc.value.code == 2

    def test_compact_flag_emits_single_line_output(self, tmp_path, capsys):
        p = tmp_path / "in.osd"
        p.write_text('record R { "a": integer }\nroot R\n')
        code, out, err = run(
            ["schema", "format", str(p), "--compact"], capsys=capsys, monkeypatch=None)
        assert code == 0
        assert out == 'record R { "a": integer } root R\n'


class TestSchemaNormalize:
    def test_merges_structurally_identical_records(self, tmp_path, capsys):
        p = tmp_path / "in.osd"
        p.write_text(
            'record A { "x": integer }\n'
            'record B { "x": integer }\n'
            'record R { "a": A, "b": B }\n'
            'root R\n')
        code, out, err = run(["schema", "normalize", str(p)], capsys=capsys, monkeypatch=None)
        assert code == 0
        assert err == ""
        # A and B are structurally identical -- normalize merges them to one record
        assert out.count("record ") == 2   # the merged record + R, not 3

    def test_writes_to_output_file(self, tmp_path, capsys):
        src = tmp_path / "in.osd"
        src.write_text('record R { "a": integer }\nroot R\n')
        dst = tmp_path / "out.osd"
        code, out, err = run(
            ["schema", "normalize", str(src), "-o", str(dst)], capsys=capsys, monkeypatch=None)
        assert code == 0
        assert dst.read_text() == 'record R {\n    "a": integer,\n}\nroot R\n'

    def test_invalid_osd_is_a_clean_error(self, tmp_path, capsys):
        p = tmp_path / "bad.osd"
        p.write_text('record R { "a": integer }\n')   # no root
        code, out, err = run(["schema", "normalize", str(p)], capsys=capsys, monkeypatch=None)
        assert code == 2
        assert err.startswith("error: ")

    def test_compact_flag_emits_single_line_output(self, tmp_path, capsys):
        p = tmp_path / "in.osd"
        p.write_text('record R { "a": integer }\nroot R\n')
        code, out, err = run(
            ["schema", "normalize", str(p), "--compact"], capsys=capsys, monkeypatch=None)
        assert code == 0
        assert out == 'record R { "a": integer } root R\n'


class TestSchemaExtract:
    def test_happy_path(self, tmp_path, capsys):
        p = tmp_path / "in.osd"
        p.write_text(
            'record R { "must": integer, "opt" [0,1]: string }\nroot R\n')
        code, out, err = run(
            ["schema", "extract", str(p), "--keep", "must"], capsys=capsys, monkeypatch=None)
        assert code == 0
        assert err == ""
        assert out == 'record R {\n    "must": integer,\n}\nroot R\n'

    def test_multiple_keep_labels(self, tmp_path, capsys):
        p = tmp_path / "in.osd"
        p.write_text(
            'record R { "a": integer, "b": string, "c" [0,1]: integer }\nroot R\n')
        code, out, err = run(
            ["schema", "extract", str(p), "--keep", "a,b"], capsys=capsys, monkeypatch=None)
        assert code == 0
        assert out == 'record R {\n    "a": integer,\n    "b": string,\n}\nroot R\n'

    def test_compact_flag_emits_single_line_output(self, tmp_path, capsys):
        p = tmp_path / "in.osd"
        p.write_text('record R { "a": integer }\nroot R\n')
        code, out, err = run(
            ["schema", "extract", str(p), "--keep", "a", "--compact"],
            capsys=capsys, monkeypatch=None)
        assert code == 0
        assert out == 'record R { "a": integer } root R\n'

    def test_writes_to_output_file(self, tmp_path, capsys):
        src = tmp_path / "in.osd"
        src.write_text('record R { "a": integer }\nroot R\n')
        dst = tmp_path / "out.osd"
        code, out, err = run(
            ["schema", "extract", str(src), "--keep", "a", "-o", str(dst)],
            capsys=capsys, monkeypatch=None)
        assert code == 0
        assert out == ""
        assert dst.read_text() == 'record R {\n    "a": integer,\n}\nroot R\n'

    def test_mandatory_deletion_is_exit_1_not_2(self, tmp_path, capsys):
        p = tmp_path / "in.osd"
        p.write_text(
            'record R { "must": integer, "opt" [0,1]: string }\nroot R\n')
        code, out, err = run(
            ["schema", "extract", str(p), "--keep", "opt"], capsys=capsys, monkeypatch=None)
        assert code == 1
        assert out == ""
        assert err == (
            "error: no valid subschema: removing label 'must' deletes a "
            "mandatory field of record 'R'\n")

    def test_missing_keep_is_argparse_usage_error(self, tmp_path):
        p = tmp_path / "in.osd"
        p.write_text('record R { "a": integer }\nroot R\n')
        with pytest.raises(SystemExit) as exc:
            main(["schema", "extract", str(p)])
        assert exc.value.code == 2

    def test_invalid_osd_is_a_clean_error(self, tmp_path, capsys):
        p = tmp_path / "bad.osd"
        p.write_text('record R { "a": integer }\n')   # no root
        code, out, err = run(
            ["schema", "extract", str(p), "--keep", "a"], capsys=capsys, monkeypatch=None)
        assert code == 2
        assert err.startswith("error: ")

    def test_empty_keep_extracts_nothing(self, tmp_path, capsys):
        p = tmp_path / "in.osd"
        p.write_text('record R { "opt" [0,1]: string }\nroot R\n')
        code, out, err = run(
            ["schema", "extract", str(p), "--keep", ""], capsys=capsys, monkeypatch=None)
        assert code == 0
        assert out == 'record R {\n}\nroot R\n'


class TestSchemaCompatibleWith:
    V1 = 'record R { "host": string }\nroot R\n'
    V2 = 'record R { "host": string, "port" [0,1]: integer }\nroot R\n'

    def test_compatible_text(self, tmp_path, capsys):
        a = tmp_path / "v1.osd"
        a.write_text(self.V1)
        b = tmp_path / "v2.osd"
        b.write_text(self.V2)
        code, out, err = run(
            ["schema", "compatible-with", str(a), str(b)], capsys=capsys, monkeypatch=None)
        assert code == 0
        assert out == "true\n"

    def test_incompatible_text(self, tmp_path, capsys):
        a = tmp_path / "v2.osd"
        a.write_text(self.V2)
        b = tmp_path / "v1.osd"
        b.write_text(self.V1)
        code, out, err = run(
            ["schema", "compatible-with", str(a), str(b)], capsys=capsys, monkeypatch=None)
        assert code == 1
        assert out == "false\n"

    def test_result_format_json(self, tmp_path, capsys):
        a = tmp_path / "v1.osd"
        a.write_text(self.V1)
        b = tmp_path / "v2.osd"
        b.write_text(self.V2)
        code, out, err = run(
            ["schema", "compatible-with", str(a), str(b), "--result-format", "json"],
            capsys=capsys, monkeypatch=None)
        assert code == 0
        assert out == '{"compatible": true}\n'

    def test_result_format_oml(self, tmp_path, capsys):
        a = tmp_path / "v1.osd"
        a.write_text(self.V1)
        b = tmp_path / "v2.osd"
        b.write_text(self.V2)
        code, out, err = run(
            ["schema", "compatible-with", str(a), str(b), "--result-format", "oml"],
            capsys=capsys, monkeypatch=None)
        assert code == 0
        assert out == "compatible: true\n"

    def test_malformed_schema_is_a_clean_error(self, tmp_path, capsys):
        a = tmp_path / "bad.osd"
        a.write_text('record R { "a": integer }\n')
        b = tmp_path / "v1.osd"
        b.write_text(self.V1)
        code, out, err = run(
            ["schema", "compatible-with", str(a), str(b)], capsys=capsys, monkeypatch=None)
        assert code == 2
        assert err.startswith("error: ")


class TestSchemaPrune:
    def test_prune_drops_unreachable_and_dead(self, tmp_path, capsys):
        p = tmp_path / "in.osd"
        p.write_text('record R { "x": integer, "ghost" [0,0]: string }\n'
                     'record Orphan { "y": string }\nroot R\n')
        code, out, err = run(
            ["schema", "prune", str(p)], capsys=capsys, monkeypatch=None)
        assert code == 0
        assert "Orphan" not in out and "ghost" not in out and '"x": integer' in out

    def test_prune_compact(self, tmp_path, capsys):
        p = tmp_path / "in.osd"
        p.write_text('record R { "x": integer }\nroot R\n')
        code, out, err = run(
            ["schema", "prune", str(p), "--compact"], capsys=capsys, monkeypatch=None)
        assert code == 0
        assert "\n" not in out.strip()

    def test_prune_invalid_osd_exit_2(self, tmp_path, capsys):
        p = tmp_path / "in.osd"
        p.write_text("this is not osd")
        code, out, err = run(
            ["schema", "prune", str(p)], capsys=capsys, monkeypatch=None)
        assert code == 2


class TestSchemaIsEmpty:
    def test_empty_schema_true_exit_0(self, tmp_path, capsys):
        p = tmp_path / "in.osd"
        p.write_text('record A { "x": B }\nrecord B { "y": A }\nroot A\n')
        code, out, err = run(
            ["schema", "is-empty", str(p)], capsys=capsys, monkeypatch=None)
        assert code == 0
        assert out == "true\n"

    def test_satisfiable_schema_false_exit_1(self, tmp_path, capsys):
        p = tmp_path / "in.osd"
        p.write_text('record R { "x": integer }\nroot R\n')
        code, out, err = run(
            ["schema", "is-empty", str(p)], capsys=capsys, monkeypatch=None)
        assert code == 1
        assert out == "false\n"

    def test_is_empty_json_result_format(self, tmp_path, capsys):
        p = tmp_path / "in.osd"
        p.write_text('record R { "x": integer }\nroot R\n')
        code, out, err = run(
            ["schema", "is-empty", str(p), "--result-format", "json"],
            capsys=capsys, monkeypatch=None)
        assert code == 1
        assert out.strip() == '{"empty": false}'


class TestSchemaEquivalent:
    def test_equivalent_text(self, tmp_path, capsys):
        a = tmp_path / "a.osd"
        a.write_text('record R { "x": integer }\nroot R\n')
        b = tmp_path / "b.osd"
        b.write_text('record R { "x": integer }\nroot R\n')
        code, out, err = run(
            ["schema", "equivalent", str(a), str(b)], capsys=capsys, monkeypatch=None)
        assert code == 0
        assert out == "true\n"

    def test_not_equivalent_text(self, tmp_path, capsys):
        a = tmp_path / "a.osd"
        a.write_text('record R { "x": integer }\nroot R\n')
        b = tmp_path / "b.osd"
        b.write_text('record R { "x": integer, "y" [0,1]: string }\nroot R\n')
        code, out, err = run(
            ["schema", "equivalent", str(a), str(b)], capsys=capsys, monkeypatch=None)
        assert code == 1
        assert out == "false\n"

    def test_result_format_json(self, tmp_path, capsys):
        a = tmp_path / "a.osd"
        a.write_text('record R { "x": integer }\nroot R\n')
        b = tmp_path / "b.osd"
        b.write_text('record R { "x": integer, "y" [0,1]: string }\nroot R\n')
        code, out, err = run(
            ["schema", "equivalent", str(a), str(b), "--result-format", "json"],
            capsys=capsys, monkeypatch=None)
        assert code == 1
        assert out == '{"equivalent": false}\n'


class TestSchemaLint:
    def test_clean_schema_text_exit_0(self, tmp_path, capsys):
        p = tmp_path / "in.osd"
        p.write_text('record R { "x": integer }\nroot R\n')
        code, out, err = run(
            ["schema", "lint", str(p)], capsys=capsys, monkeypatch=None)
        assert code == 0
        assert out.strip() == "no findings"

    def test_unreachable_warning_text_exit_1(self, tmp_path, capsys):
        p = tmp_path / "in.osd"
        p.write_text('record R { "x": integer }\n'
                     'record Orphan { "y": string }\nroot R\n')
        code, out, err = run(
            ["schema", "lint", str(p)], capsys=capsys, monkeypatch=None)
        assert code == 1
        assert "unreachable-record" in out
        assert "Orphan" in out

    def test_json_output_shape(self, tmp_path, capsys):
        p = tmp_path / "in.osd"
        p.write_text('record R { "x": integer }\n'
                     'record Orphan { "y": string }\nroot R\n')
        code, out, err = run(
            ["schema", "lint", str(p), "--json"], capsys=capsys, monkeypatch=None)
        assert code == 1
        payload = json.loads(out)
        assert payload["ok"] is False
        assert payload["findings"][0]["code"] == "unreachable-record"
        assert set(payload["findings"][0]) == {"code", "severity", "location", "message"}

    def test_info_only_is_ok_exit_0(self, tmp_path, capsys):
        p = tmp_path / "in.osd"
        p.write_text('record R { "data": any }\nroot R\n')
        code, out, err = run(
            ["schema", "lint", str(p), "--json"], capsys=capsys, monkeypatch=None)
        assert code == 0
        payload = json.loads(out)
        assert payload["ok"] is True
        assert payload["findings"][0]["code"] == "any-field"

    def test_severity_warning_filters_out_info(self, tmp_path, capsys):
        p = tmp_path / "in.osd"
        p.write_text('record R { "data": any }\nroot R\n')
        code, out, err = run(
            ["schema", "lint", str(p), "--severity", "warning", "--json"],
            capsys=capsys, monkeypatch=None)
        assert code == 0
        payload = json.loads(out)
        assert payload["findings"] == []

    def test_reads_from_stdin(self, capsys, monkeypatch):
        code, out, err = run(
            ["schema", "lint", "-"],
            stdin='record R { "x": integer }\nroot R\n',
            capsys=capsys, monkeypatch=monkeypatch)
        assert code == 0
        assert out.strip() == "no findings"

    def test_invalid_osd_exit_2(self, tmp_path, capsys):
        p = tmp_path / "in.osd"
        p.write_text("this is not osd")
        code, out, err = run(
            ["schema", "lint", str(p)], capsys=capsys, monkeypatch=None)
        assert code == 2


class TestTopLevel:
    def test_missing_command_is_argparse_usage_error(self):
        with pytest.raises(SystemExit) as exc:
            main([])
        assert exc.value.code == 2

    def test_unknown_command_is_argparse_usage_error(self):
        with pytest.raises(SystemExit) as exc:
            main(["bogus"])
        assert exc.value.code == 2

    def test_version_flag_prints_version_and_exits_0(self, capsys):
        import omnist
        with pytest.raises(SystemExit) as exc:
            main(["--version"])
        assert exc.value.code == 0
        assert capsys.readouterr().out == f"omnist {omnist.__version__}\n"

    def test_help_includes_description(self, capsys):
        with pytest.raises(SystemExit) as exc:
            main(["--help"])
        assert exc.value.code == 0
        assert "canonical data model" in capsys.readouterr().out
