# Worked example: modeling a GitHub Actions workflow

A third real, external format — YAML this time, and the first of the
four in this set with an unanticipated **codec-level** finding, not
just a schema-level one.

Modeled against SchemaStore's
[`github-workflow.json`](https://www.schemastore.org/github-workflow.json),
retrieved 2026-07-11 — community-maintained, not an official GitHub
artifact, same caveat as [package.json's schema](package-json.md).
GitHub's own workflow docs are prose, like npm's; no formal spec exists
here either.

Source, code, and fixtures:
[`examples/github-actions/`](https://github.com/omnist-dev/omnist/tree/master/examples/github-actions).
Schema: [`workflow.osd`](https://github.com/omnist-dev/omnist/blob/master/examples/github-actions/workflow.osd).
Script: [`convert.py`](https://github.com/omnist-dev/omnist/blob/master/examples/github-actions/convert.py).

## Run it

```
python3 examples/github-actions/convert.py
```

`read_yaml` is called with `schema=` — a no-op here, same as the
pyproject.toml and package.json examples (no `date`/`time`/`datetime`/
`number` field in this schema either).

## A real finding: three of the four fixtures don't even read

This repo's own three workflow files
([`test.yml`](https://github.com/omnist-dev/omnist/blob/master/examples/github-actions/fixtures/test.yml),
[`publish.yml`](https://github.com/omnist-dev/omnist/blob/master/examples/github-actions/fixtures/publish.yml),
[`docs.yml`](https://github.com/omnist-dev/omnist/blob/master/examples/github-actions/fixtures/docs.yml))
use the ordinary, unquoted `on:` key — the standard convention almost
every real workflow file uses. **All three fail before validation even
starts**:

```
DocumentError: $: object key True is not a string
```

The cause: PyYAML's `safe_load` follows YAML 1.1 semantics, where
`on`/`off`/`yes`/`no`/`true`/`false` (in various cases) are boolean
scalars, not strings. A bare `on:` key parses to the Python boolean
`True`, not the string `"on"`:

```python
import yaml
yaml.safe_load("on:\n  push: {}\n")
# {True: {'push': {}}}
```

omnist's Document model requires every label to be a string — so
`read_yaml` correctly refuses to build a Document with a boolean key,
raising `DocumentError` rather than silently coercing it. This is
*correct* behavior for `read_yaml` given what it received; the actual
problem is one level up, in what PyYAML handed it. It's also exactly
the [notorious "Norway problem"](https://noyaml.com/) that YAML 1.1
parsers are known for (`NO` parsing as `false` is the classic example;
`on` is a less-famous but real instance of the same rule) — and it
happens to collide with the one top-level key almost every GitHub
Actions workflow file needs.

**[`test-quoted-on.yml`](https://github.com/omnist-dev/omnist/blob/master/examples/github-actions/fixtures/test-quoted-on.yml)**
is `test.yml` with the key quoted as `"on":` — a synthetic derivative,
not sourced verbatim, built specifically to demonstrate schema
validation succeeding once past this codec-level issue. Real workflow
files almost never quote this key, which is exactly what makes the
finding worth stating plainly rather than working around it silently.
Its OML is committed as
[`test-quoted-on.oml`](https://github.com/omnist-dev/omnist/blob/master/examples/github-actions/fixtures/test-quoted-on.oml).

This is a limitation of the **codec** (or arguably of PyYAML's YAML 1.1
defaults), not of OSD's schema algebra — worth keeping separate from
the schema-level gaps below.

## What OSD can model exactly

Only 2 of 8 top-level fields — `name`, `run-name` — are fully closed
and checked. That's a **quarter**, the lowest of all four examples in
this set.

## What it can't, and why

**Unions**: `on` is a **three-way** union — a bare event string, an
array of event strings, or a map of event → trigger config — one step
past the two-way unions seen in the pyproject.toml and package.json
examples. `permissions` and `concurrency` are also unions (a string
shorthand or an object).

**Open key sets**: `jobs` (job-id → job config), `env`, and `defaults`
are all open maps, same category as `[tool]`/`scripts`/`dependencies`
in the earlier examples.

**Shape depends on a sibling key, not just cardinality**: inside a
job's `steps:` array, each item alternates between a `uses:`-shaped
step (calling a reusable action) and a `run:`-shaped step (a shell
command) — within the *same* array. This is the clearest instance in
this whole set of the "meta-referential" pattern flagged in
[the overview's lessons list](index.md#if-youre-designing-a-format-for-osd):
the field that's actually present determines what shape the record is,
not a fixed discriminant OSD's cardinality model can check.

**The honest number**: 6 of 8 fields are `any` — 75%, again the
highest of the four examples, consistent with `jobs` alone carrying
most of a workflow's real content and being irreducibly open.

See also: [the pyproject.toml example](pyproject.md),
[the package.json example](package-json.md), and
[the overview](index.md) for how this compares across all four.
