"""Executes the exact CLI examples shown in docs/cli.md, against the real
fixture files in examples/cli/, so the docs can't silently drift from what
running them actually produces -- same convention as test_docs.py, applied
to the CLI page. Assumes cwd is the repo root (pytest's default).
"""
from __future__ import annotations

import pytest

from omnist import __version__
from omnist.cli import main


def run(argv, capsys, stdin_text=None, monkeypatch=None):
    if stdin_text is not None:
        import io
        monkeypatch.setattr("sys.stdin", io.StringIO(stdin_text))
    code = main(argv)
    out = capsys.readouterr()
    return code, out.out, out.err


class TestVersionAndHelpExample:
    def test_version(self, capsys):
        with pytest.raises(SystemExit) as exc:
            main(["--version"])
        assert exc.value.code == 0
        assert capsys.readouterr().out == f"omnist {__version__}\n"

    def test_help(self, capsys, monkeypatch):
        # argparse wraps help text based on terminal width (via COLUMNS);
        # pin it so this assertion doesn't depend on the runner's environment.
        monkeypatch.setenv("COLUMNS", "80")
        with pytest.raises(SystemExit) as exc:
            main(["--help"])
        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert out == (
            "usage: omnist [-h] [--version]\n"
            "              {format,convert,check,validate,infer,schema} ...\n"
            "\n"
            "One canonical data model for JSON, YAML, TOML, XML, and OML -- read, validate,\n"
            "and write any of them. See docs/cli.md for the full command reference.\n"
            "\n"
            "positional arguments:\n"
            "  {format,convert,check,validate,infer,schema}\n"
            "    format              canonicalize an OML document (the only format with no\n"
            "                        other tool for this)\n"
            "    convert             convert a document between formats (one in, one out)\n"
            "    check               report what writing as --to would adjust, without ever\n"
            "                        writing\n"
            "    validate            check a document against a schema (no schema-directed\n"
            "                        upgrading)\n"
            "    infer               draft a schema from example documents (all the same\n"
            "                        format)\n"
            "    schema              operate on a Schema (OSD)\n"
            "\n"
            "options:\n"
            "  -h, --help            show this help message and exit\n"
            "  --version             show program's version number and exit\n"
        )


class TestFormatExample:
    def test_messy_person_oml_reformats(self, capsys):
        code, out, err = run(["format", "examples/cli/messy-person.oml"], capsys)
        assert code == 0
        assert out == 'name: "Ann"\nage: 30\n'
        assert err == ""

    def test_pipe_example(self, capsys, monkeypatch):
        code, out, err = run(
            ["format", "-"], capsys, stdin_text='name:   "Ann"', monkeypatch=monkeypatch)
        assert code == 0
        assert out == 'name: "Ann"\n'

    def test_messy_person_oml_compact(self, capsys):
        code, out, err = run(
            ["format", "examples/cli/messy-person.oml", "--compact"], capsys)
        assert code == 0
        assert out == 'name: "Ann"; age: 30\n'


class TestConvertExamples:
    def test_person_json_to_oml(self, capsys):
        code, out, err = run(
            ["convert", "examples/cli/person.json", "--from", "json", "--to", "oml"], capsys)
        assert code == 0
        assert out == 'person: {\n  name: "Ann"\n  age: 30\n}\n'

    def test_person_xml_to_oml_with_schema(self, capsys):
        code, out, err = run(
            ["convert", "examples/cli/person.xml", "--from", "xml", "--to", "oml",
             "--schema", "examples/cli/person.osd"], capsys)
        assert code == 0
        assert out == 'person: {\n  name: "Ann"\n  age: 30\n}\n'

    def test_toml_to_json_via_stdin(self, capsys, monkeypatch):
        with open("examples/cli/person.toml", encoding="utf-8") as f:
            toml_text = f.read()
        code, out, err = run(
            ["convert", "-", "--from", "toml", "--to", "json"], capsys,
            stdin_text=toml_text, monkeypatch=monkeypatch)
        assert code == 0
        assert out == '{"person": {"name": "Ann", "age": 30}}\n'

    def test_report_on_lossy_json_to_toml(self, capsys):
        code, out, err = run(
            ["convert", "examples/cli/lossy.json", "--from", "json", "--to", "toml", "--report"],
            capsys)
        assert code == 0
        assert out == 'name = "Ann"\n'
        assert err == "warning: $.age: null value dropped (TOML has no null)\n"

    def test_strict_on_lossy_json_to_toml(self, capsys):
        code, out, err = run(
            ["convert", "examples/cli/lossy.json", "--from", "json", "--to", "toml", "--strict"],
            capsys)
        assert code == 1
        assert out == ""
        assert err == "error: warning: $.age: null value dropped (TOML has no null)\n"


class TestCheckExamples:
    def test_lossy_json_to_toml(self, capsys):
        code, out, err = run(
            ["check", "examples/cli/lossy.json", "--from", "json", "--to", "toml"], capsys)
        assert code == 0
        assert out == "warning: $.age: null value dropped (TOML has no null)\n"

    def test_lossy_json_to_toml_strict(self, capsys):
        code, out, err = run(
            ["check", "examples/cli/lossy.json", "--from", "json", "--to", "toml", "--strict"],
            capsys)
        assert code == 1
        assert out == "warning: $.age: null value dropped (TOML has no null)\n"


class TestInferExample:
    def test_sample1_sample2(self, capsys):
        code, out, err = run(
            ["infer", "examples/cli/sample1.json", "examples/cli/sample2.json", "--from", "json"],
            capsys)
        assert code == 0
        assert out == (
            'record Root {\n'
            '    "name": string,\n'
            '    "age" [0,1]: integer,\n'
            '}\n'
            'root Root\n'
        )


class TestValidateExamples:
    def test_person_is_valid(self, capsys):
        code, out, err = run(
            ["validate", "examples/cli/person.json", "--from", "json",
             "--schema", "examples/cli/person.osd"], capsys)
        assert code == 0
        assert out == "valid\n"

    def test_invalid_person_text(self, capsys):
        code, out, err = run(
            ["validate", "examples/cli/invalid-person.json", "--from", "json",
             "--schema", "examples/cli/person.osd"], capsys)
        assert code == 1
        assert out == (
            "invalid:\n"
            "  at $.person.age: expected integer, got string ('thirty')\n"
            "  at $.person: field 'name' occurs 0 time(s), expected exactly 1\n"
        )

    def test_invalid_person_json(self, capsys):
        code, out, err = run(
            ["validate", "examples/cli/invalid-person.json", "--from", "json",
             "--schema", "examples/cli/person.osd", "--result-format", "json"], capsys)
        assert code == 1
        assert out == (
            '{"ok": false, "errors": ['
            '{"path": "$.person.age", "message": "expected integer, got string (\'thirty\')"}, '
            '{"path": "$.person", '
            '"message": "field \'name\' occurs 0 time(s), expected exactly 1"}'
            ']}\n'
        )

    def test_person_json_flag(self, capsys):
        code, out, err = run(
            ["validate", "examples/cli/person.json", "--from", "json",
             "--schema", "examples/cli/person.osd", "--json"], capsys)
        assert code == 0
        assert out == '{"ok": true}\n'

    def test_invalid_person_json_flag(self, capsys):
        code, out, err = run(
            ["validate", "examples/cli/invalid-person.json", "--from", "json",
             "--schema", "examples/cli/person.osd", "--json"], capsys)
        assert code == 1
        assert out == (
            '{"ok": false, "message": "invalid:\\n'
            '  at $.person.age: expected integer, got string (\'thirty\')\\n'
            '  at $.person: field \'name\' occurs 0 time(s), expected exactly 1", '
            '"errors": ['
            '{"path": "$.person.age", "code": "type-mismatch", '
            '"message": "expected integer, got string (\'thirty\')"}, '
            '{"path": "$.person", "code": "cardinality", '
            '"message": "field \'name\' occurs 0 time(s), expected exactly 1"}'
            ']}\n'
        )

    def test_syntax_failure_json_flag_via_stdin(self, capsys, monkeypatch):
        code, out, err = run(
            ["validate", "-", "--from", "json", "--schema", "examples/cli/person.osd", "--json"],
            capsys, stdin_text='{not valid json', monkeypatch=monkeypatch)
        assert code == 2
        assert out == (
            '{"ok": false, "message": "invalid JSON: Expecting property name enclosed '
            'in double quotes: line 1 column 2 (char 1)", "errors": []}\n'
        )


class TestSchemaFormatExample:
    def test_messy_person_osd_reformats(self, capsys):
        code, out, err = run(["schema", "format", "examples/cli/messy-person.osd"], capsys)
        assert code == 0
        assert out == (
            'record Person {\n'
            '    "name": string,\n'
            '    "age" [0,1]: integer,\n'
            '}\n'
            'root Person\n'
        )

    def test_messy_person_osd_compact(self, capsys):
        code, out, err = run(
            ["schema", "format", "examples/cli/messy-person.osd", "--compact"], capsys)
        assert code == 0
        assert out == 'record Person { "name": string, "age" [0,1]: integer } root Person\n'


class TestSchemaPruneExample:
    def test_prune_stdin_example(self, capsys, monkeypatch):
        code, out, err = run(
            ["schema", "prune", "-"], capsys,
            stdin_text='record R { "x": integer, "ghost" [0,0]: string }\n'
                       'record Orphan { "y": string }\nroot R\n',
            monkeypatch=monkeypatch)
        assert code == 0
        assert out == 'record R {\n    "x": integer,\n}\nroot R\n'


class TestSchemaIsEmptyExample:
    def test_is_empty_stdin_example(self, capsys, monkeypatch):
        code, out, err = run(
            ["schema", "is-empty", "-"], capsys,
            stdin_text='record A { "x": B }\nrecord B { "y": A }\nroot A\n',
            monkeypatch=monkeypatch)
        assert code == 0
        assert out == "true\n"


class TestSchemaLintExample:
    def test_duplicate_records_lint(self, capsys):
        code, out, err = run(
            ["schema", "lint", "examples/cli/duplicate-records.osd"], capsys)
        assert code == 1
        assert out == (
            "warning: duplicate-record: Customer, Employee: records "
            "'Employee' are structurally identical to 'Customer'; "
            "merge them with `schema normalize`\n"
        )


class TestSchemaNormalizeExample:
    def test_merges_duplicate_records(self, capsys):
        code, out, err = run(
            ["schema", "normalize", "examples/cli/duplicate-records.osd"], capsys)
        assert code == 0
        assert out == (
            'record Company {\n'
            '    "employee": Customer,\n'
            '    "customer": Customer,\n'
            '}\n'
            'record Customer {\n'
            '    "name": string,\n'
            '}\n'
            'root Company\n'
        )


class TestSchemaExtractExample:
    def test_quote_order_extract_drops_order_side(self, capsys):
        code, out, err = run(
            ["schema", "extract", "examples/cli/quote-order.osd",
             "--keep", "quote,line,desc,price"], capsys)
        assert code == 0
        assert out == (
            'record Line {\n'
            '    "desc": string,\n'
            '    "price": number,\n'
            '}\n'
            'record Quote {\n'
            '    "line" [1,]: Line,\n'
            '}\n'
            'record Root {\n'
            '    "quote" [0,1]: Quote,\n'
            '}\n'
            'root Root\n'
        )

    def test_mandatory_deletion_error_via_stdin(self, capsys, monkeypatch):
        code, out, err = run(
            ["schema", "extract", "-", "--keep", "opt"], capsys,
            stdin_text='record R { "must": integer, "opt" [0,1]: string }\nroot R\n',
            monkeypatch=monkeypatch)
        assert code == 1
        assert out == ""
        assert err == (
            "error: no valid subschema: removing label 'must' deletes a "
            "mandatory field of record 'R'\n")


class TestSchemaCompatibleWithExample:
    def test_v1_compatible_with_v2(self, capsys):
        code, out, err = run(
            ["schema", "compatible-with", "examples/cli/v1.osd", "examples/cli/v2.osd"], capsys)
        assert code == 0
        assert out == "true\n"


class TestSchemaEquivalentExample:
    def test_v1_not_equivalent_to_v2(self, capsys):
        code, out, err = run(
            ["schema", "equivalent", "examples/cli/v1.osd", "examples/cli/v2.osd"], capsys)
        assert code == 1
        assert out == "false\n"
