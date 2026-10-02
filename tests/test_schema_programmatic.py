"""Programmatic-schema rules of omnist-spec v0.28.0-beta: S-8 (`schema.invalid-name`
at `$`), S-22 (`schema.invalid-label` at the record path), S-23 (cannot arise:
no caller-supplied record ordering exists in this API) and S-15/OSD-16/S-24 (a
schema writer fails on `max = 0`).  No conformance vector pins any of these
(docs/09-divergence-ledger.md DIV-5), so these tests are the only pin.
"""
from __future__ import annotations

import inspect

import pytest

from omnist import (
    Field,
    Record,
    Ref,
    Schema,
    SchemaError,
    WriteError,
    infer,
    parse_schema,
    t,
)

BAD_NAMES = ["bad name", "", "1x", "\u00e9t\u00e9", "a-b", "a\n", "a\udc80", "x.y", " a"]
BAD_LABELS = ["a\udc80", "\ud800", "x\udfff", "\udcff tail", "ok\ud83d"]


def _rec(*labels: str) -> Record:
    return Record([Field(lbl, t.string) for lbl in labels])


# -- S-8 ---------------------------------------------------------------------

@pytest.mark.parametrize("name", BAD_NAMES)
def test_record_name_must_be_an_identifier(name: str) -> None:
    with pytest.raises(SchemaError) as ei:
        Schema(Ref("Root"), {"Root": _rec("a"), name: _rec("b")})
    assert ei.value.code == "schema.invalid-name"
    assert ei.value.path == "$"
    assert repr(name) in str(ei.value)


@pytest.mark.parametrize("name", BAD_NAMES)
def test_ref_target_must_be_an_identifier(name: str) -> None:
    with pytest.raises(SchemaError) as ei:
        Ref(name)
    assert ei.value.code == "schema.invalid-name"
    assert ei.value.path == "$"
    assert repr(name) in str(ei.value)


def test_non_string_ref_name_is_invalid_name() -> None:
    with pytest.raises(SchemaError) as ei:
        Ref(3)  # type: ignore[arg-type]
    assert ei.value.code == "schema.invalid-name"


@pytest.mark.parametrize("name", ["A", "_", "_a1", "a_B_9", "Root"])
def test_valid_names_are_accepted(name: str) -> None:
    s = Schema(Ref(name), {name: _rec("a")})
    assert s.root.name == name


# -- S-22 --------------------------------------------------------------------

@pytest.mark.parametrize("label", BAD_LABELS)
def test_label_must_encode_to_utf8(label: str) -> None:
    with pytest.raises(SchemaError) as ei:
        Schema(Ref("Root"), {"Root": _rec("ok"), "Other": _rec("fine", label)})
    assert ei.value.code == "schema.invalid-label"
    assert ei.value.path == "Other"          # the record path, never the label
    assert label not in ei.value.path


def test_invalid_label_in_the_root_record() -> None:
    with pytest.raises(SchemaError) as ei:
        Schema(Ref("Root"), {"Root": _rec("a\udc80")})
    assert (ei.value.code, ei.value.path) == ("schema.invalid-label", "Root")


def test_invalid_label_in_a_record_with_an_invalid_name_reports_the_name() -> None:
    # S-22: `$` when R is not itself a valid name; here the S-8 violation is
    # the reported one (at least one is reported -- spec 8.3.3).
    with pytest.raises(SchemaError) as ei:
        Schema(Ref("Root"), {"Root": _rec("a"), "bad name": _rec("a\udc80")})
    assert (ei.value.code, ei.value.path) == ("schema.invalid-name", "$")


def test_osd_text_with_a_lone_surrogate_label_is_refused() -> None:
    with pytest.raises(SchemaError) as ei:
        parse_schema('record Root { "a\udc80": string }\nroot Root')
    assert (ei.value.code, ei.value.path) == ("schema.invalid-label", "Root")


@pytest.mark.parametrize("label", ["a", "\u00e9", "\U0001f600", "a b", "a\u0000b"])
def test_valid_scalar_value_labels_are_accepted(label: str) -> None:
    assert Schema(Ref("R"), {"R": _rec(label)}).env["R"].field(label) is not None


# -- S-23 --------------------------------------------------------------------

def test_no_caller_supplied_record_ordering_exists() -> None:
    """The writer's only option is `indent`: there is no ordering argument
    naming records, so `schema.unknown-record` cannot arise in this API."""
    assert list(inspect.signature(Schema.to_osd).parameters) == ["self", "indent"]


# -- S-15 / OSD-16 / S-24 ------------------------------------------------------

def _zero(name_field: str = "a") -> Schema:
    return Schema(Ref("Root"), {"Root": Record([Field(name_field, t.string, 0, 0)])})


def test_zero_zero_cardinality_stays_constructible() -> None:
    assert Field("a", t.string, 0, 0).max == 0
    assert _zero().env["Root"].field("a") is not None


@pytest.mark.parametrize("indent", [4, None, 2])
def test_to_osd_refuses_max_zero_at_the_record_path(indent: object) -> None:
    s = Schema(Ref("Root"), {
        "Root": Record([Field("c", Ref("Child"))]),
        "Child": Record([Field("a", t.string), Field("gone", t.integer, 0, 0)]),
    })
    with pytest.raises(WriteError) as ei:
        s.to_osd(indent=indent)  # type: ignore[arg-type]
    assert ei.value.code == "write.unsupported-value"
    assert ei.value.path == "Child"
    assert "gone" not in (ei.value.path or "")


def test_to_osd_accepts_optional_and_bounded_fields() -> None:
    s = Schema(Ref("Root"), {"Root": Record([Field("a", t.string, 0, 1), Field("b", t.string, 0, 3),
                                              Field("c", t.string, 0, None)])})
    assert parse_schema(s.to_osd()) == s


def test_prune_removes_max_zero_so_the_result_writes() -> None:
    s = Schema(Ref("Root"), {"Root": Record([Field("a", t.string), Field("gone", t.string, 0, 0)])})
    out = s.prune()
    assert out.env["Root"].field("gone") is None
    assert parse_schema(out.to_osd()) == out


def test_prune_keeps_an_unsatisfiable_root_so_the_writer_still_refuses() -> None:
    # S-24: prune keeps an unsatisfiable root record intact, so a caller
    # cannot rely on it alone to make a max = 0 schema writable.
    s = Schema(Ref("Root"), {"Root": Record([Field("self", Ref("Root")),
                                              Field("gone", t.string, 0, 0)])})
    assert s.is_empty()
    out = s.prune()
    assert out.env["Root"].field("gone").max == 0      # type: ignore[union-attr]
    with pytest.raises(WriteError) as ei:
        out.to_osd()
    assert (ei.value.code, ei.value.path) == ("write.unsupported-value", "Root")


def _no_zero_max(s: Schema) -> bool:
    return all(f.max != 0 for r in s.env.values() for f in r.fields)


def test_algebra_outputs_never_introduce_max_zero() -> None:
    s = Schema(Ref("Root"), {
        "Root": Record([Field("a", Ref("A"), 0, None), Field("b", Ref("B"), 0, 2)]),
        "A": Record([Field("x", t.string)]),
        "B": Record([Field("x", t.string)]),
        "Dead": Record([Field("y", t.integer)]),
    })
    for out in (s.prune(), s.normalize(), s.extract("a", "x")):
        assert _no_zero_max(out)
        assert parse_schema(out.to_osd()) == out


def test_normalize_drops_max_zero_so_the_result_writes() -> None:
    s = Schema(Ref("Root"), {"Root": Record([Field("a", t.string), Field("gone", t.string, 0, 0)])})
    out = s.normalize()
    assert _no_zero_max(out)
    assert parse_schema(out.to_osd()) == out


# -- infer derives S-8-valid record names --------------------------------------

@pytest.mark.parametrize("label", [
    "\u00e9", "\u00fcber", "123", "0", "\u0663", "\u65e5\u672c", "a b", "a-b", "__", "_", "9lives",
    "\u00e9\u00e9", "x\u00e9",
])
def test_infer_record_names_are_identifiers(label: str) -> None:
    s = infer([{label: {"k": 1}, "other": {"k": 2}}])
    import re
    for name in s.env:
        assert re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name), name
    assert parse_schema(s.to_osd()) == s


def test_to_osd_rechecks_a_label_added_after_construction() -> None:
    s = Schema(Ref("Root"), {"Root": _rec("a")})
    s.env["Root"].fields.append(Field("a" + chr(0xDC80), t.string))
    with pytest.raises(SchemaError) as ei:
        s.to_osd()
    assert (ei.value.code, ei.value.path) == ("schema.invalid-label", "Root")
    with pytest.raises(SchemaError):
        s.to_osd(indent=None)
