"""omnist-spec v0.34.0-beta: C-12 (YAML and TOML refuse a repeated key), C-11
(JSON keeps the last value at the first position), C-13 (``!!pairs``, ``!!omap``
and ``!!set`` are refused with ``format.tag-forbidden``)."""
from __future__ import annotations

import json
import re

import pytest

from omnist import Doc, ParseError, read_json, read_toml, read_yaml
from omnist.cli import main

LINE_COL = re.compile(r"[1-9][0-9]*:[1-9][0-9]*")


class TestYamlRepeatedKey:
    @pytest.mark.parametrize("text, at", [
        ("a: 1\nb: 2\na: 3\n", "3:1"),
        ("{a: 1, a: 2}\n", "1:8"),
        ("o:\n  k: 1\n  k: 2\n", "3:3"),
        ("m:\n  - {a: 1, a: 2}\n", "2:12"),
        ('a: 1\n"a": 2\n', "2:1"),
        ("a: 1\na: [2, 3]\n", "2:1"),
        ("&k a: 1\n*k : 2\n", None),
    ])
    def test_refused_as_a_codec_syntax_error(self, text, at):
        if at is None:
            # an alias is not a key spelling this reader resolves: still never accepted
            with pytest.raises(ParseError):
                read_yaml(text)
            return
        with pytest.raises(ParseError) as info:
            read_yaml(text)
        assert (info.value.code, info.value.path) == ("parse.codec-syntax", at)
        assert LINE_COL.fullmatch(info.value.path)

    def test_through_the_doc_api(self):
        with pytest.raises(ParseError) as info:
            Doc.from_yaml("a: 1\na: 2\n")
        assert info.value.code == "parse.codec-syntax"

    def test_through_the_cli(self, tmp_path, capsys):
        src = tmp_path / "d.yaml"
        src.write_text("a: 1\na: 2\n", encoding="utf-8")
        assert main(["convert", str(src), "--from", "yaml", "--to", "oml", "--json"]) != 0
        payload = json.loads(capsys.readouterr().out)
        got = [(e["path"], e["code"]) for e in payload["errors"]]
        assert got == [("2:1", "parse.codec-syntax")]

    @pytest.mark.parametrize("text, want", [
        ("x: {a: 1}\ny: {a: 2}\n", [("x", [("a", 1)]), ("y", [("a", 2)])]),
        ("a: 1\nA: 2\n", [("a", 1), ("A", 2)]),
        ("a: &a {x: 1}\nb:\n  <<: *a\n  x: 2\n", [("a", [("x", 1)]), ("b", [("x", 2)])]),
        ("a: &a {x: 1}\nb: &b {x: 2}\nc:\n  <<: [*a, *b]\n", [
            ("a", [("x", 1)]), ("b", [("x", 2)]), ("c", [("x", 1)])]),
        ("a: &a {x: 1}\nc:\n  <<: *a\n  <<: *a\n", [("a", [("x", 1)]), ("c", [("x", 1)])]),
        ("1: a\n1.0: b\n", None),
    ])
    def test_not_a_repeat(self, text, want):
        if want is None:
            # keys of different types are not a repeat (this one fails later: a non-string key)
            with pytest.raises(Exception) as info:
                read_yaml(text)
            assert getattr(info.value, "code", None) != "parse.codec-syntax"
            return
        assert read_yaml(text) == want

    def test_a_value_tagged_key_counts_as_the_string_it_is(self):
        with pytest.raises(ParseError):
            read_yaml("a: 1\n=: 2\n=: 3\n")


class TestTomlRepeatedKey:
    @pytest.mark.parametrize("text", [
        "a = 1\na = 2\n", "[t]\nk = 1\nk = 2\n", 'a = 1\n"a" = 2\n',
        "a.b = 1\na.b = 2\n", "t = {k = 1, k = 2}\n"])
    def test_refused_as_a_codec_syntax_error(self, text):
        with pytest.raises(ParseError) as info:
            read_toml(text)
        assert info.value.code == "parse.codec-syntax" and LINE_COL.fullmatch(info.value.path)


class TestJsonRepeatedKey:
    def test_last_value_at_the_first_position(self):
        # C-11: the surviving edge sits where the key was first written
        assert read_json('{"a": 1, "b": 2, "a": 3}') == [("a", 3), ("b", 2)]
        assert read_json('{"a": 1, "a": [2, 3], "b": 0}') == [("a", 2), ("a", 3), ("b", 0)]


class TestYamlForbiddenTags:
    @pytest.mark.parametrize("text", [
        "t: !!omap [{k: 1}, {j: 2}]\n",
        "t: !!pairs [{k: 1}, {k: 2}]\n",
        "t: !!set {x, y}\n",
        "t: !!set\n  ? x\n  ? y\n",
        "t: !!omap []\n",
        "!!omap [{k: 1}]\n",
        "a: &s !!set {x}\nb: *s\n",
        "? !!set {x}\n: 1\n",
        "t: [1, [2, !!pairs []]]\n",
        "t: !!omap\n",
    ])
    def test_refused_at_the_document_root(self, text):
        with pytest.raises(ParseError) as info:
            read_yaml(text)
        assert (info.value.code, info.value.path) == ("format.tag-forbidden", "$")

    def test_through_the_cli(self, tmp_path, capsys):
        src = tmp_path / "d.yaml"
        src.write_text("t: !!set {x}\n", encoding="utf-8")
        assert main(["convert", str(src), "--from", "yaml", "--to", "oml", "--json"]) != 0
        payload = json.loads(capsys.readouterr().out)
        got = [(e["path"], e["code"]) for e in payload["errors"]]
        assert got == [("$", "format.tag-forbidden")]

    @pytest.mark.parametrize("text, want", [
        ("t:\n  - {k: 1}\n  - {j: 2}\n", [("t", [("k", 1)]), ("t", [("j", 2)])]),
        ("t: !!str 5\n", [("t", "5")]),
        ("t: !!seq [1, 2]\n", [("t", 1), ("t", 2)]),
        ("t: !!map {a: 1}\n", [("t", [("a", 1)])]),
        ("t: !custom 5\n", None),
    ])
    def test_other_tags_keep_their_reading(self, text, want):
        if want is None:
            with pytest.raises(ParseError) as info:
                read_yaml(text)
            assert info.value.code != "format.tag-forbidden"
            return
        assert read_yaml(text) == want
