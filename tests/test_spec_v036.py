"""omnist-spec v0.36.0-beta: C-19 (the JSON tokens NaN, Infinity and -Infinity
are parse.codec-syntax), E-33 (a runner compares two NaNs as equal), C-18 and
D-28/D-29 for XML pretyping at scale."""
from __future__ import annotations

import math
import sys
import time
from pathlib import Path

import pytest

from omnist import ParseError, parse_schema, read_json, read_oml, read_toml, read_xml, read_yaml
from omnist.errors import DocumentError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tools.conformance.referee as referee  # noqa: E402


class TestJsonNonFiniteTokens:
    @pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity"])
    @pytest.mark.parametrize("shape", ["{{\"a\": {t}}}", "[{t}]", "{t}"])
    def test_token_is_codec_syntax(self, token, shape):
        # Used to read as a non-finite float (CPython's json accepts the tokens).
        with pytest.raises(ParseError) as exc:
            read_json(shape.format(t=token))
        assert exc.value.code == "parse.codec-syntax"

    def test_overflowing_literal_still_reads_infinity(self):
        assert read_json('{"a": 1e999}') == [("a", math.inf)]
        assert read_json('{"a": -1e999}') == [("a", -math.inf)]

    def test_other_formats_still_spell_them(self):
        assert math.isnan(read_yaml("a: .nan\n")[0][1])
        assert read_yaml("a: -.inf\n")[0][1] == -math.inf
        assert math.isnan(read_toml("a = nan\n")[0][1])
        assert read_toml("a = inf\n")[0][1] == math.inf
        assert math.isnan(read_oml("a: nan\n")[0][1])
        assert read_oml("a: -inf\n")[0][1] == -math.inf


class TestRunnerNanEquality:
    def test_two_nans_are_equal(self):
        assert referee.compare_document("a: nan", "a: nan")

    def test_nan_is_not_a_number_that_is_not_nan(self):
        assert not referee.compare_document("a: nan", "a: 1.0")
        assert not referee.compare_document("a: nan", "a: inf")

    def test_structure_still_compared(self):
        assert referee.compare_document("a: {b: nan; c: 1}", "a: {b: nan; c: 1}")
        assert not referee.compare_document("a: {b: nan; c: 1}", "a: {b: nan; c: 2}")
        assert not referee.compare_document("a: nan\nb: 1", "a: nan")
        assert not referee.compare_document("a: nan", "b: nan")

    def test_library_equality_is_unchanged(self):
        nan = read_oml("a: nan\n")
        assert nan != read_oml("a: nan\n")


_SCHEMA = 'record Inner { "v": %s }\nrecord R { "r": Inner }\nroot R'
_N = 1_000_000


class TestXmlPretypeGrammar:
    @pytest.mark.parametrize("typ", ["integer", "number"])
    @pytest.mark.parametrize("tail", ["x", "."])
    def test_hostile_leaf_is_rejected_in_linear_time(self, typ, tail):
        s = parse_schema(_SCHEMA % typ)
        for sign in ("", "-"):
            body = sign + "9" * _N + tail
            t0 = time.perf_counter()
            with pytest.raises(ParseError):
                read_xml(f"<r><v>{body}</v></r>", schema=s)
            assert time.perf_counter() - t0 < 2.0

    def test_trailing_e_is_rejected(self):
        s = parse_schema(_SCHEMA % "number")
        with pytest.raises(ParseError):
            read_xml(f"<r><v>{'9' * _N}e</v></r>", schema=s)

    @pytest.mark.parametrize("text", ["+5", "007", "0x1F", "1_000", "5.0", "NaN", "INF"])
    def test_non_json_forms_stay_strings_for_integer(self, text):
        with pytest.raises(ParseError):
            read_xml(f"<r><v>{text}</v></r>", schema=parse_schema(_SCHEMA % "integer"))

    def test_number_overflow_reads_infinity(self):
        s = parse_schema(_SCHEMA % "number")
        assert read_xml("<r><v>1e999</v></r>", schema=s)[0][1][0][1] == math.inf
        assert read_xml("<r><v>-1e999</v></r>", schema=s)[0][1][0][1] == -math.inf
        assert read_xml("<r><v>1e-999</v></r>", schema=s)[0][1][0][1] == 0.0
        assert math.copysign(1.0, read_xml("<r><v>-0</v></r>", schema=s)[0][1][0][1]) == -1.0

    def test_long_number_has_no_digit_limit(self):
        s = parse_schema(_SCHEMA % "number")
        assert read_xml(f"<r><v>{'9' * 5000}</v></r>", schema=s)[0][1][0][1] == math.inf

    def test_integer_digit_count_excludes_the_sign(self):
        s = parse_schema(_SCHEMA % "integer")
        assert read_xml(f"<r><v>-{'9' * 4300}</v></r>", schema=s)
        with pytest.raises(DocumentError) as exc:
            read_xml(f"<r><v>-{'9' * 4301}</v></r>", schema=s)
        assert exc.value.code == "document.limit.int-digits"
        assert exc.value.path == "$.r.v"
