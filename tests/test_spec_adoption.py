"""Adoption of omnist-spec v0.21.0-beta (D-14, D-21, E-11, E-23, E-13, E-27,
OML-25/26/27, OSD-14/15, the YAML merge-key order, the algebra/document/format
codes).

Each test states the rule it pins and, where the behaviour used to differ,
what the reference did before -- measured, not assumed (docs/09-divergence-
ledger.md DIV-4, DIV-5, DIV-6).
"""
from __future__ import annotations

import importlib
import io
import json
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from omnist import (
    Doc,
    Field,
    ParseError,
    Record,
    Ref,
    Scalar,
    Schema,
    SchemaError,
    WriteError,
    infer,
    infer_with_report,
    parse_schema,
    read_json,
    read_oml,
    read_toml,
    read_xml,
    read_yaml,
    to_osd,
    write_xml,
)
from omnist._encoding import decode_utf8, strip_bom
from omnist._position import line_col, position
from omnist.cli import _errors_of, main
from omnist.errors import DocumentError

fmt = importlib.import_module("omnist.formats")
BOM = "\ufeff"


def cli(argv, capsys, monkeypatch=None, stdin=None):
    if stdin is not None:
        monkeypatch.setattr("sys.stdin", stdin)
    code = main(argv)
    out, err = capsys.readouterr()
    return code, out, err


def diag(out):
    return [(e["path"], e["code"]) for e in json.loads(out)["errors"]]


# ---------------------------------------------------------------- D-14

class TestInvalidUtf8AtTheByteOrientedEntryPoint:
    """D-14: the CLI decodes on the caller's behalf, so it is a byte-oriented
    entry point and invalid UTF-8 MUST be `parse.invalid-encoding` at `1:1`.
    Before: an uncaught UnicodeDecodeError, exit 1, no diagnostic (DIV-6)."""

    BAD = [
        b'{"a":"x\xe2\x82"}',            # truncated sequence
        b"\x80{}",                       # lone continuation byte at offset 0
        b'a: "x\xc0\xaf"\n',             # overlong encoding
        b'a: "x\xed\xa0\x80"\n',         # an encoded surrogate
        b'a = "x\xf5\x80\x80\x80"\n',    # above U+10FFFF
        b"\xef\xbb",                     # a *truncated BOM*: D-14 fires, not D-15
    ]

    @pytest.mark.parametrize("data", BAD)
    @pytest.mark.parametrize("from_", ["json", "yaml", "toml", "xml", "oml"])
    def test_file_input_every_codec(self, tmp_path, capsys, data, from_):
        p = tmp_path / "in"
        p.write_bytes(data)
        argv = (["format", str(p), "--json"] if from_ == "oml" else
                ["convert", str(p), "--from", from_, "--to", "oml", "--json"])
        code, out, err = cli(argv, capsys)
        assert code == 2 and err == ""
        assert diag(out) == [("1:1", "parse.invalid-encoding")]     # exactly one diagnostic

    @pytest.mark.parametrize("cmd", [["format"], ["schema", "format"], ["schema", "normalize"]])
    def test_oml_and_osd_commands(self, tmp_path, capsys, cmd):
        p = tmp_path / "in"
        p.write_bytes(b'a: "x\xe2\x82"\n')
        code, out, _ = cli([*cmd, str(p), "--json"], capsys)
        assert code == 2 and diag(out) == [("1:1", "parse.invalid-encoding")]

    def test_plain_error_output_names_the_rule_without_a_traceback(self, tmp_path, capsys):
        p = tmp_path / "in"
        p.write_bytes(b"\xff")
        code, out, err = cli(["format", str(p)], capsys)
        assert code == 2 and out == "" and err.startswith("error: input is not valid UTF-8")

    def test_stdin_bytes_are_decoded_strictly(self, capsys, monkeypatch):
        stdin = io.TextIOWrapper(io.BytesIO(b'a: "x\xe2\x82"\n'), encoding="utf-8")
        code, out, _ = cli(["format", "-", "--json"], capsys, monkeypatch, stdin)
        assert code == 2 and diag(out) == [("1:1", "parse.invalid-encoding")]

    def test_stdin_valid_multibyte_is_accepted_and_newlines_are_not_translated(
            self, capsys, monkeypatch):
        stdin = io.TextIOWrapper(io.BytesIO('a: "é€😀"\r\nb: 2\r\n'.encode()), encoding="utf-8")
        code, out, _ = cli(["convert", "-", "--from", "oml", "--to", "json"], capsys,
                           monkeypatch, stdin)
        assert code == 0 and json.loads(out) == {"a": "é€😀", "b": 2}

    def test_a_text_only_stdin_is_already_decoded(self, capsys, monkeypatch):
        """A str-typed source may be treated as decoded (Sec2.5): an in-process
        stand-in for stdin has no bytes to validate."""
        code, out, _ = cli(["format", "-"], capsys, monkeypatch, io.StringIO("a: 1\n"))
        assert code == 0 and out == "a: 1\n"

    def test_file_input_valid_multibyte_and_crlf(self, tmp_path, capsys):
        p = tmp_path / "in.json"
        p.write_bytes('{"a": "é€😀"}\r\n'.encode())
        code, out, _ = cli(["convert", str(p), "--from", "json", "--to", "oml"], capsys)
        assert code == 0 and "é€😀" in out

    def test_decode_utf8_reports_one_diagnostic_at_1_1_and_never_repairs(self):
        with pytest.raises(ParseError) as exc:
            decode_utf8(b"ok\n\xff\xfe\xfd more \xc0\n")
        assert (exc.value.code, exc.value.path) == ("parse.invalid-encoding", "1:1")
        assert exc.value.errors == []
        assert decode_utf8("é€😀".encode()) == "é€😀"
        assert decode_utf8(b"") == ""

    def test_a_str_typed_reader_treats_its_input_as_already_decoded(self):
        """D-14 is about bytes; a U+FFFD or a surrogate-escape artefact inside
        a str is a property of an already-decoded string (Sec2.5)."""
        assert read_json('{"a": "\ufffd"}') == [("a", "\ufffd")]
        assert read_oml('a: "\udcff"\n') == [("a", "\udcff")]


# ---------------------------------------------------------------- D-21

class TestStripBom:
    def test_one_mark_is_consumed_and_only_at_offset_zero(self):
        assert strip_bom(BOM + "a" + BOM) == "a" + BOM
        assert strip_bom("a") == "a"

    def test_a_second_mark_is_left_alone_unless_the_caller_asks(self):
        assert strip_bom(BOM + BOM + "a") == BOM + "a"           # OML/OSD reject it themselves

    def test_a_second_mark_is_rejected_at_1_1_for_a_codec(self):
        with pytest.raises(ParseError) as exc:
            strip_bom(BOM + BOM + "a", reject_second=True)
        assert (exc.value.code, exc.value.path) == ("parse.codec-syntax", "1:1")
        assert strip_bom(BOM + "a", reject_second=True) == "a"
        assert strip_bom("a" + BOM, reject_second=True) == "a" + BOM

    def test_yaml_first_unquoted_key_starting_with_a_mark_is_the_documented_loss(self):
        with pytest.raises(ParseError):
            read_yaml(BOM + BOM + "a: 1\n")
        assert read_yaml(BOM + 'a' + BOM + 'b: 1\n') == [("a" + BOM + "b", 1)]
        assert read_yaml(BOM + '"' + BOM + 'a": 1\n') == [(BOM + "a", 1)]


# ------------------------------------------------------- E-11: positions

def test_line_col_and_position():
    assert line_col("ab\ncd", 0) == (1, 1)
    assert line_col("ab\ncd", 2) == (1, 3)
    assert line_col("ab\ncd", 3) == (2, 1)
    assert line_col("ab\ncd", 5) == (2, 3)          # just past the last character
    assert position("ab\ncd", 4) == "2:2"


class TestCodecSyntaxCarriesALineColPath:
    """`parse.codec-syntax` with a `line:col` path (E-11). Before: `parse.syntax`,
    an unregistered code, with no path at all (DIV-4)."""

    @pytest.mark.parametrize("reader,text,expected", [
        # (a trailing comma is not used here: CPython 3.13 words and positions
        # that error differently from 3.11/3.12, and the position is the library's)
        (read_json, '{"a" 1}', "1:6"),
        (read_json, '{\n "a": 1,\n "b" 2}', "3:6"),
        (read_json, "", "1:1"),
        (read_toml, "a = \n", "1:5"),
        (read_toml, "a = 1\nb = \n", "2:5"),
        (read_yaml, "a: [1, 2\n", "2:1"),
        (read_yaml, "a: 1\n b: 2\n", "2:3"),
        (read_yaml, "<<: *x\n", "1:5"),
        (read_yaml, "a: \x07\n", "1:4"),                       # PyYAML's ReaderError offset
        (read_xml, "<a>\n  <b></a>", "2:8"),
        (read_xml, "", "1:1"),
    ])
    def test_position(self, reader, text, expected):
        with pytest.raises(ParseError) as exc:
            reader(text)
        assert (exc.value.code, exc.value.path) == ("parse.codec-syntax", expected)

    def test_toml_position_helpers(self):
        class NewStyle(Exception):                  # Python 3.14 exposes the position
            lineno, colno = 4, 9

        assert fmt._toml_position(NewStyle("x"), "") == "4:9"
        assert fmt._toml_position(Exception("Invalid value (at line 2, column 3)"), "") == "2:3"
        assert fmt._toml_position(Exception("Unclosed (at end of document)"), "ab\ncd") == "2:3"
        assert fmt._toml_position(Exception("no position at all"), "ab") == "1:1"

    def test_yaml_position_helpers(self):
        class Marked(Exception):
            class problem_mark:
                line, column = 2, 4

        class ContextOnly(Exception):
            problem_mark = None

            class context_mark:
                line, column = 0, 0

        class Reader(Exception):
            position = 4

        assert fmt._yaml_position(Marked(), "") == "3:5"
        assert fmt._yaml_position(ContextOnly(), "") == "1:1"
        assert fmt._yaml_position(Reader(), "ab\ncd") == "2:2"
        assert fmt._yaml_position(Exception(), "") == "1:1"


# ---------------------------------------- XML data profile (E-7, xml.md)

class TestXmlProfileRefusalsComeAfterWellFormedness:
    """`format.dtd-forbidden`, `format.entity-forbidden` and
    `format.mixed-content` are refusals of well-formed input at path `$`, and
    a malformed document is a syntax error even when it also has an entity.
    Before: all three were `parse.syntax` (issue #345)."""

    @pytest.mark.parametrize("text,code", [
        ("<d><f>&nbsp;</f></d>", "format.entity-forbidden"),
        ('<d a="&nbsp;"><f>x</f></d>', "format.entity-forbidden"),     # inside an attribute value
        ("<!DOCTYPE d><d/>", "format.dtd-forbidden"),
        ('<!DOCTYPE d [<!ENTITY x "y">]><d>&x;</d>', "format.dtd-forbidden"),
        ("<d>text<f/></d>", "format.mixed-content"),
        ("<d><f/>text</d>", "format.mixed-content"),
    ])
    def test_refusal(self, text, code):
        with pytest.raises(ParseError) as exc:
            read_xml(text)
        assert (exc.value.code, exc.value.path) == (code, "$")

    @pytest.mark.parametrize("text", [
        "<d>&nbsp;<f></d>",                    # malformed: mismatched tag, and an entity
        "<d><f>&nbsp;</f>",                    # malformed: unclosed
        '<d a="&nbsp;"><f></d>',               # entity in an attribute, then malformed
        "<d>&nbsp;",                           # malformed: never closed
    ])
    def test_malformed_input_with_an_entity_is_a_syntax_error(self, text):
        with pytest.raises(ParseError) as exc:
            read_xml(text)
        assert exc.value.code == "parse.codec-syntax"
        assert exc.value.path != "$"

    def test_a_syntax_error_before_the_entity_wins_naturally(self):
        with pytest.raises(ParseError) as exc:
            read_xml("<d><</d>&nbsp;")
        assert exc.value.code == "parse.codec-syntax"

    def test_predefined_and_numeric_references_and_cdata_are_fine(self):
        assert read_xml("<d>&lt;&gt;&amp;&quot;&apos;&#65;&#x42;</d>") == [("d", "<>&\"'AB")]
        assert read_xml("<d><![CDATA[&nbsp; &undefined;]]></d>") == [("d", "&nbsp; &undefined;")]
        assert read_xml("<d><!-- &nbsp; --><f>x</f></d>") == [("d", [("f", "x")])]

    def test_the_entity_recheck_reports_a_failure_it_cannot_neutralise_as_syntax(self):
        # an undefined reference the neutralising pattern does not cover
        # (a name starting with a digit): the re-check fails again, and that
        # is reported as what it is, at its own position.
        with pytest.raises(ParseError) as exc:
            read_xml("<d>&1x;</d>")
        assert exc.value.code == "parse.codec-syntax"

    def test_multi_root_write_is_format_multiple_roots(self):
        with pytest.raises(WriteError) as exc:
            write_xml([("a", 1), ("b", 2)])
        assert (exc.value.code, exc.value.path) == ("format.multiple-roots", "$")

    def test_cli_reports_the_refusal_as_a_structured_diagnostic(self, tmp_path, capsys):
        p = tmp_path / "in.xml"
        p.write_text("<d><f>&nbsp;</f></d>")
        code, out, _ = cli(["convert", str(p), "--from", "xml", "--to", "oml", "--json"], capsys)
        assert code == 2 and diag(out) == [("$", "format.entity-forbidden")]


# ---------------------------------------------- document.* codes (D-13)

class TestDocumentCodes:
    """`document.*` diagnostics carry a code and a Document path (E-11)."""

    @pytest.mark.parametrize("reader,text,path", [
        (read_json, '{"m":[[1,2],[3,4]]}', "$.m[0]"),
        (read_json, "[1]", "$"),
        (read_yaml, "on:\n  push: true\n", "$"),
    ])
    def test_unlabeled_element(self, reader, text, path):
        with pytest.raises(DocumentError) as exc:
            reader(text)
        assert (exc.value.code, exc.value.path) == ("document.unlabeled-element", path)

    def test_depth_nodes_and_int_digits_limits(self):
        with pytest.raises(ParseError) as exc:
            read_json("[" * 300 + "]" * 300)
        assert (exc.value.code, exc.value.path) == ("document.limit.depth", "$")
        with pytest.raises(ParseError) as exc:
            read_oml("a: " + "{ b: " * 300 + "1" + " }" * 300)
        assert (exc.value.code, exc.value.path) == ("document.limit.depth", "$")
        with pytest.raises(ParseError) as exc:
            read_json('{"n": ' + "9" * 5000 + "}")
        assert (exc.value.code, exc.value.path) == ("document.limit.int-digits", "$")
        with pytest.raises(ParseError) as exc:
            read_oml("n: " + "9" * 5000)
        assert (exc.value.code, exc.value.path) == ("document.limit.int-digits", "$")
        with pytest.raises(DocumentError) as exc:
            Doc.of({"n": 10 ** 5000})
        assert (exc.value.code, exc.value.path) == ("document.limit.int-digits", "$.n")

    def test_the_cli_reports_a_document_error_as_a_diagnostic(self, tmp_path, capsys):
        p = tmp_path / "in.json"
        p.write_text('{"m":[[1]]}')
        code, out, _ = cli(["convert", str(p), "--from", "json", "--to", "oml", "--json"], capsys)
        assert code == 2 and diag(out) == [("$.m[0]", "document.unlabeled-element")]

    def test_errors_of_an_uncoded_failure_is_empty(self):
        assert _errors_of(DocumentError("plain")) == []
        assert _errors_of(ParseError("plain")) == []


# ------------------------------------------------- OML-25 / OML-26 / OML-27

class TestOmlLeftoverAndSeparators:
    """The code depends on whether the document has ended, not on what is
    missing (E-25). Before: `parse.unexpected-token` for all of them, and
    `parse.trailing-content` was never emitted at all (DIV-4)."""

    @pytest.mark.parametrize("text,path", [
        ("a: 1 b: 2", "1:6"),
        ("a: 2024-01-01T99", "1:14"),
        ("a: 1 }", "1:6"),
        ("a: 1 ,", "1:6"),
        ("a: 1\n}", "2:1"),
        ("nan: 1", "1:4"), ("inf: 1", "1:4"), ("5: 1", "1:2"),
        ("true: 1", "1:5"), ("null: 1", "1:5"),
        ("1\n2", "2:1"),
        ("{a: 1} b", "1:8"),
        ("a: {b: 1}}", "1:10"),
    ])
    def test_trailing_content(self, text, path):
        with pytest.raises(ParseError) as exc:
            read_oml(text)
        assert (exc.value.code, exc.value.path) == ("parse.trailing-content", path)

    @pytest.mark.parametrize("text,path", [
        ("a: { b: 1 c: 2 }", "1:11"),
        ("a: [1 2]", "1:7"),
        ("a: [1, 2\n", "2:1"),                    # unterminated: NOT separator-in-array
        ("a: [1\n", "2:1"),
        ("x: {a: [1, 2\n}", "2:1"),
        ("x: {a: [1\n}", "2:1"),
        ("[1, 2] 3", "1:1"),
    ])
    def test_unexpected_token(self, text, path):
        with pytest.raises(ParseError) as exc:
            read_oml(text)
        assert (exc.value.code, exc.value.path) == ("parse.unexpected-token", path)

    @pytest.mark.parametrize("text,path", [
        ("a: [1\n2]", "2:1"),
        ("a: [1;2]", "1:7"),
        ("a: [1\n{b: 1}]", "2:1"),
    ])
    def test_separator_in_array(self, text, path):
        with pytest.raises(ParseError) as exc:
            read_oml(text)
        assert (exc.value.code, exc.value.path) == ("parse.separator-in-array", path)

    @pytest.mark.parametrize("text,code,path", [
        ("a: { null: 1 }", "parse.reserved-word-label", "1:6"),
        ("a: hello", "parse.bare-word", "1:4"),
        ("hello", "parse.bare-word", "1:1"),
        ("a: []", "parse.empty-array", "1:4"),
        ("a: [[1]]", "parse.nested-array", "1:5"),
    ])
    def test_the_other_value_grammar_codes(self, text, code, path):
        with pytest.raises(ParseError) as exc:
            read_oml(text)
        assert (exc.value.code, exc.value.path) == (code, path)

    @pytest.mark.parametrize("text", [
        "a: [1\n]", "a: [\n1,\n2\n]", "1 # done", "a: 1\n\nb: 2", "a: [1, 2,]"])
    def test_legal_shapes_still_read(self, text):
        assert read_oml(text)

    def test_end_of_input_is_a_real_one_based_position_not_0_0(self):
        with pytest.raises(ParseError) as exc:
            read_oml("a: {\n  b: 1")
        assert exc.value.path == "2:7"


# --------------------------------------------------- OSD: E-11 / E-23 / E-13

class TestOsdPositionsAndSchemaPaths:
    def _err(self, text):
        with pytest.raises(SchemaError) as exc:
            parse_schema(text)
        return exc.value.code, exc.value.path

    @pytest.mark.parametrize("text,expected", [
        ('record R {\n    "a": string,\n}\nroot @', ("parse.unexpected-token", "4:6")),
        ('record R {\n    "a": string\n}\nroot R\nfoo', ("parse.unexpected-token", "5:1")),
        ('record R {\n    "a": string,\n', ("schema.unquoted-label", "R")),
        ('record R {\n    "a": string', ("parse.unexpected-token", "2:16")),
        ('record R {\n    "a": "string",\n}\nroot R', ("schema.quoted-type", "R")),
        ('record R {\n    "a": 5,\n}\nroot R', ("parse.unexpected-token", "2:10")),
    ])
    def test_parse_errors_are_line_col(self, text, expected):
        assert self._err(text) == expected

    def test_string_errors_report_the_opening_quote(self):          # E-23
        assert self._err('record R {\n    "abc: string,\n}\nroot R') == (
            "parse.unterminated-string", "2:5")
        assert self._err('record R {\n    "a\x01b": string,\n}\nroot R') == (
            "parse.control-character", "2:5")
        # after a backslash the ban still applies (Sec5.3.1), newline included
        assert self._err('record R {\n    "a\\\x01b": string,\n}\nroot R') == (
            "parse.control-character", "2:5")
        assert self._err('record R {\n    "a\\\nb": string,\n}\nroot R') == (
            "parse.control-character", "2:5")

    @pytest.mark.parametrize("field,expected", [
        ('"a" []: string', ("schema.empty-cardinality", "R.a")),
        ('"a" [1.5]: string', ("schema.non-integer-cardinality", "R.a")),
        ('"a" [2,1]: string', ("schema.invalid-cardinality", "R.a")),
        ('"data": any?', ("schema.nullable-any", "R.data")),
        ('"a": Other?', ("schema.nullable-ref", "R.a")),
        ('"a": Ghost', ("schema.unknown-type", "R.a")),
        ('"a": Any', ("schema.unknown-type", "R.a")),               # `any` is exact-case
        ('"a": string, "a": integer', ("schema.duplicate-field", "R")),
        ('a: string', ("schema.unquoted-label", "R")),
        ('"": string', ("schema.empty-label", "R")),
        ('"a[0]": string', ("schema.bracket-in-label", "R")),
    ])
    def test_schema_codes_use_schema_paths(self, field, expected):
        text = f"record Other {{ \"x\": string }}\nrecord R {{ {field} }}\nroot R"
        assert self._err(text) == expected

    def test_whole_schema_cases_use_dollar(self):
        assert self._err('record R { "a": string }') == ("schema.no-root", "$")
        assert self._err('record R { "a": string }\nroot Ghost') == ("schema.unknown-type", "$")
        assert self._err('record R { "a": string }\nroot R\nroot R') == (
            "schema.duplicate-root", "$")

    def test_programmatic_construction_carries_codes_too(self):
        with pytest.raises(SchemaError) as exc:
            Record([Field("a", Scalar("string")), Field("a", Scalar("string"))])
        assert exc.value.code == "schema.duplicate-field"
        with pytest.raises(SchemaError) as exc:
            Field("a", Scalar("string"), 2, 1)
        assert exc.value.code == "schema.invalid-cardinality"
        with pytest.raises(SchemaError) as exc:
            Schema(Ref("R"), {"R": Record([Field("a", Ref("Ghost"))])})
        assert (exc.value.code, exc.value.path) == ("schema.unknown-type", "R.a")
        with pytest.raises(SchemaError) as exc:
            Schema(Ref("R"), {"R": Record([]), "string": Record([])})
        assert (exc.value.code, exc.value.path) == ("schema.reserved-name", "string")
        from omnist import t
        from omnist.schema import nullable
        with pytest.raises(SchemaError) as exc:
            nullable(t.any)
        assert exc.value.code == "schema.nullable-any"
        with pytest.raises(SchemaError) as exc:
            nullable(Ref("R"))                                        # type: ignore[arg-type]
        assert exc.value.code == "schema.nullable-ref"
        s = Schema(Ref("R"), {"R": Record([])})
        with pytest.raises(SchemaError) as exc:
            s.resolve(Ref("Ghost"))
        assert exc.value.code == "schema.unknown-type"

    def test_the_cli_reports_osd_diagnostics(self, tmp_path, capsys):
        p = tmp_path / "s.osd"
        p.write_text('record R {\n    "a" []: string,\n}\nroot R\n')
        code, out, _ = cli(["schema", "format", str(p), "--json"], capsys)
        assert code == 2 and diag(out) == [("R.a", "schema.empty-cardinality")]


# --------------------------------------------------- OSD-4: unknown escapes

def test_osd_unrecognised_escape_is_weak_unescaping_not_an_error():
    """#347: OSD has no named escapes (Sec5.3.1, OSD-1), so `\\q` is `q`; OSD
    can never raise `parse.invalid-escape`."""
    s = parse_schema('record R {\n    "a\\qb": string,\n}\nroot R\n')
    assert s.env["R"].fields[0].label == "aqb"
    assert parse_schema('record R { "a\\nb": string }\nroot R').env["R"].fields[0].label == "anb"


# ---------------------------------------------------- OSD-14 / OSD-15

class TestOsdWriterEscapes:
    def _schema(self, label):
        return Schema(Ref("R"), {"R": Record([Field(label, Scalar("string"))])})

    @pytest.mark.parametrize("label,written", [
        ("a\\b", '"a\\\\b"'),
        ('a"b', '"a\\"b"'),
        ('a\\"b', '"a\\\\\\"b"'),
        ("a\\", '"a\\\\"'),
        ("a b:c#d", '"a b:c#d"'),
        ("a\x7fb", '"a\x7fb"'),                 # DEL is not a C0 control
        ("a\u2028b", '"a\u2028b"'),
        ("é€😀", '"é€😀"'),
    ])
    def test_exactly_two_escapes(self, label, written):
        text = to_osd(self._schema(label))
        assert f"    {written}: string," in text
        assert parse_schema(text) == self._schema(label)
        assert parse_schema(to_osd(self._schema(label), indent=None)) == self._schema(label)

    @pytest.mark.parametrize("control", ["\x00", "\x01", "\n", "\t", "\r", "\x1f"])
    def test_a_c0_control_in_a_label_fails_the_write_at_the_records_path(self, control):
        with pytest.raises(WriteError) as exc:
            to_osd(self._schema(f"a{control}b"))
        assert (exc.value.code, exc.value.path) == ("write.unsupported-value", "R")
        assert control not in str(exc.value)          # the byte never reaches a message either

    def test_the_failure_is_unconditional_and_names_the_first_offending_record(self):
        s = Schema(Ref("A"), {
            "A": Record([Field("ok", Scalar("string"))]),
            "B": Record([Field("bad\x01", Scalar("string"))])})
        with pytest.raises(WriteError) as exc:
            to_osd(s, indent=None)
        assert exc.value.path == "B"

    def test_the_cli_writer_fails_cleanly_with_a_diagnostic(self, tmp_path, capsys):
        p = tmp_path / "s.osd"
        p.write_text('record R {\n    "a\\\\b": string,\n}\nroot R\n')
        code, out, _ = cli(["schema", "format", str(p)], capsys)
        assert code == 0 and '"a\\\\b"' in out

    @settings(max_examples=300, deadline=None)
    @given(st.text(
        alphabet=st.characters(min_codepoint=0x20, blacklist_categories=("Cs",),
                               blacklist_characters="[]"),
        min_size=1, max_size=12))
    def test_property_parse_of_to_osd_is_the_identity_for_any_writable_label(self, label):
        s = self._schema(label)
        assert parse_schema(to_osd(s)) == s
        assert parse_schema(to_osd(s, indent=None)) == s


# -------------------------------------------------------- YAML merge keys

def keys(text, *path):
    node = read_yaml(text)
    for label in path:
        node = next(v for k, v in node if k == label)
    return node


class TestYamlMergeKeyOrder:
    """Source order, merged entries first, local key wins, earliest alias
    wins among merged. Before: PyYAML flattened a merge sequence in reverse
    (DIV-4)."""

    def test_sequence_is_in_source_order(self):
        text = ("base: &base\n  region: eu\nlimits: &limits\n  retries: 3\n"
                "svc:\n  <<: [*base, *limits]\n  name: api\n")
        assert keys(text, "svc") == [("region", "eu"), ("retries", 3), ("name", "api")]

    def test_single_alias_then_local_entries(self):
        assert keys("d: &d\n  a: 1\n  b: 2\ne:\n  <<: *d\n  c: 3\n", "e") == [
            ("a", 1), ("b", 2), ("c", 3)]

    def test_local_key_wins_in_the_merged_keys_position_before_or_after_the_merge(self):
        assert keys("d: &d\n  a: 1\n  b: 2\ne:\n  <<: *d\n  a: 99\n", "e") == [("a", 99), ("b", 2)]
        assert keys("d: &d\n  a: 1\n  b: 2\ne:\n  a: 99\n  <<: *d\n", "e") == [("a", 99), ("b", 2)]

    def test_earliest_alias_wins_a_collision_between_merged_keys(self):
        assert keys("p: &p\n  a: 1\nq: &q\n  a: 2\nr:\n  <<: [*p, *q]\n", "r") == [("a", 1)]

    def test_collision_keeps_first_position_and_value_precedence(self):
        text = ("p: &p\n  a: 1\n  b: 5\nq: &q\n  b: 2\n  c: 3\n"
                "r:\n  <<: [*p, *q]\n  c: 99\n")
        assert keys(text, "r") == [("a", 1), ("b", 5), ("c", 99)]

    def test_nested_merge_puts_the_grandparent_first(self):
        text = "g: &g\n  a: 1\nm: &m\n  <<: *g\n  b: 2\nn:\n  <<: *m\n  c: 3\n"
        assert keys(text, "n") == [("a", 1), ("b", 2), ("c", 3)]

    def test_repeated_alias_contributes_once(self):
        assert keys("p: &p\n  a: 1\n  b: 2\nr:\n  <<: [*p, *p]\n", "r") == [("a", 1), ("b", 2)]

    def test_the_merge_key_never_survives_as_a_label(self):
        assert "<<" not in [k for k, _ in keys("d: &d {a: 1}\ne:\n  <<: *d\n", "e")]

    def test_a_merged_mapping_can_itself_merge_a_sequence(self):
        text = ("a: &a {x: 1}\nb: &b {y: 2}\nm: &m\n  <<: [*b, *a]\n  z: 3\n"
                "n:\n  <<: *m\n  w: 4\n")
        assert keys(text, "n") == [("y", 2), ("x", 1), ("z", 3), ("w", 4)]

    def test_non_mapping_merge_sources_are_clean_errors(self):
        for text in ("a:\n  <<: 5\n", "a:\n  <<: [1, 2]\n", "a:\n  <<: [{x: 1}, 2]\n"):
            with pytest.raises(ParseError) as exc:
                read_yaml(text)
            assert exc.value.code == "parse.codec-syntax" and ":" in exc.value.path

    def test_an_unhashable_key_in_a_merge_is_a_clean_error(self):
        with pytest.raises(ParseError) as exc:
            read_yaml("a: &a {x: 1}\nb:\n  <<: *a\n  ? [1, 2]\n  : v\n")
        assert exc.value.code == "parse.codec-syntax"

    def test_value_tag_key_is_kept_as_a_string_like_pyyaml(self):
        assert keys("a: &a {x: 1}\nb:\n  <<: *a\n  =: 2\n", "b") == [("x", 1), ("=", 2)]

    def test_local_duplicates_still_resolve_last_wins_like_pyyaml(self):
        assert keys("a: &a {x: 1}\nb:\n  <<: *a\n  y: 1\n  y: 2\n", "b") == [("x", 1), ("y", 2)]

    def test_a_document_without_a_merge_is_unchanged(self):
        assert read_yaml("a: 1\na: 2\nb: [3, 4]\n") == [("a", 2), ("b", 3), ("b", 4)]


class TestYamlAnchorsNeverCrashOrHang:
    """D-18/D-19/D-20 are NOT implemented (DIV-3), but a self-referential
    definition must fail cleanly or read, never crash or hang."""

    @pytest.mark.parametrize("text", [
        "a: &A\n  b: *A\n",
        "a: &A [*A]\n",
        "a: &x\n  <<: *x\n",
        "a: &a {<<: *a, k: 1}\n",
        "x: &x\n  y: &y\n    <<: *x\n",
        "a: &a\n  b: &b\n    c: *a\n    <<: *b\n",
    ])
    def test_self_referential(self, text):
        try:
            read_yaml(text)
        except (ParseError, DocumentError):
            pass                                            # a clean, typed error

    def test_a_deep_chain_of_merges_terminates(self):
        text = "a0: &a0 {k0: 0}\n" + "".join(
            f"a{i}: &a{i}\n  <<: *a{i - 1}\n  k{i}: {i}\n" for i in range(1, 60))
        assert len(keys(text, "a59")) == 60

    def test_a_doubling_chain_of_plain_aliases_hits_the_node_budget_not_the_cpu(self):
        text = "a0: &a0 {x: 1}\n" + "".join(
            f"a{i}: &a{i} [*a{i - 1}, *a{i - 1}]\n" for i in range(1, 40))
        with pytest.raises((ParseError, DocumentError)):
            read_yaml(text)


# ------------------------------------------------------------- algebra

class TestAlgebraCodes:
    def test_extract_invalidating_the_root(self):
        s = parse_schema('record R { "a": string, "b": string }\nroot R')
        with pytest.raises(SchemaError) as exc:
            s.extract("a")
        assert (exc.value.code, exc.value.path) == ("algebra.extract-invalidates-root", "R")

    def test_infer_codes_and_paths(self):
        cases = [
            ([], ("algebra.infer-no-samples", "$")),
            ([Doc.of(1)], ("algebra.infer-scalar-root", "$")),
            ([Doc.from_oml("id: 7\n"), Doc.from_oml('id: "x"\n')],
             ("algebra.infer-conflicting-scalars", "Root.id")),
            ([Doc.from_oml("id: 7\n"), Doc.from_oml("id: { a: 1 }\n")],
             ("algebra.infer-mixed-shape", "Root.id")),
        ]
        for samples, expected in cases:
            with pytest.raises(SchemaError) as exc:
                infer(samples)
            assert (exc.value.code, exc.value.path) == expected

    def test_s21_infer_never_emits_any_unless_asked_and_reports_both_openings(self):
        """S-21: `infer` MUST NOT emit `any` unless requested."""
        mixed = [Doc.from_oml("a: 1\nb: 1\n"), Doc.from_oml('a: "x"\nb: { c: 1 }\n')]
        with pytest.raises(SchemaError):
            infer(mixed)
        schema, fallbacks = infer_with_report(mixed, allow_any=True)
        assert sorted(f.location for f in fallbacks) == ["Root.a", "Root.b"]
        assert to_osd(schema).count(": any") == 2
        assert ": any" not in to_osd(infer([Doc.from_oml('a: 1\nb: "x"\n')]))

    def test_the_cli_json_error_carries_the_algebra_code(self, tmp_path, capsys):
        p = tmp_path / "s.osd"
        p.write_text('record R {\n    "a": string,\n    "b": string,\n}\nroot R\n')
        code, out, _ = cli(["schema", "extract", str(p), "--keep", "a", "--json"], capsys)
        assert code == 1 and diag(out) == [("R", "algebra.extract-invalidates-root")]


# ------------------------------------------------------ format.* renames

def test_adjustment_codes_are_the_registered_format_codes():
    import datetime
    assert [a.code for a in Doc.of({"d": datetime.date(2024, 1, 1)}).check_json()] == [
        "format.temporal-stringified"]
    assert [a.code for a in Doc.of({"t": datetime.time(9, 30)}).check_yaml()] == [
        "format.temporal-stringified"]
    assert [a.code for a in Doc.of({"r": {"n": 1}}).check_xml()] == ["format.value-stringified"]
    assert [a.code for a in Doc.of({"a": "\x85"}).check_yaml()] == [
        "format.string-line-break-char"]


# ------------------------------------------------ raw BOM never in a file

_TEXT_SUFFIXES = {".py", ".md", ".yml", ".yaml", ".toml", ".json", ".txt", ".osd", ".oml",
                  ".cfg", ".ini", ".html", ".css", ".js", ".xml", ".rst", ".in"}
_SKIP_DIRS = {".git", ".venv", "vendor", "node_modules", "site", "__pycache__", ".hypothesis",
              ".mypy_cache", ".ruff_cache", ".pytest_cache", "build", "dist"}


def find_raw_boms(root: Path):
    """Every text file under ``root`` containing the three bytes of a UTF-8
    encoded U+FEFF -- invisible in an editor, so a raw one in source or in a
    test is a bug: write it as the escape ``\\ufeff``."""
    found = []
    for path in sorted(root.rglob("*")):
        if any(part in _SKIP_DIRS or part.endswith(".egg-info") for part in path.parts):
            continue
        if (path.is_file() and path.suffix in _TEXT_SUFFIXES
                and b"\xef\xbb\xbf" in path.read_bytes()):
            found.append(str(path.relative_to(root)))
    return found


def test_no_tracked_text_file_contains_a_raw_byte_order_mark():
    assert find_raw_boms(Path(__file__).resolve().parent.parent) == []


def test_the_bom_guard_bites_in_source_and_in_tests(tmp_path):
    (tmp_path / "omnist").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "vendor").mkdir()
    (tmp_path / "omnist" / "a.py").write_bytes(b'X = "\xef\xbb\xbf"\n')
    (tmp_path / "tests" / "test_b.py").write_bytes(b'assert read("\xef\xbb\xbfa") == 1\n')
    (tmp_path / "vendor" / "spec.json").write_bytes(b"\xef\xbb\xbf{}")      # not ours: skipped
    (tmp_path / "tests" / "clean.py").write_text('X = "\\ufeff"\n')          # the escape is fine
    (tmp_path / "docs.pdf").write_bytes(b"\xef\xbb\xbf")                     # binary: skipped
    assert find_raw_boms(tmp_path) == ["omnist/a.py", "tests/test_b.py"]


def test_the_cli_reports_a_collected_materialize_failure_in_full(tmp_path, capsys):
    """A materialize ParseError carries every problem (.errors), not one."""
    doc_f, schema_f = tmp_path / "d.json", tmp_path / "s.osd"
    doc_f.write_text('{"a": "x", "b": "y"}')
    schema_f.write_text('record R {\n    "a": integer,\n    "b": integer,\n}\nroot R\n')
    code, out, _ = cli(["convert", str(doc_f), "--from", "json", "--to", "oml",
                        "--schema", str(schema_f), "--json"], capsys)
    assert code == 2
    assert diag(out) == [("$.a", "materialize.inexact-conversion"),
                         ("$.b", "materialize.inexact-conversion")]
