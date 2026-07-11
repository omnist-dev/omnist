#!/usr/bin/env python3
"""Validate a pyproject.toml against a schema for PEP 621's fixed
`[project]` metadata, with every genuinely open region marked `any`.

This exercises `any` (see docs/schema.md#the-any-type), OSD `#` comments
(see docs/schema.md#comments), path-based validation errors, and
`omnist schema lint`'s `any`-field inventory.

Run: python3 examples/pyproject_validate.py
"""
import pathlib

from omnist import Doc, lint, parse_schema, read_toml

HERE = pathlib.Path(__file__).resolve().parent

SCHEMA = """
record Project {
    "name":             string,
    "version":          string,
    "description":      string,
    "requires-python":  string,
    "dependencies" [0,]: string,
    "optional-dependencies": any,  # per-extra dependency groups -- open key set, not modeled
    "scripts":               any,  # console-script name -> entry point string -- open key set
    "entry-points":           any,  # plugin group -> name -> entry point -- open key set
    "urls":                   any,  # arbitrary link labels (Homepage, Docs, ...) -- open key set
}
record Root {
    "project":       Project,
    "tool" [0,1]:    any,  # [tool.*] is arbitrary per-tool config -- not modeled
}
root Root
"""


def main():
    s = parse_schema(SCHEMA)

    print("== a correct pyproject.toml validates ==")
    good = read_toml((HERE / "pyproject_sample.toml").read_text())
    result = s.validate(Doc(good))
    print("valid:", result.ok)
    assert result.ok

    print("\n== a broken one -- missing 'name' -- fails at its exact path ==")
    bad = read_toml((HERE / "pyproject_sample_broken.toml").read_text())
    bad_result = s.validate(Doc(bad))
    print(bad_result)
    assert not bad_result.ok
    assert any(
        f.path == "$.project" and "'name'" in f.message
        for f in bad_result.errors
    )

    print("\n== omnist schema lint: the any-field inventory ==")
    findings = [(f.code, f.location) for f in lint(s) if f.code == "any-field"]
    for code, location in findings:
        print(f"{code}: {location}")
    assert {loc for _, loc in findings} == {
        "Project.optional-dependencies",
        "Project.scripts",
        "Project.entry-points",
        "Project.urls",
        "Root.tool",
    }


if __name__ == "__main__":
    main()
