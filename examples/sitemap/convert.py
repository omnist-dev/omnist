#!/usr/bin/env python3
"""Validate sitemap.xml files against sitemap.osd, and show the
resulting OML.

For each fixture: read the XML, validate it against the schema, and
print the equivalent OML. This schema is structurally the cleanest of
the four examples in this set -- no unions, no open key sets -- but
``invalid-values.xml`` deliberately violates the sitemaps.org spec's
``changefreq`` enum and ``priority`` range while staying type-correct.
It still validates: OSD has no enum or range constraint, only scalar
*types*. That's a documented finding, not a bug in this script or the
fixture -- see docs/examples/sitemap.md.

``read_xml`` is called with ``schema=``. Unlike the pyproject.toml,
package.json, and GitHub Actions examples, this is **not** a no-op
here: ``lastmod`` is schema-typed ``date``, so schema-directed reading
upgrades the ISO string to a real ``datetime.date``.

Each fixture's OML is committed alongside it as ``<name>.oml``, and
``tests/test_examples_sitemap.py`` asserts an exact match.

Run: python3 examples/sitemap/convert.py
"""
from pathlib import Path

from omnist import Doc, parse_schema, read_xml, write_oml

HERE = Path(__file__).parent
FIXTURES = sorted((HERE / "fixtures").glob("*.xml"))


def main():
    schema = parse_schema((HERE / "sitemap.osd").read_text())

    for fixture in FIXTURES:
        print(f"== {fixture.name} ==")
        node = read_xml(fixture.read_text(), schema=schema)
        result = schema.validate(Doc(node))
        if result.ok:
            print("valid: True")
            print(write_oml(node))
        else:
            print("valid: False")
            print(result)
        print()


if __name__ == "__main__":
    main()
