# omnist's OML/OSD conformance runner

Runs `omnist`'s own CLI and library against
[`omnist-spec`](https://github.com/omnist-dev/omnist-spec)'s conformance
fixtures, judging structural equality with `omnist`'s own `read_oml`,
`parse_schema`, and `Schema.isomorphic_to()`. See
[`docs/conformance-harness.md`](https://github.com/omnist-dev/omnist-spec/blob/master/docs/conformance-harness.md)
in `omnist-spec` for the full spec (CLI wrapper contract, fixture format,
comparison algorithm) -- this is orientation, not a second definition.

Ported from `omnist-spec`'s `conformance/orchestrator/` (issue #283): that
code was Python-`omnist`-specific despite living in the
implementation-agnostic `omnist-spec` repo, so it lives here now, next to
the code it exercises. The fixtures themselves stay in `omnist-spec` --
they're the genuinely portable part, usable by a TS or Rust port's own
future runner too.

## Layout

```
tools/conformance/
  referee.py       structural comparison (Sec4) -- Document via Doc.__eq__,
                   Schema via exact/isomorphic modes (Schema.isomorphic_to)
  cli_runner.py    invokes the real omnist CLI per Sec2's verified contract
  self_test.py     runs vendor/omnist-spec's _referee-self-test/ fixtures
  runner.py        runs vendor/omnist-spec's real per-operation fixtures
                   (conformance/fixtures/, directory-per-case format)
  vector_runner.py runs vendor/omnist-spec's test-suite/ JSON-vector suite
                   (139 vectors, envelope format -- see its own docstring)
```

`runner.py` and `vector_runner.py` are two separate runners over two
separate fixture shapes from the same `omnist-spec` pin (issue #286)
-- deliberately not unified, since the two vector formats don't share a
natural code path. Both share `referee.py`/`cli_runner.py`.

## Fixture sourcing: a pinned git submodule

`vendor/omnist-spec` is a git submodule pinned to a specific
`omnist-spec` tag -- **not** tracking `omnist-spec@master`, so fixture
updates are explicit, reviewable version bumps rather than silent drift.

Cloning this repo doesn't check the submodule out by default; either
clone with `--recurse-submodules`, or after a normal clone:

```bash
git submodule update --init
```

### Bumping the pin

When `omnist-spec` cuts a new tag with fixture changes worth picking up:

```bash
cd vendor/omnist-spec
git fetch origin <new-tag>
git checkout FETCH_HEAD
cd ../..
git add vendor/omnist-spec
git commit -m "chore: bump vendor/omnist-spec to <new-tag>"
```

Run the runner locally before committing the bump (see below) --
a fixture-content change is exactly the kind of thing this exists to catch.

## Running it

Requires `omnist` installed and on `PATH` (`pip install -e .` from the
repo root is enough; the editable install puts the `omnist` console
script on `PATH`). Set `OMNIST_CLI` to test a different build.

```bash
python3 -m tools.conformance.self_test      # referee self-check
python3 -m tools.conformance.runner         # all wired operations (fixtures)
python3 -m tools.conformance.runner validate normalize   # a subset
python3 -m tools.conformance.vector_runner  # the 139-vector test-suite/
```

`vector_runner.py` compares diagnostics in **code-agnostic mode**
(``ok`` plus the set of ``path``s, never ``code``) -- omnist's own
diagnostic codes predate `omnist-spec`'s Sec8.3 code taxonomy and were
never renamed to match it. It also drives `infer`/`infer_with_report`
through the library directly rather than through the CLI (the CLI's
`infer` positional argument is `nargs='+'`, so a zero-samples vector can
never reach it), and skips `document-model/limits.json`'s 6 vectors
(a runtime-configurable safety limit this omnist doesn't expose) and any
`oml-grammar`/`osd-grammar` vector asserting specific diagnostics on a
syntax-level parse failure (`ParseError.errors` is empty for those by
design). See the module's own docstring for the full reasoning, including
one further vector skipped as a reported, genuine spec/implementation
divergence rather than silently worked around.

Wired into CI (`.github/workflows/test.yml`'s `conformance` job) on every
push and PR -- this is the actual point of the move from `omnist-spec`:
nothing previously caught a regression against the spec automatically.

## Unit tests vs. the real conformance run

`tests/test_conformance_tools.py` unit-tests this package's own logic
(referee comparison rules, CLI-arg building, pass/fail/skip branching)
against synthetic fixtures and monkeypatched CLI calls -- it runs in the
normal `pytest -q` suite with no submodule required, and is what keeps
this package itself at the project's usual 100%-coverage bar. The
`conformance` CI job above, which runs against the real submodule
fixtures, is the actual conformance gate; the two are complementary, not
redundant.
