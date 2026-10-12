"""omnist-spec v0.35.0-beta: E-36 (Document path label quoting), E-37 (temporal
writers) and C-14 (lowercase hex in YAML escapes)."""
from __future__ import annotations

import datetime as dt

import pytest

from omnist import WriteReport, doc, read_toml, read_yaml
from omnist._paths import label_segment


class TestLabelSegment:
    @pytest.mark.parametrize("label, seg", [
        ("name", ".name"), ("a b", ".a b"), ("$", ".$"), ("é", ".é"), ("0", ".0"),
        ("", '[""]'), ("a.b", '["a.b"]'), ("item[0]", '["item[0]"]'),
        ('q"x', '["q\\"x"]'), ("a\\b", '["a\\\\b"]'),
        ("l1\nl2", '["l1\\nl2"]'), ("a\tb\rc", '["a\\tb\\rc"]'),
        ("a\x1fb", '["a\\u001fb"]'), ("a\x00b", '["a\\u0000b"]'),
        ("a\x7fb", '["a\\u007fb"]'), ("a\x85b", '["a\\u0085b"]'),
        ("a\u2028b", '["a\\u2028b"]'), ("a\u2029b", '["a\\u2029b"]'),
        ("é.ü", '["é.ü"]'),
    ])
    def test_segment(self, label, seg):
        assert label_segment(label) == seg

    def test_doc_path_uses_the_rule(self):
        d = doc({"a.b": {"x y": 1}})
        assert d.edges()[0][1].path == '$["a.b"]'
        assert d.edges()[0][1].edges()[0][1].path == '$["a.b"].x y'

    def test_add_and_set_use_the_rule(self):
        d = doc({"a": 1})
        d.add("b.c", {"k": 1})
        d.set("d e", {"k": 2})
        paths = [c.path for _, c in d.edges()]
        assert paths == ["$.a", '$["b.c"]', "$.d e"]


class TestTomlTemporals:
    def test_offset_time_is_stringified_with_a_warning(self):
        d = doc({"t": dt.time(12, 0, tzinfo=dt.timezone(dt.timedelta(hours=1)))})
        rep = WriteReport()
        text = d.to_toml(report=rep)
        assert text == 't = "12:00:00+01:00"\n'
        assert [(a.code, a.path) for a in rep] == [("format.temporal-stringified", "$.t")]

    def test_datetime_uses_the_t_separator(self):
        d = doc({"t": dt.datetime(2024, 1, 15, 12, 0,
                                            tzinfo=dt.timezone(dt.timedelta(hours=1)))})
        assert d.to_toml() == "t = 2024-01-15T12:00:00+01:00\n"
        assert read_toml(d.to_toml()) == read_toml("t = 2024-01-15T12:00:00+01:00")

    def test_local_time_stays_native(self):
        assert doc({"t": dt.time(12, 0)}).to_toml() == "t = 12:00:00\n"


class TestYamlTemporals:
    def test_time_is_double_quoted(self):
        rep = WriteReport()
        text = doc({"t": dt.time(12, 0)}).to_yaml(report=rep)
        assert text == 't: "12:00:00"\n'
        assert [a.code for a in rep] == ["format.temporal-stringified"]

    def test_offset_time_is_double_quoted(self):
        t = dt.time(12, 0, tzinfo=dt.timezone(dt.timedelta(hours=1)))
        assert doc({"t": t}).to_yaml() == 't: "12:00:00+01:00"\n'

    def test_datetime_uses_the_t_separator(self):
        d = doc({"t": dt.datetime(2024, 1, 15, 12, 0)})
        assert d.to_yaml() == "t: 2024-01-15T12:00:00\n"
        assert read_yaml(d.to_yaml()) == read_yaml("t: 2024-01-15 12:00:00")


class TestYamlEscapeCase:
    @pytest.mark.parametrize("ch, esc", [
        ("\x1f", "\\x1f"), ("\x7f", "\\x7f"), ("\x80", "\\x80"), ("\x9f", "\\x9f"),
        ("\ufffe", "\\ufffe"), ("\uffff", "\\uffff"),
    ])
    def test_lowercase(self, ch, esc):
        assert doc({"a": f"x{ch}y"}).to_yaml() == f'a: "x{esc}y"\n'

    def test_a_literal_backslash_is_not_touched(self):
        assert read_yaml(doc({"a": "\\x1F\x1f"}).to_yaml()) == read_yaml(
            'a: "\\\\x1F\\x1f"')

    def test_astral_escape_keeps_its_uppercase_marker(self):
        text = doc({"a": "x\x1f\U00010000y"}).to_yaml()
        assert text == 'a: "x\\x1f\\U00010000y"\n'
