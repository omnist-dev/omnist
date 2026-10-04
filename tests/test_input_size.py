"""omnist-spec v0.30.0-beta D-23/D-24 (Sec2.4.2): a maximum input size, in BYTES,
checked before decoding and before any parsing; `document.limit.input-size`
at `$`; an input exactly at the maximum is accepted.  This implementation's
default is 64 MiB (`DEFAULT_MAX_INPUT_BYTES`), configurable per call through
`max_input_bytes` (the CLI has no limit flags, so it always uses the default).
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

from omnist import (
    Doc,
    Format,
    ParseError,
    read_json,
    read_oml,
    read_toml,
    read_xml,
    read_yaml,
    register_format,
)
from omnist._encoding import (
    DEFAULT_MAX_INPUT_BYTES,
    check_input_size,
    validate_max_input_bytes,
)
from omnist.cli import main

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tools.conformance.vector_runner as vr  # noqa: E402

READERS = {
    "json": (read_json, '{"a":"%s"}'),
    "yaml": (read_yaml, "a: %s\n"),
    "toml": (read_toml, 'a = "%s"\n'),
    "xml": (read_xml, "<a>%s</a>"),
    "oml": (read_oml, 'a: "%s"'),
}
FROM = {"json": Doc.from_json, "yaml": Doc.from_yaml, "toml": Doc.from_toml,
        "xml": Doc.from_xml, "oml": Doc.from_oml}


def _sized(fmt: str, size: int) -> str:
    template = READERS[fmt][1]
    base = len((template % "").encode())
    return template % ("x" * (size - base))


def _refusal(exc: ParseError) -> tuple:
    return exc.code, exc.path


@pytest.mark.parametrize("fmt", sorted(READERS))
def test_at_the_maximum_is_accepted_and_one_over_is_refused(fmt):
    read = READERS[fmt][0]
    at, over = _sized(fmt, 40), _sized(fmt, 41)
    assert len(at.encode()) == 40 and len(over.encode()) == 41
    read(at, max_input_bytes=40)
    FROM[fmt](at, max_input_bytes=40)
    for fn in (read, FROM[fmt]):
        with pytest.raises(ParseError) as ei:
            fn(over, max_input_bytes=40)
        assert _refusal(ei.value) == ("document.limit.input-size", "$")


@pytest.mark.parametrize("fmt", sorted(READERS))
def test_checked_before_the_input_is_parsed(fmt):
    # the text is malformed as well as too long: the size refusal comes first
    with pytest.raises(ParseError) as ei:
        READERS[fmt][0]("\x00{[" * 20, max_input_bytes=10)
    assert _refusal(ei.value) == ("document.limit.input-size", "$")


@pytest.mark.parametrize("text, size", [
    ("\u00e9" * 10, 20),            # two bytes each: 10 characters, 20 bytes
    ("\ufeff" + "a" * 17, 20),      # a leading mark counts as 3 bytes, before it is stripped
    ("\ud800" * 2 + "ab", 8),       # a lone surrogate counts as 3 (surrogatepass), never crashes
    ("\U0001f600" * 5, 20),         # four bytes each
])
def test_bytes_not_characters(text, size):
    check_input_size(text, size)
    with pytest.raises(ParseError) as ei:
        check_input_size(text, size - 1)
    assert _refusal(ei.value) == ("document.limit.input-size", "$")


def test_bytes_input_is_measured_as_received():
    check_input_size(b"\xff" * 5, 5)               # not UTF-8, but size comes before decoding
    with pytest.raises(ParseError):
        check_input_size(b"\xff" * 6, 5)


def test_json_bom_pair_through_a_reader():
    read_json("\ufeff" + '{"a":"xxxxxxxxx"}', max_input_bytes=20)
    with pytest.raises(ParseError):
        read_json("\ufeff" + '{"a":"xxxxxxxxxx"}', max_input_bytes=20)


@pytest.mark.parametrize("bad", [0, -1, True, "5", 1.5, None])
def test_the_option_is_validated_like_the_other_limits(bad):
    exc = ValueError if isinstance(bad, int) and not isinstance(bad, bool) else TypeError
    with pytest.raises(exc):
        validate_max_input_bytes(bad)
    for fmt in READERS:
        with pytest.raises(exc):
            READERS[fmt][0]("x", max_input_bytes=bad)
    with pytest.raises(exc):
        Doc.from_format("json", "{}", max_input_bytes=bad)


def test_the_default_is_documented_64_mib_and_applies_when_no_option_is_given():
    assert DEFAULT_MAX_INPUT_BYTES == 64 * 1024 * 1024
    big = "a" * (DEFAULT_MAX_INPUT_BYTES + 1)
    for fmt in READERS:
        with pytest.raises(ParseError) as ei:
            READERS[fmt][0](big)
        assert _refusal(ei.value) == ("document.limit.input-size", "$")
    with pytest.raises(ParseError):
        Doc.from_format("oml", big)
    # a few characters that are many bytes: only the exact count can tell
    wide = "\u20ac" * (DEFAULT_MAX_INPUT_BYTES // 3 + 1)
    with pytest.raises(ParseError):
        read_oml(wide)


def test_from_format_checks_a_plugin_reader_that_has_no_such_option():
    register_format(Format("size-plugin", lambda text: [("n", len(text))], lambda n, **k: ""))
    assert Doc.from_format("size-plugin", "abc", max_input_bytes=3).to_data() == [("n", 3)]
    with pytest.raises(ParseError) as ei:
        Doc.from_format("size-plugin", "abcd", max_input_bytes=3)
    assert _refusal(ei.value) == ("document.limit.input-size", "$")


def test_from_format_passes_the_option_to_a_builtin_reader():
    assert Doc.from_format("json", '{"a":1}', max_input_bytes=7).to_data() == [("a", 1)]
    with pytest.raises(ParseError):
        Doc.from_format("json", '{"a":1}', max_input_bytes=6)


# ---------------------------------------------------------------------------
# CLI: the default maximum, applied to Documents (not schemas), stopping early
# ---------------------------------------------------------------------------

class _CountingStream(io.BytesIO):
    def __init__(self, data: bytes) -> None:
        super().__init__(data)
        self.requested: list = []

    def read(self, size=-1):  # type: ignore[override]
        self.requested.append(size)
        return super().read(size)


class _StdinWithBuffer:
    def __init__(self, data: bytes) -> None:
        self.buffer = _CountingStream(data)


@pytest.fixture
def tiny_default(monkeypatch):
    monkeypatch.setattr("omnist.cli.DEFAULT_MAX_INPUT_BYTES", 12)


def _payload(capsys):
    import json
    return json.loads(capsys.readouterr().out)


def test_cli_file_over_the_default_fails_with_the_code(tiny_default, tmp_path, capsys):
    f = tmp_path / "d.oml"
    f.write_bytes(b'a: "xxxxxxxxxxxx"\n')
    assert main(["format", str(f), "--json"]) == 2
    errors = _payload(capsys)["errors"]
    assert [(e["path"], e["code"]) for e in errors] == [("$", "document.limit.input-size")]


def test_cli_file_at_the_default_is_accepted(tiny_default, tmp_path, capsys):
    f = tmp_path / "d.oml"
    f.write_bytes(b'a: "xxxxxxx"')        # exactly 12 bytes
    assert len(f.read_bytes()) == 12
    assert main(["format", str(f), "--json"]) == 0
    capsys.readouterr()


def test_cli_size_precedes_invalid_utf8(tiny_default, tmp_path, capsys):
    f = tmp_path / "d.oml"
    f.write_bytes(b"\xff" * 40)
    assert main(["format", str(f), "--json"]) == 2
    assert _payload(capsys)["errors"][0]["code"] == "document.limit.input-size"


def test_cli_bom_is_counted(tiny_default, tmp_path, capsys):
    f = tmp_path / "d.oml"
    f.write_bytes("\ufeff".encode() + b"a: 1;b: 2")     # 3 + 9 = 12: accepted
    assert main(["format", str(f), "--json"]) == 0
    capsys.readouterr()
    f.write_bytes("\ufeff".encode() + b"a: 1;b: 22")    # 13: refused
    assert main(["format", str(f), "--json"]) == 2
    assert _payload(capsys)["errors"][0]["code"] == "document.limit.input-size"


def test_cli_stdin_stops_reading_once_the_maximum_is_crossed(tiny_default, monkeypatch, capsys):
    stdin = _StdinWithBuffer(b"a: 1\n" * 10_000)
    monkeypatch.setattr("sys.stdin", stdin)
    assert main(["format", "-", "--json"]) == 2
    assert _payload(capsys)["errors"][0]["code"] == "document.limit.input-size"
    assert stdin.buffer.requested == [13]          # maximum + 1, never "everything"
    assert stdin.buffer.tell() == 13


def test_cli_text_only_stdin_is_checked_too(tiny_default, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("a: 1\n" * 100))
    assert main(["format", "-", "--json"]) == 2
    assert _payload(capsys)["errors"][0]["code"] == "document.limit.input-size"
    monkeypatch.setattr("sys.stdin", io.StringIO("a: 1\n"))
    assert main(["format", "-"]) == 0
    capsys.readouterr()


@pytest.mark.parametrize("argv", [
    ["convert", "{f}", "--from", "oml", "--to", "json"],
    ["check", "{f}", "--from", "oml", "--to", "json"],
])
def test_cli_every_document_read_is_bounded(tiny_default, tmp_path, capsys, argv):
    f = tmp_path / "d.oml"
    f.write_bytes(b'a: "xxxxxxxxxxxxxxxxxxxx"')
    assert main([a.replace("{f}", str(f)) for a in argv] + ["--json"]) == 2
    assert _payload(capsys)["errors"][0]["code"] == "document.limit.input-size"


def test_cli_a_schema_file_is_not_a_document_and_is_not_bounded(tiny_default, tmp_path, capsys):
    s = tmp_path / "s.osd"
    s.write_text('record R {\n  "aaaaaaaaaaaaaaaaaaaa": string,\n}\nroot R\n')
    assert main(["schema", "format", str(s)]) == 0
    capsys.readouterr()


def test_cli_text_only_stdin_schema_is_not_bounded(tiny_default, monkeypatch, capsys):
    monkeypatch.setattr(
        "sys.stdin", io.StringIO('record R {\n  "aaaaaaaaaaaaaaaaaaaa": string,\n}\nroot R\n'))
    assert main(["schema", "format", "-"]) == 0
    capsys.readouterr()


# ---------------------------------------------------------------------------
# The conformance runner: `declared_max_input_bytes` is understood (E-20a)
# ---------------------------------------------------------------------------

def _size_vector(fmt, text, declared, expect):
    return {"name": "n", "operation": "parse",
            "input": {"format": fmt, "text": text, "declared_max_input_bytes": declared},
            "expect": expect}


REFUSED = {"ok": False, "diagnostics": [{"path": "$", "code": "document.limit.input-size"}]}


def test_runner_runs_input_size_vectors_with_exactly_the_declared_maximum():
    doc = {"edges": [["a", {"scalar": {"kind": "integer", "value": 1}}]]}
    assert vr.skip_reason(_size_vector("oml", "a: 1", 4, REFUSED)) is None
    assert vr.run_vector(_size_vector("oml", "a: 1", 4, {"ok": True, "document": doc})) == (
        "pass", "ok")
    assert vr.run_vector(_size_vector("oml", "a: 1", 3, REFUSED)) == ("pass", "ok")
    # the same input at the declared maximum, expecting a refusal, is a fail
    status, msg = vr.run_vector(_size_vector("oml", "a: 1", 4, REFUSED))
    assert status == "fail" and msg == "expected failure, the read succeeded"
    # and over it, expecting success, is a fail
    status, msg = vr.run_vector(_size_vector("oml", "a: 1", 3, {"ok": True, "document": doc}))
    assert status == "fail" and "expected success" in msg


def test_runner_still_fails_any_other_unknown_declared_key():
    v = _size_vector("oml", "a: 1", 4, REFUSED)
    v["input"]["declared_max_widgets"] = 1
    status, msg = vr.run_vector(v)
    assert status == "fail" and "declared_max_widgets" in msg


def test_runner_refuses_a_bytes_hex_library_limit_vector():
    v = {"name": "n", "operation": "parse",
         "input": {"format": "json", "bytes_hex": "7b7d", "declared_max_input_bytes": 4},
         "expect": {"ok": True}}
    status, msg = vr.run_vector(v)
    assert status == "fail" and "library-limit vector is text" in msg
