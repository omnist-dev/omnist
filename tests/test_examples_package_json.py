"""Exercise examples/package-json/ directly (not just subprocess-clean-exit
like test_examples.py's sweep) so docs/examples/package-json.md can't
drift from what validating the fixtures actually produces.
"""
import pathlib

import pytest

from omnist import Doc, parse_schema, read_json, write_oml
from omnist.schema import AnyType

ROOT = pathlib.Path(__file__).resolve().parent.parent
EXAMPLE_DIR = ROOT / "examples" / "package-json"
FIXTURES = sorted((EXAMPLE_DIR / "fixtures").glob("*.json"))


@pytest.fixture(scope="module")
def schema():
    return parse_schema((EXAMPLE_DIR / "package.osd").read_text())


def test_fixtures_exist():
    names = {f.name for f in FIXTURES}
    assert names == {
        "npm-init-default.json",
        "invented-widget-cli.json",
    }


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda p: p.name)
def test_fixture_validates(schema, fixture):
    node = read_json(fixture.read_text())
    result = schema.validate(Doc(node))
    assert result.ok, f"{fixture.name} failed validation:\n{result}"


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda p: p.name)
def test_committed_oml_matches_write_oml(schema, fixture):
    # mirrors convert.py's actual call, including schema= -- a no-op here
    # since package.osd has no date/time/datetime/number field, but kept
    # identical to what convert.py runs so this test can't drift from it
    node = read_json(fixture.read_text(), schema=schema)
    expected = write_oml(node)
    oml_path = fixture.with_suffix(".oml")
    assert oml_path.exists(), f"missing committed OML fixture: {oml_path.name}"
    actual = oml_path.read_text()
    assert actual == expected, (
        f"{oml_path.name} is stale -- doesn't match write_oml(read_json("
        f"{fixture.name})). Regenerate it."
    )


def test_any_fields_match_documented_count(schema):
    pkg = schema.env["PackageJson"]
    any_fields = {f.label for f in pkg.fields if isinstance(f.type, AnyType)}
    assert any_fields == {
        "author",
        "bugs",
        "repository",
        "bin",
        "scripts",
        "dependencies",
        "devDependencies",
        "engines",
    }
    assert len(pkg.fields) == 16
