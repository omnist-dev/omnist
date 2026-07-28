"""Executes the worked examples from the formal grammar docs.

Each test corresponds to a numbered row in the "Worked examples" table of
``docs/design/oml-grammar.md`` or ``docs/design/schema-osd-grammar.md``, so
the claims in those docs can't silently rot. These are the same
verify-before-claim snippets used while drafting the grammars, kept here as
real tests rather than one-off scratch scripts.
"""
import datetime

import pytest

from omnist import ParseError, SchemaError, parse_schema, read_oml
from omnist.oml import _MAX_DEPTH, _MAX_INT_DIGITS

# ---------------------------------------------------------------------------
# docs/design/oml-grammar.md -- Worked examples
# ---------------------------------------------------------------------------

def test_oml_ex1_date_then_t_with_valid_time_is_one_datetime_token():
    assert read_oml("2024-01-01T10:30") == datetime.datetime(2024, 1, 1, 10, 30)


def test_oml_ex2_date_then_t_with_non_time_text_splits_into_date_and_ident():
    with pytest.raises(ParseError, match="trailing content"):
        read_oml("2024-01-01T99")


def test_oml_ex3_raw_string_has_no_escape_processing():
    assert read_oml("a: 'C:\\no\\escapes'") == [("a", "C:\\no\\escapes")]


def test_oml_ex4_multiline_string_strips_leading_newline():
    assert read_oml('a: """\nhello\nworld"""') == [("a", "hello\nworld")]


def test_oml_ex5_multiline_string_embedded_short_quote_runs_are_literal():
    assert read_oml('a: """\nsays ""hi"" there"""') == [("a", 'says ""hi"" there')]


def test_oml_ex6_reserved_word_as_nested_bare_label_is_explicit_error():
    with pytest.raises(ParseError, match="reserved word"):
        read_oml("a: { null: 1 }")


def test_oml_ex7_multiline_string_with_4_trailing_quotes():
    with pytest.raises(ParseError, match="unterminated string"):
        read_oml('a: """\nx""""')


def test_oml_ex8_multiline_string_with_5_trailing_quotes():
    with pytest.raises(ParseError):
        read_oml('a: """\nx"""""')


def test_oml_ex9_nan_is_a_number_token_never_a_label():
    with pytest.raises(ParseError):
        read_oml("nan: 1")


def test_oml_ex10_quoted_nan_is_a_valid_label():
    assert read_oml('"nan": 1') == [("nan", 1)]


@pytest.mark.parametrize("spelling", ["inf", "-inf"])
def test_oml_inf_is_a_number_token_never_a_label(spelling):
    # Symmetric with ex9 above (issue #262): inf/-inf are reserved NUMBER
    # spellings the same way nan is, so bare (unquoted) they can never be
    # read as a label either.
    with pytest.raises(ParseError):
        read_oml(f"{spelling}: 1")


@pytest.mark.parametrize("spelling", ["inf", "-inf"])
def test_oml_quoted_inf_is_a_valid_label(spelling):
    # Symmetric with ex10 above (issue #262): quoting forces the STRING
    # token, which is a valid label for inf/-inf same as it is for nan.
    assert read_oml(f'"{spelling}": 1') == [(spelling, 1)]


def test_oml_ex11_top_level_null_colon_fails_as_trailing_content_not_reserved_word():
    with pytest.raises(ParseError, match="trailing content"):
        read_oml("null: 1")


def test_oml_ex12_nested_null_colon_fails_as_explicit_reserved_word():
    with pytest.raises(ParseError, match="reserved word"):
        read_oml("a: { null: 1 }")


def test_oml_ex13_limits_at_the_boundary_succeed():
    assert read_oml("9" * _MAX_INT_DIGITS) == int("9" * _MAX_INT_DIGITS)
    nested = "a: " + ("{a: " * _MAX_DEPTH) + "1" + (" }" * _MAX_DEPTH)
    read_oml(nested)  # must not raise


def test_oml_ex14_limits_one_past_the_boundary_fail():
    with pytest.raises(ParseError, match="digits"):
        read_oml("9" * (_MAX_INT_DIGITS + 1))
    nested = "a: " + ("{a: " * (_MAX_DEPTH + 1)) + "1" + (" }" * (_MAX_DEPTH + 1))
    with pytest.raises(ParseError, match="nesting"):
        read_oml(nested)


def test_oml_ex15_repeated_label_is_two_edges_not_a_list_value():
    assert read_oml('tag: "x"\ntag: "y"') == [("tag", "x"), ("tag", "y")]


def test_oml_ex16_empty_braces_is_empty_edge_list():
    assert read_oml("a: {}") == [("a", [])]


def test_oml_ex17_bare_top_level_scalar_is_the_whole_document():
    assert read_oml('"hello"') == "hello"


def test_oml_ex18_compact_write_round_trips():
    from omnist import write_oml

    node = [("a", 1), ("b", [("x", 1), ("y", 2)])]
    text = write_oml(node, indent=None)
    assert text == "a: 1; b: { x: 1; y: 2 }"
    assert read_oml(text) == node


def test_oml_ex19_array_syntax_expands_to_repeated_edges():
    assert read_oml("b: [1, 2, 3]") == [("b", 1), ("b", 2), ("b", 3)]


# ---------------------------------------------------------------------------
# docs/design/schema-osd-grammar.md -- Worked examples
# ---------------------------------------------------------------------------

def test_osd_ex1_label_backslash_escape_drops_backslash_no_named_escapes():
    s = parse_schema('record R { "a\\nb": string }\nroot R')
    assert s.env["R"].fields[0].label == "anb"


def test_osd_ex2_cardinality_m_n():
    s = parse_schema('record R { "a" [1,5]: string }\nroot R')
    f = s.env["R"].fields[0]
    assert (f.min, f.max) == (1, 5)


def test_osd_ex3_cardinality_m_open():
    s = parse_schema('record R { "a" [5,]: string }\nroot R')
    f = s.env["R"].fields[0]
    assert (f.min, f.max) == (5, None)


def test_osd_ex4_cardinality_open_n():
    s = parse_schema('record R { "a" [,5]: string }\nroot R')
    f = s.env["R"].fields[0]
    assert (f.min, f.max) == (0, 5)


def test_osd_ex5_cardinality_fully_open():
    s = parse_schema('record R { "a" [,]: string }\nroot R')
    f = s.env["R"].fields[0]
    assert (f.min, f.max) == (0, None)


def test_osd_ex6_empty_cardinality_is_an_error():
    with pytest.raises(SchemaError, match="empty cardinality"):
        parse_schema('record R { "a" []: string }\nroot R')


def test_osd_ex7_negative_cardinality_rejected_by_field_not_parser():
    with pytest.raises(SchemaError, match="invalid cardinality"):
        parse_schema('record R { "a" [-1]: string }\nroot R')


def test_osd_ex8_inverted_cardinality_rejected_by_field_not_parser():
    with pytest.raises(SchemaError, match="invalid cardinality"):
        parse_schema('record R { "a" [1,0]: string }\nroot R')


def test_osd_ex9_fractional_cardinality_is_an_error():
    with pytest.raises(SchemaError, match="whole number"):
        parse_schema('record R { "a" [1.5]: string }\nroot R')


def test_osd_ex10_nullable_scalar():
    s = parse_schema('record R { "a": string? }\nroot R')
    f = s.env["R"].fields[0]
    assert f.type.name == "string" and f.type.nullable is True


def test_osd_ex11_nullable_ref_is_rejected():
    with pytest.raises(SchemaError, match=r"cannot apply to the reference"):
        parse_schema('record S { "x": string }\nrecord R { "a": S? }\nroot R')


def test_osd_ex12_reserved_scalar_name_as_record_name_is_rejected():
    with pytest.raises(SchemaError, match="reserved scalar name"):
        parse_schema('record string { "a": string }\nroot string')


def test_osd_ex13_duplicate_record_definition_is_rejected():
    with pytest.raises(SchemaError, match="duplicate definition"):
        parse_schema('record R{"a":string}\nrecord R{"b":string}\nroot R')


def test_osd_ex14_missing_root_is_rejected():
    with pytest.raises(SchemaError, match="must declare a root"):
        parse_schema('record R{"a":string}')


def test_osd_ex15_unquoted_label_is_rejected():
    with pytest.raises(SchemaError, match="quoted field name"):
        parse_schema('record R{a:string}\nroot R')


def test_osd_ex16_trailing_comma_in_record_body_is_accepted():
    s = parse_schema('record R { "a": string, }\nroot R')
    assert [f.label for f in s.env["R"].fields] == ["a"]


def test_osd_ex17_comments_are_discarded_anywhere():
    s = parse_schema(
        '# comment\nrecord R { "a": string } # trailing\nroot R'
    )
    assert [f.label for f in s.env["R"].fields] == ["a"]


def test_osd_ex18_to_osd_roundtrip():
    from omnist import to_osd

    s = parse_schema('record R { "a" [0,3]: string? }\nroot R')
    assert to_osd(s) == 'record R {\n    "a" [0,3]: string?,\n}\nroot R\n'


def test_osd_ex19_compact_to_osd_roundtrip():
    from omnist import to_osd

    s = parse_schema('record R { "a": string }\nroot R')
    text = to_osd(s, indent=None)
    assert text == 'record R { "a": string } root R\n'
    assert s.equivalent(parse_schema(text))


def test_osd_ex20_any_field_with_cardinality():
    from omnist import AnyType

    s = parse_schema('record R { "data": any }\nroot R')
    assert isinstance(s.env["R"].fields[0].type, AnyType)

    s2 = parse_schema('record R { "data" [0,]: any }\nroot R')
    f2 = s2.env["R"].fields[0]
    assert isinstance(f2.type, AnyType)
    assert (f2.min, f2.max) == (0, None)


def test_osd_ex21_any_question_mark_is_rejected():
    with pytest.raises(SchemaError, match=r"'any' already includes null"):
        parse_schema('record R { "data": any? }\nroot R')


def test_osd_ex22_record_named_any_is_rejected():
    with pytest.raises(
        SchemaError, match=r"'any' is a reserved type name"
    ):
        parse_schema('record any { "a": string }\nroot any')


def test_osd_ex23_capitalized_any_is_unknown_ref_not_reserved():
    with pytest.raises(SchemaError, match="unknown type"):
        parse_schema('record R { "data": Any }\nroot R')


@pytest.mark.parametrize(
    "ch", ["@", "&", "/", "^", "%", "!", "~", "`", "$"]
)
def test_osd_unknown_character_is_rejected(ch):
    with pytest.raises(SchemaError, match="unexpected character"):
        parse_schema('record R { "a": ' + ch + ' }\nroot R')
