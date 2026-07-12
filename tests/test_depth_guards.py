"""Writer/check depth guards (issue #220, W1).

``read_oml`` already fails cleanly on documents nested past the shared
maximum depth (``ParseError: nesting exceeds the maximum depth (200)``).
Every path that recurses over a *Python-constructed* canonical node --
the writers, the ``check_*`` simulators, and the ``Doc`` export helpers
that can be reached with a node that bypassed ``build_node``'s own guard
-- must fail exactly as cleanly instead of raising a raw
``RecursionError``.

These nodes are built directly as raw edge-lists (not via ``build_node``/
``Doc.of``) because that is exactly how the bug reproduces: a Document
assembled programmatically, without going through the depth-checked
constructors.
"""
from __future__ import annotations

import pytest

from omnist import (
    Doc,
    DocumentError,
    WriteError,
    check_json,
    check_oml,
    check_toml,
    check_xml,
    check_yaml,
    write_json,
    write_oml,
    write_toml,
    write_xml,
    write_yaml,
)


def deep_node(depth: int, leaf: object = 1) -> object:
    """A canonical node nested ``depth`` levels deep: [('a', [('a', ... leaf)]))]."""
    node: object = leaf
    for _ in range(depth):
        node = [("a", node)]
    return node


DEEP = 5000       # well past the limit -- the raw RecursionError repro depth
JUST_UNDER = 190  # comfortably under the 200 limit


class TestWriteOml:
    def test_too_deep_raises_write_error_naming_the_limit(self):
        with pytest.raises(WriteError, match=r"nesting exceeds the maximum depth \(200\)"):
            write_oml(deep_node(DEEP))

    def test_just_under_limit_succeeds(self):
        text = write_oml(deep_node(JUST_UNDER))
        assert text.count("a: {") == JUST_UNDER - 1

    def test_too_deep_raises_in_compact_mode_too(self):
        with pytest.raises(WriteError, match=r"nesting exceeds the maximum depth \(200\)"):
            write_oml(deep_node(DEEP), indent=None)

    def test_too_deep_raises_with_arrays_flag(self):
        with pytest.raises(WriteError, match=r"nesting exceeds the maximum depth \(200\)"):
            write_oml(deep_node(DEEP), arrays=True)


class TestCheckOml:
    def test_always_safe_empty_report(self):
        # check_oml never traverses the node -- OML is unconditionally
        # lossless, so there is nothing to simulate.  No guard needed.
        assert check_oml(deep_node(DEEP)).adjustments == []


class TestWriteJson:
    def test_too_deep_raises_write_error(self):
        with pytest.raises(WriteError, match=r"nesting exceeds the maximum depth \(200\)"):
            write_json(deep_node(DEEP))

    def test_just_under_limit_succeeds(self):
        text = write_json(deep_node(JUST_UNDER))
        assert text.count('"a":') == JUST_UNDER


class TestCheckJson:
    def test_too_deep_raises_write_error(self):
        with pytest.raises(WriteError, match=r"nesting exceeds the maximum depth \(200\)"):
            check_json(deep_node(DEEP))

    def test_just_under_limit_succeeds(self):
        rep = check_json(deep_node(JUST_UNDER))
        assert rep.adjustments == []


class TestWriteYaml:
    def test_too_deep_raises_write_error(self):
        with pytest.raises(WriteError, match=r"nesting exceeds the maximum depth \(200\)"):
            write_yaml(deep_node(DEEP))

    def test_just_under_limit_succeeds(self):
        text = write_yaml(deep_node(JUST_UNDER))
        assert text.count("a:") == JUST_UNDER


class TestCheckYaml:
    def test_too_deep_raises_write_error(self):
        with pytest.raises(WriteError, match=r"nesting exceeds the maximum depth \(200\)"):
            check_yaml(deep_node(DEEP))

    def test_just_under_limit_succeeds(self):
        rep = check_yaml(deep_node(JUST_UNDER))
        assert rep.adjustments == []


class TestWriteToml:
    def test_too_deep_raises_write_error(self):
        with pytest.raises(WriteError, match=r"nesting exceeds the maximum depth \(200\)"):
            write_toml(deep_node(DEEP))

    def test_just_under_limit_succeeds(self):
        text = write_toml(deep_node(JUST_UNDER))
        assert text.count("[a") or text  # just needs to not blow the stack


class TestCheckToml:
    def test_too_deep_raises_write_error(self):
        with pytest.raises(WriteError, match=r"nesting exceeds the maximum depth \(200\)"):
            check_toml(deep_node(DEEP))

    def test_just_under_limit_succeeds(self):
        rep = check_toml(deep_node(JUST_UNDER))
        assert rep.adjustments == []


class TestWriteXml:
    def test_too_deep_raises_write_error(self):
        with pytest.raises(WriteError, match=r"nesting exceeds the maximum depth \(200\)"):
            write_xml(deep_node(DEEP))

    def test_just_under_limit_succeeds(self):
        text = write_xml(deep_node(JUST_UNDER))
        assert text.count("<a>") == JUST_UNDER


class TestCheckXml:
    def test_too_deep_raises_write_error(self):
        with pytest.raises(WriteError, match=r"nesting exceeds the maximum depth \(200\)"):
            check_xml(deep_node(DEEP))

    def test_just_under_limit_succeeds(self):
        rep = check_xml(deep_node(JUST_UNDER))
        assert rep.adjustments == []


class TestDocExport:
    """``Doc`` can be constructed directly from a raw node (``Doc(node)``),
    bypassing ``build_node``'s own depth guard -- ``to_data``/``to_grouped``
    must still fail cleanly rather than blow the C stack."""

    def test_to_data_too_deep_raises_document_error(self):
        d = Doc(deep_node(DEEP))
        with pytest.raises(DocumentError, match=r"nesting exceeds the maximum depth \(200\)"):
            d.to_data()

    def test_to_data_just_under_limit_succeeds(self):
        d = Doc(deep_node(JUST_UNDER))
        assert d.to_data() == deep_node(JUST_UNDER)

    def test_to_grouped_too_deep_raises_document_error(self):
        d = Doc(deep_node(DEEP))
        with pytest.raises(DocumentError, match=r"nesting exceeds the maximum depth \(200\)"):
            d.to_grouped()

    def test_to_grouped_just_under_limit_succeeds(self):
        d = Doc(deep_node(JUST_UNDER))
        assert d.to_grouped()["a"] is not None
