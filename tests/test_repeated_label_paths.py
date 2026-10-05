"""omnist-spec E-10 / Sec8.4 (v0.30.0-beta): the index ``[i]`` is on EVERY edge of a
label that occurs more than once in a node, including the first, and absent
when the label occurs once.  Pinned across Doc, validate, materialize, the
writers' error paths and the report paths.
"""
from __future__ import annotations

import pytest

from omnist import (
    Doc,
    ParseError,
    WriteError,
    WriteReport,
    materialize,
    parse_schema,
    read_oml,
    write_toml,
    write_xml,
    write_yaml,
)
from omnist._paths import edge_paths

_SCHEMA_N = 'record R {\n  "n" [1,]: integer,\n}\nroot R\n'
_SCHEMA_Y = 'record R {\n  "y": string,\n}\nroot R\n'


@pytest.mark.parametrize("labels, expected", [
    ([], []),
    (["a"], ["$.a"]),
    (["a", "b"], ["$.a", "$.b"]),
    (["a", "a"], ["$.a[0]", "$.a[1]"]),
    (["a", "b", "a"], ["$.a[0]", "$.b", "$.a[1]"]),
    (["a", "a", "b", "b", "b"], ["$.a[0]", "$.a[1]", "$.b[0]", "$.b[1]", "$.b[2]"]),
])
def test_edge_paths(labels, expected):
    node = [(lbl, 1) for lbl in labels]
    assert [p for _l, _c, p in edge_paths("$", node)] == expected


def test_doc_edges_index_every_occurrence():
    doc = Doc.from_oml("item: 1; item: 2; solo: 3")
    assert [d.path for _l, d in doc.edges()] == ["$.item[0]", "$.item[1]", "$.solo"]


def test_nested_paths_are_per_node():
    doc = Doc.from_oml("item: {n: 1; n: 2}; item: {n: 3}")
    inner = [[d.path for _l, d in c.edges()] for _l, c in doc.edges()]
    assert inner == [["$.item[0].n[0]", "$.item[0].n[1]"], ["$.item[1].n"]]


@pytest.mark.parametrize("oml, osd, expected", [
    ('n: "a"; n: "b"; n: "c"', _SCHEMA_N, ["$.n[0]", "$.n[1]", "$.n[2]"]),
    ('n: "a"', _SCHEMA_N, ["$.n"]),
    ("y: 1; x: 1; x: 2", _SCHEMA_Y, ["$.y", "$.x[0]", "$.x[1]"]),
])
def test_validate_paths(oml, osd, expected):
    res = parse_schema(osd).validate(Doc.from_oml(oml))
    assert [e.path for e in res.errors if e.code != "validate.cardinality"] == expected


def test_materialize_paths():
    node = read_oml('n: "a"; n: 2; n: "c"')
    with pytest.raises(ParseError) as ei:
        materialize(node, parse_schema(_SCHEMA_N))
    assert [e.path for e in ei.value.errors] == ["$.n[0]", "$.n[2]"]


def test_toml_null_path_indexed():
    with pytest.raises(WriteError) as ei:
        write_toml(read_oml("a: null; a: 1"))
    assert ei.value.path == "$.a[0]"


def test_xml_label_path_indexed():
    with pytest.raises(WriteError) as ei:
        write_xml(read_oml('r: {"bad name": 1; "bad name": 2}'))
    assert ei.value.path == "$.r.bad name[0]"


def test_yaml_report_path_indexed():
    rep = WriteReport()
    write_yaml(read_oml('a: "x\u0085"; a: "y\u0085"'), report=rep)
    assert [d.path for d in rep.adjustments] == ["$.a[0]", "$.a[1]"]
