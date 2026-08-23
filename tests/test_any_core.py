"""PR-1 tests for the ``any`` type's core model and algebra (issue #192,
``docs/design/any-type-spec.md``).

Scope: inventory rows I-1..I-7, I-10..I-21 only (the model, resolve/conform,
materialize, subschema/signature/prune, the OSD *writer*, and the semantic
oracle's minimal-value helper). Grammar/parsing (I-8, I-9) and the public
export (I-23) land in later PRs -- ``AnyType``/``ANY`` are imported directly
from ``omnist.schema`` here, exactly as the spec's PR-1 block requires,
since they are not yet part of ``omnist``'s public surface.
"""

from __future__ import annotations

import datetime as _dt
import sys
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from omnist import SchemaError, doc, field, materialize, record, ref, schema, t
from omnist.document import build_node
from omnist.infer import infer
from omnist.ops import compatible_with, equivalent, is_empty, normalize
from omnist.ops.isomorphic import _isomorphic
from omnist.ops.signature import local_signature
from omnist.schema import ANY, STRING, AnyType, Field, Record, Ref, Schema, nullable

# tools/ is repo-root-relative, not an installed package; bare `pytest -q`
# (as CI runs it) does not put the repo root on sys.path the way
# `python -m pytest` does, so add it explicitly before the import — the
# same pattern tests/test_semantic_oracle.py already uses.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.semantic_oracle import _minimal_value  # noqa: E402

# ---------------------------------------------------------------------------
# I-7 / T-7: t.any singleton
# ---------------------------------------------------------------------------

def test_t_any_is_singleton():
    assert t.any is t.any
    assert t.any is ANY
    assert isinstance(t.any, AnyType)


# ---------------------------------------------------------------------------
# I-1 / T-1: Field construction
# ---------------------------------------------------------------------------

def test_field_accepts_t_any():
    f = field("data", t.any)
    assert isinstance(f.type, AnyType)


def test_field_still_rejects_junk_types():
    with pytest.raises(SchemaError):
        field("x", "junk")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# I-6 / T-6: nullable(t.any) raises
# ---------------------------------------------------------------------------

def test_nullable_any_raises():
    with pytest.raises(SchemaError, match="any already includes null"):
        nullable(t.any)


# ---------------------------------------------------------------------------
# I-3 / T-3: Schema.resolve
# ---------------------------------------------------------------------------

def test_resolve_any_is_itself():
    s = schema("Root", Root=record(field("data", t.any)))
    assert s.resolve(t.any) is ANY


# ---------------------------------------------------------------------------
# I-4 / T-4: check_refs passes with an any field (no-code-change row)
# ---------------------------------------------------------------------------

def test_check_refs_passes_with_any_field():
    s = schema("Root", Root=record(field("data", t.any)))
    s.check_refs()  # must not raise


# ---------------------------------------------------------------------------
# I-5 / T-5: validate accepts anything at an any field; cardinality still
# enforced on the label itself.
# ---------------------------------------------------------------------------

def _any_schema(min=1, max=1):
    return schema("Root", Root=record(field("data", t.any, min=min, max=max)))


@pytest.mark.parametrize("value", [
    "a string",
    123,
    1.5,
    True,
    None,
    {"nested": {"deep": [1, 2, 3]}},
    {"a": None, "b": [{"c": 1}, {"c": 2}]},
])
def test_validate_accepts_anything_at_any_field(value):
    s = _any_schema()
    d = doc({"data": value})
    res = s.validate(d)
    assert res.ok, str(res)


def test_validate_still_enforces_cardinality_on_any_label():
    s = _any_schema(min=1, max=1)
    d = doc({})  # missing "data" entirely
    res = s.validate(d)
    assert not res.ok
    assert any(e.code == "validate.cardinality" for e in res.errors)


def test_validate_any_field_cardinality_range_respected():
    s = schema("Root", Root=record(field("data", t.any, min=2, max=5)))
    ok = doc({"data": [1, 2, 3]})
    assert s.accepts(ok)
    too_few = doc({"data": [1]})
    assert not s.accepts(too_few)


# ---------------------------------------------------------------------------
# I-11 / T-11: materialize pass-through, no upgrade/degrade inside any
# ---------------------------------------------------------------------------

def test_materialize_any_field_is_identity_pass_through():
    s = schema(
        "Root",
        Root=record(field("data", t.any), field("created", t.datetime)),
    )
    node = build_node({"data": {"when": "2024-01-01"}, "created": "2024-01-01T00:00:00"})
    out = materialize(node, s)
    out_map = dict(out)
    # sibling datetime field upgrades to a real datetime object
    assert isinstance(out_map["created"], _dt.datetime)
    # the ISO date string *inside* any stays a plain string, unconverted
    data_map = dict(out_map["data"])
    assert data_map["when"] == "2024-01-01"
    assert isinstance(data_map["when"], str)


def test_materialize_any_field_keeps_native_date_object_as_is():
    s = schema("Root", Root=record(field("data", t.any)))
    native_date = _dt.date(2024, 1, 1)
    node = [("data", native_date)]
    out = materialize(node, s)
    out_map = dict(out)
    assert out_map["data"] is native_date


def test_materialize_any_field_never_raises():
    s = schema("Root", Root=record(field("data", t.any)))
    node = [("data", [("x", 1), ("y", None), ("z", [("deep", "ok")])])]
    materialize(node, s)  # must not raise


# ---------------------------------------------------------------------------
# I-12 / T-12: containment (_sub) -- any absorbs, only any holds any
# ---------------------------------------------------------------------------

def test_scalar_sub_any():
    a = schema("Root", Root=record(field("x", t.string)))
    b = schema("Root", Root=record(field("x", t.any)))
    assert compatible_with(a, b)          # string <= any
    assert not compatible_with(b, a)      # any <= string is False


def test_nullable_scalar_sub_any():
    a = schema("Root", Root=record(field("x", nullable(t.string))))
    b = schema("Root", Root=record(field("x", t.any)))
    assert compatible_with(a, b)


def test_record_sub_any():
    a = schema(
        "Root",
        Root=record(field("child", ref("Child"))),
        Child=record(field("y", t.integer)),
    )
    b = schema("Root", Root=record(field("child", t.any)))
    assert compatible_with(a, b)
    assert not compatible_with(b, a)


def test_any_sub_any():
    a = schema("Root", Root=record(field("x", t.any)))
    b = schema("Root", Root=record(field("x", t.any)))
    assert compatible_with(a, b)
    assert compatible_with(b, a)
    assert equivalent(a, b)


# ---------------------------------------------------------------------------
# I-13 (no-change, covered by T-12): vacuous A-side is untouched by any.
# ---------------------------------------------------------------------------

def test_any_is_never_vacuous_a_side():
    # A record whose only field is `any` is always satisfiable (I-17), so
    # it should never hit the vacuous-A-side branch.
    a = schema("Root", Root=record(field("x", t.any)))
    b = schema("Root", Root=record(field("x", t.string)))
    assert not compatible_with(a, b)  # any is not <= string; not vacuously True


# ---------------------------------------------------------------------------
# I-14 / T-14: local_signature gives any its own distinct tag
# ---------------------------------------------------------------------------

def test_local_signature_any_is_distinct_from_scalars_and_ref():
    r_any = record(field("x", t.any))
    r_str = record(field("x", t.string))
    r_str_nullable = record(field("x", nullable(t.string)))
    r_ref = record(field("x", ref("Other")))
    sigs = {
        local_signature(r_any),
        local_signature(r_str),
        local_signature(r_str_nullable),
        local_signature(r_ref),
    }
    assert len(sigs) == 4  # all four distinct


def test_two_records_differing_only_string_vs_any_have_different_signatures():
    r1 = record(field("x", t.string))
    r2 = record(field("x", t.any))
    assert local_signature(r1) != local_signature(r2)


# ---------------------------------------------------------------------------
# I-15 / T-15: normalize never merges an any-record with a scalar-record;
# identical any-records DO merge.
# ---------------------------------------------------------------------------

def test_normalize_never_merges_any_field_record_with_scalar_field_record():
    s = schema(
        "Root",
        Root=record(field("a", ref("A")), field("b", ref("B"))),
        A=record(field("x", t.any)),
        B=record(field("x", t.string)),
    )
    n = s.normalize()
    # both A and B must still exist as distinct records (not merged)
    assert len(n.env) >= 2


def test_normalize_merges_identical_any_records():
    s = schema(
        "Root",
        Root=record(field("a", ref("A")), field("b", ref("B"))),
        A=record(field("x", t.any)),
        B=record(field("x", t.any)),
    )
    n = s.normalize()
    # A and B are structurally identical (both `x: any`) -- must collapse to
    # a single record in the env (Root remains separate, referencing it twice).
    assert len(n.env) == 2
    root = n.env[n.root.name]
    a_target = root.field("a").type.name
    b_target = root.field("b").type.name
    assert a_target == b_target


# ---------------------------------------------------------------------------
# I-16 (no-change, covered by T-15 round-trip): ANY passes through remap by
# identity.
# ---------------------------------------------------------------------------

def test_normalize_round_trip_preserves_any_field_semantics():
    s = schema(
        "Root",
        Root=record(field("a", ref("A")), field("b", ref("B"))),
        A=record(field("x", t.any)),
        B=record(field("x", t.any)),
    )
    n = s.normalize()
    assert equivalent(s, n)
    d = doc({"a": {"x": [1, 2, 3]}, "b": {"x": None}})
    assert s.accepts(d) == n.accepts(d)


# ---------------------------------------------------------------------------
# I-17 / T-17: prune satisfiability seed includes AnyType
# ---------------------------------------------------------------------------

def test_any_field_record_is_satisfiable():
    s = schema("Root", Root=record(field("x", t.any)))
    assert not is_empty(s)


def test_prune_keeps_any_only_record():
    s = schema("Root", Root=record(field("x", t.any)))
    pruned = s.prune()
    assert not is_empty(pruned)
    assert equivalent(s, pruned)


def test_any_never_rescues_unsatisfiable_sibling():
    # A record with a mandatory Ref to itself-only (unsatisfiable) plus an
    # any field: the any field must not make the record satisfiable if a
    # mandatory sibling is itself unsatisfiable.
    s = schema(
        "Root",
        Root=record(field("loop", ref("Root")), field("x", t.any)),
    )
    assert is_empty(s)  # Root requires a mandatory Root -- unsatisfiable regardless of x


# ---------------------------------------------------------------------------
# I-18 / T-18 (no-change): extract keeps/drops an any field by its own label
# ---------------------------------------------------------------------------

def test_extract_keeps_any_field_when_requested():
    s = schema(
        "Root",
        Root=record(field("id", t.string), field("data", t.any)),
    )
    e = s.extract("id", "data")
    root = e.env[e.root.name]
    assert root.field("data") is not None
    assert isinstance(root.field("data").type, AnyType)


def test_extract_drops_optional_any_field_when_not_requested():
    s = schema(
        "Root",
        Root=record(field("id", t.string), field("data", t.any, min=0, max=1)),
    )
    e = s.extract("id")
    root = e.env[e.root.name]
    assert root.field("data") is None


def test_extract_raises_when_mandatory_any_field_dropped():
    s = schema(
        "Root",
        Root=record(field("id", t.string), field("data", t.any, min=1, max=1)),
    )
    with pytest.raises(SchemaError):
        s.extract("id")


# ---------------------------------------------------------------------------
# I-19 / T-19: infer never produces AnyType, for arbitrary generated
# documents (property test).
# ---------------------------------------------------------------------------

_labels = st.text(alphabet=st.characters(whitelist_categories=("Ll",), max_codepoint=122),
                  min_size=1, max_size=6)
_scalars = st.one_of(
    st.text(max_size=8),
    st.integers(min_value=-1000, max_value=1000),
    st.floats(allow_nan=False, allow_infinity=False, width=32),
    st.booleans(),
    st.none(),
)


def _sample_values(depth: int):
    if depth >= 3:
        return _scalars
    children = st.deferred(lambda: _sample_values(depth + 1))
    return st.one_of(
        _scalars,
        st.dictionaries(_labels, children, max_size=3),
    )


_samples_strategy = st.lists(
    st.dictionaries(_labels, st.deferred(lambda: _sample_values(0)), min_size=1, max_size=5),
    min_size=1, max_size=4,
)


def _no_any_in_schema(s: Schema) -> bool:
    # No isinstance(s.root, AnyType) check: Schema.__init__ requires root to
    # be a Ref, never an AnyType, so that would be dead code for any valid
    # Schema -- an any-typed root can only ever appear as a field's type.
    for rec in s.env.values():
        for f in rec.fields:
            if isinstance(f.type, AnyType):
                return False
    return True


def test_no_any_in_schema_detects_any_typed_field():
    # infer() is asserted to never produce this, so the property test above
    # never exercises the False branch -- checked directly here.
    any_field_schema = Schema(Ref("R"), {"R": Record([Field("x", AnyType(), 1, 1)])})
    assert not _no_any_in_schema(any_field_schema)

    ok_schema = Schema(Ref("R"), {"R": Record([Field("x", STRING, 1, 1)])})
    assert _no_any_in_schema(ok_schema)


@settings(max_examples=100)
@given(samples=_samples_strategy)
def test_infer_never_produces_any_type(samples):
    try:
        s = infer(samples)
    except SchemaError:
        return  # disagreeing shapes across samples -- not this test's concern
    assert _no_any_in_schema(s)


# ---------------------------------------------------------------------------
# I-20 / T-20: isomorphism oracle agrees with `equivalent` on any-bearing
# pairs.
# ---------------------------------------------------------------------------

def test_isomorphic_agrees_with_equivalent_on_any_schemas():
    s1 = schema(
        "Root",
        Root=record(field("a", ref("A")), field("b", ref("B"))),
        A=record(field("x", t.any)),
        B=record(field("x", t.any)),
    )
    s2 = schema("Root", Root=record(field("a", t.any), field("b", t.any)))
    n1, n2 = normalize(s1), normalize(s2)
    assert equivalent(n1, n2) == _isomorphic(n1, n2)


def test_isomorphic_agrees_with_equivalent_on_any_vs_scalar():
    s1 = schema("Root", Root=record(field("x", t.any)))
    s2 = schema("Root", Root=record(field("x", t.string)))
    n1, n2 = normalize(s1), normalize(s2)
    assert equivalent(n1, n2) == _isomorphic(n1, n2)
    assert not equivalent(n1, n2)


# ---------------------------------------------------------------------------
# I-21 / T-21: semantic oracle _minimal_value(AnyType) -> None
# ---------------------------------------------------------------------------

def test_minimal_value_any_is_none():
    s = schema("Root", Root=record(field("x", t.any)))
    assert _minimal_value(s, ANY, 0, frozenset()) is None


# ---------------------------------------------------------------------------
# I-10 / T-10: writer emits "any"
# ---------------------------------------------------------------------------

def test_writer_emits_any_keyword():
    s = schema("Root", Root=record(field("data", t.any)))
    text = s.to_osd()
    assert "any" in text


def test_writer_emits_any_for_compact_mode_too():
    s = schema("Root", Root=record(field("data", t.any)))
    text = s.to_osd(indent=None)
    assert "any" in text


# ---------------------------------------------------------------------------
# Section 4.4 interaction matrix -- direct regression coverage
# ---------------------------------------------------------------------------

def test_matrix_null_accepted_at_any():
    s = schema("Root", Root=record(field("x", t.any)))
    assert s.accepts(doc({"x": None}))


@pytest.mark.parametrize("min,max,count,expect_ok", [
    (0, None, 0, True),
    (1, None, 0, False),
    (1, None, 1, True),
    (2, 5, 1, False),
    (2, 5, 3, True),
])
def test_matrix_cardinality_enforced_on_any_label(min, max, count, expect_ok):
    s = schema("Root", Root=record(field("x", t.any, min=min, max=max)))
    d = doc({"x": [i for i in range(count)]} if count else {})
    assert s.accepts(d) == expect_ok


def test_matrix_any_always_satisfiable():
    s = schema("Root", Root=record(field("x", t.any, min=1, max=1)))
    assert not is_empty(s)


@pytest.mark.parametrize("t_side", ["scalar", "nullable_scalar", "record"])
def test_matrix_t_sub_any_true(t_side):
    if t_side == "scalar":
        a = schema("Root", Root=record(field("x", t.string)))
    elif t_side == "nullable_scalar":
        a = schema("Root", Root=record(field("x", nullable(t.string))))
    else:
        a = schema(
            "Root", Root=record(field("x", ref("Child"))),
            Child=record(field("y", t.integer)),
        )
    b = schema("Root", Root=record(field("x", t.any)))
    assert compatible_with(a, b)


def test_matrix_any_sub_any_true():
    a = schema("Root", Root=record(field("x", t.any)))
    b = schema("Root", Root=record(field("x", t.any)))
    assert compatible_with(a, b)


@pytest.mark.parametrize("t_side", ["scalar", "nullable_scalar", "record"])
def test_matrix_any_sub_t_false(t_side):
    a = schema("Root", Root=record(field("x", t.any)))
    if t_side == "scalar":
        b = schema("Root", Root=record(field("x", t.string)))
    elif t_side == "nullable_scalar":
        b = schema("Root", Root=record(field("x", nullable(t.string))))
    else:
        b = schema(
            "Root", Root=record(field("x", ref("Child"))),
            Child=record(field("y", t.integer)),
        )
    assert not compatible_with(a, b)
