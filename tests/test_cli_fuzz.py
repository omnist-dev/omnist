"""Crash-freedom fuzzing of the omnist CLI's own error-surfacing path.

This does NOT re-fuzz the codecs/parsers themselves -- that's already
covered by ``tests/test_fuzz.py`` (round-trip and crash-freedom fuzzing of
``read_*``/``write_*``/``parse_schema`` directly), and the CLI is a thin
wrapper that calls exactly those functions (see ``docs/design/cli-spec.md``
§1: "no new behavior"). What's specific to the CLI layer, and not covered
there, is whether arbitrary/malformed input always comes back as a clean
exit code (0/1/2) with a stderr message, regardless of command or
``--from``/``--to`` combination, never an uncaught traceback escaping
``main()``.
"""
from __future__ import annotations

import io

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from omnist.cli import FMT_CHOICES, main

_SUPPRESS = settings(
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
    max_examples=100,
)

_fmt = st.sampled_from(FMT_CHOICES)
_text = st.text(max_size=200)

# Biased toward characters that actually appear in these formats' own
# syntax -- far more likely to reach deep parser states than pure random
# unicode (same rationale as tests/test_fuzz.py's _syntax_like_text).
_SYNTAX_ALPHABET = st.sampled_from(
    list(' \t\n\r;:{}[]<>"\',#-+.0123456789eEtTzZabcdefghijklmnopqrstuvwxyz_?='))
_syntax_like_text = st.text(alphabet=_SYNTAX_ALPHABET, max_size=200)


def _assert_clean_exit(call, *, text, label):
    # No except SystemExit here: from_fmt/to_fmt are always drawn from the
    # valid FMT_CHOICES set (never an arbitrary string), so argparse itself
    # never rejects them -- verified directly (2000-example run, zero
    # SystemExits). A real usage-error path would need a separate fuzzer
    # that also mutates the format flags themselves, not this one.
    try:
        code = call()
    except Exception as exc:  # pragma: no cover -- a crash-freedom bug, not expected
        raise AssertionError(
            f"{label} raised {type(exc).__name__} instead of a clean exit "
            f"on input {text!r}"
        ) from exc
    assert code in (0, 1, 2)


@_SUPPRESS
@given(text=_text, from_fmt=_fmt, to_fmt=_fmt)
def test_convert_never_crashes_on_arbitrary_input(capsys, monkeypatch, text, from_fmt, to_fmt):
    monkeypatch.setattr("sys.stdin", io.StringIO(text))
    _assert_clean_exit(
        lambda: main(["convert", "-", "--from", from_fmt, "--to", to_fmt]),
        text=text, label="convert")
    capsys.readouterr()


@_SUPPRESS
@given(text=_syntax_like_text, from_fmt=_fmt, to_fmt=_fmt)
def test_convert_never_crashes_on_syntax_like_input(capsys, monkeypatch, text, from_fmt, to_fmt):
    monkeypatch.setattr("sys.stdin", io.StringIO(text))
    _assert_clean_exit(
        lambda: main(["convert", "-", "--from", from_fmt, "--to", to_fmt]),
        text=text, label="convert")
    capsys.readouterr()


@_SUPPRESS
@given(text=_text, from_fmt=_fmt)
def test_validate_never_crashes_on_arbitrary_input(tmp_path, capsys, monkeypatch, text, from_fmt):
    schema_f = tmp_path / "s.osd"
    schema_f.write_text('record R { "a": integer }\nroot R\n')
    monkeypatch.setattr("sys.stdin", io.StringIO(text))
    _assert_clean_exit(
        lambda: main(["validate", "-", "--from", from_fmt, "--schema", str(schema_f)]),
        text=text, label="validate")
    capsys.readouterr()


@_SUPPRESS
@given(text=_text, from_fmt=_fmt, to_fmt=_fmt)
def test_check_never_crashes_on_arbitrary_input(capsys, monkeypatch, text, from_fmt, to_fmt):
    monkeypatch.setattr("sys.stdin", io.StringIO(text))
    _assert_clean_exit(
        lambda: main(["check", "-", "--from", from_fmt, "--to", to_fmt]),
        text=text, label="check")
    capsys.readouterr()


@_SUPPRESS
@given(text=_text, from_fmt=_fmt, to_fmt=_fmt)
def test_convert_strict_never_crashes(capsys, monkeypatch, text, from_fmt, to_fmt):
    monkeypatch.setattr("sys.stdin", io.StringIO(text))
    _assert_clean_exit(
        lambda: main(["convert", "-", "--from", from_fmt, "--to", to_fmt, "--strict"]),
        text=text, label="convert --strict")
    capsys.readouterr()


# ---------------------------------------------------------------------------
# `schema extract` (issue #142) -- arbitrary/malformed OSD text and arbitrary
# --keep label lists must always come back as a clean exit code (0/1/2),
# never an uncaught traceback. SchemaError's new "no valid subschema" path
# isn't exercised by test_fuzz.py's parse_schema-only crash-freedom fuzzing,
# since that never calls extract() afterward.
# ---------------------------------------------------------------------------

_keep_text = st.text(alphabet=st.sampled_from(list('abcXYZ,')), max_size=20)


@_SUPPRESS
@given(text=_text, keep=_keep_text)
def test_schema_extract_never_crashes_on_arbitrary_input(capsys, monkeypatch, text, keep):
    monkeypatch.setattr("sys.stdin", io.StringIO(text))
    _assert_clean_exit(
        lambda: main(["schema", "extract", "-", "--keep", keep]),
        text=text, label="schema extract")
    capsys.readouterr()


@_SUPPRESS
@given(text=_syntax_like_text, keep=_keep_text)
def test_schema_extract_never_crashes_on_syntax_like_input(capsys, monkeypatch, text, keep):
    monkeypatch.setattr("sys.stdin", io.StringIO(text))
    _assert_clean_exit(
        lambda: main(["schema", "extract", "-", "--keep", keep]),
        text=text, label="schema extract")
    capsys.readouterr()


# ---------------------------------------------------------------------------
# ``schema prune`` / ``schema is-empty`` (issue #151) -- same crash-freedom
# contract as every other command: arbitrary/malformed OSD text must always
# come back as a clean exit code, never a traceback.
# ---------------------------------------------------------------------------

@_SUPPRESS
@given(text=_text)
def test_schema_prune_never_crashes_on_arbitrary_input(capsys, monkeypatch, text):
    monkeypatch.setattr("sys.stdin", io.StringIO(text))
    _assert_clean_exit(
        lambda: main(["schema", "prune", "-"]),
        text=text, label="schema prune")
    capsys.readouterr()


@_SUPPRESS
@given(text=_text)
def test_schema_is_empty_never_crashes_on_arbitrary_input(capsys, monkeypatch, text):
    monkeypatch.setattr("sys.stdin", io.StringIO(text))
    _assert_clean_exit(
        lambda: main(["schema", "is-empty", "-"]),
        text=text, label="schema is-empty")
    capsys.readouterr()
