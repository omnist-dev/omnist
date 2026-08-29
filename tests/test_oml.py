"""Tests for OML (Omnist Markup Language) -- omnist's native codec.

Covers happy-path round-tripping of every Document shape (all seven scalars
plus null, repeated/interleaved labels, arbitrary nesting) and the edge
cases worked out in the design: string escaping, raw strings (E2), multiline
strings (E3) and their interaction with the SEP/newline separator, numeric
edge cases, reserved words, top-level brace disambiguation, the integer
digit-count limit (DoS hardening), and the nesting-depth limit.
"""
import datetime

import pytest

from omnist import Doc, ParseError, check_oml, doc, parse_schema, read_oml, write_oml
from omnist.registry import formats, get_format

# ---------------------------------------------------------------------------
# Happy paths: round-tripping every scalar kind
# ---------------------------------------------------------------------------

def test_oml_is_a_registered_format():
    assert "oml" in formats()
    fmt = get_format("oml")
    assert fmt.read is read_oml and fmt.write is write_oml and fmt.check is check_oml


@pytest.mark.parametrize("src,expected", [
    ('a: "hello"', [("a", "hello")]),
    ("a: 42", [("a", 42)]),
    ("a: -42", [("a", -42)]),
    ("a: 3.14", [("a", 3.14)]),
    ("a: -3.14", [("a", -3.14)]),
    ("a: 1e10", [("a", 1e10)]),
    ("a: 1.5e-3", [("a", 1.5e-3)]),
    ("a: true", [("a", True)]),
    ("a: false", [("a", False)]),
    ("a: null", [("a", None)]),
    ("a: 2024-01-01", [("a", datetime.date(2024, 1, 1))]),
    ("a: 12:30:00", [("a", datetime.time(12, 30, 0))]),
    ("a: 2024-01-01T12:30:00", [("a", datetime.datetime(2024, 1, 1, 12, 30, 0))]),
    ("a: nan", None),   # NaN isn't self-equal; checked separately below
    ("a: inf", [("a", float("inf"))]),
    ("a: -inf", [("a", float("-inf"))]),
])
def test_scalar_round_trip(src, expected):
    node = read_oml(src)
    if expected is None:
        import math
        assert math.isnan(node[0][1])
    else:
        assert node == expected
    # round-trips through the canonical writer
    if expected is not None:
        assert read_oml(write_oml(node)) == node


def test_empty_document_is_empty_node():
    assert read_oml("") == []
    assert read_oml("   \n  \n") == []


def test_crlf_line_endings_act_as_separators():
    # \r\n (not just bare \n) is recognized as a separator.
    assert read_oml("a: 1\r\nb: 2\r\n") == [("a", 1), ("b", 2)]


def test_bare_leaf_document():
    assert read_oml("42") == 42
    assert read_oml('"just a string"') == "just a string"


def test_stray_character_is_a_parse_error():
    with pytest.raises(ParseError, match="stray character"):
        read_oml("a: `")


@pytest.mark.parametrize(
    "ch", ["@", "&", "/", "^", "%", "!", "~", "`", "$"]
)
def test_stray_characters_are_rejected(ch):
    # NOTE (#218): '[' used to be in this sweep too, but it's grammar now
    # (array syntax) -- see test_array_* below.
    with pytest.raises(ParseError, match="stray character"):
        read_oml("a: " + ch)


def test_unmatched_close_bracket_is_a_parse_error():
    # ']' alone, not closing an array, is now a recognized-but-invalid
    # token (RBRACKET) rather than a "stray character" -- '[' is grammar
    # now, so the scanner tokenizes ']' too instead of falling through to
    # the stray-character path. Still a ParseError either way.
    with pytest.raises(ParseError):
        read_oml("a: ]")


@pytest.mark.parametrize("src,match", [
    ("a: 2024-13-01", "invalid date"),
    ("a: 25:00:00", "invalid time"),
    ("a: 2024-13-01T00:00:00", "invalid datetime"),
])
def test_invalid_temporal_literals_are_parse_errors(src, match):
    with pytest.raises(ParseError, match=match):
        read_oml(src)


def test_repeated_labels_and_interleaving():
    node = read_oml("a: 1\nb: 2\na: 3\nb: 4\na: 5")
    assert node == [("a", 1), ("b", 2), ("a", 3), ("b", 4), ("a", 5)]
    d = Doc(node)
    assert d.count("a") == 3
    assert [c.value for c in d.get("a")] == [1, 3, 5]


def test_nested_braces_arbitrary_depth():
    node = read_oml('a: { b: { c: { d: "leaf" } } }')
    assert node == [("a", [("b", [("c", [("d", "leaf")])])])]


def test_inline_brace_style_with_semicolons():
    assert read_oml('{ a: 1; b: 2 }') == [("a", 1), ("b", 2)]


def test_comments_are_ignored():
    node = read_oml("# a top comment\na: 1  # trailing comment\nb: 2\n")
    assert node == [("a", 1), ("b", 2)]


# ---------------------------------------------------------------------------
# String escaping
# ---------------------------------------------------------------------------

def test_basic_escapes():
    node = read_oml(r'a: "line1\nline2\ttabbed\\backslash\"quote"')
    assert node == [("a", 'line1\nline2\ttabbed\\backslash"quote')]


def test_unicode_escape_bmp():
    assert read_oml(r'a: "é"') == [("a", "é")]


def test_unicode_escape_astral_surrogate_pair():
    assert read_oml(r'a: "😀"') == [("a", "\U0001F600")]


def test_unpaired_surrogate_rejected():
    with pytest.raises(ParseError):
        read_oml(r'a: "\uD83D"')
    with pytest.raises(ParseError):
        read_oml(r'a: "\uDE00"')


def test_surrogate_pair_via_u_escapes():
    # a valid \uD800-\uDBFF high surrogate immediately followed by a valid
    # \uDC00-\uDFFF low surrogate \u escape combines into one astral code
    # point (as opposed to the literal-UTF-8 path tested above).
    src = 'a: "' + chr(92) + 'uD83D' + chr(92) + 'uDE00"'
    assert read_oml(src) == [("a", "\U0001F600")]


def test_non_surrogate_unicode_escape_is_returned_as_is():
    src = 'a: "' + chr(92) + 'u0041"'
    assert read_oml(src) == [("a", "A")]


def test_unterminated_escape_sequence_rejected():
    with pytest.raises(ParseError, match="unterminated escape sequence"):
        read_oml('a: "' + chr(92))


def test_high_surrogate_followed_by_non_low_surrogate_rejected():
    # a high surrogate followed by something that isn't a valid \u-escaped
    # low surrogate (wrong escape, or a non-surrogate \u value) is rejected.
    with pytest.raises(ParseError, match="unpaired high surrogate"):
        read_oml(r'a: "\uD83DA"')   # followed by A ('A'), not a low surrogate
    with pytest.raises(ParseError, match="unpaired high surrogate"):
        read_oml(r'a: "\uD83Dx"')        # not followed by a \u escape at all


def test_high_surrogate_followed_by_well_formed_non_low_surrogate_escape_rejected():
    # a high surrogate followed by a *well-formed* \uXXXX escape (valid 4 hex
    # digits) whose value simply isn't in the low-surrogate range DC00-DFFF
    # is still an unpaired-high-surrogate error -- distinct from "not a \u
    # escape at all" (\uD83DA) and "malformed hex" (\uD83Dx) above.
    src = 'a: "' + chr(92) + 'uD83D' + chr(92) + 'u0041"'
    with pytest.raises(ParseError, match="unpaired high surrogate"):
        read_oml(src)


def test_invalid_unicode_escape_needs_four_hex_digits():
    with pytest.raises(ParseError, match=r"invalid \\u escape"):
        read_oml(r'a: "\u12"')


def test_invalid_escape_character_rejected():
    with pytest.raises(ParseError, match=r"invalid escape"):
        read_oml(r'a: "\z"')


def test_control_character_must_be_escaped():
    with pytest.raises(ParseError):
        read_oml('a: "tab\there"')  # literal tab byte, not escaped


def test_writer_emits_minimal_escapes_only():
    text = write_oml([("a", 'has "quotes" and \\backslash\\ and \n newline')])
    assert text == r'a: "has \"quotes\" and \\backslash\\ and \n newline"'
    # / is never escaped on write even though \/ is accepted on read
    assert write_oml([("a", "a/b")]) == 'a: "a/b"'
    assert read_oml(r'a: "a\/b"') == [("a", "a/b")]


# ---------------------------------------------------------------------------
# Raw strings (E2)
# ---------------------------------------------------------------------------

def test_raw_string_no_escape_processing():
    node = read_oml(r"a: 'C:\talks\ada\slides.key'")
    assert node == [("a", r"C:\talks\ada\slides.key")]


def test_raw_string_cannot_contain_apostrophe():
    with pytest.raises(ParseError):
        read_oml("a: 'it''s broken'")  # terminates at the first '


def test_unterminated_raw_string_is_a_parse_error():
    with pytest.raises(ParseError, match="unterminated raw string"):
        read_oml("a: 'never closed")


def test_raw_string_canonical_writer_never_emits_it():
    node = read_oml(r"a: 'C:\x'")
    text = write_oml(node)
    assert "'" not in text
    assert text == r'a: "C:\\x"'


# ---------------------------------------------------------------------------
# Multiline strings (E3) and SEP/newline interaction
# ---------------------------------------------------------------------------

def test_multiline_basic():
    node = read_oml('a: """\nline one\nline two\n"""')
    assert node == [("a", "line one\nline two\n")]


def test_multiline_leading_newline_stripped_but_internal_kept():
    node = read_oml('a: """\nx\ny\n"""')
    assert node[0][1] == "x\ny\n"


def test_multiline_no_leading_newline_needed():
    node = read_oml('a: """same line start"""')
    assert node == [("a", "same line start")]


def test_multiline_leading_crlf_stripped():
    # a \r\n right after the opening """ is stripped just like a bare \n.
    # (a bare \r elsewhere in the body is a control character and must be
    # escaped, so this only exercises the opening-CRLF special case.)
    node = read_oml('a: """\r\nx\n"""')
    assert node[0][1] == "x\n"


def test_unterminated_multiline_string_is_a_parse_error():
    with pytest.raises(ParseError, match="unterminated multiline string"):
        read_oml('a: """never closed')


def test_control_character_in_multiline_string_must_be_escaped():
    # \t and \n are allowed unescaped in a multiline string; any other
    # control character (e.g. a literal \r not part of the opening CRLF) is
    # rejected just like in an ordinary string.
    src = 'a: """x' + chr(13) + 'y"""'
    with pytest.raises(ParseError, match="control character"):
        read_oml(src)


def test_multiline_internal_newlines_never_act_as_sep():
    node = read_oml('a: """\nx\ny\n"""\nb: 1')
    assert node == [("a", "x\ny\n"), ("b", 1)]


def test_multiline_immediately_followed_by_label_is_parse_error():
    # closing """ with no SEP before the next label -- G5 "no silent concatenation"
    with pytest.raises(ParseError):
        read_oml('a: """\nx\ny\n"""b: 1')


def test_multiline_followed_by_semicolon_sep_is_valid():
    node = read_oml('a: """\nx\ny\n""";b: 1')
    assert node == [("a", "x\ny\n"), ("b", 1)]


def test_multiline_escapes_still_processed():
    node = read_oml('a: """back\\\\slash and \\"escaped quote\\""""')
    assert node == [("a", 'back\\slash and "escaped quote"')]


@pytest.mark.parametrize("src,value", [
    ('a: """x"""', "x"),
    ('a: """"""', ""),
    ('a: """"x"""', '"x'),
    ('a: """""x"""', '""x'),
])
def test_multiline_touching_quote_runs(src, value):
    assert read_oml(src) == [("a", value)]


def test_multiline_four_touching_quotes_leaves_dangling_string():
    # open(3) + close(3) consumes 6 of the 7 quotes; 1 left over starts a new,
    # unterminated ordinary STRING token -> ParseError
    with pytest.raises(ParseError):
        read_oml('a: """""""')


def test_multiline_escaped_quote_breaks_terminator_run():
    node = read_oml('a: """x\\"""y"""')
    assert node == [("a", 'x"""y')]


def test_multiline_canonical_writer_never_emits_it():
    node = read_oml('a: """\nx\ny\n"""')
    text = write_oml(node)
    assert '"""' not in text
    assert text == 'a: "x\\ny\\n"'


# ---------------------------------------------------------------------------
# Top-level brace / structural disambiguation
# ---------------------------------------------------------------------------

def test_brace_must_wrap_entire_document():
    with pytest.raises(ParseError):
        read_oml("{ a: 1 }\nb: 2")


def test_one_set_of_braces_around_everything_is_fine():
    assert read_oml("{ a: 1; b: 2 }") == [("a", 1), ("b", 2)]


def test_two_bare_leaves_is_an_error():
    with pytest.raises(ParseError):
        read_oml("42\n43")


def test_empty_braces_is_empty_node():
    assert read_oml("{ ;;; }") == []
    assert read_oml("{ }") == []


def test_two_edges_without_separator_is_error():
    with pytest.raises(ParseError):
        read_oml("a: 1 b: 2")


def test_two_edges_with_newline_separator_is_fine():
    assert read_oml("a: 1\nb: 2") == [("a", 1), ("b", 2)]


# ---------------------------------------------------------------------------
# Structural parse errors inside braces
# ---------------------------------------------------------------------------

def test_missing_colon_after_label_is_a_parse_error():
    with pytest.raises(ParseError, match="expected ':'"):
        read_oml("{a 1}")


def test_non_label_token_where_label_expected_is_a_parse_error():
    with pytest.raises(ParseError, match="expected a label"):
        read_oml("{1: 2}")


def test_missing_closing_brace_is_a_parse_error():
    with pytest.raises(ParseError, match=r"expected '\}'"):
        read_oml("{a: 1")


def test_missing_value_after_colon_is_a_parse_error():
    with pytest.raises(ParseError, match="expected a value"):
        read_oml("{a: }")


# ---------------------------------------------------------------------------
# Reserved words and labels
# ---------------------------------------------------------------------------

def test_reserved_word_as_bare_label_is_error():
    with pytest.raises(ParseError):
        read_oml("true: 1")


def test_reserved_word_as_bare_label_inside_braces_is_error():
    # at the top level "true: 1" fails the _looks_like_edge() lookahead and
    # is parsed as a bare scalar instead (caught elsewhere); inside braces,
    # a non-first edge's label always goes through parse_label() directly.
    with pytest.raises(ParseError, match="reserved word"):
        read_oml("{a: 1\ntrue: 2}")


def test_quoted_reserved_word_label_is_fine():
    assert read_oml('"true": 1') == [("true", 1)]


def test_nullable_is_not_reserved():
    assert read_oml("nullable: 1") == [("nullable", 1)]


def test_capitalized_nan_is_bare_ident_not_keyword():
    with pytest.raises(ParseError):
        read_oml("a: NaN")
    assert read_oml('a: "NaN"') == [("a", "NaN")]


@pytest.mark.parametrize("spelling", ["INF", "Inf", "-INF", "-Inf"])
def test_capitalized_inf_is_not_the_keyword(spelling):
    # Issue #262, symmetric with the nan test above: only the exact
    # lowercase spellings inf/-inf are the reserved NUMBER tokens; any
    # other casing is not the keyword, so it's rejected as a bare word in
    # value position (or a stray leading '-' for the negative spellings,
    # since a capitalized "INF"/"Inf" doesn't match the reserved -inf
    # token either) -- never silently accepted as +/-infinity.
    with pytest.raises(ParseError):
        read_oml(f"a: {spelling}")
    quoted = read_oml(f'a: "{spelling}"')
    assert quoted == [("a", spelling)]


def test_label_cannot_start_with_digit():
    with pytest.raises(ParseError):
        read_oml("123: 1")
    assert read_oml('"123": 1') == [("123", 1)]


def test_hyphenated_label():
    assert read_oml("a-b: 1") == [("a-b", 1)]


@pytest.mark.parametrize("label", ["inf", "nan", "-inf"])
def test_reserved_number_spelling_as_label_round_trips(label):
    # Regression test for issue #71: "inf"/"nan"/"-inf" are reserved NUMBER
    # spellings with higher tokenizer priority than IDENT, so write_oml must
    # always quote them as labels -- writing them bare produces OML that
    # read_oml cannot parse back, breaking OML's documented lossless
    # round-trip guarantee.
    node = [(label, 1)]
    written = write_oml(node)
    assert written == f'"{label}": 1'
    assert read_oml(written) == node


# ---------------------------------------------------------------------------
# Numeric edge cases
# ---------------------------------------------------------------------------

def test_negative_zero_integer_is_exactly_zero():
    node = read_oml("a: -0")
    assert node[0][1] == 0
    assert not isinstance(node[0][1], bool)


def test_negative_zero_float_is_sign_preserving():
    import math
    node = read_oml("a: -0.0")
    assert math.copysign(1.0, node[0][1]) == -1.0


def test_leading_zero_integer_is_rejected():
    # Issue #328/omnist-spec Sec4.2.3: int-part is "0" alone, or a nonzero
    # digit then any digits -- never a 0 followed by more digits. Matches
    # the vendored vector oml-grammar/numbers/leading-zero-integer-is-an
    # -error exactly (path "1:4" -- the offset of the leading "0").
    with pytest.raises(ParseError) as exc:
        read_oml("n: 01\n")
    assert exc.value.code == "parse.leading-zero"
    assert exc.value.path == "1:4"


def test_leading_zero_in_decimal_is_rejected():
    # The fractional part does not exempt the integer part from the same
    # rule -- matches oml-grammar/numbers/leading-zero-in-decimal-is-an
    # -error.
    with pytest.raises(ParseError) as exc:
        read_oml("n: 00.5\n")
    assert exc.value.code == "parse.leading-zero"
    assert exc.value.path == "1:4"


def test_leading_zero_negative_and_exponent_forms_are_rejected_too():
    for text in ("n: -01\n", "n: 01e5\n", "n: -00.5e2\n"):
        with pytest.raises(ParseError) as exc:
            read_oml(text)
        assert exc.value.code == "parse.leading-zero", text


def test_single_zero_and_negative_forms_remain_valid():
    # A bare "0" is exactly one digit, so it's never a leading zero; a
    # fraction less than 1 legitimately starts with "0."; a negative sign
    # does not change int-part's own rule -- matches the vendored
    # happy-path vector oml-grammar/numbers/single-zero-and-negative-forms
    # -are-valid.
    node = read_oml("a: 0\nb: -0\nc: 0.5\nd: -12\n")
    assert node == [("a", 0), ("b", 0), ("c", 0.5), ("d", -12)]


def test_integer_digit_limit_enforced():
    ok = "9" * 4300
    assert read_oml(f"a: {ok}")[0][1] == int(ok)
    too_big = "9" * 4301
    with pytest.raises(ParseError):
        read_oml(f"a: {too_big}")


def test_overflow_and_underflow_are_defined_not_errors():
    assert read_oml("a: 1e400")[0][1] == float("inf")
    assert read_oml("a: 1e-400")[0][1] == 0.0


# ---------------------------------------------------------------------------
# Depth limit
# ---------------------------------------------------------------------------

def test_nesting_depth_limit():
    too_deep = "a: " + "{ b: " * 201 + "1" + " }" * 201
    with pytest.raises(ParseError):
        read_oml(too_deep)


# ---------------------------------------------------------------------------
# Performance: the scanner must be near-linear, not O(n^2) (issue #155, B1)
# ---------------------------------------------------------------------------

def _edges_source(n: int) -> str:
    return "\n".join(f"k{i}: {i}" for i in range(n))


def test_tokenizer_scales_near_linearly_not_quadratically():
    """``_Scanner._next`` used to slice ``self.s[self.i:]`` per token, an
    O(n^2) copy that made 4x the input take ~16x the time. A ratio bound
    (not a wall-clock ceiling) keeps this deterministic under CI load: an
    O(n) scanner should see 4x input take roughly 4x as long; a quadratic
    scanner would take roughly 16x. We allow generous headroom (6x) so the
    test only fails on genuine superlinear regressions, not noise."""
    import time

    n = 15000
    small = _edges_source(n)
    large = _edges_source(n * 4)

    # Warm up (import/regex-compile costs shouldn't count against either leg).
    read_oml(_edges_source(200))

    t0 = time.perf_counter()
    read_oml(small)
    t_small = time.perf_counter() - t0

    t0 = time.perf_counter()
    read_oml(large)
    t_large = time.perf_counter() - t0

    assert t_large < t_small * 6, (
        f"4x input took {t_large / t_small:.2f}x as long "
        f"(small={t_small:.3f}s, large={t_large:.3f}s) -- looks superlinear")


# ---------------------------------------------------------------------------
# BOM / encoding
# ---------------------------------------------------------------------------

def test_bom_is_ignored():
    assert read_oml("﻿a: 1") == [("a", 1)]


# ---------------------------------------------------------------------------
# Document round-trip: every scalar kind, repeats, interleaving, nesting
# ---------------------------------------------------------------------------

def test_full_document_round_trip_lossless():
    node = [
        ("title", "Conference"),
        ("attendee", "Ann"),
        ("session", [
            ("id", 1),
            ("active", True),
        ]),
        ("attendee", "Bob"),
        ("session", [
            ("id", 2),
            ("active", False),
        ]),
        ("when", datetime.datetime(2024, 1, 1, 9, 30)),
        ("opens", datetime.time(9, 0)),
        ("on", datetime.date(2024, 6, 1)),
        ("price", 29.99),
        ("capacity", 4300 and 250),
        ("notes", None),
    ]
    text = write_oml(node)
    assert read_oml(text) == node
    # OML never needs an adjustment -- check_oml is always empty
    assert list(check_oml(node)) == []


# A fixed source string exercising every token kind the scanner produces:
# STRING (plain, with escapes), STRING via raw ('...') and multiline ("""),
# INTEGER (incl. negative), NUMBER (decimal and exponent forms, incl. -inf/
# nan/inf), DATE, TIME, DATETIME, IDENT (true/false/null and a bare label),
# nested braces, comments, and semicolon separators.  This is the "golden"
# regression fixture for the B1 tokenizer rewrite (issue #155): the exact
# parsed value is pinned so a scanner change that shifts even one token
# boundary (e.g. an off-by-one in the ``pos=`` conversion) is caught.
_GOLDEN_OML = r'''# a comment before anything else
plain: "hello \"world\"\n"; raw: 'C:\no\escapes'
multi: """
line one
line two"""
neg-int: -42; big-int: 4300
dec: -3.14; exp: 6.02e23; special: nan; pos-inf: inf; neg-inf: -inf
d: 2024-06-01
t: 09:30:00
dt: 2024-06-01T09:30:00
flags: { on: true; off: false; nothing: null }
nested: { a: { b: { c: "deep" } } }
'''

_GOLDEN_NODE = [
    ("plain", 'hello "world"\n'),
    ("raw", r"C:\no\escapes"),
    ("multi", "line one\nline two"),
    ("neg-int", -42),
    ("big-int", 4300),
    ("dec", -3.14),
    ("exp", 6.02e23),
    ("special", float("nan")),
    ("pos-inf", float("inf")),
    ("neg-inf", float("-inf")),
    ("d", datetime.date(2024, 6, 1)),
    ("t", datetime.time(9, 30, 0)),
    ("dt", datetime.datetime(2024, 6, 1, 9, 30, 0)),
    ("flags", [("on", True), ("off", False), ("nothing", None)]),
    ("nested", [("a", [("b", [("c", "deep")])])]),
]


def test_golden_mixed_token_round_trip():
    """Byte-identical (modulo NaN) golden fixture covering every token kind --
    the safety net for the B1 O(n^2) tokenizer fix (issue #155)."""
    node = read_oml(_GOLDEN_OML)
    # NaN != NaN, so compare piecewise: everything but the "special" edge
    # compares equal, and "special" is checked separately for nan-ness.
    for (lbl, val), (glbl, gval) in zip(node, _GOLDEN_NODE):
        assert lbl == glbl
        if lbl == "special":
            assert isinstance(val, float) and val != val  # nan
        else:
            assert val == gval
    # Canonical writer output is stable and re-parses to the exact same node.
    rewritten = write_oml(node)
    reparsed = read_oml(rewritten)
    for (lbl, val), (glbl, gval) in zip(reparsed, node):
        assert lbl == glbl
        if lbl == "special":
            assert isinstance(val, float) and val != val
        else:
            assert val == gval


def test_doc_to_oml_and_from_oml_methods():
    d = doc({"name": "Ann", "tags": ["x", "y"]})
    text = d.to_oml()
    d2 = Doc.from_oml(text)
    assert d2.to_grouped() == d.to_grouped()


# ---------------------------------------------------------------------------
# Schema-directed read
# ---------------------------------------------------------------------------

def test_schema_directed_deserialization():
    s = parse_schema('record R { "d": date, "n": number }\nroot R')
    node = read_oml('d: "2024-01-01"\nn: 3', schema=s)
    assert node == [("d", datetime.date(2024, 1, 1)), ("n", 3.0)]


def test_validate_against_schema_after_read():
    s = parse_schema(
        'record Member { "name": string, "role": string }\n'
        'record Team { "name": string, "members" [1,]: Member }\nroot Team')
    d = Doc.from_oml(
        'name: "Platform"\n'
        'members: {\n'
        '  name: "Ann"\n'
        '  role: "dev"\n'
        '}\n'
    )
    assert s.validate(d).ok


# ---------------------------------------------------------------------------
# Full real-life document (matches the design doc's worked example)
# ---------------------------------------------------------------------------

REAL_LIFE_OML = r'''
venue: {
    name: "Strange Loop"
    building: {
        address: {
            street: "123 Main St"
            city: "St. Louis"
            country: "US"
        }
        room: "Ballroom A"
    }
}
session: {
    title: "Schema Compatibility, Revisited"
    speaker: {
        name: "Ada Lovelace"
        bio: """
Works on data models and provenance.
Quote: "Hopper said it best".
Path: C:\\talks\\ada\\slides.key
"""
    }
    note: "Recording starts five minutes late."
    note: 'Slides posted after the talk -- path on the laptop: C:\talks\ada\slides.key'
    start: 2024-09-18T14:00:00
    duration: 50
    tags: "schemas"
    tags: "compatibility"
}
attendee_count: 312
virtual: false
'''


def test_real_life_document_round_trips():
    node = read_oml(REAL_LIFE_OML)
    d = Doc(node)
    assert d.get_one("venue").get_one("name").value == "Strange Loop"
    address = d.get_one("venue").get_one("building").get_one("address")
    assert address.get_one("city").value == "St. Louis"
    session = d.get_one("session")
    assert [t.value for t in session.get("tags")] == ["schemas", "compatibility"]
    assert [n.value for n in session.get("note")] == [
        "Recording starts five minutes late.",
        "Slides posted after the talk -- path on the laptop: C:\\talks\\ada\\slides.key",
    ]
    bio = session.get_one("speaker").get_one("bio").value
    assert bio.startswith("Works on data models")
    assert 'Quote: "Hopper said it best".' in bio
    assert session.get_one("start").value == datetime.datetime(2024, 9, 18, 14, 0, 0)

    text = write_oml(node)
    assert read_oml(text) == node


def test_real_life_document_validates_against_a_schema():
    s = parse_schema('''
        record Address { "street": string, "city": string, "country": string }
        record Building { "address": Address, "room": string }
        record Venue { "name": string, "building": Building }
        record Speaker { "name": string, "bio": string }
        record Session {
            "title": string,
            "speaker": Speaker,
            "note" [0,]: string,
            "start": datetime,
            "duration": integer,
            "tags" [0,]: string,
        }
        record Root {
            "venue": Venue,
            "session": Session,
            "attendee_count": integer,
            "virtual": boolean,
        }
        root Root
    ''')
    d = Doc.from_oml(REAL_LIFE_OML)
    result = s.validate(d)
    assert result.ok, result.errors


# ---------------------------------------------------------------------------
# write_oml edge cases
# ---------------------------------------------------------------------------

def test_write_oml_bare_scalar_document():
    assert write_oml(42) == "42"


def test_write_oml_empty_nested_node():
    assert write_oml([("a", [])]) == "a: {}"


def test_write_oml_label_needing_quotes():
    # a label that isn't a bare-identifier shape gets written as a quoted
    # string label instead.
    assert write_oml([("a b", 1)]) == '"a b": 1'


def test_write_oml_label_with_trailing_newline_is_quoted():
    # regression for #170: $ in the bare-label regex also matched just
    # before a trailing "\n", so "A\n" was written as a bare label and the
    # output failed to parse back. A label ending in a newline must be
    # quoted (with the newline escaped) and round-trip exactly.
    written = write_oml([("A\n", 1)])
    assert written == '"A\\n": 1'
    assert read_oml(written) == [("A\n", 1)]


def test_write_oml_nan():
    assert write_oml([("a", float("nan"))]) == "a: nan"


def test_write_oml_rejects_unsupported_scalar_type():
    with pytest.raises(TypeError, match="has no OML scalar form"):
        write_oml([("a", object())])


def test_write_oml_escapes_cr_tab_and_other_control_chars():
    text = write_oml([("a", "x\ry\tz\x01")])
    assert text == 'a: "x\\ry\\tz\\u0001"'


# ---------------------------------------------------------------------------
# write_oml(indent=None) -- compact, single-line output
# ---------------------------------------------------------------------------

def test_write_oml_compact_exact_string():
    node = [
        ("name", "Platform"),
        ("members", [("name", "Ann"), ("role", "dev")]),
        ("members", [("name", "Bob"), ("role", "pm")]),
    ]
    assert write_oml(node, indent=None) == (
        'name: "Platform"; members: { name: "Ann"; role: "dev" }; '
        'members: { name: "Bob"; role: "pm" }')


def test_write_oml_compact_empty_nested_node():
    assert write_oml([("a", [])], indent=None) == "a: {}"


def test_write_oml_compact_bare_scalar_document():
    assert write_oml(42, indent=None) == "42"


@pytest.mark.parametrize("node", [
    [("title", "Conference"),
     ("attendee", "Ann"),
     ("session", [("id", 1), ("active", True)]),
     ("attendee", "Bob"),
     ("session", [("id", 2), ("active", False)]),
     ("when", datetime.datetime(2024, 1, 1, 9, 30)),
     ("price", 29.99),
     ("notes", None)],
    [("a", [("b", [("c", 1)])])],
    [("tag", "x"), ("tag", "y")],
])
def test_write_oml_compact_round_trips(node):
    assert read_oml(write_oml(node, indent=None)) == node


# ---------------------------------------------------------------------------
# [...] array syntax (#218) -- pure syntactic sugar for repeated same-label
# edges, expanded at parse time. No array type in the Document model.
# ---------------------------------------------------------------------------

def test_array_worked_example_from_issue():
    src = (
        'a: "x"\n'
        "b: [1, 2, 3]\n"
        "c: true\n"
        "b: [4, 5, 6]\n"
    )
    assert read_oml(src) == [
        ("a", "x"),
        ("b", 1), ("b", 2), ("b", 3),
        ("c", True),
        ("b", 4), ("b", 5), ("b", 6),
    ]


def test_array_expands_to_repeated_edges_minimal():
    assert read_oml("b: [1, 2, 3]") == [("b", 1), ("b", 2), ("b", 3)]


def test_array_of_brace_subtrees():
    src = 'members: [{name: "Ann"}, {name: "Bob"}]'
    assert read_oml(src) == [
        ("members", [("name", "Ann")]),
        ("members", [("name", "Bob")]),
    ]


def test_array_nested_array_is_a_parse_error():
    with pytest.raises(ParseError, match="(?i)nested array"):
        read_oml("b: [[1,2]]")


def test_array_empty_is_a_parse_error():
    with pytest.raises(ParseError, match="(?i)empty array"):
        read_oml("b: []")


def test_array_trailing_comma_is_legal():
    assert read_oml("b: [1, 2, 3,]") == [("b", 1), ("b", 2), ("b", 3)]


def test_array_newlines_inside_brackets_are_legal_and_insignificant():
    src = "b: [\n  1,\n  2,\n  3\n]"
    assert read_oml(src) == [("b", 1), ("b", 2), ("b", 3)]


def test_array_bare_newline_as_separator_is_illegal():
    with pytest.raises(ParseError):
        read_oml("b: [1\n2]")


def test_array_semicolon_as_separator_is_illegal():
    with pytest.raises(ParseError):
        read_oml("b: [1; 2]")


def test_array_comments_inside_brackets_are_legal():
    src = "b: [\n  1, # one\n  2, # two\n]"
    assert read_oml(src) == [("b", 1), ("b", 2)]


def test_array_in_label_position_is_a_parse_error():
    with pytest.raises(ParseError):
        read_oml("[1, 2]: 3")


def test_bare_array_at_top_level_is_a_parse_error():
    with pytest.raises(ParseError):
        read_oml("[1, 2, 3]")


def test_array_with_null_elements():
    assert read_oml("b: [1, null, 3]") == [("b", 1), ("b", None), ("b", 3)]


# ---------------------------------------------------------------------------
# write_oml(arrays=...) -- writer support
# ---------------------------------------------------------------------------

_GOLDEN_NODES_FOR_NO_REGRESSION = [
    [("a", "x"), ("b", 1), ("c", True)],
    [("tag", "x"), ("tag", "y")],
    [("a", [("b", [("c", 1)])])],
    [("title", "Conference"),
     ("attendee", "Ann"),
     ("session", [("id", 1), ("active", True)]),
     ("attendee", "Bob"),
     ("session", [("id", 2), ("active", False)]),
     ("when", datetime.datetime(2024, 1, 1, 9, 30)),
     ("price", 29.99),
     ("notes", None)],
    [("b", 1), ("b", 2), ("c", True), ("b", 3)],
    [],
]


@pytest.mark.parametrize("node", _GOLDEN_NODES_FOR_NO_REGRESSION)
def test_write_oml_arrays_false_is_byte_identical_to_default(node):
    # arrays=False (the default) must never change existing output -- this
    # is the no-regression proof for issue #218.
    assert write_oml(node, arrays=False) == write_oml(node)
    assert write_oml(node, arrays=False, indent=None) == write_oml(node, indent=None)


def test_write_oml_arrays_true_collapses_runs_pretty():
    node = [("a", "x"), ("b", 1), ("b", 2), ("b", 3), ("c", True)]
    text = write_oml(node, arrays=True)
    assert text == 'a: "x"\nb: [1, 2, 3]\nc: true'


def test_write_oml_arrays_true_collapses_runs_compact():
    node = [("a", "x"), ("b", 1), ("b", 2), ("b", 3), ("c", True)]
    text = write_oml(node, arrays=True, indent=None)
    assert text == 'a: "x"; b: [1, 2, 3]; c: true'


def test_write_oml_arrays_true_run_of_one_stays_scalar():
    node = [("b", 1), ("c", True)]
    assert write_oml(node, arrays=True) == "b: 1\nc: true"


def test_write_oml_arrays_true_never_merges_across_a_different_label():
    # [('b',1),('b',2),('c',True),('b',3)] -- the two b-runs are NOT
    # adjacent (interrupted by c), so they must stay two separate outputs:
    # b: [1, 2], c: true, b: 3 -- never merged into one array.
    node = [("b", 1), ("b", 2), ("c", True), ("b", 3)]
    text = write_oml(node, arrays=True)
    assert text == "b: [1, 2]\nc: true\nb: 3"
    assert read_oml(text) == node


def test_write_oml_arrays_true_of_brace_subtrees():
    node = [("members", [("name", "Ann")]), ("members", [("name", "Bob")])]
    text = write_oml(node, arrays=True)
    assert text == 'members: [{ name: "Ann" }, { name: "Bob" }]'
    assert read_oml(text) == node


def test_write_oml_arrays_true_of_empty_record_element():
    # An empty record inside a multi-element array run renders as the
    # bare brace pair "{}" (issue #239 -- previously untested branch).
    node = [("members", []), ("members", [("name", "Ann")])]
    text = write_oml(node, arrays=True)
    assert text == 'members: [{}, { name: "Ann" }]'
    assert read_oml(text) == node


def test_write_oml_arrays_true_no_wrap_regardless_of_length():
    # Pretty mode: arrays are always single-line, no line-wrapping, no
    # matter how long the run is (explicit design decision, #218).
    node = [("b", i) for i in range(20)]
    text = write_oml(node, arrays=True)
    assert "\n" not in text
    assert text.startswith("b: [") and text.endswith("]")
    assert read_oml(text) == node


@pytest.mark.parametrize("node", _GOLDEN_NODES_FOR_NO_REGRESSION + [
    [("b", 1), ("b", 2), ("c", True), ("b", 3)],
    [("members", [("name", "Ann")]), ("members", [("name", "Bob")])],
    [("members", []), ("members", [("name", "Ann")])],
])
def test_write_oml_arrays_true_round_trips_pretty_and_compact(node):
    assert read_oml(write_oml(node, arrays=True)) == node
    assert read_oml(write_oml(node, arrays=True, indent=None)) == node


# ---------------------------------------------------------------------------
# Hypothesis: array form == repeated-label form (reader equivalence), and
# read_oml(write_oml(node, arrays=True)) == node for arbitrary nodes
# (writer never-reorders property).
# ---------------------------------------------------------------------------

from hypothesis import given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

_array_scalar = st.one_of(
    st.integers(min_value=-1_000_000, max_value=1_000_000),
    st.booleans(),
    st.text(alphabet=st.characters(blacklist_categories=("Cs",), blacklist_characters='"\\'),
             max_size=10),
    st.none(),
)


@given(label=st.from_regex(r"[A-Za-z_][A-Za-z0-9_]{0,8}", fullmatch=True),
       values=st.lists(_array_scalar, min_size=1, max_size=6))
@settings(max_examples=100)
def test_array_equivalence_property(label, values):
    array_src = f"{label}: [" + ", ".join(_write_test_scalar(v) for v in values) + "]"
    repeated_src = "\n".join(f"{label}: {_write_test_scalar(v)}" for v in values)
    assert read_oml(array_src) == read_oml(repeated_src)


def _write_test_scalar(v):
    return write_oml([("x", v)]).split(": ", 1)[1]


@given(node=st.recursive(
    st.lists(
        st.tuples(
            st.from_regex(r"[A-Za-z_][A-Za-z0-9_]{0,6}", fullmatch=True),
            _array_scalar,
        ),
        min_size=0, max_size=6,
    ),
    lambda children: st.lists(
        st.tuples(
            st.from_regex(r"[A-Za-z_][A-Za-z0-9_]{0,6}", fullmatch=True),
            children,
        ),
        min_size=0, max_size=6,
    ),
    max_leaves=8,
))
@settings(max_examples=100)
def test_write_oml_arrays_true_round_trip_property(node):
    assert read_oml(write_oml(node, arrays=True)) == node
    assert read_oml(write_oml(node, arrays=True, indent=None)) == node
