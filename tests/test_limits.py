"""Omnist-spec v0.34.0-beta: the safety limits of Sec2.4 are configurable per
call (``max_depth``, ``max_nodes``, ``max_int_digits`` on every reader), an
integer-digit refusal carries the Document path of the literal (E-4a, DIV-29),
D-28 counts the digits of the value, D-29 reads an overflow literal as an
infinity, and the XML pretyping of an over-limit integer is a coded refusal."""
from __future__ import annotations

import math
import sys

import pytest

from omnist import (
    Doc,
    DocumentError,
    Format,
    ParseError,
    parse_schema,
    read_json,
    read_oml,
    read_toml,
    read_xml,
    read_yaml,
    register_format,
)
from omnist._limits import DEFAULT_LIMITS, make_limits
from omnist.document import find_over_limit
from omnist.formats import _toml_mark_over_limit, _toml_string_end

READERS = {"json": read_json, "yaml": read_yaml, "toml": read_toml,
           "xml": read_xml, "oml": read_oml}
DIGIT_CODE = "document.limit.int-digits"


def _failure(fn, *args, **kwargs):
    with pytest.raises((ParseError, DocumentError)) as info:
        fn(*args, **kwargs)
    return info.value.code, info.value.path


class TestMakeLimits:
    def test_defaults(self):
        limits = make_limits()
        assert limits == DEFAULT_LIMITS
        assert (limits.max_depth, limits.max_nodes, limits.max_int_digits) == (200, 1_000_000, 4300)
        assert limits.magnitude == 10 ** 4300

    def test_values_are_kept(self):
        limits = make_limits(3, 7, 9)
        assert (limits.max_depth, limits.max_nodes, limits.max_int_digits) == (3, 7, 9)

    @pytest.mark.parametrize("name, ceiling", [
        ("max_depth", 200), ("max_nodes", 10_000_000), ("max_int_digits", 4300)])
    def test_bounds(self, name, ceiling):
        make_limits(**{name: 1})
        make_limits(**{name: ceiling})
        for bad in (0, -1, ceiling + 1):
            with pytest.raises(ValueError, match=name):
                make_limits(**{name: bad})
        for bad in (True, 1.5, "3", None):
            with pytest.raises(TypeError, match=name):
                make_limits(**{name: bad})

    @pytest.mark.parametrize("fmt", sorted(READERS))
    @pytest.mark.parametrize("option", ["max_depth", "max_nodes", "max_int_digits"])
    def test_every_reader_validates_its_options(self, fmt, option):
        with pytest.raises(ValueError, match=option):
            READERS[fmt]("a: 1", **{option: 0})
        with pytest.raises(TypeError, match=option):
            READERS[fmt]("a: 1", **{option: "3"})


# one document per format holding a leaf at depth 3 (root, a, b, then c)
AT_DEPTH = {"json": '{"a": {"b": {"c": 1}}}', "yaml": "a:\n  b:\n    c: 1\n",
            "toml": "[a.b]\nc = 1\n", "xml": "<a><b><c>x</c></b></a>",
            "oml": "a: { b: { c: 1 } }"}
PAST_DEPTH = {"json": '{"a": {"b": {"c": {"d": 1}}}}', "yaml": "a:\n  b:\n    c:\n      d: 1\n",
              "toml": "[a.b.c]\nd = 1\n", "xml": "<a><b><c><d>x</d></c></b></a>",
              "oml": "a: { b: { c: { d: 1 } } }"}


@pytest.mark.parametrize("fmt", sorted(READERS))
class TestConfigurableLimits:
    def test_depth(self, fmt):
        READERS[fmt](AT_DEPTH[fmt], max_depth=3)
        assert _failure(READERS[fmt], PAST_DEPTH[fmt], max_depth=3) == ("document.limit.depth", "$")
        READERS[fmt](PAST_DEPTH[fmt])          # the default 200 is untouched

    def test_nodes(self, fmt):
        flat = {"json": '{"a": 1, "b": 2}', "yaml": "a: 1\nb: 2\n", "toml": "a = 1\nb = 2\n",
                "xml": "<a>1</a>", "oml": "a: 1\nb: 2\n"}[fmt]
        nested = {"json": '{"a": {"b": 1}}', "yaml": "a:\n  b: 1\n", "toml": "[a]\nb = 1\n",
                  "xml": "<r><a>1</a></r>", "oml": "a: { b: 1 }"}[fmt]
        READERS[fmt](flat, max_nodes=1)
        assert _failure(READERS[fmt], nested, max_nodes=1) == ("document.limit.nodes", "$")

    def test_int_digits(self, fmt):
        if fmt == "xml":
            pytest.skip("an XML leaf is text: the digit limit applies to a pretyped integer")
        at = {"json": '{"a": 999}', "yaml": "a: 999\n", "toml": "a = 999\n", "oml": "a: 999"}[fmt]
        past = {"json": '{"a": 1000}', "yaml": "a: 1000\n", "toml": "a = 1000\n",
                "oml": "a: 1000"}[fmt]
        READERS[fmt](at, max_int_digits=3)
        assert _failure(READERS[fmt], past, max_int_digits=3) == (DIGIT_CODE, "$.a")
        READERS[fmt](past)                      # the default 4300 is untouched

    def test_doc_from_format_passes_the_options(self, fmt):
        assert Doc.from_format(fmt, AT_DEPTH[fmt], max_depth=3) == Doc.from_format(
            fmt, AT_DEPTH[fmt])
        with pytest.raises((ParseError, DocumentError)) as info:
            Doc.from_format(fmt, PAST_DEPTH[fmt], max_depth=3)
        assert info.value.code == "document.limit.depth"


class TestDocConstructors:
    def test_each_from_method_passes_the_options(self):
        for method, fmt in (("from_json", "json"), ("from_yaml", "yaml"), ("from_toml", "toml"),
                            ("from_xml", "xml"), ("from_oml", "oml")):
            constructor = getattr(Doc, method)
            constructor(AT_DEPTH[fmt], max_depth=3)
            with pytest.raises((ParseError, DocumentError)) as info:
                constructor(PAST_DEPTH[fmt], max_depth=3, max_nodes=1000, max_int_digits=100)
            assert info.value.code == "document.limit.depth"

    def test_a_plugin_reader_without_the_options_is_refused_not_ignored(self):
        register_format(Format("limits-plugin", lambda text: [("n", len(text))],
                               lambda node, **_: ""))
        assert Doc.from_format("limits-plugin", "abc").to_data() == [("n", 3)]
        with pytest.raises(TypeError):
            Doc.from_format("limits-plugin", "abc", max_depth=3)


class TestIntDigitsAtTheLiteralsPath:
    """E-4a (DIV-29): the Document path of the literal, not ``$``, for every
    format, including a literal past CPython's own int-string guard."""

    BIG = "9" * 5000

    @pytest.mark.parametrize("fmt, text, path", [
        ("json", '{"a": %s}', "$.a"),
        ("json", '{"o": {"a": [1, %s]}}', "$.o.a[1]"),
        ("json", '{"a": -%s}', "$.a"),
        ("yaml", "a: %s\n", "$.a"),
        ("yaml", "o:\n  a:\n    - 1\n    - %s\n", "$.o.a[1]"),
        ("yaml", "a: -%s\n", "$.a"),
        ("yaml", "a: +%s\n", "$.a"),
        ("toml", "a = %s\n", "$.a"),
        ("toml", "[o]\na = [1, %s]\n", "$.o.a[1]"),
        ("toml", "o = {a = %s}\n", "$.o.a"),
        ("toml", "a = -%s\n", "$.a"),
        ("toml", "a = [\n  1,\n  %s,  # trailing\n]\n", "$.a[1]"),
        ("oml", "a: %s", "$.a"),
        ("oml", "o: { a: [1, %s] }", "$.o.a[1]"),
        ("oml", "a: -%s", "$.a"),
        ("oml", "%s", "$"),
    ])
    def test_past_cpythons_own_guard(self, fmt, text, path):
        assert _failure(READERS[fmt], text % self.BIG) == (DIGIT_CODE, path)

    def test_the_first_one_in_document_order_is_reported(self):
        assert _failure(read_json, '{"x": {"y": %s}, "a": %s}' % ((self.BIG,) * 2)) == (
            DIGIT_CODE, "$.x.y")
        assert _failure(read_oml, "x: { y: %s }\na: %s" % ((self.BIG,) * 2)) == (
            DIGIT_CODE, "$.x.y")

    def test_an_oml_literal_message_names_the_position(self):
        with pytest.raises(ParseError, match=r"line 2, col 4: integer literal has 5000 digits"):
            read_oml("a: 1\nb: " + self.BIG)

    def test_the_limit_is_exact(self):
        digits = "9" * 4300
        assert read_json('{"a": %s}' % digits) == [("a", int(digits))]
        assert read_oml("a: " + digits) == [("a", int(digits))]
        assert _failure(read_json, '{"a": %s9}' % digits) == (DIGIT_CODE, "$.a")

    def test_negative_sign_and_leading_plus_are_not_digits(self):
        assert read_json('{"a": -999}', max_int_digits=3) == [("a", -999)]
        assert read_yaml("a: +999\n", max_int_digits=3) == [("a", 999)]
        assert read_toml("a = +999\n", max_int_digits=3) == [("a", 999)]
        assert _failure(read_json, '{"a": -1000}', max_int_digits=3) == (DIGIT_CODE, "$.a")

    def test_a_duplicate_key_hides_a_literal_that_never_enters_the_document(self):
        # C-11: the first value is replaced, so its literal is not in the Document
        assert read_json('{"a": %s, "a": 1}' % self.BIG) == [("a", 1)]


class TestD28DigitsOfTheValue:
    """D-28: the decimal digits of the value, not of the spelling."""

    @pytest.mark.parametrize("fmt, template", [("yaml", "a: %s\n"), ("toml", "a = %s\n")])
    @pytest.mark.parametrize("literal, value", [
        ("0x3E7", 999), ("0o1747", 999), ("0b1111100111", 999), ("9_9_9", 999)])
    def test_three_digit_values_are_accepted(self, fmt, template, literal, value):
        if fmt == "yaml" and literal == "0o1747":
            literal = "01747"           # YAML 1.1 octal has no `o`
        assert READERS[fmt](template % literal, max_int_digits=3) == [("a", value)]

    @pytest.mark.parametrize("fmt, template", [("yaml", "a: %s\n"), ("toml", "a = %s\n")])
    @pytest.mark.parametrize("literal", ["0xFFF", "0o1750", "0b1111101000", "1_000"])
    def test_four_digit_values_are_refused(self, fmt, template, literal):
        if fmt == "yaml" and literal == "0o1750":
            literal = "01750"           # YAML 1.1 octal has no `o`
        assert _failure(READERS[fmt], template % literal, max_int_digits=3) == (DIGIT_CODE, "$.a")

    def test_yaml_leading_zero_octal(self):
        assert read_yaml("a: 01747\n", max_int_digits=3) == [("a", 999)]
        assert _failure(read_yaml, "a: 01750\n", max_int_digits=3) == (DIGIT_CODE, "$.a")

    def test_a_3600_digit_hex_literal_is_over_the_default(self):
        assert _failure(read_yaml, "a: 0x" + "F" * 3600 + "\n") == (DIGIT_CODE, "$.a")
        assert _failure(read_toml, "a = 0x" + "F" * 3600 + "\n") == (DIGIT_CODE, "$.a")

    def test_a_4301_digit_binary_literal_is_within_the_default(self):
        value = int("1" * 4301, 2)
        assert read_yaml("a: 0b" + "1" * 4301 + "\n") == [("a", value)]
        assert read_toml("a = 0b" + "1" * 4301 + "\n") == [("a", value)]

    def test_a_sexagesimal_and_other_non_decimal_spellings(self):
        assert read_yaml("a: 1:30\n", max_int_digits=3) == [("a", 90)]
        assert read_yaml("a: 0\nb: -0\n") == [("a", 0), ("b", 0)]


class TestTomlMarking:
    """``tomllib`` has no integer hook, so a literal past CPython's guard is
    found by a small scanner; whatever it misses falls back to ``$``."""

    def test_comments_and_strings_are_not_literals(self):
        big = "9" * 5000
        text = ('# %s\ns = "%s"\nl = \'%s\'\nm = """\n%s \\" %s"""\nn = \'\'\'%s\'\'\'\n'
                'a = %s\n') % (big, big, big, big, big, big, big)
        assert _failure(read_toml, text) == (DIGIT_CODE, "$.a")

    def test_a_multiline_string_with_quotes_at_its_end(self):
        big = "9" * 5000
        text = 's = """x"""""\na = %s\n' % big       # two quotes of content before the end
        assert _failure(read_toml, text) == (DIGIT_CODE, "$.a")

    def test_an_unterminated_string_does_not_hang_or_crash(self):
        for text in ('a = "x', "a = 'x", 'a = """x', "a = '''x", 'a = "x\\'):
            with pytest.raises(ParseError) as info:
                read_toml(text)
            assert info.value.code == "parse.codec-syntax"
            assert _toml_string_end(text, text.index(text[4])) <= len(text)

    def test_marking_only_decimal_literals_in_a_value_position(self):
        big = "9" * 5000
        assert _toml_mark_over_limit("a = 1\n", 4300) is None
        assert _toml_mark_over_limit("a = 0x%s\n" % ("F" * 5000), 4300) is None
        marked = _toml_mark_over_limit("a = %s\nb = [%s,%s]\n" % (big, big, big), 4300)
        assert marked is not None and marked[1] == "1e-400"
        assert marked[0] == "a = 1e-400\nb = [1e-400,1e-400]\n"
        # a spelling the document already uses is never the marker
        taken = _toml_mark_over_limit("f = 1e-400\na = %s\n" % big, 4300)
        assert taken is not None and taken[1] == "1e-401"

    def test_a_rewrite_that_still_fails_falls_back_to_the_whole_document(self):
        # the second literal follows a string, so the scanner does not take it
        # for a value; the rewritten text is then not TOML, and the reader
        # reports the first problem it actually had: the digit limit, at `$`
        big = "9" * 5000
        assert _failure(read_toml, 'a = %s\nb = "x" %s\n' % (big, big)) == (DIGIT_CODE, "$")

    def test_a_bare_key_of_many_digits_is_not_a_value(self):
        big = "9" * 5000
        assert _toml_mark_over_limit("%s = 1\n" % big, 4300) is None
        assert read_toml("%s = 1\n" % big) == [(big, 1)]

    def test_when_the_scanner_finds_nothing_the_whole_document_is_reported(self):
        # a process that has lowered CPython's own guard below this limit
        limit = sys.get_int_max_str_digits()
        sys.set_int_max_str_digits(640)
        try:
            assert _failure(read_toml, "a = %s\n" % ("9" * 700)) == (DIGIT_CODE, "$")
            assert _failure(read_json, '{"a": %s}' % ("9" * 700)) == (DIGIT_CODE, "$.a")
            assert _failure(read_yaml, "a: %s\n" % ("9" * 700)) == (DIGIT_CODE, "$.a")
            assert _failure(read_oml, "a: %s" % ("9" * 700)) == (DIGIT_CODE, "$.a")
            schema = parse_schema('record R { "a": integer }\nroot R\n')
            assert _failure(read_xml, "<a>%s</a>" % ("9" * 700), schema=schema) == (
                DIGIT_CODE, "$.a")
        finally:
            sys.set_int_max_str_digits(limit)


class TestXmlIntegerPretyping:
    """E-4a / section 7.1: an over-limit integer leaf is a coded refusal at the
    leaf's path, not an uncaught ValueError."""

    SCHEMA = parse_schema(
        'record Item { "n": integer }\n'
        'record Wrap { "item" [0,]: Item }\n'
        'record R { "w": Wrap }\nroot R\n')

    def test_the_leaf_path(self):
        text = "<w><item><n>1000</n></item></w>"
        assert _failure(read_xml, text, schema=self.SCHEMA, max_int_digits=3) == (
            DIGIT_CODE, "$.w.item.n")

    def test_repeated_labels_are_indexed(self):
        text = "<w><item><n>1</n></item><item><n>1000</n></item></w>"
        assert _failure(read_xml, text, schema=self.SCHEMA, max_int_digits=3) == (
            DIGIT_CODE, "$.w.item[1].n")

    def test_past_cpythons_own_guard(self):
        text = "<w><item><n>%s</n></item></w>" % ("9" * 5000)
        assert _failure(read_xml, text, schema=self.SCHEMA) == (DIGIT_CODE, "$.w.item.n")

    def test_at_the_limit_and_negative(self):
        assert read_xml("<w><item><n>-999</n></item></w>", schema=self.SCHEMA,
                        max_int_digits=3) == [("w", [("item", [("n", -999)])])]

    def test_a_field_the_schema_does_not_declare_stays_text(self):
        schema = parse_schema('record R { "w": any }\nroot R\n')
        assert read_xml("<w><n>%s</n></w>" % ("9" * 5000), schema=schema) == [
            ("w", [("n", "9" * 5000)])]

    def test_without_a_schema_a_leaf_is_text(self):
        assert read_xml("<a>%s</a>" % ("9" * 5000)) == [("a", "9" * 5000)]

    def test_doc_from_xml_takes_the_option(self):
        with pytest.raises(DocumentError) as info:
            Doc.from_xml("<w><item><n>1000</n></item></w>", schema=self.SCHEMA, max_int_digits=3)
        assert (info.value.code, info.value.path) == (DIGIT_CODE, "$.w.item.n")


class TestNodeAndDepthCounting:
    def test_an_xml_leaf_element_is_not_a_node(self):
        # E-4a: only the root and an element with child elements are nodes,
        # as in every other format
        text = "<r><a>1</a><b>2</b><c>3</c></r>"
        assert read_xml(text, max_nodes=2)[0][0] == "r"
        assert _failure(read_xml, text, max_nodes=1) == ("document.limit.nodes", "$")

    def test_an_oml_scalar_counts_as_a_level(self):
        # the value of an edge in a node at depth n sits at n + 1, a scalar as
        # much as a brace subtree (D-12: what parses must build)
        assert read_oml("a: { b: 1 }", max_depth=2) == [("a", [("b", 1)])]
        assert _failure(read_oml, "a: { b: 1 }", max_depth=1) == ("document.limit.depth", "$")
        assert read_oml("a: 1", max_depth=1) == [("a", 1)]
        assert read_oml("a: [1, 2]", max_depth=1) == [("a", 1), ("a", 2)]

    def test_what_parses_builds(self):
        for depth in (1, 2, 3, 199, 200):
            text = "a: " + "{a: " * (depth - 1) + "1" + " }" * (depth - 1)
            Doc.from_oml(text, max_depth=depth).to_json()


class TestD29Overflow:
    """D-29: a literal that rounds to infinity is accepted and reads as an
    infinity; underflow reads as ``0.0``."""

    @pytest.mark.parametrize("fmt, text", [
        ("json", '{"a": 1e999}'), ("yaml", "a: 1.0e+999\n"), ("toml", "a = 1e999\n"),
        ("oml", "a: 1e999")])
    def test_positive(self, fmt, text):
        assert READERS[fmt](text) == [("a", math.inf)]

    @pytest.mark.parametrize("fmt, text", [
        ("json", '{"a": -1e999}'), ("yaml", "a: -1.0e+999\n"), ("toml", "a = -1e999\n"),
        ("oml", "a: -1e999")])
    def test_negative(self, fmt, text):
        assert READERS[fmt](text) == [("a", -math.inf)]

    @pytest.mark.parametrize("fmt, text", [
        ("json", '{"a": 1e-999}'), ("toml", "a = 1e-999\n"), ("oml", "a: 1e-999")])
    def test_underflow(self, fmt, text):
        value = READERS[fmt](text)[0][1]
        assert value == 0.0 and not math.copysign(1.0, value) < 0

    def test_nested_and_repeated(self):
        assert read_json('{"o": {"a": [1e400, 2]}}') == [("o", [("a", math.inf), ("a", 2)])]

    def test_an_infinity_is_not_an_integer_digit_count(self):
        assert read_json('{"a": 1e999}', max_int_digits=1) == [("a", math.inf)]

    def test_xml_pretyping_of_a_number_leaf(self):
        schema = parse_schema('record R { "x": number }\nroot R\n')
        assert read_xml("<x>1e999</x>", schema=schema) == [("x", math.inf)]


class TestYamlTimestampIsNotAnIntegerLimit:
    def test_an_impossible_date_is_a_syntax_error(self):
        # PyYAML resolves `2001-13-45` as a timestamp, then it is not a date; it
        # used to be reported as document.limit.int-digits
        assert _failure(read_yaml, "a: 2001-13-45\n") == ("parse.codec-syntax", "1:1")


class TestFindOverLimit:
    def test_paths(self):
        from omnist._limits import OverLimitInt
        marker = OverLimitInt()
        assert find_over_limit(1) is None
        assert find_over_limit(marker) == "$"
        node = [("a", 1), ("b", [("c", 2), ("c", marker)])]
        assert find_over_limit(node) == "$.b.c[1]"
        assert find_over_limit([("a", [("b", 1)])]) is None
