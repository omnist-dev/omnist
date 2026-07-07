# Openness: why there is no `Map`, and the case for `any`

> **Status:** decision record + design study, 2026-07-06.
> `Map` — **refused, settled** (fourth recurrence of the question).
> `any` — **shipped in v0.5.0** (maintainer go, 2026-07-07, after the
> study below concluded the algebra can carry it, §7–§8). The full
> normative specification is [any-type-spec.md](any-type-spec.md), and
> [model.md](model.md) §1 now describes the shipped model, `any`
> included.

## 1. Summary

The same design question keeps returning in different disguises: *can the
schema be a little more flexible about what counts as a match?* It arrived
three times during the original design — as scalar unions, as multi-shape
nullability, and as "should a record stay open to whatever keys show up" —
and was refused each time, for one reason: the moment a value can match
more than one candidate type, there is no principled way to decide which
one it "really" is, and the algebra's decidable yes-or-no answers degrade
into heuristic guesses. A fourth arrival came in 2026-07 via an external
code review, dressed as a `Map` type.

This document settles the question in both directions at once:

- **`Map` (open keys, uniform values) is refused** — not because it breaks
  decidability (a homogeneous map doesn't), but because it opens the
  schema's *label alphabet*, which is the thing every algorithm in the
  algebra reasons over. §3 gives the full argument.
- **`any` (a declared field whose subtree is unchecked) is supportable and
  recommended** — it opens only the *value domain* at an explicitly marked
  leaf, leaves the label alphabet closed and finite, and every operation
  extends to it with two-line rules rather than pervasive special cases.
  §5–§8 give the study and worked examples; §9 states the costs honestly.

The distinction generalizes: **open values at a visible leaf — acceptable;
open labels in the structure — never.** That is the line, and it is why the
two proposals that superficially resemble each other get opposite answers.

## 2. Definitions

**`Map`** would be a field position whose *keys* are unconstrained but
whose values all share one type — the `{ [string]: T }` of TypeScript, the
`additionalProperties: {...}` of JSON Schema:

```
record Config { "env" map[string]: string }     # NOT valid OSD — refused
```

**`any`** would be an eighth type keyword (lowercase, joining the seven
scalar keywords) usable as a field's type. A field typed `any` accepts
*any* value — any scalar, `null`, or any record subtree of any shape — and
validation does not descend into it. The field's **label** is still fixed,
declared, and counted; its **cardinality** still applies; only the value's
shape is unconstrained:

```
record Event {
    "id":               string,
    "type":             string,
    "created":          datetime,
    "data":             any,        # payload varies by event type; unchecked
    "attachments" [0,]: any,        # cardinality still applies to the label
}
root Event
```

`any` includes `null` (it is the top of the value lattice), so `any?` is
redundant and rejected by the grammar. The `root` statement continues to
name a record — the grammar (`schema := record* 'root' NAME`) is unchanged;
a maximally permissive schema, if ever wanted, is a one-field wrapper
record, not a new root form.

## 3. Why `Map` is refused

First, the honest steelman: a homogeneous map **is** decidable. Because
every value shares one type, `compatible_with` over two maps reduces to
containment of their value types — no union-style candidate ambiguity. And
the ergonomic appeal is real: settings objects, lookup tables, and
`{ [id]: User }` indexes are everyday shapes. The refusal is *not* "it
can't be done."

It is refused because decidability is the floor, not the bar, and `Map`
fails three tests above the floor:

**3.1 It opens the label alphabet.** Every algorithm in the algebra —
`prune`'s satisfiability walk, `normalize`'s partition refinement over
local signatures, the isomorphism oracle, `subschema`'s coinductive
containment, and above all `extract` — reasons over the finite set of
labels the schema declares. A `Map` position has an *infinite* label
alphabet. This is not one feature; it is a special case threaded through
every operation. `extract(labels...)` becomes outright ill-defined at a
`Map`: every label matches, so "the minimal subschema recognizing only
these labels" has no answer there.

**3.2 It reintroduces the union ambiguity at the shape level.** Is
`{"red": 5, "blue": 3}` a `Record` with fields `red` and `blue`, or a
`Map` of `string → integer`? There is no principled answer — only
heuristics (key-count thresholds, shape-uniformity guesses). That is
exactly the "more than one candidate, no principled winner" failure that
disqualified unions, relocated from the scalar level to the shape level.
`infer` in particular would be forced to guess.

**3.3 It breaks the multi-format claim.** Arbitrary map keys are not valid
XML element names. A canonical model that cannot round-trip one of its
four formats at `Map` positions has quietly given up "multi-format from
day one." (Contrast §5: an `any` subtree is still an ordinary Document
subtree, so every format constraint that already holds keeps holding.)

### 3.4 The sanctioned encoding for key-value data

Open key-value data already has a fully closed representation — the entry
list:

```
record Env      { "entry" [0,]: EnvEntry }
record EnvEntry { "key": string, "value": string }
root Env
```

This round-trips all four formats (repeated `<entry>` elements in XML,
naturally), touches zero algorithms, and keeps every guarantee intact.
Its honest limits, stated rather than hidden: it does **not** enforce key
uniqueness (two entries with the same `"key"` both validate), it loses the
"these are semantically keys" signal, and — most importantly — it requires
*owning the data shape*. You can use it for data you produce; you cannot
use it to validate third-party data whose shape you don't control. That
last gap is one of the motivations for `any` (§6.1), not a reason to
readmit `Map`.

## 4. The dividing line, stated precisely

Two observations explain why `any` survives the tests `Map` fails:

**4.1 `any` is a lattice top; `Map` is a partially overlapping sibling.**
`any` absorbs totally: every type `T` satisfies `T ⊑ any`, and `any ⊑ T`
only when `T` is `any`. Total absorption yields trivially clean, decidable
containment rules. `Map`, by contrast, *partially overlaps* `Record` — a
closed record instance is also a valid instance of a compatible map — and
partial overlap between kinds is precisely what makes containment,
minimization, and inference messy. Tops are clean; siblings are messy.
(A pleasant corollary: with `any`, the subschema lattice becomes bounded —
the empty schema at the bottom, the all-accepting schema at the top.)

**4.2 `any` never opens the label alphabet.** An `any` field's label is
declared and fixed; the field is a *schema leaf*. Nothing inside it is
schema-addressable, so no algorithm's finite-alphabet assumption is
touched. `Map` opens labels — the structural currency of the whole
algebra; `any` opens only a leaf's value domain.

And `any` passes the no-ambiguity test that killed unions: a union is
*several candidates competing* for one value with no principled winner;
`any` is *one declared candidate* that accepts everything. Validation
never has to decide anything.

## 5. Precedent

The concept is classical in exactly this domain and ubiquitous elsewhere:

| System | Escape hatch | Discipline |
|---|---|---|
| DTD / XSD | `ANY`, `xs:any` | Explicit, with `processContents` modes |
| JSON Schema / OpenAPI | `{}` / `true`, `additionalProperties` | **Open by default**; ecosystem lint fights to close it |
| Protobuf | `google.protobuf.Any`, `Struct` | Explicit; standard for passthrough payloads |
| TypeScript | `any` vs `unknown` | `any` infects and propagates; `unknown` is contained — the community's hard-won lesson |
| Pydantic | `typing.Any` | Explicit unvalidated passthrough |

The pattern worth copying is not "have an escape hatch" but "make it
explicit, contained, and never chosen by the tool." Omnist's proposed
`any` is closed-by-default with a single grep-visible opening that `infer`
never produces — the configuration other ecosystems' lint rules try to
reach retroactively, here by construction.

## 6. Why `any` earns its place (the industry case)

**6.1 Schemas usually describe data the author doesn't control.** Without
`any`, a schema must describe the *entire* document or validation fails on
the parts not yet modeled — so Omnist can only validate documents that fit
entirely inside the author's modeling budget. Third-party webhooks,
vendor configs, and spec'd-open sections are simply out of reach, not
merely inconvenient. The entry-list encoding (§3.4) doesn't help here: it
requires restructuring data you don't own.

**6.2 The envelope pattern.** Possibly the most common JSON validation
task in industry: a rigorously typed envelope around a variant payload —
Stripe/GitHub webhooks, CloudEvents, message-queue messages. Omnist has no
unions, so today it cannot process these documents at all. With `any`, the
clean two-stage pattern works: validate the envelope (closed), dispatch on
the `type` field in application code, then validate the payload against a
per-event-type schema (also closed). Note this does **not** smuggle unions
back in: the schema never chooses among candidates — the *application*
dispatches explicitly, and each validation step remains fully closed and
decidable. The choice lives in user code, where it is visible and
debuggable, not in the algebra.

**6.3 Spec'd-open formats.** `pyproject.toml` is the canonical TOML
example: the core tables are specified, but `[tool.*]` is *defined* to be
open — third-party tools own those subtrees. A pyproject schema is
impossible in today's model and natural with `any`. The same shape recurs
everywhere: Kubernetes annotations, docker-compose `x-` extensions, CI
configs with plugin sections.

**6.4 Gradual adoption.** Gradual typing is why TypeScript and mypy won
adoption: "type the 80% you understand, escape-hatch the rest, tighten
over time." All-or-nothing schemas are an adoption cliff. And Omnist ships
its own tightening ratchet: `infer` never *emits* `any` (§7), but pointed
at the real documents flowing through an `any` region it *proposes the
replacement schema*. The escape hatch comes with its own exit.

**6.5 Signal-to-noise.** Validating a document with an unmodeled section
today produces a wall of `unexpected field` errors — noise that teaches
users to distrust the tool. Deliberately silencing a known-unknown region
makes real errors stand out.

## 7. Operation-by-operation study

The requirement for adoption is that every operation extends to `any` with
small, local, provably correct rules — no pervasive special-casing. The
study finds exactly that:

| Operation | Rule for `any` | Notes |
|---|---|---|
| `validate` | At an `any`-typed field: accept, do not descend. | Cardinality of the label still enforced; `null` accepted (`any` is top). |
| `compatible_with` | `T ⊑ any` for every `T`; `any ⊑ T` only if `T` is `any`. | Two clauses in the coinductive `_sub`; everything else unchanged. |
| `equivalent` | `any ≡ any` only. | Follows from bidirectional containment. |
| `normalize` | `any` is one more atomic kind in the partition refinement — effectively an eighth scalar for signature purposes. | Records merge only when `any`-ness of corresponding fields matches. |
| `prune` / `is_empty` | `any` is always satisfiable. | Can never create a useless or unsatisfiable state; if anything, pruning simplifies. |
| `extract` | An `any` field is a schema leaf: kept or dropped wholesale by its own label. | Nothing inside is schema-addressable, so extraction cannot (and need not) reach in. |
| `infer` | **Never emits `any`.** | Not a carve-out: `infer`'s contract is "the most specific schema accepting the examples," and `any` is never most-specific. The rule falls out of the spec. |
| `materialize` | Pass the subtree through exactly as the reader produced it — no leaf upgrades inside `any`. | The conformance guarantee holds trivially. Inside `any`, values behave as under `schema=None`, scoped to the subtree. |
| writers / `check_*` | Untouched. | They operate on Documents, not schemas; an `any` subtree is an ordinary Document subtree. |
| isomorphism oracle | `any` matches only `any` in `local_signature`. | One more kind tag. |

**Testing note (the one real piece of infrastructure work):** the semantic
oracle brute-force-enumerates documents against set-theoretic ground
truth. `any`'s value space is infinite, so the oracle needs a finite
witness strategy for `any` positions — a representative sample (one value
of each scalar kind, `null`, a small record, bounded nesting). This is
test-harness design, not a soundness question, but it is real work and
part of the implementation cost.

## 8. Worked examples: the trade-offs, concretely

> The `any` examples below are illustrative — the keyword does not parse
> today. If `any` is adopted, they become executable doc-tests per the
> project's docs-as-tests convention. The `Map` examples are deliberately
> **not** valid OSD, and never will be.

### 8.1 What `any` buys: one schema for a webhook stream

```
record Event {
    "id":      string,
    "type":    string,
    "created": datetime,
    "data":    any,
}
root Event
```

Both of these documents validate against that one schema:

```json
{"id": "evt_1", "type": "user.created",
 "created": "2026-07-01T09:30:00",
 "data": {"name": "Ann", "email": "ann@example.com"}}
```

```json
{"id": "evt_2", "type": "payment.settled",
 "created": "2026-07-01T09:31:00",
 "data": {"amount_cents": 1250, "currency": "EUR"}}
```

Today's closed model cannot express this schema *at all*: there is no type
for `"data"` that accepts both payloads, because there are (deliberately)
no unions. Stage two of the pattern: the application reads `"type"`, then
validates the payload against a per-event-type **closed** schema —

```
record PaymentSettled { "amount_cents": integer, "currency": string }
root PaymentSettled
```

— so each validation step stays closed and decidable; the dispatch lives
in user code, visibly.

### 8.2 What `any` costs: the compatibility blind spot

The producer team renames a payload field between versions. Both schema
versions type the payload `any`:

```
# v1                                    # v2
record Event {                          record Event {
    "type": string,                         "type": string,
    "data": any,                            "data": any,
}                                       }
root Event                              root Event
```

Payloads change from `{"amount_cents": 1250}` to `{"amount": 1250}` — a
breaking change for every consumer. Yet `v2.compatible_with(v1)` returns
**True**, vacuously: inside `any`, nothing is compared. Had the payload
been closed —

```
record Event { "type": string, "data": Payment }
record Payment { "amount_cents": integer }
root Event
```

— the same rename would make `compatible_with` return **False**, catching
the break before it ships. **Checking ends exactly where `any` begins**:
the flagship guarantee is only as strong as the schema's closed portion.

### 8.3 A second cost of `any`: no conversions inside

```
record R { "when": datetime, "data": any }
root R
```

Reading `{"when": "2026-07-01T09:30:00", "data": {"since": "2024-01-01"}}`
with `schema=` upgrades `"when"` to a real `datetime` object — but
`data.since` stays the plain string `"2024-01-01"`. Inside `any`, values
arrive exactly as the reader produced them (the `schema=None` behavior,
scoped to the subtree). Predictable, but a surprise if undocumented.

### 8.4 The `Map` ambiguity, concretely

One document, two would-be readings:

```json
{"red": 5, "blue": 3}
```

```
record Palette { "red": integer, "blue": integer }   # closed reading (valid today)
record Counts  { map[string]: integer }              # open reading (refused)
```

Both accept the document, and nothing in the data says which is meant.
`infer` would be forced to guess between them on every input;
`extract("red")` is well-defined under the first reading and meaningless
under the second. And in XML, a key like `"light blue"` cannot even be an
element name. This is §3.2 and §3.3 run on real data.

### 8.5 The entry-list encoding: what the closed alternative gives and gives up

The sanctioned pattern (§3.4), valid today:

```
record Env      { "entry" [0,]: EnvEntry }
record EnvEntry { "key": string, "value": string }
root Env
```

What it gives: full guarantees, `extract`/`normalize`/`compatible_with`
all meaningful, round-trips XML naturally as repeated `<entry>` elements.
What it gives up, shown rather than told — duplicate keys validate:

```json
{"entry": [{"key": "A", "value": "1"},
           {"key": "A", "value": "2"}]}
```

…and the data must be *authored in this shape*: a third party's
`{"A": "1", "B": "2"}` cannot be validated without restructuring it
first, which is exactly what you cannot do to data you don't own.

### 8.6 Trade-off summary

| | Closed model (today) | + `any` | + `Map` (refused) |
|---|---|---|---|
| Envelope / variant payloads | impossible | ✓ two-stage dispatch (§8.1) | ✗ (map values must share one type — doesn't help) |
| Open-key data (env vars, labels) | entry-list encoding; requires owning the data shape (§8.5) | accepted but unchecked (over-broad) | ✓ natively, values still typed |
| `compatible_with` guarantee | total | total outside `any`; vacuous inside (§8.2) | total in theory, but complexity leaks into every operation |
| Label alphabet (what the algebra reasons over) | finite, closed | finite, closed | **infinite** at map positions |
| XML round-trip | ✓ | ✓ | breaks on arbitrary keys |
| `infer` | most-specific, deterministic | unchanged (never emits `any` by default; `--allow-any` opts in loudly) | forced heuristic guessing (§8.4) |

The table is deliberately honest about the residual gap: for *open-key
data specifically*, `Map` would have been the better tool than `any` —
values would still be typed, keys still open. The refusal is about what
`Map` costs the algebra (row 4), not a denial that the use case exists.
With `Map` refused and `any` adopted, natively-validated open-key data
with per-value typing remains unserved; the entry-list encoding and `any`
each cover part of it from different sides.

## 9. The costs, stated plainly

Adopting `any` changes the model's headline from **"closed by
construction"** to **"closed by default; open only where explicitly
marked."** That is a real weakening and this document does not pretend
otherwise. What keeps it acceptable:

1. **Openness is demarcated and grep-visible.** Every hole in a schema's
   guarantees is a literal `any` token in its text. `Map`'s openness would
   have been structural and pervasive; this is localized and auditable.
2. **`compatible_with` becomes locally vacuous at `any` — the sharpest
   cost.** Any change inside an `any` region is "backward compatible" by
   definition: true, but empty. A schema that is 40% `any` gives
   compatibility verdicts that are 40% meaningless *while looking
   authoritative* — the green-test-suite-full-of-mocks failure mode.
   Documentation must say this loudly wherever `any` is described.
3. **Downstream tooling burden.** Any future codegen, form generator, or
   doc generator needs an "unchecked node" branch. Small but permanent.
4. **Positioning.** "Everything checked, decidable" is the project's
   differentiator. The precise claim survives: the differentiator was
   never "no escape hatch," it was a *decidable algebra* — which `any`
   preserves and JSON Schema's default openness does not. But the
   marketing language must be updated honestly, starting with
   [model.md](model.md) §1, whose "no structureless escape hatches
   (`Any`, open objects, maps)" clause splits: open objects and maps stay
   refused; `any` becomes the model's one deliberate, contained opening.

## 10. Guardrails (adopted as requirements, not suggestions)

If and when `any` is implemented, these ship with it:

1. **Never inferred.** `infer` proposes only closed schemas — the analog
   of `noImplicitAny`: the tool never introduces the hole; a human must
   write it.
2. **Grammar discipline.** Lowercase `any` keyword alongside the seven
   scalar keywords; `any?` rejected as redundant; `root` grammar
   unchanged.
3. **The ratchet is documented.** The `any`-tightening workflow — run
   `infer` over real documents at an `any` position, review, replace — is
   documented next to `any` itself, so the escape hatch and its exit are
   learned together.
4. **Loud docs.** Every place `any` is documented also states what it
   costs (§9.2, and the worked example in §8.2, in particular).
5. **Future, not blocking:** a `schema lint`-style count/flag of `any`
   usage would give teams a governance dial (TypeScript's
   `no-explicit-any` precedent). Noted for later; not part of the initial
   implementation.

## 11. Decision record

- **`Map`: refused, settled.** Fourth recurrence of the openness question
  (scalar unions → multi-shape nulls → open records, during initial
  design; `Map` via external review, 2026-07). The refusal is now a
  documented position with a stated dividing line (§4), not a recurring
  debate. Future proposals that open the **label alphabet** — maps, open
  records, wildcard keys — are answered by §3 of this document.
- **`any`: recommended for adoption; not yet scheduled.** The study (§7–§8)
  finds every operation extends with small local rules and the algebra
  remains sound and decidable end to end. Implementation is a separate
  go/no-go: it requires an issue with the full plan (grammar + parser,
  `_sub` clauses, signature/minimize kind, oracle witness strategy, docs
  including the model.md §1 revision, full test/fuzz coverage to the
  project's usual bar), a minor version bump (new capability), and the
  guardrails of §10. Until that lands, the shipped model remains exactly
  as model.md describes it.
