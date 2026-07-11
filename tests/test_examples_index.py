"""Checks that docs/examples/index.md's comparison table can't drift
from what the four example schemas actually report.
"""
import pathlib

import pytest

from omnist import parse_schema
from omnist.schema import AnyType

ROOT = pathlib.Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"

# (schema path, root record name, expected total, expected any)
CASES = [
    (EXAMPLES / "pyproject" / "pyproject.osd", "Project", 20, 7),
    (EXAMPLES / "package-json" / "package.osd", "PackageJson", 16, 8),
    (EXAMPLES / "github-actions" / "workflow.osd", "Workflow", 8, 6),
    (EXAMPLES / "sitemap" / "sitemap.osd", "Url", 4, 0),
]


@pytest.mark.parametrize(
    "schema_path, record_name, expected_total, expected_any",
    CASES,
    ids=lambda v: v if isinstance(v, str) else "",
)
def test_field_counts_match_index_table(
    schema_path, record_name, expected_total, expected_any
):
    schema = parse_schema(schema_path.read_text())
    record = schema.env[record_name]
    total = len(record.fields)
    any_count = sum(1 for f in record.fields if isinstance(f.type, AnyType))
    assert total == expected_total, (
        f"{schema_path.name}/{record_name}: total fields is {total}, "
        f"but docs/examples/index.md's table claims {expected_total}"
    )
    assert any_count == expected_any, (
        f"{schema_path.name}/{record_name}: any fields is {any_count}, "
        f"but docs/examples/index.md's table claims {expected_any}"
    )
