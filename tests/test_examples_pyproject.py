"""Exercise examples/pyproject/ directly (not just subprocess-clean-exit
like test_examples.py's sweep) so docs/examples/pyproject.md can't drift
from what validating the fixtures actually produces.
"""
import pathlib

import pytest

from omnist import Doc, parse_schema, read_toml, write_oml
from omnist.schema import AnyType

ROOT = pathlib.Path(__file__).resolve().parent.parent
EXAMPLE_DIR = ROOT / "examples" / "pyproject"
FIXTURES = sorted((EXAMPLE_DIR / "fixtures").glob("*.toml"))


@pytest.fixture(scope="module")
def schema():
    return parse_schema((EXAMPLE_DIR / "pyproject.osd").read_text())


def test_fixtures_exist():
    names = {f.name for f in FIXTURES}
    assert names == {
        "omnist.toml",
        "spam-eggs.toml",
        "invented-dynamic-version.toml",
    }


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda p: p.name)
def test_fixture_validates(schema, fixture):
    node = read_toml(fixture.read_text())
    result = schema.validate(Doc(node))
    assert result.ok, f"{fixture.name} failed validation:\n{result}"


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda p: p.name)
def test_fixture_round_trips_to_oml(fixture):
    node = read_toml(fixture.read_text())
    oml = write_oml(node)
    assert oml.strip()


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda p: p.name)
def test_committed_oml_matches_write_oml(fixture):
    node = read_toml(fixture.read_text())
    expected = write_oml(node)
    oml_path = fixture.with_suffix(".oml")
    assert oml_path.exists(), f"missing committed OML fixture: {oml_path.name}"
    actual = oml_path.read_text()
    assert actual == expected, (
        f"{oml_path.name} is stale -- doesn't match write_oml(read_toml("
        f"{fixture.name})). Regenerate it."
    )


def test_any_fields_match_documented_count(schema):
    project = schema.env["Project"]
    any_fields = {f.label for f in project.fields if isinstance(f.type, AnyType)}
    assert any_fields == {
        "readme",
        "license",
        "optional-dependencies",
        "urls",
        "scripts",
        "gui-scripts",
        "entry-points",
    }
    assert len(project.fields) == 20
