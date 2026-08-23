"""Unit tests for tools/conformance/ (issue #283) -- exercises the
ported orchestrator's own logic (referee comparison, cli_runner arg
building, runner/self_test pass/fail/skip branches) against synthetic
tmp_path fixture directories and monkeypatched cli_runner calls, so
this suite runs without the vendor/omnist-spec submodule needing to be
checked out. The submodule's real fixtures are exercised separately by
the dedicated conformance CI job (.github/workflows/conformance.yml),
not by this file.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tools.conformance.cli_runner as cli_runner  # noqa: E402
import tools.conformance.referee as referee  # noqa: E402
import tools.conformance.runner as runner  # noqa: E402
import tools.conformance.self_test as self_test  # noqa: E402

# --------------------------------------------------------------- referee

def test_compare_document_equal():
    assert referee.compare_document("a: 1", "a: 1")


def test_compare_document_not_equal_reordered():
    assert not referee.compare_document("a: 1\nb: 2", "b: 2\na: 1")


def test_compare_schema_exact_equal_reordered_fields():
    a = 'record R { "x": integer, "y": string }\nroot R'
    b = 'record R { "y": string, "x": integer }\nroot R'
    assert referee.compare_schema(a, b, "exact")


def test_compare_schema_exact_not_equal_cardinality():
    a = 'record R { "x": integer }\nroot R'
    b = 'record R { "x": integer? }\nroot R'
    assert not referee.compare_schema(a, b, "exact")


def test_compare_schema_isomorphic_tolerates_renaming():
    a = 'record Root { "x": Foo }\nrecord Foo { "n": integer }\nroot Root'
    b = 'record Root { "x": Bar }\nrecord Bar { "n": integer }\nroot Root'
    assert referee.compare_schema(a, b, "isomorphic")


def test_compare_schema_unknown_mode_raises():
    with pytest.raises(ValueError, match="unknown comparison mode"):
        referee.compare_schema('record R{"x":integer}\nroot R',
                               'record R{"x":integer}\nroot R', "bogus")


# ------------------------------------------------------------ cli_runner

def test_all_cli_runner_functions_build_expected_args(tmp_path, monkeypatch):
    seen = {}

    def fake_run(args, stdin_text=None):
        seen["args"] = args
        seen["stdin"] = stdin_text
        return "", "", 0

    monkeypatch.setattr(cli_runner, "_run", fake_run)

    p = tmp_path / "a.osd"
    q = tmp_path / "b.osd"
    inp = tmp_path / "in.oml"

    cli_runner.write(inp)
    assert seen["args"] == ["format", str(inp)]

    cli_runner.validate(inp, p)
    assert seen["args"] == ["validate", str(inp), "--from", "oml",
                            "--schema", str(p), "--json"]

    cli_runner.materialize(inp, p)
    assert seen["args"] == ["convert", str(inp), "--from", "oml", "--to", "oml",
                            "--schema", str(p), "--json"]

    cli_runner.normalize(p)
    assert seen["args"] == ["schema", "normalize", str(p)]

    cli_runner.prune(p)
    assert seen["args"] == ["schema", "prune", str(p)]

    cli_runner.extract(p, ["a", "b"])
    assert seen["args"] == ["schema", "extract", str(p), "--keep", "a,b"]

    cli_runner.is_empty(p)
    assert seen["args"] == ["schema", "is-empty", str(p), "--result-format", "json"]

    cli_runner.compatible_with(p, q)
    assert seen["args"] == ["schema", "compatible-with", str(p), str(q),
                            "--result-format", "json"]

    cli_runner.equivalent(p, q)
    assert seen["args"] == ["schema", "equivalent", str(p), str(q),
                            "--result-format", "json"]

    cli_runner.infer([p, q])
    assert seen["args"] == ["infer", str(p), str(q), "--from", "oml"]

    cli_runner.infer([p], allow_any=True)
    assert seen["args"] == ["infer", str(p), "--from", "oml", "--allow-any"]

    cli_runner.lint(p)
    assert seen["args"] == ["schema", "lint", str(p), "--json"]


def test_run_helper_invokes_subprocess(monkeypatch):
    captured = {}

    class FakeProc:
        stdout = "out"
        stderr = "err"
        returncode = 3

    def fake_subprocess_run(argv, input=None, capture_output=None,  # noqa: A002
                            text=None, encoding=None):
        captured["argv"] = argv
        captured["input"] = input
        return FakeProc()

    monkeypatch.setattr(cli_runner.subprocess, "run", fake_subprocess_run)
    out, err, code = cli_runner._run(["format", "x.oml"], stdin_text="a: 1")
    assert (out, err, code) == ("out", "err", 3)
    assert captured["argv"][0] == cli_runner.CLI
    assert captured["input"] == "a: 1"


# ----------------------------------------------------------------- runner

def _mk_case(base: Path, name: str) -> Path:
    d = base / name
    d.mkdir(parents=True)
    return d


def test_run_write_pass(tmp_path, monkeypatch):
    case = _mk_case(tmp_path, "c1")
    (case / "input.oml").write_text("a: 1\n")
    (case / "expected.oml").write_text("a: 1\n")
    monkeypatch.setattr(cli_runner, "write", lambda p: ("a: 1\n", "", 0))
    status, msg = runner.run_write(case)
    assert status == "pass"


def test_run_write_fail_nonzero_exit(tmp_path, monkeypatch):
    case = _mk_case(tmp_path, "c1")
    (case / "input.oml").write_text("bad\n")
    (case / "expected.oml").write_text("a: 1\n")
    monkeypatch.setattr(cli_runner, "write", lambda p: ("", "boom", 2))
    status, msg = runner.run_write(case)
    assert status == "fail" and "boom" in msg


def test_run_write_fail_mismatch(tmp_path, monkeypatch):
    case = _mk_case(tmp_path, "c1")
    (case / "input.oml").write_text("a: 1\n")
    (case / "expected.oml").write_text("a: 1\n")
    monkeypatch.setattr(cli_runner, "write", lambda p: ("a: 2\n", "", 0))
    status, msg = runner.run_write(case)
    assert status == "fail"


def test_run_validate_pass_and_fail(tmp_path, monkeypatch):
    case = _mk_case(tmp_path, "c1")
    (case / "expected").mkdir()
    (case / "expected" / "ok.txt").write_text("true\n")
    monkeypatch.setattr(cli_runner, "validate",
                        lambda i, s: (json.dumps({"ok": True}), "", 0))
    assert runner.run_validate(case)[0] == "pass"

    monkeypatch.setattr(cli_runner, "validate",
                        lambda i, s: (json.dumps({"ok": False}), "", 1))
    assert runner.run_validate(case)[0] == "fail"

    monkeypatch.setattr(cli_runner, "validate", lambda i, s: ("not json", "", 0))
    status, msg = runner.run_validate(case)
    assert status == "fail" and "non-JSON" in msg


def test_run_materialize_all_branches(tmp_path, monkeypatch):
    case = _mk_case(tmp_path, "c1")
    (case / "expected").mkdir()
    (case / "expected" / "ok.txt").write_text("true\n")
    (case / "expected" / "output.oml").write_text("a: 1\n")

    monkeypatch.setattr(cli_runner, "materialize", lambda i, s: ("a: 1\n", "", 0))
    assert runner.run_materialize(case)[0] == "pass"

    monkeypatch.setattr(cli_runner, "materialize", lambda i, s: ("", "boom", 2))
    status, _ = runner.run_materialize(case)
    assert status == "fail"

    monkeypatch.setattr(cli_runner, "materialize", lambda i, s: ("a: 2\n", "", 0))
    assert runner.run_materialize(case)[0] == "fail"

    (case / "expected" / "ok.txt").write_text("false\n")
    monkeypatch.setattr(cli_runner, "materialize", lambda i, s: ("", "err", 2))
    assert runner.run_materialize(case)[0] == "pass"
    monkeypatch.setattr(cli_runner, "materialize", lambda i, s: ("a: 1\n", "", 0))
    status, _ = runner.run_materialize(case)
    assert status == "fail"


def test_run_normalize_and_prune(tmp_path, monkeypatch):
    case = _mk_case(tmp_path, "c1")
    (case / "expected.osd").write_text('record R { "x": integer }\nroot R\n')

    monkeypatch.setattr(cli_runner, "normalize",
                        lambda s: ('record R { "x": integer }\nroot R\n', "", 0))
    assert runner.run_normalize(case)[0] == "pass"

    monkeypatch.setattr(cli_runner, "normalize", lambda s: ("", "boom", 1))
    assert runner.run_normalize(case)[0] == "fail"

    monkeypatch.setattr(cli_runner, "normalize",
                        lambda s: ('record R { "x": string }\nroot R\n', "", 0))
    assert runner.run_normalize(case)[0] == "fail"

    monkeypatch.setattr(cli_runner, "prune",
                        lambda s: ('record R { "x": integer }\nroot R\n', "", 0))
    assert runner.run_prune(case)[0] == "pass"


def test_run_boolean_helpers(tmp_path, monkeypatch):
    case = _mk_case(tmp_path, "c1")
    (case / "expected.txt").write_text("true\n")

    monkeypatch.setattr(cli_runner, "is_empty",
                        lambda s: (json.dumps({"empty": True}), "", 0))
    assert runner.run_is_empty(case)[0] == "pass"
    monkeypatch.setattr(cli_runner, "is_empty",
                        lambda s: (json.dumps({"empty": False}), "", 0))
    assert runner.run_is_empty(case)[0] == "fail"
    monkeypatch.setattr(cli_runner, "is_empty", lambda s: ("nope", "", 0))
    status, msg = runner.run_is_empty(case)
    assert status == "fail" and "non-JSON" in msg

    monkeypatch.setattr(cli_runner, "compatible_with",
                        lambda a, b: (json.dumps({"compatible": True}), "", 0))
    assert runner.run_compatible_with(case)[0] == "pass"

    monkeypatch.setattr(cli_runner, "equivalent",
                        lambda a, b: (json.dumps({"equivalent": True}), "", 0))
    assert runner.run_equivalent(case)[0] == "pass"


def test_run_extract_all_branches(tmp_path, monkeypatch):
    case = _mk_case(tmp_path, "c1")
    (case / "keep.txt").write_text("a,b\n")
    (case / "expected").mkdir()
    (case / "expected" / "ok.txt").write_text("true\n")
    (case / "expected" / "output.osd").write_text('record R { "a": integer }\nroot R\n')

    monkeypatch.setattr(cli_runner, "extract",
                        lambda s, keep: ('record R { "a": integer }\nroot R\n', "", 0))
    assert runner.run_extract(case)[0] == "pass"

    monkeypatch.setattr(cli_runner, "extract", lambda s, keep: ("", "boom", 1))
    assert runner.run_extract(case)[0] == "fail"

    monkeypatch.setattr(cli_runner, "extract",
                        lambda s, keep: ('record R { "a": string }\nroot R\n', "", 0))
    assert runner.run_extract(case)[0] == "fail"

    (case / "expected" / "ok.txt").write_text("false\n")
    monkeypatch.setattr(cli_runner, "extract", lambda s, keep: ("", "err", 2))
    assert runner.run_extract(case)[0] == "pass"
    monkeypatch.setattr(cli_runner, "extract",
                        lambda s, keep: ('record R {}\nroot R\n', "", 0))
    assert runner.run_extract(case)[0] == "fail"


def test_run_infer_all_branches(tmp_path, monkeypatch):
    case = _mk_case(tmp_path, "c1")
    samples = case / "samples"
    samples.mkdir()
    (samples / "1.oml").write_text("x: 1\n")
    (case / "expected").mkdir()
    (case / "expected" / "ok.txt").write_text("true\n")
    (case / "expected" / "output.osd").write_text(
        'record Root { "x": integer }\nroot Root\n')

    monkeypatch.setattr(cli_runner, "infer",
                        lambda files, allow_any=False: (
                            'record Root { "x": integer }\nroot Root\n', "", 0))
    assert runner.run_infer(case)[0] == "pass"

    monkeypatch.setattr(cli_runner, "infer",
                        lambda files, allow_any=False: ("", "boom", 1))
    assert runner.run_infer(case)[0] == "fail"

    monkeypatch.setattr(cli_runner, "infer",
                        lambda files, allow_any=False: (
                            'record Root { "x": string }\nroot Root\n', "", 0))
    assert runner.run_infer(case)[0] == "fail"

    (case / "allow_any.txt").write_text("true\n")
    (case / "expected" / "ok.txt").write_text("false\n")
    monkeypatch.setattr(cli_runner, "infer",
                        lambda files, allow_any=False: ("", "err", 2))
    assert runner.run_infer(case)[0] == "pass"
    monkeypatch.setattr(cli_runner, "infer",
                        lambda files, allow_any=False: (
                            'record Root { "x": integer }\nroot Root\n', "", 0))
    status, _ = runner.run_infer(case)
    assert status == "fail"


def test_run_lint_all_branches(tmp_path, monkeypatch):
    case = _mk_case(tmp_path, "c1")
    expected = {"ok": True, "findings": []}
    (case / "expected.json").write_text(json.dumps(expected))

    monkeypatch.setattr(cli_runner, "lint",
                        lambda s: (json.dumps({"ok": True, "findings": []}), "", 0))
    assert runner.run_lint(case)[0] == "pass"

    monkeypatch.setattr(cli_runner, "lint", lambda s: ("not json", "", 0))
    status, msg = runner.run_lint(case)
    assert status == "fail" and "non-JSON" in msg

    finding = {"code": "x", "severity": "warning", "location": "R.a", "message": "m1"}
    (case / "expected.json").write_text(json.dumps({"ok": False, "findings": [finding]}))
    monkeypatch.setattr(
        cli_runner, "lint",
        lambda s: (json.dumps({"ok": False, "findings": [
            {**finding, "message": "totally different wording"}]}), "", 0))
    assert runner.run_lint(case)[0] == "pass"  # message text excluded from comparison

    monkeypatch.setattr(
        cli_runner, "lint",
        lambda s: (json.dumps({"ok": False, "findings": [
            {**finding, "code": "different-code"}]}), "", 0))
    assert runner.run_lint(case)[0] == "pass"  # code excluded from comparison (Sec8.5.2 rule 4)

    monkeypatch.setattr(
        cli_runner, "lint",
        lambda s: (json.dumps({"ok": False, "findings": [
            {**finding, "location": "R.different"}]}), "", 0))
    status, msg = runner.run_lint(case)
    assert status == "fail" and "expected" in msg


def test_run_operation_missing_dir_and_no_cases(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "FIXTURES_DIR", tmp_path)
    assert runner.run_operation("write") == (0, 0, 0)

    (tmp_path / "write").mkdir()
    assert runner.run_operation("write") == (0, 0, 0)


def test_run_operation_no_runner_wired(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "FIXTURES_DIR", tmp_path)
    op_dir = tmp_path / "totally_unwired_operation"
    case = _mk_case(op_dir, "c1")
    (case / "purpose.txt").write_text("edge-case\n")
    passed, failed, skipped = runner.run_operation("totally_unwired_operation")
    assert (passed, failed, skipped) == (0, 0, 1)


def test_run_operation_mixed_pass_fail(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "FIXTURES_DIR", tmp_path)
    op_dir = tmp_path / "write"
    c1 = _mk_case(op_dir, "c1")
    (c1 / "input.oml").write_text("a: 1\n")
    (c1 / "expected.oml").write_text("a: 1\n")
    c2 = _mk_case(op_dir, "c2")
    (c2 / "input.oml").write_text("a: 1\n")
    (c2 / "expected.oml").write_text("a: 2\n")

    calls = iter([("a: 1\n", "", 0), ("a: 1\n", "", 0)])
    monkeypatch.setattr(cli_runner, "write", lambda p: next(calls))
    passed, failed, skipped = runner.run_operation("write")
    assert (passed, failed, skipped) == (1, 1, 0)


def test_main_missing_fixtures_dir(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(runner, "FIXTURES_DIR", tmp_path / "nope")
    code = runner.main([])
    assert code == 2
    assert "submodule" in capsys.readouterr().err


def test_main_all_pass_and_all_fail(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "FIXTURES_DIR", tmp_path)
    op_dir = tmp_path / "write"
    c1 = _mk_case(op_dir, "c1")
    (c1 / "input.oml").write_text("a: 1\n")
    (c1 / "expected.oml").write_text("a: 1\n")
    monkeypatch.setattr(cli_runner, "write", lambda p: ("a: 1\n", "", 0))
    assert runner.main(["write"]) == 0

    monkeypatch.setattr(cli_runner, "write", lambda p: ("a: 2\n", "", 0))
    assert runner.main(["write"]) == 1

    assert runner.main([]) in (0, 1)  # default operation set, no crash


# -------------------------------------------------------------- self_test

def test_self_test_run_case_all_branches(tmp_path):
    case = tmp_path / "c1"
    case.mkdir()
    (case / "kind.txt").write_text("document\n")
    (case / "expect.txt").write_text("equal\n")
    (case / "a.oml").write_text("a: 1\n")
    (case / "b.oml").write_text("a: 1\n")
    assert self_test.run_case(case)[0] is True

    (case / "expect.txt").write_text("not-equal\n")
    passed, msg = self_test.run_case(case)
    assert passed is False and "expected" in msg

    case2 = tmp_path / "c2"
    case2.mkdir()
    (case2 / "kind.txt").write_text("schema\n")
    (case2 / "expect.txt").write_text("equal\n")
    (case2 / "mode.txt").write_text("exact\n")
    (case2 / "a.osd").write_text('record R { "x": integer }\nroot R\n')
    (case2 / "b.osd").write_text('record R { "x": integer }\nroot R\n')
    assert self_test.run_case(case2)[0] is True

    case3 = tmp_path / "c3"
    case3.mkdir()
    (case3 / "kind.txt").write_text("bogus\n")
    (case3 / "expect.txt").write_text("equal\n")
    passed, msg = self_test.run_case(case3)
    assert passed is False and "bad kind.txt" in msg

    case4 = tmp_path / "c4"
    case4.mkdir()
    (case4 / "kind.txt").write_text("document\n")
    (case4 / "expect.txt").write_text("bogus\n")
    passed, msg = self_test.run_case(case4)
    assert passed is False and "bad expect.txt" in msg


def test_self_test_main_missing_dir(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(self_test, "FIXTURES_DIR", tmp_path / "nope")
    assert self_test.main() == 2

    monkeypatch.setattr(self_test, "FIXTURES_DIR", tmp_path)
    assert self_test.main() == 2  # exists but empty


def test_self_test_main_pass_and_fail(tmp_path, monkeypatch):
    monkeypatch.setattr(self_test, "FIXTURES_DIR", tmp_path)
    case = tmp_path / "c1"
    case.mkdir()
    (case / "purpose.txt").write_text("edge-case\n")
    (case / "kind.txt").write_text("document\n")
    (case / "expect.txt").write_text("equal\n")
    (case / "a.oml").write_text("a: 1\n")
    (case / "b.oml").write_text("a: 1\n")
    assert self_test.main() == 0

    (case / "expect.txt").write_text("not-equal\n")
    assert self_test.main() == 1
