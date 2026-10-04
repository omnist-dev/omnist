"""omnist-spec v0.32.0-beta C-9 (Sec7.3): a writer MUST fail with
`write.unsupported-value`, unconditionally, on a string value or an edge label
that has no UTF-8 encoding (a lone surrogate, a surrogate-escape artefact
U+DC80..U+DCFF), in ALL five writers, never emitting it (not even as an escape).
No conformance vector pins it (DIV-5), so these tests are the only pin.

The path is the Document path of the node HOLDING the string: the leaf for a
value (indexed per E-10), the node holding the edge for a label.
"""
from __future__ import annotations

import pytest

from omnist import (
    Doc,
    WriteError,
    check_json,
    check_oml,
    check_toml,
    check_xml,
    check_yaml,
    read_json,
    read_oml,
    write_json,
    write_oml,
    write_toml,
    write_xml,
    write_yaml,
)

LONE = "\ud800"
ESCAPED = b"\xff".decode("utf-8", "surrogateescape")          # U+DCFF
HALVES = chr(0xD83D) + chr(0xDE00)    # two lone surrogates, not one character
assert ESCAPED == "\udcff"

WRITERS = {"json": write_json, "yaml": write_yaml, "toml": write_toml, "xml": write_xml,
           "oml": write_oml}
CHECKERS = {"json": check_json, "yaml": check_yaml, "toml": check_toml, "xml": check_xml,
            "oml": check_oml}

# (node, expected path): every format must refuse each, at that path.
CASES = {
    "value lone surrogate": ([("r", [("a", LONE)])], "$.r.a"),
    "value surrogate escape": ([("r", [("a", ESCAPED)])], "$.r.a"),
    "value two halves of a pair": ([("r", [("a", HALVES)])], "$.r.a"),
    "value amid valid text": ([("r", [("a", "ok " + LONE + " ok")])], "$.r.a"),
    "value indexed": ([("r", [("a", "ok"), ("a", LONE)])], "$.r.a[1]"),
    "value first of repeated": ([("r", [("a", LONE), ("a", "ok")])], "$.r.a[0]"),
    "label at top level": ([(LONE, 1)], "$"),
    "label nested": ([("r", [("ok", 1), ("x" + ESCAPED, 2)])], "$.r"),
    "label with a value beneath": ([("r", [(LONE, [("v", 1)])])], "$.r"),
    "label beneath a repeated edge": ([("r", [("p", [("q", 1)]), ("p", [(LONE, 1)])])],
                                      "$.r.p[1]"),
}


@pytest.mark.parametrize("fmt", sorted(WRITERS))
@pytest.mark.parametrize("case", sorted(CASES))
def test_every_writer_refuses_at_the_holder_path(fmt, case):
    node, path = CASES[case]
    for strict in (False, True):
        kwargs = {} if fmt == "oml" else {"strict": strict}
        with pytest.raises(WriteError) as ei:
            WRITERS[fmt](node, **kwargs)
        assert (ei.value.code, ei.value.path) == ("write.unsupported-value", path)
    with pytest.raises(WriteError) as ei:                 # check_* simulates the write
        CHECKERS[fmt](node)
    assert (ei.value.code, ei.value.path) == ("write.unsupported-value", path)
    with pytest.raises(WriteError) as ei:                 # and so does the Doc surface
        Doc(node).to_format(fmt)
    assert (ei.value.code, ei.value.path) == ("write.unsupported-value", path)


@pytest.mark.parametrize("fmt", ["json", "yaml", "oml", "xml"])
def test_a_bare_scalar_root_is_refused_at_dollar(fmt):
    with pytest.raises(WriteError) as ei:
        WRITERS[fmt](LONE)
    assert (ei.value.code, ei.value.path) == ("write.unsupported-value", "$")


def test_toml_root_scalar_is_refused_at_dollar_as_well():
    with pytest.raises(WriteError) as ei:
        write_toml(LONE)
    assert (ei.value.code, ei.value.path) == ("write.unsupported-value", "$")


def test_the_issue_350_repro_now_fails_and_is_never_spelled_as_an_escape():
    node = read_json('{"a":"\\ud800"}')                    # readers are untouched (D-14)
    assert node == [("a", LONE)]
    with pytest.raises(WriteError) as ei:
        write_json(node)
    assert (ei.value.code, ei.value.path) == ("write.unsupported-value", "$.a")
    for fmt in ("yaml", "oml", "xml", "toml"):
        wrapped = [("r", node)] if fmt == "xml" else node
        with pytest.raises(WriteError):
            WRITERS[fmt](wrapped)


def test_the_first_offender_in_document_order_is_reported():
    node = [("a", [("x", 1), ("y", LONE)]), ("b", LONE)]
    with pytest.raises(WriteError) as ei:
        write_json(node)
    assert ei.value.path == "$.a.y"


ENCODABLE = ["plain", chr(0xE9), chr(0x20AC), chr(0x1F600), chr(0x85), chr(0xFFFD),
            chr(0xE000), ""]


@pytest.mark.parametrize("text", ENCODABLE)
@pytest.mark.parametrize("fmt", sorted(WRITERS))
def test_every_encodable_string_still_writes(fmt, text):
    node = [("r", [("a", text)])]
    out = WRITERS[fmt](node)
    assert isinstance(out, str)
    out.encode("utf-8")


def test_oml_round_trip_of_astral_text_is_unchanged():
    node = read_oml('a: "\U0001f600"')
    assert read_oml(write_oml(node)) == node


def test_a_node_deeper_than_the_depth_limit_is_still_a_depth_error_not_a_recursion_error():
    deep: object = 1
    for _ in range(1200):
        deep = [("a", deep)]
    for fmt in sorted(WRITERS):
        with pytest.raises(WriteError) as ei:
            WRITERS[fmt](deep)
        assert ei.value.code == "document.limit.depth"
    ok_deep = [("a", [("b", LONE)])]
    with pytest.raises(WriteError) as ei:
        write_json(ok_deep)
    assert ei.value.path == "$.a.b"
