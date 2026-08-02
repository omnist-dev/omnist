# Changelog

All notable changes to this project are documented here. The format is loosely
based on [Keep a Changelog](https://keepachangelog.com/); this project is
**beta**, and the public API is covered by the
[stability policy](docs/stability.md) — stable surfaces change only through a
deprecation cycle, not silently between releases.

## [v0.8.0] — `read_xml` no longer infers scalar kind from text shape (BREAKING)

- Closed [#288](https://github.com/omnist-dev/omnist/issues/288):
  `read_xml` used to guess `int`/`float`/`bool` from the shape of an
  element's text before any schema was involved (`<m>1</m>` read back as
  the integer `1`, not the string `"1"`). This contradicted
  `omnist-spec`'s own documented design — XML has no native typed
  literals (unlike YAML's `true` token or TOML's `29.97` number literal),
  so unlike YAML/TOML it's meant to stay untyped at stage 1, exactly like
  JSON/OML. Resolved in the spec's favor after checking both sides (the
  coercion was real, deliberate, and tested — this genuinely reverses a
  design decision, not a bugfix for drift). **Breaking**: every XML
  element's text now always reads as a plain `str`, regardless of shape.
  Recover the typed value with `schema=`, same as any other textual
  format.
- To make schema-directed reading actually recover those types (as
  `docs/formats/xml.md`'s own "materialization" story always promised),
  `read_xml(text, schema=)` gained its own extra pass that upgrades a
  canonically-spelled numeric/boolean string before handing the node to
  the shared `materialize()` — value-exact spelling only
  (`"true"`/`"false"`, no leading zero or `+`), not merely-parseable.
  This is deliberately **not** a change to `materialize()` itself:
  `materialize()` still rejects a numeric-looking string for every other
  format, since a string in JSON/YAML/TOML/OML is always a deliberate
  choice, never an untyped placeholder the way it always is in XML
  (caught by the `conformance` CI job — an omnist-spec vector explicitly
  pins this rejection).
- `write_xml`'s `string.ambiguous` adjustment code is gone (there's no
  more ambiguity to report — a string round-trips as a string now). A new
  `value.stringified` code covers what `string.ambiguous` didn't: a real
  `bool`/`int`/`float` value written to XML now reads back as a string
  and is reported, closing a previously-silent gap.
- This change lands without a deprecation cycle, despite `read_xml`'s
  behavior being part of the documented public API surface — with no
  known users of this project yet, staging a two-release deprecation for
  a genuine spec-conformance fix would cost more than it protects.



## [v0.7.19] — wire omnist-spec's 139-vector test-suite/ into the conformance runner

- Closed [#286](https://github.com/omnist-dev/omnist/issues/286): added
  `tools/conformance/vector_runner.py`, a second runner alongside
  `runner.py` that walks `omnist-spec`'s `test-suite/` JSON-vector suite
  (139 vectors, envelope `name`/`spec`/`operation`/`purpose`/`input`/
  `expect`) — deliberately not unified with the directory-fixture format,
  sharing only `referee.py`/`cli_runner.py`. Wired into the `conformance`
  CI job. Currently 103 pass, 36 skip, 0 fail.
- Diagnostics are compared in **code-agnostic mode** (`ok` plus the set of
  `path`s, never `code`) per §8.5.2 rule 4: omnist's own diagnostic codes
  (`type-mismatch`, `temporal.stringified`, …) predate `omnist-spec`'s
  §8.3 code taxonomy and were never renamed to match it.
- `infer`/`infer_with_report` are driven directly through the library
  rather than the CLI, so `infer/errors/zero-samples-is-an-error` — which
  the CLI's `nargs='+'` argument can never reach — actually runs (and
  passes) instead of being skipped.
- `document-model/limits.json`'s 6 vectors skip (a runtime-configurable
  safety limit this omnist doesn't expose), as do `oml-grammar`/
  `osd-grammar` vectors asserting specific diagnostics on a syntax-level
  parse failure (`ParseError.errors` is empty for those by design).
- Found and reported one genuine spec/implementation divergence rather
  than working around it:
  `formats-xml/basic/interleaved-elements-preserve-order` expects XML
  element text to always decode to the Document `string` kind, but
  `docs/formats/xml.md` documents `read_xml`'s shape-based coercion
  heuristic (`"1"` reads back as the integer `1`). Skipped with a clear
  comment, not silently passed.

## [v0.7.18] — own OML/OSD conformance runner, wired into CI

- Closed [#283](https://github.com/omnist-dev/omnist/issues/283): moved
  `omnist-spec`'s conformance-test orchestrator (`referee.py`,
  `cli_runner.py`, `runner.py`, `self_test.py`) into this repo as
  `tools/conformance/` — that code was Python-`omnist`-specific despite
  living in the implementation-agnostic `omnist-spec` repo, importing
  `omnist` directly and shelling out to its CLI. No change to the
  comparison logic itself (`Doc.__eq__` for documents, `Schema.__eq__`/
  `Schema.isomorphic_to()` for exact/isomorphic schema comparison) — a
  relocation plus CI wiring, exactly as scoped.
  - Fixtures come from `omnist-spec`'s `conformance/fixtures/` via a git
    submodule (`vendor/omnist-spec`) pinned to a tag, not tracking
    `omnist-spec@master` — deliberate, so fixture updates are explicit,
    reviewable bumps. `omnist-spec` had no tag covering its current
    conformance-harness state (its only tag, `v0.0.1-alpha`, predates all
    of it), so tagged `omnist-spec@v0.1.0-alpha` at the current state to
    pin against.
  - New `conformance` job in `.github/workflows/test.yml`, checking out
    the submodule and running both `self_test` (the referee's own
    correctness, Sec6) and `runner` (all 11 wired operations against the
    real fixtures) on every push/PR — closing the actual gap the issue
    was about: nothing in this repo's CI previously caught a regression
    against the spec at all.
  - `tools/conformance/`'s own logic is unit-tested
    (`tests/test_conformance_tools.py`, 100% coverage) against synthetic
    fixtures and monkeypatched CLI calls, independent of the submodule
    being checked out — the `conformance` CI job against the real
    fixtures is the actual conformance gate, complementary not redundant.
  - Added `[tool.pytest.ini_options] testpaths = ["tests"]` and
    `[tool.ruff] extend-exclude = ["vendor"]` — without these, pytest's
    default discovery collects the submodule's own `self_test.py`
    (matches pytest's `*_test.py` pattern) and tries to import a module
    not on this repo's `sys.path`, and `ruff check .` lints the vendored
    sibling repo's code as if it were ours.
  - `omnist-spec#27` tracks removing the now-redundant orchestrator from
    `omnist-spec` on their side.

## [v0.7.17] — `Schema.isomorphic_to()`; `infer --allow-any --json`

- Closed [#279](https://github.com/omnist-dev/omnist/issues/279): added
  `Schema.isomorphic_to(other)` -- stricter than `equivalent()` (same
  document language is necessary but not sufficient; this additionally
  requires the same record graph structure, up to a renaming of records).
  Deliberately an *additional*, narrower operation, not a redefinition of
  `equivalent()` as the model's canonical definition of schema equality
  -- `_isomorphic` in `omnist/ops/isomorphic.py` stays private, now with
  two consumers (its existing property-test oracle role, and this new
  public method). Confirmed empirically that the algorithm's correctness
  doesn't depend on its inputs being pre-normalized, which the module's
  original docstring's "assumed already normalized" note could have been
  read to require -- `isomorphic_to` delegates directly, no internal
  `normalize()` call needed. Motivated by `omnist-spec`'s conformance
  harness (`docs/conformance-harness.md` §4/§6.2), which needs this for
  comparing `infer`'s output: `infer` never merges structurally-identical
  generated records (that's `normalize`'s job, not `infer`'s), and a
  buggy implementation that accidentally merges two identical records
  still accepts the same documents -- `equivalent()` reports that as
  correct, a false negative `isomorphic_to` catches (different record-set
  cardinality, no bijection possible regardless of naming).
- Fixed [#280](https://github.com/omnist-dev/omnist/issues/280):
  `infer --allow-any`'s opening report always printed plain text to
  stderr, ignoring `--json`, unlike every other diagnostic-producing CLI
  command. Now emits `{"opened": [{"location", "reason"}, ...]}` on
  stderr when `--json` is passed, matching `AnyFallback`'s shape. Schema
  output on stdout is unaffected either way.

## [v0.7.16] — allow `convert --from oml --to oml --schema`

- Fixed [#277](https://github.com/omnist-dev/omnist/issues/277): `omnist
  convert --from oml --to oml --schema SCHEMA` was refused
  unconditionally — the same-format guard ran before `args.schema` was
  even read. The refusal is correct with no schema (a pure no-op;
  `omnist format` is the dedicated command for that), but a schema turns
  it into a real operation (schema-directed materialization: read OML,
  upgrade against the schema, write OML back) that had no other CLI path
  at all (`format`/`check` have no `--schema`). Now only refuses the
  no-schema case; `convert` already had the machinery
  (`_READERS[args.from_](..., schema=schema)`) to do the rest. Unblocks
  the conformance harness work on `omnist-spec` (`omnist-spec#26`).

## [v0.7.15] — structural equality for Field/Record/Schema; doc drift fixes

- Closed [#273](https://github.com/omnist-dev/omnist/issues/273): added
  `__eq__` to `Field`, `Record`, and `Schema` in `omnist/schema.py` —
  previously they fell back to Python's default identity comparison, so
  two structurally identical schemas compared unequal unless they were
  the literal same object. `Field.__eq__` compares `label`/`type`/
  `min`/`max`; `Record.__eq__` compares fields as an order-independent
  set (declaration order isn't semantically significant); `Schema.__eq__`
  compares `root` and `env`, likewise order-independent. Confirmed
  `Ref`/`Scalar`/`AnyType.__eq__` were already correct before relying on
  `Field.__eq__`'s delegation to `type ==`. This is a dependency for the
  new conformance harness being built against `omnist-spec`'s
  `conformance-harness.md` §5, which needs to compare an implementation's
  actual OSD output against expected output by structural equality, not
  text diffing.
- Fixed [#271](https://github.com/omnist-dev/omnist/issues/271):
  `openness.md`/`any-type-spec.md` had drifted since `any` shipped in
  v0.5.0 and `--allow-any` was added — a stale Decision Record, an
  absolute "never inferred" guardrail contradicting the documented
  opt-in, and a matching overstatement in the non-goals section. All
  three now consistently describe the default vs. the explicit,
  loudly-reported exception.
- Fixed [#272](https://github.com/omnist-dev/omnist/issues/272):
  `formats/overview.md`'s "Special features, mapped to OML" table had
  paragraph-length cells fighting a table's own scanning purpose —
  replaced with one prose subsection per format.

## [v0.7.14] — symmetric inf/-inf boundary tests

- Closed [#262](https://github.com/omnist-dev/omnist/issues/262): `nan`
  already had two boundary tests `inf`/`-inf` didn't — that a capitalized
  spelling isn't the reserved keyword, and that the reserved spelling
  quoted is a valid label. Added the symmetric coverage
  (`test_capitalized_inf_is_not_the_keyword`,
  `test_oml_inf_is_a_number_token_never_a_label`,
  `test_oml_quoted_inf_is_a_valid_label`). Behavior was already correct
  (`nan`/`inf`/`-inf` share one tokenizer priority slot); this is
  test-coverage-only, no production code changed. Companion issues filed
  on the TypeScript and Rust ports (omnist-ts#74, omnist-rs#75) for the
  same gap remain open there.

## [v0.7.13] — spec-conformance audit fixes

Six issues found during a full verification pass of the `omnist-spec`
specification against this repository's source and test suite.

- Fixed [#263](https://github.com/omnist-dev/omnist/issues/263) (spec S-3):
  the Python builder API (`schema()`/`Schema()`) silently accepted a record
  named after a scalar keyword (e.g. `string`) or `any` — a record type
  position can never resolve to it, since a bare name resolves to the
  builtin scalar first. `osd.py`'s parser already rejected this; `Schema.check_refs`
  now rejects it too, so both surfaces agree.
- Fixed [#264](https://github.com/omnist-dev/omnist/issues/264) (spec S-7):
  `nullable(ref(...))` raised a bare `AttributeError` instead of `SchemaError`.
  `nullable()` now checks for `Ref` explicitly, same as its existing `AnyType`
  check, and points the caller at cardinality `[0,1]` instead.
- Closed [#265](https://github.com/omnist-dev/omnist/issues/265): added a
  test locking in that `infer()` sets a repeated label's cardinality
  `min=0` whenever *any* sample has more than one occurrence — never the
  smallest count observed across samples (the behavior was already
  correct; only the multi-sample case was untested).
- Closed [#266](https://github.com/omnist-dev/omnist/issues/266): added a
  test locking in that `normalize()`'s tie-break for a merged block is the
  alphabetical minimum of the block, not declaration order (behavior was
  already correct; every existing test happened to have the two orders
  coincide).
- Closed [#267](https://github.com/omnist-dev/omnist/issues/267): tightened
  `extract()`'s determinism test to assert the exact expected message
  instead of "one of three legitimate reasons," and removed a stale
  comment claiming iteration-order nondeterminism that doesn't actually
  exist (`env` is a dict with guaranteed insertion order); added a second
  variant confirming the rule is declaration order, not alphabetical.
- Closed [#268](https://github.com/omnist-dev/omnist/issues/268): added a
  test locking in the documented YAML sharp edge where a bare, unquoted
  `12:00:00` resolves to the integer `43200` (YAML 1.1 sexagesimal
  resolution — PyYAML's behavior, not an omnist choice, with no read-side
  workaround).

## [v0.7.12] — closed read_xml's node-budget gap

- Fixed [#260](https://github.com/omnist-dev/omnist/issues/260):
  `read_xml` had no node-count ceiling at all, unlike the other three
  readers after #256's fix. XML has no aliasing mechanism to create a
  DAG the way YAML anchors do, and `defusedxml` already blocks DTDs
  (closing the classic entity-expansion vector upstream) — so this
  wasn't a known exploit, just a defense-in-depth gap where one reader
  didn't share the same size ceiling as the rest. `_xml_to_node` now
  threads the same `_MAX_NODES` budget counter through its recursion
  that `build_node` uses, raising `DocumentError` once the ceiling is
  exceeded.

## [v0.7.11] — closed a YAML alias-amplification hole

- Fixed [#256](https://github.com/omnist-dev/omnist/issues/256):
  PyYAML resolves `*alias` references as shared object identity (a DAG),
  not clones. `build_node`'s cycle guard only detected a literal cycle
  (a value that is its own ancestor on the current path), not a shared
  DAG node reached via two different, non-ancestor paths — so a chain of
  doubly-referenced anchors ("billion laughs") got walked in full at
  every occurrence, materializing `O(2**n)` nodes from an `O(n)`-sized
  source text. `_MAX_DEPTH` didn't help either: the attack is shallow
  and wide, not deep.
  `build_node` now threads a shared running node-count budget through
  its recursion (same pattern as the existing `seen` cycle-guard),
  rejecting once `_MAX_NODES` (1,000,000) is exceeded — chosen with
  ~7.5x headroom above the ~132,001 actual node-visits the project's own
  "100k-edge document" performance benchmark
  ([why-omnist.md](docs/why-omnist.md#performance)) requires, confirmed
  by running that exact benchmark shape through the new guard uncapped
  before picking the number.
  Reported via cross-implementation checking against the Rust port
  (omnist-rs#42).
- Version bump to 0.7.11.

## [v0.7.10] — Doc.add()/set() now enforce combined cursor+subtree depth

- Fixed [#255](https://github.com/omnist-dev/omnist/issues/255):
  `Doc.add()`/`Doc.set()` called `build_node` with the default `depth=0`,
  ignoring how deep the cursor performing the mutation already was in
  the tree — so a mutation at a deep cursor could silently produce a
  document exceeding `_MAX_DEPTH` (200) with no `DocumentError`. `Doc`
  now carries its own `depth` (incremented on every cursor returned by
  `edges()`/`get()`/`get_one()`/`child()`), threaded into `build_node`
  from `add()`/`set()` as `self.depth + 1`.
  Reported by the omnist-ts port (issue omnist-ts#37/#70) and confirmed
  independently in Python via cross-implementation checking against the
  Rust port.
- `Doc.__init__` gains a new `depth: int = 0` parameter — additive and
  call-compatible with every existing call site, not a breaking change
  under the [stability policy](docs/stability.md); the frozen signature
  table in `tests/test_public_api.py` is updated to match.
- Version bump to 0.7.10.

## [v0.7.9] — fixed non-deterministic prune() output ordering

- Fixed [#253](https://github.com/omnist-dev/omnist/issues/253):
  `Schema.prune()`'s output environment ordering was non-deterministic
  across process runs, since `PYTHONHASHSEED` randomizes `str` hash
  values (and so `set` iteration order) by default. `prune()` built its
  result by iterating a `set` of reachable record names rather than the
  input schema's own (insertion-order-stable) `env` dict, so the same
  input could come back with a different record order each run.
  Reported by the omnist-ts port's cross-implementation differential
  testing — thanks for the clean repro and suggested fix direction.
  `prune()` now iterates `env` filtered to survivors, so the output
  order always matches the input's declaration order.
- Version bump to 0.7.9.

## [v0.7.8] — CI gate for doc-example coverage

- Added `tools/check_doc_examples.py`, run as a new `doc-examples` job in
  CI on every PR: diffs `docs/*.md` against the base branch and fails if
  any added/changed code block lacks a `<!-- verified-by:
  path::test_name -->` or `<!-- doc-illustrative -->` marker. This is a
  presence check only — it doesn't (yet) confirm a `verified-by` marker
  is honest, i.e. that the named test really asserts the doc's exact
  literal text. See issue #249 for that stronger check, filed for design
  review rather than built now.
- Documented the marker convention in `docs/testing.md`'s new
  "Doc-example coverage" section, with the version-string bug (#248) as
  the motivating example of why a passing, plausibly-named test isn't
  proof of anything on its own.
- `tools/check_doc_examples.py` ships with its own test suite
  (`tests/test_check_doc_examples.py`, 100% coverage), run against real
  throwaway git repos rather than mocked git output.
- Version bump to 0.7.8.

## [v0.7.7] — documentation examples audited and backfilled

- Ran a full audit of every code example across `docs/*.md` (212 fenced
  blocks in 29 files) to determine which are actually verified against
  their exact displayed output, not just "a test with a plausible name
  exists somewhere." Found 27 real gaps and 2 doc claims that had
  drifted into being factually false.
- Fixed two false claims: `docs/design/openness.md` said `any` "does not
  parse today" (it has shipped since v0.5.0); `docs/design/cli-spec.md`
  said `omnist/cli.py` "doesn't exist yet" (it has for weeks).
- Fixed the stale version strings in `docs/api.md` (`0.1.3`) and
  `docs/cli.md` (`0.2.9`) — both had drifted for 5+ releases because the
  test guarding them checked the *live* `__version__`, never the doc's
  own literal text. Added a regression test that reads both docs'
  literal strings directly and compares them to the live version, so
  this can't recur silently.
- Backfilled all 27 gaps with tests asserting the *exact literal text*
  each doc shows, not a derived property (`.ok`, a substring, sorted
  keys) standing in for it — that substitution is what let the version
  bug hide behind a passing, plausibly-named test in the first place.
- Version bump to 0.7.7.

## [v0.7.6] — deck slide title clarity

- Retitled the "The algebra, in code" deck slide to "Schema algebra, in
  code" — the original title was ambiguous about which algebra on first
  read.

## [v0.7.5] — 100% line coverage, deck slide reorder

- Closed the repo's last remaining coverage gaps, bringing the whole
  repository (not just the `omnist` package) to 100% line coverage.
  Every missing line was individually classified before being fixed:
  defensive `assert False, "expected X"` trip-wires that, by
  construction, never execute while the suite passes got a
  `# pragma: no cover` and a one-line reason, not a test written to
  deliberately break the library. Genuinely rare-but-real branches (a
  helper's mismatch case Hypothesis rarely generates by chance, a
  recursion base case at max depth, a NEL-handling branch not hit by
  every Hypothesis seed) were forced deterministically with a direct
  unit test or an explicit `@example(...)`, not left to random-seed
  luck. Two branches turned out to be unreachable dead code on
  inspection — an empty-`env` `Schema` the constructor can't actually
  produce, and a `write_toml` failure path that never fires once the
  root is constrained to a list (verified directly against a
  3000-example run) — and were deleted rather than tested around.
- Reordered the introduction deck: the JSON/YAML/TOML/XML format-grid
  slide now follows directly after the OML tree-diagram slide, since
  it's the direct payoff of "here's the tree" -> "here's that tree in
  four formats" -- previously it was separated from OML by the OSD
  automaton slide, an unrelated schema-level concept.
- Updated `docs/testing.md` and `docs/presentation.html` to state the
  now-accurate 100% coverage figure (previously 99%).

- Added a "The algebra, in code" slide to `docs/presentation.html`,
  showing `compatible_with`, `equivalent`, `normalize`, and `extract`
  called against the deck's running Service/Database example — the
  algebra was named on two other slides but never actually demonstrated.
  Every call in the code panel is verified against the real library, not
  hand-typed.
- Fixed #243: cold-loading a direct link to certain slides (e.g.
  `presentation.html#/12`) landed one slide early, a bug inside
  reveal.js's own hash-parsing internals. Rather than depend on that
  parse, the deck now re-derives the intended slide from `location.hash`
  itself and explicitly forces it after init settles, overriding
  whatever reveal landed on. Root load and normal navigation (swipe,
  keyboard, click) are unaffected.
- Fixed #239: closed a coverage gap in `omnist/oml.py`'s compact-array
  writer — the empty-record (`{}`) branch of `_write_array_element` had
  no test. `omnist/` is back to 100% line coverage.

## [v0.7.3] — introduction deck now scales on mobile

- Rebuilt `docs/presentation.html` on reveal.js (MIT, vendored) instead of
  a hand-rolled sidebar layout. The custom sidebar consumed ~45% of a
  phone-width screen, cramming every slide's content into what was left.
  Reveal.js uniformly scales the whole slide to fit any viewport, so a
  phone sees the same layout shrunk to fit, not a squeezed reflow.
  Verified across mobile/tablet/desktop viewports.
- Regenerated `docs/images/og-presentation.png` from the new title slide.

## [v0.7.2] — introduction deck, and one example everywhere

- Added `docs/presentation.html`: a self-hosted, maintainable introduction
  deck (plain HTML/CSS, real Mermaid diagrams, vendored so it has no
  external dependency), linked from the mkdocs nav and `why-omnist.md`.
  Rebuilt from a compiled, unmaintainable export as a follow-up, once the
  deck's own example had drifted from the docs'.
- Replaced the docs' `Team`/`Member` example with `Service`/`Database`
  across `README.md`, `schema.md`, `design/model.md` (both teaching
  sections, both Mermaid diagrams), `glossary.md`, and
  `examples/canonical_model.py`, matching the introduction deck so the two
  don't show a different example to the reader.
- Added Open Graph / Twitter Card meta tags and a generated social-preview
  image for the introduction deck.
- Corrected a factual claim on the deck's "Checked, not asserted" slide
  (100% line coverage → 99%, the true current figure) found while
  verifying the deck's claims against the repository.

## [v0.7.1] — beta hardening

A batch of hardening work in response to an external QA audit. No
public API changes; safe to upgrade from 0.7.0 without any migration.

- **Bug fix: `infer`/`validate` no longer crash on pathologically deep
  documents.** A `Doc` built directly from a hand-assembled node deeper
  than 200 levels (bypassing the reader's construction-time depth cap)
  could overflow the call stack with a raw `RecursionError` in `infer`,
  and in `validate` against a recursive schema. They now raise a clean
  `DocumentError` naming the limit — matching the reader and writer
  guards. Only inputs that previously crashed are affected; no valid
  input changes.
- **The stability policy is now mechanically enforced.** A new
  `tests/test_public_api.py` freezes the public API surface
  (`__all__` plus every exported name's signature) and fails CI if it
  drifts, turning the deprecation-cycle promise from discipline into a
  gate.
- **Known-limitations page.** A new [`docs/limitations.md`](docs/limitations.md)
  collects the deliberate edges of the model — the four expressiveness
  gaps, `compatible_with` vacuity inside `any`, the depth limit, format
  lossiness, and XML's data-profile narrowness — each linked to its
  full explanation.
- **Dev/CI hardening.** `coverage` is now a declared dev dependency
  (so the documented coverage workflow runs from a fresh
  `pip install .[dev]`); `mypy --strict` now also covers `tools/`; and
  a weekly, non-gating benchmark workflow tracks performance without a
  flaky latency gate.

## [v0.7.0] — beta

Omnist is now **beta**. The new [stability policy](docs/stability.md)
states what that means precisely: the Document and Schema models, the
OSD/OML grammars (additive-only), the public API surface, and the
exception types now change only through a deprecation cycle (deprecate
in one minor release, remove no earlier than the next). Beta is not
1.0 — v1.0 remains gated on the `any`-type openness decision.

Two behavior fixes found in the pre-beta review:

- **Writers no longer crash on deeply nested Documents.** `write_*`,
  `check_*`, and `Doc.to_data()`/`to_grouped()` on a Document nesting
  past 200 levels now raise a clean `WriteError`/`DocumentError` naming
  the limit — matching the readers' existing parse-depth cap — instead
  of a raw Python `RecursionError`. The limit is one shared constant
  across readers and writers. (A `Doc` built directly from a raw
  hand-assembled node can still overflow `validate`/`infer`; this is
  documented in the API reference.)
- **`--arrays` on OSD-only CLI commands is now an error.** `infer`,
  `schema format`, and `schema normalize` previously accepted the flag
  as a silent no-op; they now reject it with exit code 2 and a message
  pointing at the commands it applies to (`format`, `convert --to
  oml`).

Docs coherence pass: `guide.md` now covers the `any` type, `#`
comments, `[...]` arrays, compact mode, `schema lint`, and the four
real-world worked examples; glossary entries added for all of those;
the stability policy and the three design records
(`any-type-spec`, `openness`, `cli-spec`) are in the site nav; the new
write-depth limit is documented in the API reference and every format
page.

## [v0.6.0] — `[...]` array syntax for OML

Adds `[...]` array syntax to OML as pure syntactic sugar for repeated
same-label edges — `label: [v1, v2, ..., vn]` expands at parse time to
`n` repeated `label:` edges at that exact position. There is no array
type in the Document model: an array is edge-multiplication sugar, not
a value, so nesting (`[[1,2]]`) is rejected, and no other codec (OSD
included) is touched.

- **Reader**: unconditional, no flag — any `.oml` file may use array
  syntax once written with it; old files without arrays parse
  identically. Array elements may be a scalar, `null`, or a `{ }` brace
  subtree, but never another array. Comma is the only element
  separator (a bare newline/`;` is a `ParseError`); a trailing comma is
  legal; `[]` (empty) is a `ParseError`, not a zero-edge expansion;
  comments and newlines inside `[...]` are ordinary trivia, same as
  everywhere else.
- **Writer**: `write_oml(node, *, indent=2, arrays=False)` — default
  `False` is byte-identical to today's output for every existing
  caller. `arrays=True` collapses any maximal run of ≥ 2 consecutive
  same-label edges into array form (a run of 1 stays scalar; a run
  never merges across a different label in between); pretty mode never
  wraps an array onto multiple lines, compact mode is always inline.
  `read_oml(write_oml(node, arrays=True)) == node` holds
  unconditionally — arrays never reorder edges. `Doc.to_oml()` passes
  `arrays=` through.
- **CLI**: `--arrays` added to the same five subcommands `--compact`
  touched in #133 (`format`, `convert`, `infer`, `schema format`,
  `schema normalize`). For the three OSD-only commands (`infer`,
  `schema format`, `schema normalize`) the flag is accepted but has no
  effect, since OSD has no array syntax.
- **Docs**: a new "Arrays" section in `docs/formats/oml.md`, the ABNF
  `array` production in `docs/design/oml-grammar.md`, `arrays=`/
  `--arrays` documented in `docs/api.md`/`docs/cli.md`/
  `docs/design/cli-spec.md`, and a use-case note in
  `docs/examples/index.md` pointing at the long lists the four
  real-world examples already contain.
- **Real-world examples**: each of the four worked examples gets a
  committed `<fixture>.arrays.oml` sibling (`write_oml(..., arrays=True)`
  of the exact same Document as the existing `.oml`), linked from each
  example's fixtures table and asserted byte-exact plus
  Document-equivalent by `tests/test_examples_*.py`.

See issue #218 for the full locked design and the acceptance/rejection
table.

## [v0.5.7] — package.json, GitHub Actions, and sitemap.xml examples

Documentation/examples-only release, no `omnist` package logic changed.
Adds three more real-world worked examples alongside pyproject.toml,
and a new overview page tying all four together:

- `examples/package-json/`: models npm's package.json -- deliberately
  contrasted with pyproject.toml as a format with no formal spec at
  all, only prose docs and a third-party schema.
- `examples/github-actions/`: models a GitHub Actions workflow,
  first-party fixtures from this repo's own `.github/workflows/`. Finds
  a genuine codec-level issue: PyYAML's YAML 1.1 boolean-coercion rule
  turns a bare `on:` key into the Python boolean `True`, which
  `read_yaml` correctly refuses (`DocumentError`) -- three of the four
  fixtures fail to even read, not just validate. Highest `any`
  proportion of the four examples (75%).
- `examples/sitemap/`: models the sitemaps.org protocol -- structurally
  the cleanest of the four (0% `any`), but surfaces a fourth gap
  category none of the others did: value refinement (OSD has no enum
  or numeric-range constraint, so an out-of-spec `changefreq`/`priority`
  still validates). Also the only example where `schema=` isn't a
  no-op: `lastmod` gets upgraded to a real `date`.
- `docs/examples/index.md`: a comparison table across all four
  (computed from the schemas by `tests/test_examples_index.py`, not
  typed by hand), the four-gap taxonomy, a spec-rigor spectrum, and the
  consolidated "designing a format for OSD" lessons list (relocated
  from `pyproject.md`, generalized with findings from all four).
- `convert.py` in the pyproject.toml and package.json examples now call
  `read_toml`/`read_json` with `schema=` -- the idiomatic call, though a
  no-op for those two schemas (no `date`/`time`/`datetime`/`number`
  field in either).
- `mkdocs.yml` nav restructured: the four examples plus the overview
  now live under one "Real-world examples" section instead of flat
  top-level entries.

## [v0.5.6] — commit OML fixtures for the pyproject.toml example

Documentation/examples-only release, no `omnist` package logic changed.
Follow-up to v0.5.5: each `examples/pyproject/fixtures/*.toml` now has a
committed `.oml` sibling, generated by `write_oml` and asserted exact by
a new test (`test_committed_oml_matches_write_oml`), so the mapping is
readable without running `convert.py`. `docs/examples/pyproject.md`
links to each.

## [v0.5.5] — pyproject.toml worked example

Documentation/examples-only release, no `omnist` package logic changed.
Adds `examples/pyproject/`: an OSD schema modeling the real
`pyproject.toml` spec (PEP 517/621/639/794), three TOML fixtures
(first-party, an official PSF teaching example, and one synthetic
fixture — no third-party project files, to avoid any copyright
ambiguity), and `convert.py` validating each against the schema and
printing the resulting OML.

`docs/examples/pyproject.md` is the companion write-up: a candid
can/cannot-model analysis (unions, open key sets, cross-field
constraints — OSD structurally can't express any of the three), a
false-reject vs. false-accept breakdown, a comparison against
hand-written JSON Schema, and a "lessons learned" section on what
structures to avoid when designing a new format meant for OSD.
`tests/test_examples_pyproject.py` keeps the doc's claims (field counts,
which fields are `any`) from drifting out of sync with the schema.

## [v0.5.4] — document `#` comments in OSD/OML

Documentation-only release: `#` line comments have always worked in both OSD
(`docs/schema.md`) and OML (`docs/formats/oml.md`), but weren't documented as
a first-class feature. Both docs now cover syntax, valid positions, a worked
snippet, and the fact that comments are lexical trivia — they never
round-trip through `to_osd()`/`write_oml()`. Each new doc snippet is mirrored
as an executable test in `tests/test_docs.py`.

Also adds a parametrized guard test (`tests/test_grammar_docs.py` for OSD,
`tests/test_oml.py` for OML) sweeping stray out-of-grammar characters
(`@ & / ^ % ! ~` backtick `$`) in bare/unquoted position, asserting each is
rejected with `SchemaError`/`ParseError` as already documented. No parser or
grammar changes — this closes a gap in what was *tested*, not a behavior
change.

## [v0.5.3] — uniform `--json` across the CLI

`--json` is now a **global flag on every command** (`format`, `convert`,
`check`, `infer`, `validate`, and all `schema` subcommands), not just
`validate` and `schema lint`. It gives one uniform, machine-readable guarantee:
**on any data/parse/IO error, the command prints `{"ok": false, "message",
"errors"}` to stdout (stderr empty) with the exact same exit code** — so a
wrapper (CI, a Node/Python subprocess) can detect and classify failure from any
command without string-matching stderr. Result-bearing commands (`check`,
`schema is-empty`/`compatible-with`/`equivalent`, plus `validate`) also emit
their structured result as JSON under `--json`, matching `--result-format json`.

This is additive and opt-in: **no behavior changes without `--json`.** Every
command is byte-identical to before when the flag is absent, `validate --json`
and `schema lint --json` are byte-identical to their prior output, and exit
codes are unchanged in every case. argparse usage errors (unknown flag, missing
required argument) remain argparse's own stderr message + exit `2` — a
deliberate boundary, since those are caller bugs rather than data errors.
`--result-format` is unchanged and retained (it still offers `oml` encoding).

- Shared `--json` via an `argparse` parent parser on every subparser; the
  per-command `--json` on `validate`/`schema lint` is now that inherited flag.
- Uniform error shape from one source (`_json_error`); every in-handler error
  site funnels through a `_fail(args, exc, code)` helper and `main()`'s handler
  honors `--json`.
- Docs: `docs/cli.md` gains a "Machine mode: `--json`" section and a scripting
  note; `docs/design/cli-spec.md` kept in sync.

## [v0.5.2] — `infer --allow-any`

An opt-in, **default-off** mode for `infer` that turns its two hard failure
points — a label that is an object in some samples and a scalar in others,
and a label that is a scalar of more than one kind — into `any` fields
instead of raising, for bootstrapping a draft schema from messy or
polymorphic data (webhooks, scraped APIs).

The invariant is preserved, just made conditional: **`infer` never emits
`any` by default.** `infer(samples)` and `infer(samples, allow_any=False)`
behave exactly as before — still raising `SchemaError` at both conflict
points, byte-for-byte. Passing `--allow-any` / `allow_any=True` is itself
the deliberate act; the guardrail moves from per-field to per-invocation,
not gone. And it is **loud**: the CLI reports on stderr exactly which fields
it opened and why, so the result reads as a to-tighten draft, not a
finished schema.

- New `infer_with_report(samples, root_name="Root", *, allow_any=False) ->
  (Schema, list[AnyFallback])` does the work; `infer` is now a thin wrapper
  returning just the schema. `AnyFallback` is a frozen
  `(location, reason)` dataclass. Both are exported.
- `omnist infer --allow-any` writes the schema to stdout (still pipeable)
  and the summary to stderr. Without the flag, a conflicting sample errors
  exactly as today.
- A field opens at the **narrowest node** — the conflicting field only.
  Clean nested structure still infers as a record. Wherever `infer` did
  fall back, the result has vacuous compatibility at that field, like any
  hand-written `any`.

Additive, opt-in surface with no default-path change — hence a patch bump.

## [v0.5.1] — `schema lint`

A new `omnist schema lint` command (and `omnist.lint` API) runs
non-destructive structural diagnostics on a *schema* — the counterpart to
`validate`, which checks a *document*. It **reports, never mutates**:
`prune`/`normalize` remain the transforms that fix things; `lint` only
surfaces them. Four checks:

- `unsatisfiable-record` (`warning`) — a reachable record no finite
  document can match (e.g. a mandatory ref cycle).
- `unreachable-record` (`warning`) — a record defined but never reachable
  from the root; `prune` drops these.
- `duplicate-record` (`warning`) — two+ structurally identical records
  under different names; `normalize` merges them.
- `any-field` (`info`) — an inventory of every `any`-typed field, so a
  human can audit the schema's deliberate openings.

`lint(schema)` returns a sorted list of frozen `LintFinding(code, severity,
location, message)`. The CLI prints text by default or `--json`
(`{"ok", "findings"}`), supports a `--severity {info,warning}` filter, and
exits `1` if any surviving finding is `warning`-severity (an `any`-field
inventory alone stays `0`).

Internally, `minimize.normalize`'s partition-refinement core was extracted
into a public `equivalence_classes(schema)` (reused by `duplicate-record`);
`normalize`'s output is unchanged. Additive, passive surface — the model is
untouched — hence a patch bump.

## [v0.5.0] — the `any` type

A field may now be typed `any`: its value is accepted unchecked (any
scalar, `null`, or a subtree of any shape) while its label stays fixed
and counted, exactly like any other field. One example:

```
record Event {
    "id":   string,
    "type": string,
    "data": any,
}
root Event
```

This is the headline change to the model's core claim. Every release
through v0.4.x described the schema model as **closed by construction —
no escape hatches**. As of v0.5.0 that becomes **closed by default, open
only where explicitly marked**: `any` is the one sanctioned opening, and
it is disciplined rather than free-form —

- `any` already includes `null`; `any?` is rejected as redundant.
- `any` is a reserved type name (a record can't be named `any`).
- `infer` never produces `any` — every occurrence in a schema is one a
  human deliberately wrote, and is grep-visible in the schema text.
- Stated loudly, not buried: `compatible_with` is **vacuous** inside an
  `any` region. Checking ends exactly where `any` begins; a schema that's
  40% `any` gives compatibility verdicts that are 40% meaningless while
  looking authoritative. Use it for genuinely unowned data, and narrow it
  later with `infer` once you know the real shapes.

An open *map* / wildcard-record type remains refused, and stays refused —
that would open the label alphabet the whole algebra reasons over, not
just a value at a fixed leaf. See
[the openness decision record](docs/design/openness.md) for the full
argument and [the normative spec](docs/design/any-type-spec.md) for the
implementation.

Implementation, in order: core model + algebra (#192), grammar + parser +
public export (#193), semantic-oracle witness guarantee + fuzz coverage
(#194), and this documentation sweep (#195).

## [v0.4.3] — `omnist validate --json`; Python 3.14 in CI

`omnist validate` gains a `--json` flag: a machine-readable `{ok, message,
errors}` result on stdout, built on the structured `.errors` list
`ParseError` has exposed since v0.4.1. Independent of `--result-format`
(which stays as it was) -- each `errors` entry also carries the stable
`code` (`unexpected-field`, `cardinality`, `type-mismatch`,
`null-not-allowed`, `shape-mismatch`), and read/parse errors, normally a
bare `error: ...` on stderr, are reported in the same shape on stdout
instead (`"errors": []`, message carries the parse error), so a CI
pipeline shelling out to `validate` no longer has to parse either form of
free text:

- Success: `{"ok": true}`.
- Conformance failure: `{"ok": false, "message": str, "errors": [{"path": str, "code": str, "message": str}, ...]}` — one entry per problem.
- Format-syntax failure (invalid input text, or a malformed schema): same shape, `"errors"` always `[]`.

Exit codes (`0`/`1`/`2`) and every existing (non-`--json`) output are
unchanged — this is purely additive.

Also: Python 3.14 is now in the CI test matrix alongside 3.11-3.13 and
passes without changes.

See [issue #182](https://github.com/omnist-dev/omnist/issues/182).

## [v0.4.2] — Cleanup: pinned dev deps, simplified XML parser, tidier docs

Three small, unrelated cleanup items surfaced by review (no observable
behavior change for any normal caller):

- Dev dependencies (`pytest`, `pyyaml`, `tomli_w`, `defusedxml`, `ruff`,
  `hypothesis`, `jsonschema`, `mypy`) are now pinned with `~=` compatible-
  release constraints, instead of unconstrained, to avoid unexpected CI
  breakage from upstream updates.
- `_xml_parser()` no longer makes a redundant, unused import of the
  top-level `defusedxml` package before importing the actual
  `defusedxml.ElementTree` submodule it needs. As a side effect, the
  `ImportError` message is now consistent even in the edge case where the
  top-level package imports fine but the `ElementTree` submodule itself
  doesn't.
- `docs/api.md`'s `ParseError` table row is shorter, pointing to the
  [Schema-directed deserialization](deserialization.md) page for the
  `.errors` detail instead of repeating it inline.

See [issue #177](https://github.com/omnist-dev/omnist/issues/177).

## [v0.4.1] — `ParseError` exposes structured validation errors

`ParseError` now carries a `.errors` attribute — the full list of
`(path, message, code)` problems `materialize()` (and schema-directed
readers) found, not just the formatted message string. A caller building
an API error response can now iterate `.errors` directly instead of parsing
`str(exc)`. Purely additive: `.errors` defaults to `[]`, and every existing
`str(exc)` message is unchanged, so this is a patch release, not another
minor bump.

Format-syntax `ParseError`s (invalid JSON/YAML/TOML/XML text, not a schema
conformance problem) have nothing to put in `.errors` — it's simply empty
for those, same as before this attribute existed.

See [issue #174](https://github.com/omnist-dev/omnist/issues/174).

## [v0.4.0] — XML parsing fails closed (BREAKING)

**Breaking:** `read_xml()` now requires `defusedxml` and raises `ImportError`
immediately if it's missing, instead of silently falling back to the
standard library's `xml.etree.ElementTree` with an `UnsafeXMLWarning`. The
fallback left applications parsing untrusted XML vulnerable to entity
expansion (billion laughs) and XXE attacks whenever the optional dependency
happened not to be installed — a warning to stderr is easy to miss in a
server environment, and merely warning didn't stop the unsafe parse from
happening. Install `defusedxml` (or the `xml`/`all` extra) to use `read_xml`.

`UnsafeXMLWarning` remains exported from `omnist.errors` for backward
compatibility (e.g. existing `warnings.filterwarnings` calls referencing
it), but nothing in omnist raises it anymore.

Identified during an external code-quality review of the codebase; see
[issue #173](https://github.com/omnist-dev/omnist/issues/173).

## [v0.3.0] — The paper's algorithm suite, complete and triple-verified

0.2.x was one continuous arc from "the schema model exists" to "the schema
model implements everything the underlying research (Lee & Cheung, CIKM
2010) actually promised." That arc is done, and several of its 0.2.x
releases changed observable behavior under a patch-version bump (v0.2.15
`normalize`, v0.2.22 `Doc.set`, v0.2.23 lenient-JSON and temporal
parsing) — semver debt this 0.3.0 bump settles retroactively, and a point
where naming a real milestone is honest rather than arbitrary:

- **Every operation the paper describes is implemented**: `validate`,
  `compatible_with`, `equivalent`, `normalize`, `prune`, `is_empty`,
  `extract`, `infer` — the full surface of Algorithms 1-5 plus inference,
  all as `Schema` methods and CLI subcommands.
- **The algebra is checked three independent ways**, not just tested
  against examples: bidirectional subschema inclusion (`ops/subschema.py`,
  the paper's Algorithm 4), minimize-and-isomorphism (`ops/isomorphic.py`,
  Theorem 4), and brute-force enumeration against set-theoretic ground
  truth (`tools/semantic_oracle.py`, ~2.5M checks). All three are required
  to agree, on every CI run.
- **Rigor gates, not just claims**: 100% line coverage, `mypy --strict`,
  property-based fuzzing, formal ABNF grammars verified against the
  parsers, every documentation code example executed as a test.
- **Performance measured and published**, not implied — see
  [docs/why-omnist.md#performance](https://omnist.dev/why-omnist/#performance).

**Versioning going forward**: starting with 0.3.0, a behavior change gets
a minor-version bump and an explicit CHANGELOG callout, not folded silently
into a patch release — a soft stability commitment, short of leaving
alpha. Breaking changes are still possible during 0.x; they'll just be
easier to spot.

## [v0.2.28] — OML: quote labels ending in a newline

### Fixed

- `write_oml` emitted a label with a trailing newline (e.g. `"A\n"`) as a
  *bare* label, producing OML that failed to parse back — Python's `$`
  anchor in `_BARE_LABEL_RE` also matches just before a trailing `"\n"`,
  so such labels slipped past the "needs quoting" check. The regex now
  anchors with `\Z` (true end-of-string only), so labels ending in a
  newline are written as quoted strings with the newline escaped, and the
  read/write round-trip holds. Found via issue
  [#168](https://github.com/omnist-dev/omnist/issues/168)'s differential
  fuzzing but pre-existing and unrelated to the scanner rewrite (the
  writer was never touched by it). Issue
  [#170](https://github.com/omnist-dev/omnist/issues/170).

## [v0.2.27] — OML scanner rearchitected around a single-pass master regex

Performance follow-up to the B1 O(n^2) fix in
[#155](https://github.com/omnist-dev/omnist/issues/155)/v0.2.21 and the
honest OML-read outlier published in `docs/why-omnist.md#performance`
(issue [#168](https://github.com/omnist-dev/omnist/issues/168)):

### Changed

- **Performance:** `oml.py`'s reader is now a single pass driven by one
  compiled master regex (`VERBOSE`, named groups, alternation order mirrors
  the grammar's documented priority) with `match(s, pos)` + `lastgroup`
  dispatch, instead of per-token-kind regex attempts feeding a materialized
  list of `Token` objects. Whitespace/comment/separator skipping happens
  inside the regex engine; a fast no-escape single-line string pattern
  handles the common string case in C, falling back to the existing
  char-by-char scanner only for `"""` multiline strings and strings
  containing a backslash or control character. Line/col are computed
  lazily — only when a `ParseError` is actually raised, by counting
  newlines up to the failing offset — instead of being tracked per token.
  Scalar conversion (`int()`/`float()`/date parsing) happens only when the
  parser consumes a token, not when it's scanned. Measured on the two
  benchmark shapes from `docs/why-omnist.md#performance` (same machine,
  same run): the string-heavy 33k-record shape improved from 1.06 to 0.48
  us/char, and the simple k:v shape from 1.04 to 0.53 us/char — both well
  inside the acceptance floor set for this change. Behavior is byte-for-byte
  identical to v0.2.26, including several undocumented scanner quirks
  (exact `ParseError` positions/text in a handful of edge cases) that are
  now preserved deliberately with inline comments rather than accidentally
  — verified by differential fuzzing the new scanner against the v0.2.26
  scanner over the full test corpus, the grammar doc's worked examples,
  2500 Hypothesis-generated documents, and a battery of adversarial
  rejects, with zero divergence. `docs/why-omnist.md#performance`'s OML
  read row and guidance sentence are updated to match.

## [v0.2.26] — README payoff-first pitch, rigor story, measured performance

Docs-only; closes out the codebase-review plan (issue
[#154](https://github.com/omnist-dev/omnist/issues/154), item PR-6 /
[#160](https://github.com/omnist-dev/omnist/issues/160)):

- README's "Why Omnist" now leads with what you can *do* (CI-gate schema
  evolution with a decidable `compatible_with`; one model across five
  formats; `extract` a big schema down to one service's subset) before the
  model mechanics, and gains a "Boringly correct" section stating the
  verification story plainly — 100% coverage, `mypy --strict` gate,
  fuzzing, verified ABNF grammars, executed doc examples, and the schema
  algebra checked three independent ways.
- `docs/why-omnist.md` gains a measured **Performance** section (100k-edge
  document and 200-record schema numbers, with the honest OML-read outlier
  called out) — transparency, not benchmarketing.
- `docs/README.md`'s CLI row no longer says "planned surface"; the CLI has
  been fully implemented since v0.2.8 and now lists all twelve commands.

## [v0.2.25] — Type annotation hygiene + CI typecheck gate

Mechanical type-annotation work (issue [#159](https://github.com/omnist-dev/omnist/issues/159),
PR-5 of the codebase review in [#154](https://github.com/omnist-dev/omnist/issues/154)).
All `mypy --strict` errors fixed; passes CI typecheck gate added to the workflow.

### Changed

- **Internal:** All `mypy --strict` errors resolved across `omnist/` (75 errors in 14 files);
  missing type annotations and generic type arguments now complete. Two invariant
  restructures made locally provable via assertions (`first_offender` in `extract.py`,
  `report` in `cli.py`).
- **CI:** Added `typecheck` job to workflow (`.github/workflows/test.yml`) running
  `mypy --strict omnist` to catch type regressions.
- `docs/testing.md` updated with typecheck gate documentation in CI section.

## [v0.2.24] — Brute-force semantic oracle for the schema algebra

Review follow-up (issue [#158](https://github.com/omnist-dev/omnist/issues/158),
PR-4 of the codebase review in [#154](https://github.com/omnist-dev/omnist/issues/154)).

### Added

- **`tools/semantic_oracle.py`** — a brute-force semantic oracle: enumerates
  a finite universe of documents, builds a family of schemas (systematic
  single-record schemas covering every scalar x cardinality combination,
  a few structural schemas -- an empty record, a known-empty mandatory
  cycle, optional self-recursion -- plus seeded-random two-record
  schemas), computes each schema's ground-truth language directly via
  `Schema.validate()`, and checks `compatible_with`, `is_empty`,
  `normalize`, `prune`, and `extract` against that ground truth. This is a
  *third* independent correctness check on the schema algebra, alongside
  `compatible_with`'s own Algorithm 4 inclusion test and the
  minimize+isomorphism Theorem-4 oracle (`omnist/ops/isomorphic.py`,
  cross-checked in `tests/test_fuzz.py`) -- brute-force enumeration against
  `validate()` itself cannot share a bug with either algorithm, since
  `validate()` is the ground-truth definition of a schema's language.
  `False` answers from `compatible_with` are vindicated against an
  extended (larger-cardinality) universe and, failing that, a family of
  targeted minimal witnesses built from the schema's own cardinality/type
  requirements; any pair still unresolved is reported as
  needs-manual-review rather than failing the run (a bounded-universe
  artifact, not a bug). Run it directly with `python3
  tools/semantic_oracle.py`; see `tools/README.md`.
- **`tests/test_semantic_oracle.py`** — a bounded, deterministic version of
  the same five checks over a much smaller universe and schema family, so
  it runs as part of the normal test suite (a little over a second) rather
  than as a separate slow lane.
- `docs/testing.md` now documents the algebra as checked three independent
  ways: Algorithm 4 inclusion, Theorem-4 minimize+isomorphism, and
  brute-force enumeration against ground truth.

## [v0.2.23] — Strictness/self-consistency alignments: JSON `Infinity`->`null`, XML mixed-content `ParseError`, narrowed temporal spellings

Review follow-ups (issue [#157](https://github.com/omnist-dev/omnist/issues/157),
PR-3 of the codebase review in [#154](https://github.com/omnist-dev/omnist/issues/154)).
Three behavior alignments, all choosing strictness/self-consistency over
silent permissiveness (user-approved in review):

- **Changed:** `write_json`'s lenient (default) mode used to emit the
  literal, non-standard tokens `Infinity`/`-Infinity`/`NaN` at a
  `float('inf')`/`float('nan')` leaf — text that isn't valid JSON per the
  spec, even though `check_json` already flagged it an error-severity
  `float.special` adjustment (every *other* error-severity adjustment
  mutates the output to stay well-formed, e.g. XML's illegal-char ->
  U+FFFD substitution). Lenient mode now substitutes `null` at those
  leaves instead, so `write_json`'s output always parses under a strict
  JSON parser; the adjustment entry stays error-severity, with its message
  now noting the substitution (`"... is not valid JSON; wrote null"`).
  `strict=True` is unchanged: it still refuses via `WriteError` rather than
  writing anything. `docs/formats/json.md` and `docs/formats/overview.md`'s
  comparison row, which documented the old raw-emission behavior, are
  updated to match.
  **Test-suite note:** `tests/test_fuzz.py`'s
  `test_json_round_trip_modulo_documented_adjustments` asserted that a
  `float.special` leaf round-trips to an *equal* value (true under the old
  behavior, since Python's own lenient `json.loads` reads the raw
  `Infinity`/`NaN` tokens back as the same float). That's no longer true —
  the leaf now round-trips to `None`, not the original float — so the
  property's round-trip comparison is skipped for `float.special` the same
  way it already was for `temporal.stringified`, with the reasoning
  recorded in the test itself.
- **Changed (breaking):** `read_xml`'s `_xml_to_node` used to silently
  discard non-whitespace `elem.text` and any child's `.tail` when an
  element also has child elements (XML "mixed content") — the only place
  in the library where data vanished on *read* with no `check_*` even in
  principle to surface it. It now raises `ParseError` naming the element
  ("mixed content ... is outside the data-XML profile") instead. Pretty-
  printed XML — whitespace-only text/tail around child elements, which is
  exactly the shape `write_xml`'s own indenter produces — is unaffected and
  still parses. `docs/formats/xml.md`'s mixed-content row is updated from
  "not supported" (silently dropped) to "rejected with `ParseError`".
- **Changed (breaking):** schema-directed deserialization accepted a wider
  set of temporal string spellings than documented or than OML's own
  grammar defines, because it delegated straight to
  `datetime.fromisoformat`, which (beyond the documented hyphenated-date /
  colon-time / `T`-joined-datetime forms) also parses ISO 8601 basic format
  (`"20240101"`, `"120000"`), week dates (`"2024-W01-1"`), and a
  space-separated datetime — so a numeric-looking or otherwise
  undocumented-shaped string could silently become a `date`/`time`/
  `datetime` under a temporal schema. `materialize` (`deserialize.py`) now
  checks a candidate string's shape against the documented spellings
  *before* calling `fromisoformat`, rejecting anything else via the normal
  not-value-exact `ParseError` path. `Schema.validate`'s `matches_kind`/
  `_is_iso` (`schema.py`) had the identical wide-acceptance gap and is
  narrowed the same way, so `validate()` and `materialize()` agree exactly
  on every string — a document that validates is now guaranteed to
  materialize, and vice versa (asserted directly by a new parametrized
  test, `TestValidateMaterializeAgreement`, across the boundary spellings
  for all three temporal kinds).
  **Implementation note (judgment call):** the documented spellings were
  already defined once, as `_DATE_RE`/`_TIME_RE`/`_DATETIME_RE` in
  `oml.py` (OML's own tokenizer). Rather than duplicate them, that single
  definition now lives in `schema.py` and is imported into both `oml.py`
  and `deserialize.py`. `schema.py` was chosen as the home over leaving
  them in `oml.py` (or introducing a new module) by reading the actual
  import graph: `schema.py` only imports `errors.py` at module level (its
  one `document.py` use, inside `Schema.validate`, is a lazy in-function
  import), so it already sits below both `oml.py` and `deserialize.py` in
  the dependency order — adding `schema.py` as a module-level dependency of
  `oml.py` introduces no cycle, and `schema.py` already owned
  `matches_kind`/`_is_iso`, the other half of this same "what counts as a
  temporal string" concern.

## [v0.2.22] — Enforce the int-digit cap at construction; `Doc.set` replace-all semantics

Review follow-ups (issue [#156](https://github.com/omnist-dev/omnist/issues/156),
PR-2 of the codebase review in [#154](https://github.com/omnist-dev/omnist/issues/154)):

- **Fixed (breaking-adjacent):** `build_node` (and therefore `doc()`, every
  format reader, `Doc.add`, and `Doc.set`) used to accept Python ints beyond
  CPython's 4300-digit str-conversion guard. `check_oml` reported an empty
  (all-clear) report for such a document, and `write_oml`/`write_json`/
  `Doc.__repr__` then crashed with CPython's raw `ValueError` — silently
  breaking `write_oml`'s "the write always succeeds exactly" and
  `check_oml`'s "always an empty report" guarantees. The reader (`oml.py`)
  already enforced the 4300-digit cap on parse; the model now enforces the
  same cap at every construction/mutation path, raising a clean
  `DocumentError` whose message mirrors the OML reader's existing
  `_MAX_INT_DIGITS` error. The limit is defined once, in `document.py`
  (`_MAX_INT_DIGITS`); `oml.py` imports it rather than duplicating the
  literal. Detection compares the value as an int against `10**4300` —
  never via `str()`, since str-converting an out-of-range int is exactly the
  superlinear operation this guard exists to avoid triggering. `bool` (an
  `int` subclass, always `0`/`1`) is unaffected.
  Also fixed in passing: `read_json`/`read_yaml`/`read_toml` handed an
  over-limit integer literal straight to the standard library's own
  int-string conversion during parsing (`json.loads`/`yaml.safe_load`/
  `tomllib.loads` all convert a numeric literal to `int` while they parse),
  tripping the same CPython guard as a bare `ValueError` that wasn't a
  `JSONDecodeError`/`YAMLError`/`TOMLDecodeError` and so wasn't caught by
  the existing translation to `ParseError`. All three readers now catch that
  `ValueError` too and translate it to `ParseError`, consistent with every
  other parse-time failure.
- **Changed (breaking-adjacent):** `Doc.set(label, value)` used to replace
  only the *first* edge under a repeated label and silently leave later
  duplicates in place (`count()` still returned 2+, `get_one()` still
  raised). `set` now has replace-all semantics: it removes every edge under
  `label`, then inserts one new edge at the position of the first old
  occurrence (or appends, if `label` was absent) — `set` = `remove` + `add`.
  On a label that occurs once this is unchanged (replace it in place); on a
  repeated label, every duplicate now collapses into the one new edge.
  Docstring and `docs/api.md`/`docs/guide.md` updated to state the contract
  explicitly.

## [v0.2.21] — Fix O(n^2) OML tokenizer and XML nesting-depth guard

Review follow-ups (issue [#155](https://github.com/omnist-dev/omnist/issues/155),
PR-1 of the codebase review in [#154](https://github.com/omnist-dev/omnist/issues/154)):

- **Fixed:** `oml.py`'s `_Scanner._next` sliced `self.s[self.i:]` before
  running every token regex, copying the whole unconsumed suffix per token —
  O(n^2) overall. Measured before: 20k edges 0.70s, 80k edges (1.1MB) 11.2s,
  us/char roughly quadrupling as input doubled. Every `rest`-slicing site
  (STRING-family lookahead, DATETIME/DATE/TIME/NUMBER/INTEGER/IDENT
  matching, the `nan`/`inf`/`-inf` literals) now matches the compiled
  patterns directly against `self.s` with `pos=self.i`
  (`re.Pattern.match(string, pos)`), with no copy. Tokenizer behavior is
  byte-identical — verified against the full suite plus a new golden
  mixed-token round-trip fixture. After the fix, us/char is constant as
  input scales (20k: 0.28s, 80k: 1.17s, ~1.1us/char at both sizes).
- **Fixed:** `formats.py`'s `_xml_to_node` recursed with no depth guard, so
  a ~1000-level-deep XML document crashed with a raw `RecursionError`
  instead of the clean `DocumentError` every other reader raises via
  `build_node`'s `_MAX_DEPTH` (200). `_xml_to_node` now threads a depth
  counter and raises `DocumentError` at the same limit with the same
  message shape, importing `_MAX_DEPTH` from `document.py` rather than
  duplicating the literal. Verified at the exact boundary: 200 levels of
  nesting still parses, 201 raises `DocumentError`.

## [v0.2.20] — Flatten `omnist/canonical` into `omnist`

Refactor (issue [#144](https://github.com/omnist-dev/omnist/issues/144)):

- **Changed:** `omnist/canonical/` was a historical artifact — its docstring
  still framed it as a "design proposal implementation," but it was, and
  remains, the only implementation. Moved every module up a level
  (`omnist/canonical/document.py` -> `omnist/document.py`, etc.) and
  `omnist/canonical/ops/` -> `omnist/ops/`; deleted the now-empty
  `canonical` package. Internal-layout change only — the public surface
  (`import omnist`) is byte-for-byte unchanged (`dir(omnist)`/`__all__`
  identical before and after).

## [v0.2.19] — CLI prune/is-empty, infer/normalize doc note

Follow-ups from the user's review of the schema-operations initiative
(issue [#151](https://github.com/omnist-dev/omnist/issues/151)):

- **Added:** `omnist schema prune` (writes `Schema.prune()`'s result as OSD;
  `--compact`/`-o` as elsewhere) and `omnist schema is-empty` (prints
  `true`/`false` per `--result-format`, exit `0` if empty / `1` if not,
  mirroring `compatible-with`/`equivalent`) — CLI parity for the operations
  added in v0.2.14.
- **Changed (docs only):** decided and documented that `infer()` does
  **not** auto-normalize — the raw result keeps record names 1:1 with
  sample labels; call `.normalize()` on the result where a canonical
  minimal schema is wanted. Stated in the infer docstring, guide, and
  schema page with a test-backed example. `docs/layout.md`'s ops package
  description updated to list all six modules.

## [v0.2.18] — Consistency audit, validation error codes, 100% coverage restored

Closes out the schema-operations initiative with a sweep pass
(issue [#143](https://github.com/omnist-dev/omnist/issues/143)):

- **Added:** every validation `Error` now carries a stable machine-readable
  `code` (`unexpected-field`, `cardinality`, `type-mismatch`,
  `null-not-allowed`, `shape-mismatch`) alongside `path` and `message` —
  match on `.code`, not message text, when reacting programmatically.
  `str(ValidationResult)` output is unchanged.
- **Changed:** docs/docstrings audited for wording that predated the
  initiative — `normalize` is consistently described as the canonical
  minimal form (partition refinement), not "merge structurally-identical
  records"; `docs/design/model.md` gains a paper-correspondence table
  mapping every operation to its algorithm in Lee & Cheung (CIKM 2010).
- **Fixed:** the 100% coverage target is true again — `deserialize.py` and
  `cli.py` had silently drifted to 97%; real tests now cover the drifted
  lines, with `# pragma: no cover` used only for annotated, genuinely
  unreachable defensive guards. The coverage snapshot in `docs/testing.md`
  is regenerated from an actual run (previously had invented/stale counts).

## [v0.2.17] — Subschema extraction (#142)

**Added:** `Schema.extract(*labels)` / `omnist.canonical.ops.extract.extract(schema, keep)`,
implementing the paper's Algorithm 5 (ExtractSubschema) -- given a
permissible label set, produces the minimal subschema that only recognizes
documents built from those labels. This is the paper's headline
application: trimming a large shared schema (xCBL, in the paper) down to
just what a single document type needs. Fields whose label isn't kept are
deleted; deleting a *mandatory* (`min >= 1`) field invalidates the record
that had it, invalidation propagates transitively through mandatory refs,
and if the root itself is invalidated `extract` raises `SchemaError`
naming the first offending label and record rather than silently loosening
cardinality (a deliberate design decision -- see `ops/extract.py`'s
docstring). The result is `prune()`d and `normalize()`d before being
returned, same as Algorithm 5's own final MakeUseful + Minimize step. New
CLI subcommand: `omnist schema extract SCHEMA_FILE --keep label1,label2,...`
(`--compact`/`-o` supported like `schema format`/`schema normalize`;
mandatory-deletion failure is a definite "no" -- stderr + exit 1, not the
generic exit 2 for parse/usage errors).

## [v0.2.16] — Internal equivalence oracle + property suite (#141)

**Added:** an internal, non-public second decision procedure for schema
equivalence, `omnist.canonical.ops.isomorphic._isomorphic`, implementing
the paper's Algorithm 3 step 3 (isomorphism testing between two already-
normalized schemas). This gives `equivalent()` (bidirectional
`compatible_with`, Algorithm 4) an algorithm-independent oracle: the
paper's Theorem 4 says two schemas are equivalent iff their minimized
forms are isomorphic, and a new Hypothesis property suite in
`tests/test_fuzz.py` asserts the two procedures always agree, both on
random pairs and on pairs deliberately constructed to be equivalent
(rename, field reorder, added unreachable record, added `max == 0`
field). `_isomorphic` is not exported from `omnist` or
`omnist.canonical` -- `equivalent()` stays the cheaper, single public
algorithm; the second one exists purely as a testing oracle. See
`docs/testing.md` for the "dual-algorithm oracle" writeup.

## [v0.2.15] — Rewrite `normalize()` as partition-refinement minimization (canonical minimal form)

**Changed (behavior-affecting):** `Schema.normalize()` was a single
syntactic merge pass keyed by full structural identity (including ref
target names) -- neither minimal nor canonical, and violated its own
contract (a ref-chained pair of duplicate records only merged after a
*second* `normalize()` call; mutually-recursive "twin" records that are
genuinely `equivalent()` never merged at all, no matter how many times you
called it). `normalize()` is now the paper's Algorithm 2 (MinimizeSA):
partition refinement, the same family of algorithm as DFA minimization.
It prunes first (`Schema.prune()`, added in v0.2.14), partitions env
records by a target-blind local signature, then repeatedly splits blocks
apart wherever a same-labeled ref field points at a still-distinguishable
target, until stable -- producing the canonical **minimal** equivalent
schema (fewest env records), unique up to record naming.

This changes observable output in three ways:
- **Unreachable records are now dropped** (previously survived --
  `normalize()` never looked at reachability).
- **Ref-chained duplicates merge in one call**, and **mutually-recursive
  twin records now merge** when truly equivalent (previously never did).
- **`max == 0` fields and optional-but-unsatisfiable fields disappear**,
  via the new mandatory `prune()` step.

**Design decision:** the initial partition (`local_signature`,
`ops/signature.py`) sorts a record's fields by label rather than keeping
declaration order, since `Record` validation is order-independent --
two records with the same fields in a different order now correctly
merge (previously they were structurally distinct and never did).

See [model spec §13](docs/design/model.md#13-minimization-and-canonical-form)
for the full `normalize()` <-> MinimizeSA correspondence.

## [v0.2.14] — Fix `compatible_with`/`equivalent` for empty-language schemas; add `Schema.prune()`/`Schema.is_empty()`

**Fixed:** a schema with a mandatory ref cycle (e.g. `record A { "x": B }
record B { "y": A } root A`) accepts no finite document -- the empty
language -- but `compatible_with`/`equivalent` gave wrong answers for it:
an empty schema was reported as *not* `compatible_with` anything, and two
distinct empty schemas were reported as *not* `equivalent`, when both are
vacuously true (a schema that emits no documents is trivially a subschema
of any other schema). Root cause: the paper's Algorithm 4 (SubschemaSA)
assumes its precondition MakeUsefulSA (useless-state removal) has already
run; omnist's `_sub` ran the coinductive cycle rule without it, so an
unsatisfiable record's self-matching cycle was read as "compatible with
nothing" instead of "vacuously compatible with everything."

Adds `omnist/canonical/ops/prune.py`: `satisfiable_set(s)` (least-fixpoint
satisfiability -- a record is satisfiable iff every mandatory field is a
`Scalar` or a `Ref` to a satisfiable record), plus two new public
operations, `Schema.is_empty()` (True iff the root is unsatisfiable) and
`Schema.prune()` (the paper's MakeUsefulSA analog -- an equivalent schema
with unreachable records, never-emittable `max == 0` fields, and
optional-but-unsatisfiable fields removed; the root's own fields are left
untouched when the root itself is unsatisfiable, since pruning them would
silently produce a different, satisfiable schema). `ops/subschema.py` now
computes the A-side's satisfiable set once per `compatible_with` call,
returns vacuously `True` for an unsatisfiable A-side record, skips optional
A-fields whose type is unsatisfiable, and replaces the per-path `seen` set
with a shared memo dict (coinductive assumption on entry, real result
before returning) to avoid exponential re-verification on DAG-shaped
schemas.

See issue [#139](https://github.com/omnist-dev/omnist/issues/139).

## [v0.2.13] — Internal refactor: operations package groundwork

Internal refactoring with zero behavior change (full test suite passes
untouched). `omnist/canonical/operations.py` is now an `ops/` package with
three modules (subschema/minimize/signature), each implementing one algorithm
from the Lee & Cheung paper. Additionally, `Schema.resolve()` is simplified
to a single dictionary lookup (guaranteed by `check_refs()` that env values
are always Records), and `Record.field()` is now O(1) via a label index
built during `__init__`. Groundwork for follow-up correctness initiatives
(prune/is_empty, minimize rewrite, oracle, extract).
See issue [#138](https://github.com/omnist-dev/omnist/issues/138).

## [v0.2.12] — Docs: equivalent and normalize in schema reference

Added full examples for `Schema.equivalent()` and `Schema.normalize()` to
`docs/schema.md#operations-compare-and-infer`. Both operations were already
implemented and tested, but only mentioned in a cross-reference. The section
now shows them alongside `compatible_with` and `infer` with self-contained
code snippets. Backed by new assertions in `tests/test_docs.py`.
See issue [#136](https://github.com/omnist-dev/omnist/issues/136).

## [v0.2.11] — Compact (single-line) output for OML and OSD

`write_oml(node, indent=None)` and `to_osd(schema, indent=None)` (also
`Schema.to_osd(indent=None)`) now render single-line, machine-oriented
output instead of the pretty-printed default — `indent=None` mirrors
`write_json`'s existing convention. Both compact forms round-trip through
the unchanged `read_oml`/`parse_schema`, since OML already treats `;` as
an edge separator and OSD already treats whitespace as insignificant.

The CLI gains a `--compact` flag on every command that writes OML or OSD
text: `format`, `convert` (when `--to oml`), `infer`, `schema format`,
`schema normalize`. Purely additive — all defaults are unchanged. See
issue [#133](https://github.com/omnist-dev/omnist/issues/133).

## [v0.2.10] — Rename `to_dsl`/`dsl.py` to `to_osd`/`osd.py` (Breaking)

`to_dsl()` and `Schema.to_dsl()` are renamed to `to_osd()`/`Schema.to_osd()`,
and `omnist/canonical/dsl.py` is renamed to `omnist/canonical/osd.py`. This
finishes the OSD (Omnist Schema Definition) terminology rewrite — `to_dsl`
was the one writer left following the old name instead of the `to_<format>`
pattern every other writer uses (`to_oml`, `to_json`, …). No deprecated
alias is provided, consistent with this project's practice of clean breaks
over shims (e.g. `obj`/`arr`/`ObjectType` before it).

## [v0.2.9] — `omnist --version`

Adds `omnist --version` (prints `<prog> <version>`, exit `0`) and a
one-line `description=` on the top-level parser, so `omnist --help`
explains what the tool is before listing subcommands.

## [v0.2.8] — `omnist convert --strict`/`--report`, `omnist check`

Completes the CLI implementation arc (see `docs/design/cli-spec.md`) —
`omnist --help` now matches the spec exactly.

- `omnist convert` gains `--strict`, `--report`, and `--result-format
  text|json|oml`, mapping directly to `write_<to>`'s existing `strict=`/
  `report=` parameters:
  - `--report` prints what got adjusted to stderr (encoded per
    `--result-format`); the write still happens.
  - `--strict` refuses to write at all if anything would need adjusting
    — exit `1` (a definite "no," grouped with `validate`/`compatible-with`,
    not with the usage/parse failures that exit `2`).
- New `omnist check <input> --from FMT --to FMT [--strict]
  [--result-format text|json|oml]` — reports what `write_<to>` would
  adjust without ever writing. Unlike `convert`, `--from`/`--to` may be
  equal. Default: always exits `0` (purely informational); `--strict`
  turns it into a `0`/`1` CI gate.
- Added a CLI-level crash-freedom fuzz test (arbitrary/malformed input
  across every command/format combination must always exit cleanly,
  never raise an uncaught exception) — the codecs themselves are already
  fuzzed by `tests/test_fuzz.py`; this only covers the CLI's own
  error-surfacing path.

## [v0.2.7] — `omnist convert` (core)

Adds `omnist convert <input> --from FMT --to FMT [--schema FILE] [-o
OUTPUT]` (see `docs/design/cli-spec.md`) — the core cross-format
conversion command:

- `--from oml --to oml` is rejected (exit `2`, points at `omnist format`
  instead, which already covers that case losslessly). Every other
  same-format pair (`json`→`json`, etc.) is allowed, since there's no
  replacement command for those.
- `--schema FILE` upgrades/validates the input on read per the
  [deserialization guarantee](docs/deserialization.md); a conformance
  failure raises `ParseError` (every problem found), nothing written,
  exit `2`.
- One document in, one document out, following the library's
  single-rooted Document constraint (most visible in XML's one-root
  requirement) — no batch mode.

`--strict`/`--report`/`--result-format` (the adjustment-reporting flags)
land in a follow-up release.

## [v0.2.6] — `omnist infer`

Adds `omnist infer <input>... --from FMT [-o OUTPUT]` (see
`docs/design/cli-spec.md`). All inputs must be the same format; each is
read as a `Doc`, `infer(docs)` drafts a schema from them, written out as
OSD.

## [v0.2.5] — `omnist schema normalize`/`compatible-with`/`equivalent`

Adds three more schema CLI commands (see `docs/design/cli-spec.md`):

- `omnist schema normalize <schema-file> [-o OUTPUT]` — `Schema.normalize()`,
  written back as OSD (may merge structurally-identical records, unlike
  `schema format`).
- `omnist schema compatible-with <a> <b> [--result-format text|json|oml]`
  — `a.compatible_with(b)`.
- `omnist schema equivalent <a> <b> [--result-format text|json|oml]` —
  `a.equivalent(b)`.

The latter two print `true`/`false` (`text`, default), `{"compatible":
bool}`/`{"equivalent": bool}` (`json`), or the same shape OML-encoded
(`oml`); exit `0` if true, `1` if false.

## [v0.2.4] — `omnist validate`

Adds `omnist validate <input> --from FMT --schema FILE [--result-format
text|json|oml]` (see `docs/design/cli-spec.md`). Reads the input
**without** schema-directed upgrading (mirroring the library's own
validation/deserialization split) and runs `Schema.validate`:

- `text` (default): `ValidationResult`'s own `"invalid:\n  at $.path:
  message"` formatting, or `valid`.
- `json`/`oml`: `{ok, errors}`, structurally identical either way.

Exit `0` if valid, `1` if invalid, `2` on a read/parse error.

## [v0.2.3] — first CLI commands: `omnist format` / `omnist schema format`

Adds the `omnist` command-line tool (first two commands of a multi-PR
rollout; see `docs/design/cli-spec.md` for the full planned surface):

- `omnist format <input> [-o OUTPUT]` — canonicalize an OML document
  (`read_oml` → `write_oml`). `-` for stdin, omit `-o` for stdout.
- `omnist schema format <schema-file> [-o OUTPUT]` — canonicalize an OSD
  schema file (`parse_schema` → `to_dsl`), a safe reformat only (no
  structural change).

Both commands map directly onto the existing public API with no new
behavior; malformed input raises the library's own `ParseError`/
`SchemaError`, printed cleanly to stderr with exit code `2`, never an
uncaught traceback.

## [v0.2.2] — schema-directed deserialization now guarantees conformance (BREAKING)

**Breaking:** `materialize()` (and `schema=` on every reader / `Doc.from_*`)
now raises `ParseError` for shape problems too — an unexpected field, a
missing field, the wrong cardinality, a record where a scalar was expected
or vice versa — not just scalar conversions that aren't value-exact. There's
no `strict=` flag: passing a schema is itself the request for a
guaranteed-conforming Document, so this is now the only behavior once a
schema is given; `schema=None` remains the unchanged way to opt out of any
checking. All problems found in one deserialization (scalar *and* shape) are
collected and raised together in a single `ParseError`, rather than failing
on only the first one encountered.

Previously, `materialize` only checked/converted scalar leaves and silently
passed shape mismatches through unchanged, leaving them to a separate,
explicit `schema.validate(doc)` call — see issue
[#115](https://github.com/omnist-dev/omnist/issues/115). That split meant
code passing `schema=` to a reader could still get back a Document that
didn't actually conform to it, without anything raising. `materialize` now
performs validation and upgrading together in one recursive pass (it
doesn't call `Schema.validate` after the fact — that would be a second,
redundant top-down walk with no notion of upgrading); `Schema.validate`
itself is unchanged and still useful for validating a Document you didn't
just deserialize.

If you relied on the old passthrough behavior, switch to reading without
`schema=` (untouched node, no checking at all) and call
`schema.validate(doc(...))` yourself when you want to check shape without
upgrading scalars.

## [v0.2.1] — moved to the omnist-dev GitHub organization

No code changes. The repository moved from `github.com/tomlee/omnist` to
`github.com/omnist-dev/omnist` (the old URL redirects automatically). Updated
every current reference to the new path: `pyproject.toml`'s project URLs,
`mkdocs.yml`'s `repo_url`/`repo_name`, the absolute GitHub links to source
files added in the OML/Schema DSL grammar docs and the glossary, the GitHub
Pages link (now `omnist-dev.github.io/omnist`), and `CONTRIBUTING.md`/
`SECURITY.md`'s clone/issue links. The historical CHANGELOG entry about the
earlier `dataspec` → `omnist` rename (v0.1.1a8) is left as written, since it
describes what was true at the time.

## [v0.2.0] — first PyPI release

No code changes since v0.1.9 — this is a milestone version bump marking the
first release published to PyPI, after the documentation/test-hardening
arc since v0.1.2: OML (the native lossless format, v0.1.3), four
fuzz-discovered correctness fixes across XML/YAML/OML (v0.1.4, v0.1.6-9),
order-independent `infer()` (v0.1.3), 100% line coverage, property-based
fuzz testing, and a full documentation pass (formal grammars for OML and
the Schema DSL, a glossary, a dedicated schema-directed-deserialization
page, per-format reading/writing reference sections, and diagrams for the
Document model, the Schema model, and the format-conversion flow).

## [v0.1.9]

- Fix: an XML element label containing a trailing or embedded newline (e.g.
  `'A\n'`) was silently treated as a valid XML name and written verbatim by
  `write_xml`, with `check_xml` reporting no adjustment -- but XML element
  names can't legally contain whitespace, so the newline was actually
  stripped on `read_xml`'s round-trip, losing data without warning. Root
  cause: `_XML_NAME`'s regex anchored its end with a bare `$`, which in
  Python matches either at the absolute end of the string *or* just before
  a trailing `\n` -- so `'A\n'` was incorrectly accepted as already valid.
  Anchored with `\Z` instead, so any label containing a newline (or other
  non-XML-name character) anywhere now correctly falls through to the
  existing `key.sanitized` adjustment path, the same one used for other
  illegal-XML-name labels, and round-trips losslessly via the sanitized
  name. Found by the fuzz suite. (#95)

## [v0.1.8]

- Fix: `write_xml` wrote string leaf values into element text verbatim, so a
  string containing a C0 control character that XML 1.0 forbids (e.g. `\x00`,
  `\x08`, `\x0b`, `\x0c`, `\x1f`, or a UTF-16 surrogate) produced text that
  wasn't well-formed XML -- `read_xml` would then fail to parse the writer's
  own output, and `check_xml` gave no advance warning. `check_xml`/`write_xml`
  now detect this and report a new adjustment code, `string.illegal_xml_char`
  (`"error"` severity); `write_xml` replaces each illegal character with
  U+FFFD so the output is always well-formed (`strict=True` raises instead).
  Separately, a literal `\r` survives `write_xml` as a raw CR byte, but XML's
  mandated line-ending normalization on parse turns it into `\n` -- this was
  already legal XML (not a bug) but undocumented lossiness; it's now reported
  via a new `string.cr_normalized` adjustment code (`"warning"` severity).
  Found by the fuzz suite (#64). Documented in `docs/api.md` and
  `docs/formats/xml.md`. (#67)

## [v0.1.7]

- Fix: a string used as a field label or scalar value containing U+0085
  (NEL, "next line") silently came back as a plain space after a
  `write_yaml`/`read_yaml` round-trip, with `check_yaml` reporting no
  adjustment — undocumented data loss. Root cause: PyYAML's emitter/parser
  treat U+0085 as a line-break character under the default plain/
  single-quoted scalar styles and normalize it away; U+2028/U+2029 are
  unaffected. Forcing PyYAML's double-quoted scalar style for any string
  containing U+0085 round-trips it correctly (confirmed both globally and
  per-scalar), so `write_yaml` now does this automatically via a custom
  string representer, and `check_yaml`/`write_yaml` report it with the new
  `string.line-break-char` adjustment code. (#69)

## [v0.1.6]

- Fix: an internal node with zero edges (`[]`) and a leaf holding the empty
  string (`''`) both serialize to the same XML element, `<tag />`, so
  `read_xml` couldn't tell them apart and always reconstructed the
  empty-string leaf -- a documented-but-previously-undetected round-trip
  ambiguity found by the fuzz suite (#64). `check_xml`/`write_xml` now
  report a new adjustment code, `shape.empty_ambiguous`, when writing an
  empty internal node, since that's the direction that's actually lossy
  (writing an empty-string leaf round-trips fine and is not flagged).
  Documented in `docs/api.md` and `docs/formats/xml.md`. (#68)

## [v0.1.5]

- Fix: `tests/test_fuzz.py::test_doc_and_build_node_round_trip_from_plain_python_value`
  compared two structures that could contain a bare `nan` scalar with plain
  `==`, which fails for any float `nan` (`nan != nan` in Python) even though
  the round-trip itself is correct — a deterministic test failure whenever
  Hypothesis happened to generate a NaN value, found immediately after the
  fuzz-test PR (#73) landed. Fixed by using the suite's existing
  `nan_safe_equal` helper for this comparison too, matching how the
  adjacent OML round-trip assertion in the same test already handled it.
  No library behavior changed — test-only fix. (#75)

## [v0.1.4]

- Fix: `write_oml` wrote the labels `"inf"` and `"nan"` as bare (unquoted)
  identifiers, but the scanner tokenizes these spellings as `NUMBER`
  literals (higher priority than `IDENT`), so `read_oml` could not parse
  the writer's own output back — a `ParseError` rather than the documented
  always-lossless round-trip. `_write_label` now also quotes labels
  matching these reserved `NUMBER` spellings, the same way `null`/`true`/
  `false` were already handled. (`-inf` as a label was already safe, since
  it can't start with `-` per the bare-label grammar.) (#71)

## [v0.1.3]

- New: **OML** (Omnist Markup Language) — a native, lossless codec for the
  Document model. `read_oml` / `write_oml` / `check_oml`,
  `Doc.from_oml` / `to_oml` / `check_oml`, and the `"oml"` format-registry
  entry. Every Document shape (all seven scalars, `null`, repeated and
  interleaved labels, arbitrary nesting, multiple top-level edges)
  round-trips through OML exactly — `check_oml` is always an empty
  `WriteReport`, unlike the other four formats. Supports the raw-string
  (`'…'`) and triple-quoted multiline-string (`"""…"""`) OML-Extended
  spellings on read; the canonical writer always emits OML-Core. Hardened
  against the CPython big-int-to-str DoS class (a 4300-digit limit on bare
  integers, matching `sys.get_int_max_str_digits()`'s default) and bounded
  to the Document model's own 200-level nesting depth.
- New docs: [docs/formats/oml.md](docs/formats/oml.md) (including a section
  mapping OML scalars/records onto the Python Document and builder) and
  [docs/schema.md](docs/schema.md), a standalone introduction to the Schema
  model and DSL parallel to the OML page. OML and the schema DSL are now
  promoted to first-class billing in the README, the docs index, and the
  guide, instead of being buried in format lists; the flagship examples
  (`docs/example.md`, `docs/guide.md`'s real-life example,
  `examples/canonical_model.py`) now illustrate the Document primarily in
  OML, with the other four formats shown as lossless translations.
- Fix: `infer()`'s optional-vs-required field detection was silently
  **order-dependent** — a field absent from an early sample but first seen
  in a later one could be misclassified as required (`[1,1]`) instead of
  optional (`[0,1]`), depending only on sample order. Fixed by computing
  per-sample presence in two passes (which labels exist at all, then one
  count per sample for each) instead of backfilling incrementally as
  labels were discovered.

## [v0.1.2]

Version bump only, no code or behavior changes since v0.1.1a10.

## [v0.1.1a10]

Documentation only, no code changes. Added two formal sections to
`docs/design/model.md`:

- **§11, Scalar and Python type** — a precise per-kind table of which
  Python type each scalar deserializes to, which raw values convert vs.
  raise, and how that differs from what `Schema.validate` merely checks
  (it never converts). Spells out two easy-to-miss results: `number`
  always deserializes to `float` even from an integer literal, and `bool`
  never satisfies `integer`/`number` despite being an `int` subclass.
- **§12, Inference: determining a field's Scalar from samples** — the
  exact algorithm `infer` uses: per-label kind collection, the
  integer/number collapse, the raise-on-other-mixed-kinds rule, and the
  nullable-string fallback when a field occurred but every value was
  `null` (a field that never occurs in any sample at all gets no field at
  all, which is the cardinality bookkeeping, not this algorithm).

`docs/api.md`'s `infer()` and "Schema-directed deserialization" entries
now summarize these rules and link to the formal sections instead of
leaving the Scalar↔Python-type mapping implicit.

## [v0.1.1a9]

A pre-publish review pass: no new features, but a real bug fix and a
substantial test-coverage push (89% -> 96% line coverage on `omnist/`).

- **Fixed:** `Schema(root, env)` / the `schema()` builder didn't validate
  that every environment entry is a `Record` — handing in a bare `Scalar`
  (e.g. `schema(ref("R"), R=t.string)`) crashed with a raw `AttributeError`
  from deep inside `check_refs()` instead of a clean `SchemaError`. Now
  validated up front with a clear message. (This also made a defensive
  "root must resolve to a record" check at the end of `check_refs()`
  provably unreachable dead code; removed it.)
- Closed real test gaps found while reviewing: every distinct DSL parser
  error path (missing colon, garbage top-level token, no `root`, duplicate
  definition, unquoted field label, empty cardinality, unknown reference,
  and — found while writing these — the old enum-rejection test was
  actually hitting the *tokenizer's* `|` rejection, not the parser's
  literal-type rejection, so that path was untested until now); the
  recursion-depth and cycle-detection guards `SECURITY.md` describes;
  `Doc.from_yaml`/`from_toml`/`from_xml`, `to_json`/`to_yaml`/`to_xml`,
  and `Doc == Doc`/`Doc.validate()`; malformed-input `ParseError`s for all
  four formats; the `string.ambiguous`/`null.omitted` XML adjustment codes;
  TOML's top-level-table requirement; several `compatible_with` edge cases
  (cardinality `[0,0]`, unbounded vs. bounded, a field one side doesn't
  know about); `infer()`'s zero-sample, non-object-root, mixed-type, and
  generated-name-collision cases. `dsl.py`, `document.py`, `infer.py`,
  `operations.py`, and `deserialize.py` are now at 100% line coverage.

## [v0.1.1a8]

**Breaking:** the project is renamed from `dataspec` to `omnist` ("omni-structure"),
before the first PyPI release (no users yet, so this is a clean rename, not a
deprecation period). `import dataspec` becomes `import omnist`; `DataspecError`
becomes `OmnistError`. The GitHub repository moves to
[tomlee/omnist](https://github.com/tomlee/omnist) (GitHub redirects the old
`tomlee/dataspec` URL). No behavioral changes.

## [v0.1.1a7]

Schema-directed deserialization: pass `schema=` to `read_json`/`read_yaml`/
`read_toml`/`read_xml` (and `Doc.from_json`/`from_yaml`/`from_toml`/`from_xml`)
to upgrade each leaf to match what the schema declares, when the conversion
is value-exact (`"2024-01-01" -> date`, `1.0 -> int 1`), and raise
`ParseError` when it isn't (`1.5 -> integer`, `"abc" -> integer`). Exposed
directly as `materialize(node, schema)` for already-parsed nodes. This was
the deserialization feature blocked by the value-domain ambiguity fixed in
v0.1.1a6 — every field now has exactly one candidate scalar, so there's never
a choice between candidate representations.

## [v0.1.1a6]

**Breaking:** removed value-domain composition (enums/unions) from the schema
model. A field's type is now always exactly one of the seven fixed scalars
(`string`, `integer`, `number`, `boolean`, `date`, `time`, `datetime` —
optionally nullable, e.g. `string?`) or one `Ref` to a named record — never a
composition of either. The DSL no longer has a `|` operator, literal values in
type position, or a `union`/`domain` keyword. Composable value domains made
schema-directed deserialization ambiguous: a value could satisfy more than one
candidate representation with no principled way to choose which Python type to
materialize it as, so the feature is gone rather than fixed. On the Python
builder side, the `union(...)` function is removed; a new `Scalar` class
replaces it, with ready-to-use instances exported as `STRING`, `INTEGER`,
`NUMBER`, `BOOLEAN`, `DATE`, `TIME`, `DATETIME` (also under a `t` namespace,
e.g. `t.string`) that can be passed directly as a field's type, plus a new
`nullable(scalar)` builder for the `?` form.

## [v0.1.1a5]

**Fixed:** `datetime` accepted a bare date-only string (`"2024-01-01"`) as a
valid value, because `datetime.fromisoformat` is lenient -- it defaults a
missing time component to midnight rather than rejecting the string. That
silently treated "no time given" as "the time is exactly midnight," and
meant `date` and `datetime` weren't actually mutually exclusive for the
string form (only for real `datetime.date`/`datetime.datetime` objects).
`matches_kind` now also requires that the string does *not* parse as a bare
`date`, so `date`, `time`, and `datetime` are exclusive for every value,
string or object. Narrows acceptance -- a previously-(incorrectly-)valid
string now fails `datetime`, so this is a behavior change, not purely
additive.

## [v0.1.1a4]

Three robustness fixes for the schema DSL parser, found by probing it
against its own grammar rather than just reading it (PR 2 of the model
replan):

- **Fixed:** a non-integer cardinality bound (e.g. `[1.5,3]`) crashed with
  an uncaught `ValueError` instead of a clean `SchemaError`.
- **Fixed:** the "depth guard" counted total `{` characters across the
  *whole* schema text as a proxy for nesting depth, so a large but
  perfectly flat schema (hundreds of unrelated top-level records, no
  nesting at all) was falsely rejected. The grammar has no inline
  nesting to guard against in the first place (records are never
  anonymous), so the check is removed rather than recalibrated.
- **Fixed:** a `record` or `union` could be defined with the same name
  as a builtin scalar keyword (`record string { ... }`) with no error —
  but it could never actually be referenced, since a bare name in a type
  position always means the builtin scalar. Now raises `SchemaError` at
  definition time.

## [v0.1.1a3]

`Doc` gains `check_json` / `check_yaml` / `check_toml` / `check_xml` / a
generic `check_format`, completing the `from_*`/`to_*` symmetry the v0.1.1a2
report machinery left out — every format had a `Doc.to_*` writer, but
"simulate that write and inspect the report" required dropping down to the
module-level `check_*` function on `d.to_data()`. `Format` gains an optional
fourth field, `check`, so a plugin can support `Doc.check_format` too; the
four built-ins all provide it.

## [v0.1.1a2]

Two features deferred from the v0.1.1a1 redesign, now implemented on the
canonical model:

- **Adjustment reports + strict mode for the codecs.** Writing to a format
  that can't hold every value losslessly (TOML has no `null`; JSON/XML have
  no date type; JSON has no `NaN`/`Infinity`) is lenient by default — the
  writer adjusts the value and records it as an `Adjustment` in a
  `WriteReport` — instead of losing it silently. `write_json` / `write_yaml`
  / `write_toml` / `write_xml` (and the matching `Doc.to_*`) now accept
  `report=` to inspect what changed, and `strict=True` to raise `WriteError`
  instead of adjusting. `check_json` / `check_yaml` / `check_toml` /
  `check_xml` simulate a write and return the report with no output.
- **Format registry.** `register_format(Format(name, read, write))` adds a
  custom format usable everywhere via `Doc.from_format` / `Doc.to_format`;
  `get_format` / `formats()` look up / list what's registered. The four
  built-ins register themselves on import.

New: `omnist.canonical.report` (`WriteReport`, `Adjustment`, `finish_write`)
and `omnist.canonical.registry` (`Format`, `register_format`, `get_format`,
`formats`), both re-exported from `omnist`. Documented in
[the API reference](docs/api.md#adjustment-reports-lossy-writes) and
[the guide](docs/guide.md#reading--writing-formats); covered by new tests in
`tests/test_canonical.py` and `tests/test_docs.py`.

## [v0.1.1a1]

**A breaking redesign of the core models** around the formal Data Tree /
Schema Automaton (Lee & Cheung, CIKM 2010). The v0.1.0 API (`ObjectType`,
`ArrayType`, `obj`, `arr`, `t.*`, the `root { … }` DSL) is **removed** — this
is a clean break. See [docs/design/model.md](docs/design/model.md).

- **Document** is now an ordered list of labeled edges (a Data Tree), not a
  dict-with-arrays. "Many" is a repeated label; object and array unify; XML
  interleaving is representable. The same Document represents all four formats.
- **Schema** has two named definition kinds — **`record`** (closed fields,
  each with a cardinality) and **`union`** (a value domain of kinds, literals,
  and/or null) — referenced by name (`Ref`) for reuse and recursion. There is
  no separate array type (an array is a field with `max > 1`), no `Any`, and
  no open maps (deliberately deferred); records are closed.
- **DSL**: `record` / `union` definitions, always-quoted field labels,
  `[min,max]` cardinality, `?` for value-domain null. Operations
  (`compatible_with` / `equivalent` / `normalize`) are **methods on `Schema`**.
- The earlier `compatible_with` soundness bugs cannot recur — the open-map
  `rest` construct that caused them is gone.
- Implementation lives in `omnist.canonical`; `import omnist` is its
  public surface. Docs rewritten: a new [user guide](docs/guide.md) and the
  formal [model spec](docs/design/model.md).

## [v0.1.0a9]

Three schema-compatibility/validation soundness bugs, found by comparing
omnist's `Schema`/`Type` model against the formal Schema Automaton (SA)
model it's based on (Lee & Cheung, CIKM 2010):

- **Fixed (unsound):** `compatible_with()`/`equivalent()` judged a schema
  with an open map (`{[string]: T}` / `rest=`) "backward compatible" with a
  schema that names one of those keys explicitly with an incompatible type
  -- e.g. `{[string]: string}` was wrongly judged compatible with
  `{extra?: integer, [string]: string}`, even though `{"extra": "hello"}`
  is accepted by the former and rejected by the latter. The check only ever
  compared the two schemas' `rest` types to each other and their named
  fields to each other, never a `rest`'s emitted keys against the *other*
  schema's named fields, even though an open map can emit any key,
  including one the other side names explicitly.
- **Fixed:** an `enum` of `date`/`time`/`datetime` values was wrongly
  judged incompatible with a schema accepting that kind outright (e.g. an
  enum of two specific dates vs. a plain `date` field) -- the internal
  helper that classifies an enum literal's kind only recognized
  `bool`/`int`/`float`, silently treating every temporal value as a
  `string`.
- **Fixed (unsound):** the DSL silently dropped an enum constraint when
  mixed with a bare scalar kind in a union -- `integer | "foo"` accepted
  any string, not just `"foo"`, because the parser substituted a bare
  `string` kind for the enum instead of keeping both. The Python builder's
  `enum()` had the same latent bug from the other direction: it set the
  literals' own kind on the `ScalarType` it built, which (now that
  validation correctly falls back to checking kinds alongside an enum)
  would have made every builder-built enum accept any value of that kind,
  not just its specific literals -- caught and fixed in the same pass.
  `ScalarType`/`_check_scalar`/`_scalar_subtype`/`__repr__` now support a
  scalar kind and an enum together as a real, intentional construct rather
  than two mutually-exclusive representations.

## [v0.1.0a8]

A breaking fix to XML's document-root handling, grounded in the labeled-tree
(OEM) data model the schema design is based on: the data tree's true root is
anonymous, and an XML document element is the single *named* child of that
root, not the root itself. The previous implementation conflated the two.

- **Fixed (breaking):** `read_xml` used to discard the document element's
  tag entirely (`<x><y>1</y></x>` read as `{"y": 1}`, not `{"x": {"y": 1}}`),
  and `write_xml` always invented a meaningless `<root>` wrapper, even for
  data that already had an obvious, lossless single-element XML shape. The
  document element's tag is now a real, round-tripping top-level key:
  `read_xml`/`write_xml` work with a Document that has exactly one top-level
  key (a *single-rooted* Document) — `{"x": {"y": 1}}` <-> `<x><y>1</y></x>`,
  exactly, including a detour through another format and back.
- **New:** `read_xml_documents`/`write_xml_documents` for a Document that
  *isn't* single-rooted (multiple top-level keys, or a top-level list) —
  translates a Document <-> a *forest* of XML documents, one per top-level
  key, with a list value producing one repeated-tag document per item.
  `write_xml` itself now raises `WriteError` on a non-single-rooted Document,
  unconditionally (not just under `strict`): unlike every other lossy
  adjustment in the library, there's no value-preserving fallback shape to
  wrap it in — inventing one would mean the round-tripped data no longer
  matches the schema the original was written for.
- **Removed (breaking):** `write_xml`/`check_xml`'s `root=` and `wrap_key=`
  parameters — there's nothing left to invent a name for; the document
  element's name now always comes from the data itself.
- **Documentation:** the previously-documented "XML root-name lossiness"
  (added in v0.1.0a5) is obsolete — it was a symptom of this bug, not an
  accepted limitation — and has been rewritten across `docs/formats/xml.md`,
  `docs/document.md`, `docs/formats/overview.md`, and `docs/faq.md`.

## [v0.1.0a7]

No code changes — a packaging/release-readiness check ahead of
eventually dropping the alpha suffix and publishing.

- Verified the package actually builds and installs as a real
  artifact, not just from an editable source checkout: `python -m
  build` produces a valid sdist and wheel, `twine check` passes both,
  `py.typed` is correctly included in the wheel, and installing the
  built wheel into a clean virtualenv (no source tree on the path)
  and running the full test suite against it passes.
- Found a real blocker for publishing to PyPI under the name
  `dataspec`: an unrelated package already holds it (Covera Health's
  "Data specification and normalization toolkit," last released in
  2020). Resolving this — a different distribution name, or
  requesting release of the apparently-abandoned name — is a
  prerequisite for any PyPI publish, independent of code readiness.

## [v0.1.0a6]

Performance only — no behavior changes (verified: every existing test
passed unmodified, plus the `hypothesis` property suite at 3000
examples/property, before and after each change).

- `write_toml`/`check_toml` merged three separate full-tree passes
  (int-range scan, offset-time fix, null strip) into one. Measured
  **45% faster** on a 2000-section document (52.2ms → 28.5ms) — the
  three old passes cost almost as much as `tomli_w`'s own
  serialization.
- `Doc.to_data()` and the `get()`/`at()` snapshot helper replaced
  `copy.deepcopy` with a small Document-shape-aware copy. Measured
  **~3.5x faster** on a 2000-section document (12.9ms → 3.6ms) —
  `_snapshot()` backs every `get()`/`at()` call on a container field,
  so this is the more frequently-hit fix in practice.
- `Schema.peel()` no longer allocates an empty `set()` for the common
  case (a type that isn't a named-type reference). Measured ~11%
  faster `validate()` on a 2000-field schema with no named types
  (2.99ms → 2.67ms).

## [v0.1.0a5]

- Fixed: `write_toml`/`check_toml` crashed with a raw `ValueError` on a
  timezone-aware `time` (TOML's native `time` type has no offset slot
  at all, only `date-time` does); now stringified and reported as
  `temporal.stringified`.
- New: `integer.precision_risk` — a JSON integer beyond JavaScript's
  safe-integer range (`±2**53`) round-trips exactly through Omnist's
  own `read_json`, but silently loses precision in a JS-based parser
  (a browser, Node.js); now reported (the same class of interop risk
  as TOML's existing `integer.out_of_range` check).
- Documented: the XML root element's name is discarded on read and
  doesn't survive a detour through another format — `<k>...</k>` →
  JSON → XML gives `<root>...</root>` back, not `<k>...</k>`, unless
  you explicitly re-supply `root="k"` yourself.
- Documented: a `"How incompatibilities are handled"` overview in
  `docs/formats/overview.md` naming the three buckets every
  cross-format incompatibility falls into — raises (illegal input),
  reported adjustment (lossy-but-legal), or silent read-time
  normalization (comments, XML namespace prefixes — a short, fixed
  list with no report mechanism, since neither was ever part of the
  Document model).
- New: explicit cross-format test coverage for key names that are
  syntactically significant in one format's grammar but not another
  (TOML's `. = [ ]`, YAML's `:`, the `#` comment marker shared by
  both) — found that `.` is actually *legal inside an XML name*, so a
  TOML-special key like `"a.b"` is the one case XML does **not**
  sanitize; documented in `docs/formats/xml.md`.

## [v0.1.0a4]

A security/robustness audit of the format codecs, prompted by the
question "is the library safe now?" Found and fixed five more real
bugs, none caught by the edge-case sweep in v0.1.0a3:

- Fixed: a small, ordinary YAML payload using anchors/aliases to share
  structure (not a cycle, just YAML's normal way of avoiding
  duplication) took time **exponential** in nesting depth to validate
  — a 469-byte, 9-level payload that `yaml.safe_load` parses instantly
  didn't finish validating in 15 seconds. The cause was Omnist's own
  post-parse cycle/depth check re-walking a shared subtree once per
  alias reference instead of once per unique object; PyYAML itself
  shares the constructed objects and was never the problem. Now linear
  in the number of unique objects.
- Fixed: `read_xml` silently fell back to the standard library's XML
  parser (vulnerable to XXE/entity-expansion) with no indication at
  all when the optional `defusedxml` dependency isn't installed. Now
  raises `UnsafeXMLWarning` each time this happens.
- Fixed: `read_json`/`read_toml` leaked the underlying parser's native
  exception (`json.JSONDecodeError`, `tomllib.TOMLDecodeError`) on
  malformed input instead of wrapping it in `ParseError` like
  `read_yaml`/`read_xml` already did, breaking the documented
  "catch everything with `except ParseError`" contract.
- Fixed: `write_xml` embedded literal control characters (e.g. a NUL
  byte) directly in the output with no warning — unlike the format's
  other adjustments, this isn't lossy, the result doesn't parse as XML
  *at all*. Now stripped and reported as `string.illegal_xml_char`,
  an error.
- Fixed: `infer()` crashed with a raw `AttributeError`/`TypeError` on a
  sample like `[False, {}]`, instead of the same clean, documented
  `SchemaError` every other "mix of structure and scalar" sample
  already got. A bool was classified separately from other scalars in
  the structural-mixing check; now it isn't.
- New: `tests/test_property.py` — property-based fuzzing with
  `hypothesis`, generating randomized Documents and text across every
  codec and the DSL parser on every CI run. Found three of the five
  bugs above.
- New: `SECURITY.md` — the trust model for each format (what's
  hardened, what isn't) and how to report a vulnerability (GitHub
  private vulnerability reporting, now enabled on this repo).

## [v0.1.0a3]

- Fixed: deeply/adversarially nested input (`Doc` construction, the
  functional `write_*`/`read_*` codecs, and the schema DSL parser) used
  to crash with an uncatchable `RecursionError`; each now raises a clean
  `DocumentError`/`SchemaError` past a depth limit.
- Fixed: a real key collision (e.g. JSON's `{1: "a", "1": "b"}`, or two
  XML keys sanitizing to the same element name) was reported as a soft
  warning even though it silently overwrites one value with the other;
  now reported as `key.collision`, an **error**.
- Fixed: the format registry (`register_format`/`get_format`/`formats()`)
  was an unsynchronized global dict; a plugin registered from a
  background thread could race a concurrent lookup. Now thread-safe.
- Fixed: three more silent XML/TOML data-corruption cases found by a
  systematic edge-case sweep — a string that looks like a number/bool/
  `null` silently changing type on read (`string.ambiguous`), an empty
  object/array silently becoming an empty string or vanishing entirely
  (`container.empty.ambiguous`), an integer beyond TOML's signed 64-bit
  range written without warning (`integer.out_of_range`), and a string
  containing `\r` silently losing its line endings per the XML spec's
  own normalization rules (`string.line_ending_normalized`). All four
  are now reported, and rejected by `strict=True`.
- New: `tests/edge_cases.py` / `tests/test_edge_cases.py` — a shared
  corpus of ~45 edge-case values swept across every format and a few
  API operations (`Doc`, `infer`, DSL round-trip) via general
  invariants rather than hand-coded expectations per case.
- New: `tests/test_dsl.py` negative-path coverage — one case per
  distinct `SchemaError` the hand-written DSL parser can raise.
- CI now runs `ruff check .` and every `examples/*.py` script, not just
  `pytest`.
- New: `CONTRIBUTING.md`.
- Removed the redundant `sys.path.insert` boilerplate from every
  example and test file (the editable install already covers it); a
  few `pyproject.toml` metadata fields filled in.

## [v0.1.0a2]

- New: `finish_write(text, rep, *, strict=False, report=None)`, a public
  helper format plugins can call instead of reimplementing the
  strict/report decision every built-in writer makes; the built-ins
  (`write_json`/`write_yaml`/`write_toml`/`write_xml`) now use it too.
- New: [`docs/plugins.md`](docs/plugins.md) — a guide for writing a format
  plugin (the `Format` contract, the adjustment-report pattern, a
  verified worked example, testing, and a checklist).
- Project practices: `CHANGELOG.md`, `ruff` lint config, a `py.typed`
  marker (PEP 561), and branch protection on `master` requiring CI.
- Changes from here on go through a pull request rather than a direct
  commit to `master`.
- Docs: example city/coordinates data changed from Hong Kong to London
  (and Shenzhen to Dublin); assorted doc-accuracy fixes found during a
  full pass over the doc set (stale TOML array-formatting comments, a
  missing validation error, clarified empty-array inference).

## [v0.1.0a1] - first tagged alpha

- Core model: `Doc` (the guarded data-DOM) and the `Schema`/`Type` tree
  (`ScalarType`, `ArrayType`, `ObjectType`, `AnyType`, `RefType`).
- Schema DSL: `parse_schema` / `to_dsl`, plus a Python schema builder
  (`obj`, `arr`, `mapping`, `enum`, `optional`, `nullable`, `ref`, `schema`,
  and the `t` namespace for scalar atoms).
- Pluggable format registry with built-in JSON, YAML, TOML, and XML codecs
  (`read_*` / `write_*` / `check_*`), lenient by default with adjustment
  reporting (`WriteReport` / `Adjustment`) and an opt-in `strict` mode.
- `infer()` to draft a schema from example Documents.
- Schema comparison operations: `compatible_with`, `equivalent`, `normalize`.
- Full exception hierarchy under `OmnistError`.
- GitHub Actions CI running the test suite (228 tests) on Python 3.11–3.13.
- Complete documentation set: concepts, architecture, getting started, the
  `Doc` API, the schema language, format-by-format pages, inference, schema
  comparison, an API reference, and an FAQ — every code example verified
  against the library.
