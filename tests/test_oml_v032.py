"""omnist-spec v0.31.0-beta OML-29 (a gap after the colon of an edge) and omnist#354
(a top-level braced node is not one of Sec4.6's three legal shapes).
"""
from __future__ import annotations

import pytest

from omnist import ParseError, read_oml

A1 = [("a", 1)]


@pytest.mark.parametrize("text, expected", [
    ("a:\n1", A1),
    ("a: ;1", A1),
    ("a: # c\n1", A1),
    ("a:\n\n1", A1),
    ("a:\n;\n  # c\n  1", A1),
    ("a:\n{b: 1}", [("a", [("b", 1)])]),
    ("x: {a:\n1}", [("x", A1)]),
    ("x: {a: ;\n1; b:\n2}", [("x", [("a", 1), ("b", 2)])]),
    ("a:\n[1, 2]", [("a", 1), ("a", 2)]),
    ('"a":\n"s"', [("a", "s")]),
    ("a:\n1\nb:\n2", [("a", 1), ("b", 2)]),
])
def test_oml_29_gap_after_colon(text, expected):
    assert read_oml(text) == expected


@pytest.mark.parametrize("text, code, path", [
    ("a:\n1 b: 2", "parse.trailing-content", "2:3"),     # the gap licenses no missing separator
    ("a:", "parse.unexpected-token", "1:3"),               # EOF where a value is owed
    ("a:\n", "parse.unexpected-token", "2:1"),
    ("x: {a:\n}", "parse.unexpected-token", "2:1"),       # a gap, then `}` where a value is owed
    ("x: {a:\n1 b: 2}", "parse.unexpected-token", "2:3"),
    ("a:\n:", "parse.unexpected-token", "2:1"),
])
def test_oml_29_still_rejects(text, code, path):
    with pytest.raises(ParseError) as ei:
        read_oml(text)
    assert (ei.value.code, ei.value.path) == (code, path)


@pytest.mark.parametrize("text, path", [
    ("{a: 1}", "1:1"), ("{}", "1:1"), ("{ }", "1:1"), ("{a: 1}\n", "1:1"),
    ("{a: 1} b: 2", "1:1"), ("{a: 1}\nb: 2", "1:1"), ("{a: 1}\n}", "1:1"),
    ("{{a: 1}}", "1:1"), ("  # c\n{a: 1; b: 2}", "2:1"), ("\n\n  {a: 1}", "3:3"),
])
def test_top_level_braced_node_is_rejected(text, path):
    with pytest.raises(ParseError) as ei:
        read_oml(text)
    assert (ei.value.code, ei.value.path) == ("parse.unexpected-token", path)


@pytest.mark.parametrize("text, expected", [
    ("x: {a: 1}", [("x", A1)]),
    ("x: {}", [("x", [])]),
    ("", []),
    ("42", 42),
])
def test_braces_stay_legal_below_the_root(text, expected):
    assert read_oml(text) == expected


@pytest.mark.parametrize("text, code, path", [
    ("a: 1\nb\n: 2", "parse.unexpected-token", "2:2"),    # non-first edge: newline before the colon
    ("a: 1; b ; : 2", "parse.unexpected-token", "1:8"),
    ("a: {b\n: 1}", "parse.unexpected-token", "1:6"),      # inside braces
    ("a\n: 1", "parse.bare-word", "1:1"),                   # first edge
    ("a # c\n: 1", "parse.bare-word", "1:1"),               # comment before the colon
])
def test_a_gap_before_the_colon_is_still_rejected(text, code, path):
    with pytest.raises(ParseError) as ei:
        read_oml(text)
    assert (ei.value.code, ei.value.path) == (code, path)
