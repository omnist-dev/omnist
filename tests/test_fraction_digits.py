"""A TOML or YAML fraction past six digits fails instead of truncating (#366).

The Document holds microseconds at most; PyYAML and ``tomllib`` cut a longer
fraction silently, which altered the value. A non-zero digit past the sixth is
``parse.codec-syntax``; zeros past it are dropped; offsets are kept."""
from __future__ import annotations

import datetime as dt

import pytest

from omnist import ParseError, WriteReport, doc, read_json, read_oml, read_toml, read_xml, read_yaml
from omnist.formats import fraction_inexact

UTC = dt.timezone.utc
PLUS1 = dt.timezone(dt.timedelta(hours=1))


class TestFractionInexact:
    @pytest.mark.parametrize("text, expected", [
        ("12:00:00", False), ("12:00:00.1", False), ("12:00:00.123456", False),
        ("12:00:00.1234560", False), ("12:00:00.123456000000", False),
        ("12:00:00.1234567", True), ("12:00:00.000000001", True),
        ("12:00:00.0000009Z", True), ("12:00:00.123456+01:00", False),
        ("12:00:00.1234560+01:00", False),
    ])
    def test_cases(self, text, expected):
        assert fraction_inexact(text) is expected


class TestToml:
    @pytest.mark.parametrize("src, col", [
        ("a = 00:32:00.9999999\n", "1:5"),
        ("a = 2024-01-15T12:00:00.1234567Z\n", "1:5"),
        ("a = 2024-01-15T12:00:00.000000001+01:00\n", "1:5"),
        ("a = 2024-01-15 12:00:00.0000001\n", "1:5"),
        ("x = 1\nb = [1, 00:00:00.0000001]\n", "2:9"),
        ("t = { a = 00:00:00.0000001 }\n", "1:11"),
        ("[s]\n# c\nk = 'q'\nw = 00:00:00.1234567\n", "4:5"),
    ])
    def test_non_zero_seventh_digit_fails(self, src, col):
        with pytest.raises(ParseError) as ei:
            read_toml(src)
        assert ei.value.code == "parse.codec-syntax"
        assert ei.value.path == col

    def test_zeros_past_the_sixth_are_dropped(self):
        d = read_toml("a = 00:32:00.1234560\nb = 2024-01-15T12:00:00.123456000+01:00\n")
        assert [v for _, v in d] == [dt.time(0, 32, 0, 123456),
                                     dt.datetime(2024, 1, 15, 12, 0, 0, 123456, tzinfo=PLUS1)]

    def test_offset_is_never_converted(self):
        d = read_toml("a = 2024-01-15T12:00:00.123456+01:00\n")
        assert d[0][1] == dt.datetime(2024, 1, 15, 12, 0, 0, 123456, tzinfo=PLUS1)

    def test_strings_comments_and_keys_with_long_fractions_are_untouched(self):
        src = ('a = "00:00:00.1234567"\nb = \'00:00:00.1234567\'\n'
               'c = """\n00:00:00.1234567\n"""\n# d = 00:00:00.1234567\n'
               'e = [ "x", 1.12345678 ]\nf = 5 # 00:00:00.1234567\n')
        d = read_toml(src)
        assert [v for _, v in d][:2] == ["00:00:00.1234567"] * 2

    def test_float_and_plain_seven_digits_are_not_temporals(self):
        assert read_toml("a = 3.1234567\n")[0][1] == 3.1234567


class TestYaml:
    @pytest.mark.parametrize("src, col", [
        ("a: 2024-01-15T12:00:00.1234567Z\n", "1:4"),
        ("a: 2024-01-15 12:00:00.000000001 +01:00\n", "1:4"),
        ("a: 2024-01-15T12:00:00.1234567+01:00\n", "1:4"),
        ("x: 1\nb: [1, 2024-01-15T00:00:00.0000001Z]\n", "2:8"),
    ])
    def test_non_zero_seventh_digit_fails(self, src, col):
        with pytest.raises(ParseError) as ei:
            read_yaml(src)
        assert ei.value.code == "parse.codec-syntax"
        assert ei.value.path == col

    def test_zeros_past_the_sixth_are_dropped_and_offset_kept(self):
        d = read_yaml("a: 2024-01-15T12:00:00.1234560+01:00\n")
        assert d[0][1] == dt.datetime(2024, 1, 15, 12, 0, 0, 123456, tzinfo=PLUS1)

    def test_quoted_and_tagged_strings_are_untouched(self):
        d = read_yaml('a: "2024-01-15T12:00:00.1234567Z"\nb: !!str 2024-01-15T12:00:00.1234567Z\n')
        assert [v for _, v in d] == ["2024-01-15T12:00:00.1234567Z"] * 2

    def test_date_has_no_fraction(self):
        assert read_yaml("a: 2024-01-15\n")[0][1] == dt.date(2024, 1, 15)


class TestOtherReaders:
    def test_json_and_xml_keep_the_text_verbatim(self):
        text = "2024-01-15T12:00:00.1234567Z"
        assert read_json('{"a": "%s"}' % text)[0][1] == text
        assert read_xml("<r><a>%s</a></r>" % text)[0][1][0][1] == text

    @pytest.mark.parametrize("lit", ["12:00:00.1234567", "2024-01-15T12:00:00.1234567Z"])
    def test_oml_refuses_a_seventh_digit(self, lit):
        with pytest.raises(ParseError):
            read_oml("a: %s\n" % lit)

    def test_oml_six_digits_are_kept(self):
        assert read_oml("a: 12:00:00.123456\n")[0][1] == dt.time(12, 0, 0, 123456)


class TestWritersNeverEmitWhatTheirReaderRefuses:
    """A Python ``time``/``datetime`` holds microseconds, so the writers cannot be
    handed a longer fraction; the widest one must round-trip, with no warning."""

    VALUES = [dt.time(12, 0, 0, 999999), dt.datetime(2024, 1, 15, 12, 0, 0, 999999),
              dt.datetime(2024, 1, 15, 12, 0, 0, 999999, tzinfo=PLUS1),
              dt.datetime(2024, 1, 15, 12, 0, 0, 1, tzinfo=UTC)]

    @pytest.mark.parametrize("value", VALUES)
    @pytest.mark.parametrize("fmt", ["oml", "yaml", "toml"])
    def test_round_trip(self, value, fmt):
        d = doc({"t": value})
        rep = WriteReport()
        text = getattr(d, "to_" + fmt)(report=rep) if fmt != "oml" else d.to_oml()
        back = {"oml": read_oml, "yaml": read_yaml, "toml": read_toml}[fmt](text)
        # YAML 1.1 has no time-of-day type: a bare time reads back as its text
        expected = value.isoformat() if fmt == "yaml" and type(value) is dt.time else value
        assert back[0][1] == expected
        if expected is value:
            assert not [a for a in rep if a.code == "format.temporal-stringified"]
        if fmt != "oml" and expected is value:
            assert not [a for a in getattr(d, "check_" + fmt)()
                        if a.code == "format.temporal-stringified"]
