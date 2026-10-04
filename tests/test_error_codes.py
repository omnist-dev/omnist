"""Structured codes for failures that used to yield ``"errors": []`` (issue #350).

Every raise that has a fitting code in the vendored spec's section 8.3 now
carries it; the rest stay uncoded on purpose (the spec registers no code for
them) and the ``--json`` payload still always carries a ``message``.
"""
from __future__ import annotations

import json

import pytest

from omnist import (
    Doc,
    DocumentError,
    Field,
    Record,
    Ref,
    Schema,
    WriteError,
    check_json,
    check_toml,
    check_xml,
    check_yaml,
    infer,
    write_json,
    write_oml,
    write_toml,
    write_xml,
    write_yaml,
)
from omnist.cli import main
from omnist.document import build_node

DEEP = 5000


def _deep(depth: int) -> object:
    node: object = 1
    for _ in range(depth):
        node = [("a", node)]
    return node


_RECURSIVE = Schema(Ref("A"), {"A": Record([Field("a", Ref("A"), 0, 1)])})

_DEPTH_SITES = {
    "write_oml": lambda: write_oml(_deep(DEEP)),
    "write_oml_compact": lambda: write_oml(_deep(DEEP), indent=None),
    "write_json": lambda: write_json(_deep(DEEP)),
    "write_yaml": lambda: write_yaml(_deep(DEEP)),
    "write_toml": lambda: write_toml(_deep(DEEP)),
    "write_xml": lambda: write_xml(_deep(DEEP)),
    "check_json": lambda: check_json(_deep(DEEP)),
    "check_yaml": lambda: check_yaml(_deep(DEEP)),
    "check_toml": lambda: check_toml(_deep(DEEP)),
    "check_xml": lambda: check_xml(_deep(DEEP)),
    "to_data": lambda: Doc(_deep(DEEP)).to_data(),
    "to_grouped": lambda: Doc(_deep(DEEP)).to_grouped(),
    "infer": lambda: infer([Doc(_deep(DEEP))]),
    "validate": lambda: _RECURSIVE.validate(Doc(_deep(DEEP))),
}


@pytest.mark.parametrize("site", sorted(_DEPTH_SITES))
def test_depth_refusal_carries_document_limit_depth(site):
    with pytest.raises((DocumentError, WriteError)) as exc:
        _DEPTH_SITES[site]()
    assert exc.value.code == "document.limit.depth"
    assert exc.value.path == "$"


def test_toml_bare_scalar_root_is_write_unsupported_value():
    with pytest.raises(WriteError) as exc:
        write_toml("bare leaf")
    assert exc.value.code == "write.unsupported-value"
    assert exc.value.path == "$"


def test_toml_check_of_scalar_root_unchanged():
    # check_toml never raised for a scalar root; only the write refuses.
    assert check_toml("bare leaf").adjustments == []


@pytest.mark.parametrize("make", [
    lambda: build_node(_self_cycle()),
    lambda: build_node({"a": object()}),
    lambda: Doc.of({"a": 1}).get_one("a").edges(),
    lambda: Doc.of({"a": 1}).get("zz")[0] if False else Doc.of({"a": 1}).get_one("zz"),
], ids=["cycle", "non-document-value", "edges-of-leaf", "one-of-leaf"])
def test_uncoded_failures_stay_uncoded_with_a_message(make):
    # The spec registers no code for these; inventing one would be wrong.
    with pytest.raises(DocumentError) as exc:
        make()
    assert exc.value.code is None
    assert str(exc.value)


def _self_cycle():
    d: dict = {}
    d["x"] = d
    return d


def _cli(capsys, argv):
    code = main(argv)
    out = capsys.readouterr().out
    return code, json.loads(out)


def test_cli_toml_scalar_root_payload_has_a_code(tmp_path, capsys):
    p = tmp_path / "s.json"
    p.write_text("5")
    code, payload = _cli(capsys, ["convert", str(p), "--from", "json", "--to", "toml", "--json"])
    assert code == 1
    assert payload["ok"] is False
    assert payload["message"]
    assert [e["code"] for e in payload["errors"]] == ["write.unsupported-value"]
    assert payload["errors"][0]["path"] == "$"


def test_cli_self_referential_anchor_is_alias_expansion(tmp_path, capsys):
    p = tmp_path / "c.yaml"
    p.write_text("a: &A\n  b: *A\n")
    code, payload = _cli(capsys, ["convert", str(p), "--from", "yaml", "--to", "json", "--json"])
    assert code == 2
    assert [e["code"] for e in payload["errors"]] == ["document.limit.alias-expansion"]


def test_cli_unsafe_json_value_is_write_unsupported_value(tmp_path, capsys):
    p = tmp_path / "u.json"
    p.write_text('{"a": 1e999}')
    code, payload = _cli(capsys, ["convert", str(p), "--from", "json", "--to", "json", "--json"])
    assert [e["code"] for e in payload["errors"]] == ["write.unsupported-value"]


@pytest.mark.parametrize("src, frm, to", [
    ("[1]", "json", "toml"),  # bare array: document.unlabeled-element
])
def test_cli_every_failure_payload_has_message(tmp_path, capsys, src, frm, to):
    p = tmp_path / "in"
    p.write_text(src)
    code, payload = _cli(capsys, ["convert", str(p), "--from", frm, "--to", to, "--json"])
    assert payload["ok"] is False and payload["message"]
    assert isinstance(payload["errors"], list)
