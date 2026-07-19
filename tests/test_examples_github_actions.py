"""Exercise examples/github-actions/ directly so
docs/examples/github-actions.md can't drift from what validating the
fixtures actually produces.

Unlike the other examples, this one also asserts on a *read failure*:
three of the four fixtures are real GitHub Actions workflows with a
bare, unquoted ``on:`` key, and PyYAML's YAML 1.1 boolean-coercion rule
turns that key into the Python boolean ``True`` -- rejected by
omnist's Document model, which requires string labels. That's a real,
documented finding, not a bug in this test suite.
"""
import pathlib

import pytest

from omnist import Doc, DocumentError, parse_schema, read_oml, read_yaml, write_oml
from omnist.schema import AnyType

ROOT = pathlib.Path(__file__).resolve().parent.parent
EXAMPLE_DIR = ROOT / "examples" / "github-actions"
FIXTURES = sorted((EXAMPLE_DIR / "fixtures").glob("*.yml"))
UNQUOTED_ON_FIXTURES = [f for f in FIXTURES if f.name != "test-quoted-on.yml"]


@pytest.fixture(scope="module")
def schema():
    return parse_schema((EXAMPLE_DIR / "workflow.osd").read_text())


def test_pyyaml_boolean_coercion_illustration():
    # docs/examples/github-actions.md's inline yaml.safe_load illustration
    # of *why* the DocumentError above happens -- stdlib PyYAML behavior,
    # not omnist's own, but shown as a literal example in the doc.
    import yaml
    assert yaml.safe_load("on:\n  push: {}\n") == {True: {"push": {}}}


def test_fixtures_exist():
    names = {f.name for f in FIXTURES}
    assert names == {
        "test.yml",
        "publish.yml",
        "docs.yml",
        "test-quoted-on.yml",
    }


@pytest.mark.parametrize("fixture", UNQUOTED_ON_FIXTURES, ids=lambda p: p.name)
def test_unquoted_on_key_fails_to_read(fixture):
    with pytest.raises(DocumentError, match="object key True is not a string"):
        read_yaml(fixture.read_text())


def test_quoted_on_fixture_validates(schema):
    fixture = EXAMPLE_DIR / "fixtures" / "test-quoted-on.yml"
    node = read_yaml(fixture.read_text(), schema=schema)
    result = schema.validate(Doc(node))
    assert result.ok, f"test-quoted-on.yml failed validation:\n{result}"


def test_committed_oml_matches_write_oml(schema):
    fixture = EXAMPLE_DIR / "fixtures" / "test-quoted-on.yml"
    node = read_yaml(fixture.read_text(), schema=schema)
    expected = write_oml(node)
    oml_path = fixture.with_suffix(".oml")
    assert oml_path.exists(), f"missing committed OML fixture: {oml_path.name}"
    actual = oml_path.read_text()
    assert actual == expected, (
        f"{oml_path.name} is stale -- doesn't match write_oml(read_yaml("
        f"{fixture.name})). Regenerate it."
    )


def test_committed_arrays_oml_matches_write_oml(schema):
    # steps: is the real-world case with the richest run structure in
    # this whole four-example set: 5 consecutive steps mixing uses:- and
    # run:-shaped subtrees, collapsed to one array. Also exercises a
    # matrix python-version: run of 4 plain strings.
    fixture = EXAMPLE_DIR / "fixtures" / "test-quoted-on.yml"
    node = read_yaml(fixture.read_text(), schema=schema)
    expected = write_oml(node, arrays=True)
    arrays_path = fixture.parent / f"{fixture.stem}.arrays.oml"
    assert arrays_path.exists(), f"missing committed arrays OML: {arrays_path.name}"
    actual = arrays_path.read_text()
    assert actual == expected, (
        f"{arrays_path.name} is stale -- doesn't match write_oml(read_yaml("
        f"{fixture.name}), arrays=True). Regenerate it."
    )
    oml_path = fixture.with_suffix(".oml")
    assert read_oml(actual) == read_oml(oml_path.read_text()), (
        f"{arrays_path.name} decodes to a different Document than "
        f"{oml_path.name} -- arrays must never change what a file means."
    )


def test_any_fields_match_documented_count(schema):
    workflow = schema.env["Workflow"]
    any_fields = {f.label for f in workflow.fields if isinstance(f.type, AnyType)}
    assert any_fields == {
        "on",
        "permissions",
        "env",
        "defaults",
        "concurrency",
        "jobs",
    }
    assert len(workflow.fields) == 8
