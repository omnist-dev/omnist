"""Exercise examples/pyproject/ directly (not just subprocess-clean-exit
like test_examples.py's sweep) so docs/examples/pyproject.md can't drift
from what validating the fixtures actually produces.
"""
import pathlib

import pytest

from omnist import Doc, parse_schema, read_oml, read_toml, write_oml
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
def test_committed_oml_matches_write_oml(schema, fixture):
    # mirrors convert.py's actual call, including schema= -- a no-op here
    # since pyproject.osd has no date/time/datetime/number field, but kept
    # identical to what convert.py runs so this test can't drift from it
    node = read_toml(fixture.read_text(), schema=schema)
    expected = write_oml(node)
    oml_path = fixture.with_suffix(".oml")
    assert oml_path.exists(), f"missing committed OML fixture: {oml_path.name}"
    actual = oml_path.read_text()
    assert actual == expected, (
        f"{oml_path.name} is stale -- doesn't match write_oml(read_toml("
        f"{fixture.name})). Regenerate it."
    )


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda p: p.name)
def test_committed_arrays_oml_matches_write_oml(schema, fixture):
    # write_oml(..., arrays=True) sibling (issue #218): collapses
    # consecutive same-label edges (classifiers, keywords, dependencies,
    # ...) into [...] form. Must decode to the identical Document as the
    # plain .oml -- arrays are a write option, not a different Document.
    node = read_toml(fixture.read_text(), schema=schema)
    expected = write_oml(node, arrays=True)
    arrays_path = fixture.parent / f"{fixture.stem}.arrays.oml"
    assert arrays_path.exists(), f"missing committed arrays OML: {arrays_path.name}"
    actual = arrays_path.read_text()
    assert actual == expected, (
        f"{arrays_path.name} is stale -- doesn't match write_oml(read_toml("
        f"{fixture.name}), arrays=True). Regenerate it."
    )
    oml_path = fixture.with_suffix(".oml")
    assert read_oml(actual) == read_oml(oml_path.read_text()), (
        f"{arrays_path.name} decodes to a different Document than "
        f"{oml_path.name} -- arrays must never change what a file means."
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
