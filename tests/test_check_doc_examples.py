"""Tests for tools/check_doc_examples.py -- the CI gate requiring a marker
on every new/changed code block in docs/*.md. Uses a throwaway git repo per
test so the check's git-diffing logic runs against real history, not a
mock. Calls the module in-process (not via subprocess) so coverage traces
it, matching tests/test_semantic_oracle.py's convention for tools/."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

# tools/ is repo-root-relative, not an installed package; bare `pytest -q`
# does not put the repo root on sys.path the way `python -m pytest` does.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tools.check_doc_examples as check_doc_examples  # noqa: E402


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q")
    _git(r, "config", "user.email", "test@example.com")
    _git(r, "config", "user.name", "Test")
    (r / "docs").mkdir()
    (r / "docs" / "guide.md").write_text("# Guide\n\nSome intro text.\n")
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "initial")
    base_sha = _git(r, "rev-parse", "HEAD").stdout.strip()
    r.joinpath(".git", "refs", "remotes", "origin").mkdir(parents=True)
    r.joinpath(".git", "refs", "remotes", "origin", "master").write_text(base_sha + "\n")
    return r


def _mark_origin_at_head(r: Path) -> None:
    base_sha = _git(r, "rev-parse", "HEAD").stdout.strip()
    r.joinpath(".git", "refs", "remotes", "origin", "master").write_text(base_sha + "\n")


def run_check(monkeypatch, repo: Path) -> int:
    monkeypatch.chdir(repo)
    monkeypatch.setattr(sys, "argv", ["check_doc_examples.py", "--base-ref", "origin/master"])
    return check_doc_examples.main()


def test_passes_with_no_changes(monkeypatch, repo: Path, capsys):
    code = run_check(monkeypatch, repo)
    assert code == 0
    assert "passed" in capsys.readouterr().out


def test_fails_on_new_unmarked_block(monkeypatch, repo: Path, capsys):
    guide = repo / "docs" / "guide.md"
    guide.write_text(guide.read_text() + "\n```python\nprint(1)\n```\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "add unmarked block")

    code = run_check(monkeypatch, repo)
    out = capsys.readouterr().out
    assert code == 1
    assert "no <!-- verified-by" in out
    assert "guide.md" in out


def test_passes_with_verified_by_marker(monkeypatch, repo: Path, capsys):
    guide = repo / "docs" / "guide.md"
    guide.write_text(
        guide.read_text()
        + "\n```python\nprint(1)\n```\n<!-- verified-by: tests/test_docs.py::test_x -->\n"
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "add marked block")

    code = run_check(monkeypatch, repo)
    assert code == 0


def test_passes_with_doc_illustrative_marker(monkeypatch, repo: Path, capsys):
    guide = repo / "docs" / "guide.md"
    guide.write_text(
        guide.read_text() + "\n```mermaid\ngraph LR\n  a --> b\n```\n<!-- doc-illustrative -->\n"
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "add illustrative block")

    code = run_check(monkeypatch, repo)
    assert code == 0


def test_unchanged_existing_block_in_a_touched_file_is_not_flagged(monkeypatch, repo: Path, capsys):
    # A pre-existing unmarked block, in a file the PR *does* touch (but not
    # at that block's lines), shouldn't fail the gate -- only new/changed
    # blocks are in scope, checked by an unrelated new marked block below
    # the untouched one in the same file.
    guide = repo / "docs" / "guide.md"
    guide.write_text(guide.read_text() + "\n```python\nprint('old')\n```\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "pre-existing unmarked block")
    _mark_origin_at_head(repo)

    guide.write_text(
        guide.read_text()
        + "\n## New section\n\n"
        + "```python\nprint('new')\n```\n<!-- verified-by: tests/test_docs.py::test_y -->\n"
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "add a new marked block, leave the old one alone")

    code = run_check(monkeypatch, repo)
    assert code == 0


def test_deleted_doc_file_is_skipped(monkeypatch, repo: Path, capsys):
    # changed_doc_files() can list a file that no longer exists on HEAD
    # (deleted in the diff) -- main() must skip it, not crash.
    guide = repo / "docs" / "guide.md"
    guide.write_text(guide.read_text() + "\n```python\nprint(1)\n```\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "add unmarked block")
    _mark_origin_at_head(repo)

    guide.unlink()
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "delete guide.md")

    code = run_check(monkeypatch, repo)
    assert code == 0


def test_fence_and_marker_regexes():
    assert check_doc_examples.FENCE_RE.match("```python")
    assert not check_doc_examples.FENCE_RE.match("not a fence")
    assert check_doc_examples.MARKER_RE.search("<!-- verified-by: a::b -->")
    assert check_doc_examples.MARKER_RE.search("<!-- doc-illustrative -->")
    assert not check_doc_examples.MARKER_RE.search("<!-- some other comment -->")
