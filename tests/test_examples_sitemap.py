"""Exercise examples/sitemap/ directly so docs/examples/sitemap.md
can't drift from what validating the fixtures actually produces.

Structurally the cleanest of the four examples -- no unions, no open
key sets -- but it surfaces a gap none of the other three did: value
refinement. ``invalid-values.xml`` deliberately violates the
sitemaps.org spec's ``changefreq`` enum and ``priority`` range while
staying type-correct, and this schema still accepts it. That's the
finding under test here, not a bug.
"""
import pathlib

import pytest

from omnist import Doc, parse_schema, read_xml, write_oml

ROOT = pathlib.Path(__file__).resolve().parent.parent
EXAMPLE_DIR = ROOT / "examples" / "sitemap"
FIXTURES = sorted((EXAMPLE_DIR / "fixtures").glob("*.xml"))


@pytest.fixture(scope="module")
def schema():
    return parse_schema((EXAMPLE_DIR / "sitemap.osd").read_text())


def test_fixtures_exist():
    names = {f.name for f in FIXTURES}
    assert names == {"minimal.xml", "invalid-values.xml"}


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda p: p.name)
def test_fixture_validates(schema, fixture):
    node = read_xml(fixture.read_text(), schema=schema)
    result = schema.validate(Doc(node))
    assert result.ok, f"{fixture.name} failed validation:\n{result}"


def test_lastmod_upgraded_by_schema_directed_reading(schema):
    fixture = EXAMPLE_DIR / "fixtures" / "minimal.xml"
    plain = read_xml(fixture.read_text())
    directed = read_xml(fixture.read_text(), schema=schema)
    assert plain != directed, (
        "schema= was expected to upgrade lastmod to a real date -- "
        "unlike the other three examples in this set, this is not a no-op"
    )


def test_invalid_values_fixture_demonstrates_the_gap():
    """changefreq='sometimes' (not in the spec's 7-value enum) and
    priority outside [0.0, 1.0] both validate -- OSD has no enum or
    range constraint, only scalar type. This is the documented finding
    the fixture exists to demonstrate.
    """
    fixture = EXAMPLE_DIR / "fixtures" / "invalid-values.xml"
    text = fixture.read_text()
    assert "sometimes" in text  # not one of the 7 spec-valid changefreq values
    assert "1.5" in text  # outside the spec's [0.0, 1.0] priority range


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda p: p.name)
def test_committed_oml_matches_write_oml(schema, fixture):
    node = read_xml(fixture.read_text(), schema=schema)
    expected = write_oml(node)
    oml_path = fixture.with_suffix(".oml")
    assert oml_path.exists(), f"missing committed OML fixture: {oml_path.name}"
    actual = oml_path.read_text()
    assert actual == expected, (
        f"{oml_path.name} is stale -- doesn't match write_oml(read_xml("
        f"{fixture.name})). Regenerate it."
    )
