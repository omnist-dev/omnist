"""PR-2 tests for the ``any`` type's OSD grammar exposure and public export
(issue #193, ``docs/design/any-type-spec.md`` section 8's PR-2 block).

Scope: inventory rows I-8, I-9, I-23, plus the round-trip test obligation
(T-RT) for schemas containing ``any``.
"""

from __future__ import annotations

import pytest

from omnist import AnyType, SchemaError, field, parse_schema, record, schema, t, to_osd
from omnist.ops import equivalent

# ---------------------------------------------------------------------------
# I-8 / T-8: parser accepts "any", rejects "any?"
# ---------------------------------------------------------------------------

def test_parse_any_field():
    s = parse_schema('record Root { "data": any }\nroot Root')
    f = s.env["Root"].fields[0]
    assert isinstance(f.type, AnyType)


@pytest.mark.parametrize("card", ["[0,]", "[2,5]"])
def test_parse_any_field_with_cardinality(card):
    text = f'record Root {{ "data" {card}: any }}\nroot Root'
    s = parse_schema(text)
    f = s.env["Root"].fields[0]
    assert isinstance(f.type, AnyType)


def test_any_question_mark_is_rejected():
    text = 'record Root { "data": any? }\nroot Root'
    with pytest.raises(
        SchemaError,
        match=r"'any' already includes null; 'any\?' is redundant at \d+",
    ):
        parse_schema(text)


def test_any_question_mark_exact_message():
    text = 'record Root { "data": any? }\nroot Root'
    with pytest.raises(SchemaError) as exc:
        parse_schema(text)
    pos = text.index("?")
    assert str(exc.value) == (
        f"'any' already includes null; 'any?' is redundant at {pos}"
    )


def test_capitalized_any_is_unknown_ref_not_any_type():
    """Spec section 7: a schema author typo like "x": Any (capitalized) is
    a Ref("Any") -> existing "unknown type" error; no special case."""
    text = 'record Root { "data": Any }\nroot Root'
    with pytest.raises(SchemaError, match="unknown type"):
        parse_schema(text)


# ---------------------------------------------------------------------------
# I-9 / T-9: "any" is a reserved record name
# ---------------------------------------------------------------------------

def test_record_named_any_is_rejected():
    text = 'record any { "x": string }\nroot any'
    with pytest.raises(
        SchemaError,
        match=r"'any' is a reserved type name and cannot be used as a "
              r"record name at \d+",
    ):
        parse_schema(text)


def test_record_named_any_exact_message():
    text = 'record any { "x": string }\nroot any'
    with pytest.raises(SchemaError) as exc:
        parse_schema(text)
    pos = text.index("any")
    assert str(exc.value) == (
        f"'any' is a reserved type name and cannot be used as a record "
        f"name at {pos}"
    )


# ---------------------------------------------------------------------------
# I-23 / T-23: public export
# ---------------------------------------------------------------------------

def test_anytype_is_publicly_exported():
    from omnist import AnyType as ImportedAnyType

    assert ImportedAnyType is AnyType


def test_t_any_isinstance_anytype():
    assert isinstance(t.any, AnyType)


def test_anytype_in_dunder_all():
    import omnist

    assert "AnyType" in omnist.__all__
    assert "ANY" not in omnist.__all__


# ---------------------------------------------------------------------------
# T-RT: round-trip -- parse_schema(to_osd(s)) is equivalent(s), pretty and
# compact modes, for schemas containing `any` built via t.any and via
# parsing OSD text.
# ---------------------------------------------------------------------------

def _builder_schema_with_any():
    return schema(
        "Root",
        Root=record(
            field("id", t.string),
            field("data", t.any),
            field("many", t.any, min=0, max=None),
        ),
    )


def _parsed_schema_with_any():
    return parse_schema(
        'record Root {\n'
        '    "id": string,\n'
        '    "data": any,\n'
        '    "many" [0,]: any,\n'
        '}\n'
        'root Root\n'
    )


@pytest.mark.parametrize(
    "make_schema", [_builder_schema_with_any, _parsed_schema_with_any]
)
@pytest.mark.parametrize("indent", [4, None])
def test_any_round_trip(make_schema, indent):
    s = make_schema()
    text = to_osd(s, indent=indent)
    assert "any" in text
    reparsed = parse_schema(text)
    assert equivalent(s, reparsed)
