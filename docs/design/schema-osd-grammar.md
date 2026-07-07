# OSD formal grammar

This is the formal grammar for **OSD** (Omnist Schema Definition) — the
small text language parsed by `parse_schema()` and produced by `to_osd()`
— written in ABNF ([RFC 5234](https://www.rfc-editor.org/rfc/rfc5234)). It
is the normative companion to [the Schema model & OSD page](../schema.md);
read that first for context and examples, and the
[glossary](../glossary.md) for the terms used here (record, field,
cardinality, Scalar, Ref).

Every production below has been exercised against the real implementation
in [`omnist/osd.py`](https://github.com/omnist-dev/omnist/blob/master/omnist/osd.py) (the
tokenizer regex and `_Parser` class); see [Worked
examples](#5-worked-examples) and the conformance tests in
[`tests/test_grammar_docs.py`](https://github.com/omnist-dev/omnist/blob/master/tests/test_grammar_docs.py).

## 1. Lexical grammar (tokens)

The tokenizer is a single regex alternation
([`_TOKEN`](https://github.com/omnist-dev/omnist/blob/master/omnist/osd.py)) tried left to right at each
position; the first alternative that matches wins (Python `re` tries
alternatives in order and takes the first match, not the longest — but
because each alternative here is anchored to a disjoint leading character
class in practice, this never produces a different result than longest-
match would). Whitespace and comments are discarded, not emitted as tokens.

```abnf
ws          = 1*( %x20 / %x09 / %x0D / %x0A )   ; space, tab, CR, LF
comment     = "#" *(%x00-09 / %x0B-10FFFF)      ; '#' to end of line

string      = DQUOTE *( %x5C %x00-10FFFF / %x20-21 / %x23-10FFFF
                         / sans-dquote-backslash ) DQUOTE
              ; in the tokenizer's own terms: DQUOTE, then any run of
              ; "\<any char>" (a backslash escape -- the *next* character,
              ; whatever it is, is consumed verbatim) or any non-DQUOTE
              ; non-backslash character, then a closing DQUOTE.
DQUOTE      = %x22                               ; '"'

number      = decimal-num / integer-num
decimal-num = ["-"] 1*DIGIT "." 1*DIGIT
integer-num = ["-"] 1*DIGIT

name        = (ALPHA / "_") *(ALPHA / DIGIT / "_")
              ; note: NO hyphen here, unlike OML's IDENT -- an OSD `name`
              ; allows only [A-Za-z0-9_], never '-'.
ALPHA       = %x41-5A / %x61-7A
DIGIT       = %x30-39

punct       = "{" / "}" / "[" / "]" / ":" / "," / "?"
```

### 1.1 String unescaping

A `string` token's *value* (used for a field label) is computed by
`_unquote`: it strips the surrounding quotes, then replaces every
backslash-escape pair `\X` with the single literal character `X` — there
is **no** named-escape table (no `\n`, `\t`, `\uXXXX`, etc., unlike OML).
`\X` always becomes exactly `X`, whatever `X` is, including `\\` → `\` and
`\"` → `"`. This means a label like `"a\nb"` literally contains the two
characters `n` and `b` after the backslash is dropped — it is **not** a
newline. See [Worked examples](#5-worked-examples) #1.

## 2. Syntactic grammar

```abnf
schema      = *( record-def / root-def )
              ; declarations may appear in any order/interleaving; there is
              ; no requirement that `root` come last, though by convention
              ; (and `to_osd`'s own output) it does.

record-def  = %s"record" name "{" [field *( "," field ) [","]] "}"
              ; a trailing comma after the last field is allowed (and is
              ; what `to_osd` always emits); fields are otherwise comma-
              ; separated with no trailing/leading comma permitted between
              ; them.

root-def    = %s"root" name
              ; exactly one root-def must appear in a well-formed schema
              ; (parse_schema raises SchemaError "a schema must declare a
              ; root" if none is found); a second root-def silently
              ; overwrites the first -- there is no duplicate-root check.

field       = string [cardinality] ":" type
              ; the label MUST be a quoted `string` token -- an unquoted
              ; `name` in label position is a SchemaError ("expected a
              ; quoted field name"). This is OSD's quoting rule in
              ; full: quoted = data string (always a label, the only use
              ; for a string literal in this grammar); unquoted = schema
              ; name (a scalar keyword or a Ref).

cardinality = "[" [int] ["," [int]] "]"
              ; four shapes, all accepted:
              ;   "[" n "]"        -> min = max = n
              ;   "[" m "," n "]"  -> min = m, max = n
              ;   "[" m "," "]"    -> min = m, max = unbounded (None)
              ;   "[" "," n "]"    -> min = 0, max = n
              ;   "[" "," "]"      -> min = 0, max = unbounded (None)
              ; "[" "]" (no digits and no comma) is a SchemaError ("empty
              ; cardinality"). Omitting `cardinality` entirely defaults to
              ; [1,1] (exactly-one, the same as "[1]").
int         = 1*DIGIT
              ; a cardinality bound is always a bare non-negative integer
              ; literal at the token level (no leading '-'); the parser
              ; additionally rejects a `number` token containing "." here
              ; ("cardinality must be a whole number"). A *negative* min or
              ; an inverted (max < min) range is still tokenizable but is
              ; rejected one layer up, by Field's own constructor
              ; (SchemaError "... has an invalid cardinality [...]"), not
              ; by the OSD parser itself -- see Worked examples #7-#8.

type        = scalar-type / any-type / ref-type
scalar-type = scalar-name ["?"]
scalar-name = %s"string" / %s"integer" / %s"number" / %s"boolean"
            / %s"date" / %s"time" / %s"datetime"
              ; the seven fixed scalar kinds -- SCALAR_NAMES in
              ; omnist/schema.py. "?" makes the scalar nullable;
              ; omitting it means non-nullable.

any-type    = %s"any"
              ; the eighth, unconstrained type -- accepts every legal
              ; Document value (see docs/design/any-type-spec.md). "?"
              ; CANNOT follow `any`: `any?` is a SchemaError ("'any'
              ; already includes null; 'any?' is redundant at ...")
              ; because null is already a member of `any`'s value set --
              ; unlike scalar-type, there is no nullable variant to opt
              ; into. A capitalized `Any` is NOT this production; it is
              ; an ordinary `name` token and therefore a `ref-type`,
              ; producing the existing "unknown type" error if
              ; undefined -- `any` is reserved only in its exact,
              ; lowercase spelling.

ref-type    = name
              ; any `name` token that is NOT one of the seven scalar-name
              ; keywords is parsed as a Ref to a (possibly not-yet-defined)
              ; record name; resolution is by name lookup in the schema's
              ; env, so forward references and mutual recursion both work.
              ; "?" CANNOT follow a ref-type: `Ref?` is a SchemaError
              ; ("'?' cannot apply to the reference ...; use cardinality
              ; [0,1] for an optional field") -- nullability is a scalar-
              ; only concept; optionality on a Ref is expressed via
              ; cardinality [0,1] instead.
```

### 2.1 Reserved names

A `record-def` whose `name` is one of the seven `scalar-name` keywords is a
`SchemaError` at definition time ("... is a reserved scalar name; a record
cannot be defined with this name, or it could never be referenced..."),
because a bare `name` in type position is *always* resolved as the builtin
scalar first — defining a same-named record would make it permanently
unreachable. The keyword `any` is reserved the same way and for the same
reason, but with its own message: a `record-def` named `any` is a
`SchemaError` ("'any' is a reserved type name and cannot be used as a
record name at ..."). Defining the same record `name` twice is also a
`SchemaError` ("duplicate definition ...").

### 2.2 No value-domain composition

There is deliberately no `|` (union), no enum, no literal-valued field, and
no separate `union`/`domain` declaration anywhere in this grammar — a
field's `type` is always exactly one `scalar-type` or one `ref-type`, never
a composition of either. See [the model spec](model.md) for the rationale
(a composable value-domain would make schema-directed deserialization
ambiguous).

## 3. Comments

`#` starts a comment that runs to the end of the line; comments (like
whitespace) are discarded by the tokenizer before the parser ever sees a
token, so a comment may appear anywhere whitespace is allowed — between
declarations, inside a `record { ... }` body, after a field, etc.

## 4. Quoting rule (label vs. schema name) — summary

This is the single most important disambiguation in the grammar, repeated
here for emphasis: a `"quoted"` token is always a **data string** — in this
grammar that only ever means a field's label. An unquoted `name` is always
a **schema name** — either one of the seven scalar keywords, or a `Ref` to
a record defined (or to be defined) elsewhere in the same schema. The two
spellings are never interchangeable: a bare `name` cannot supply a label,
and a quoted `string` cannot supply a type.

## 5. Worked examples

Each row was run against `parse_schema`/`to_osd` to confirm the claimed
behavior (see `tests/test_grammar_docs.py` for the executable form).

| # | Input | Result |
|---|---|---|
| 1 | `record R { "a\nb": string }` | label is the literal 3-character string `anb` (the `\n` escape pair becomes just `n`, since there is no named-escape table) — *not* `a` + newline + `b` |
| 2 | `"a" [1,5]: string` | field cardinality `(min=1, max=5)` |
| 3 | `"a" [5,]: string` | field cardinality `(min=5, max=None)` (unbounded) |
| 4 | `"a" [,5]: string` | field cardinality `(min=0, max=5)` |
| 5 | `"a" [,]: string` | field cardinality `(min=0, max=None)` |
| 6 | `"a" []: string` | `SchemaError`: "empty cardinality" |
| 7 | `"a" [-1]: string` | tokenizes fine, but `Field.__init__` rejects it: `SchemaError`: "field 'a' has an invalid cardinality [-1,-1]" |
| 8 | `"a" [1,0]: string` | tokenizes fine (max < min), rejected the same way: `SchemaError`: "field 'a' has an invalid cardinality [1,0]" |
| 9 | `"a" [1.5]: string` | `SchemaError`: "cardinality must be a whole number, got '1.5'" |
| 10 | `"a": string?` | nullable scalar field, `Scalar("string", nullable=True)` |
| 11 | `"a": Other?` (Ref with `?`) | `SchemaError`: "'?' cannot apply to the reference 'Other'; use cardinality [0,1] for an optional field" |
| 12 | `record string { "a": string }` | `SchemaError`: "'string' is a reserved scalar name; a record cannot be defined with this name..." |
| 13 | `record R{"a":string}\nrecord R{"b":string}` | `SchemaError`: "duplicate definition 'R'" |
| 14 | `record R{"a":string}` (no `root`) | `SchemaError`: "a schema must declare a root" |
| 15 | `record R{a:string}` (unquoted label) | `SchemaError`: "expected a quoted field name ..., got 'a'" |
| 16 | `record R { "a": string, }` (trailing comma) | OK — trailing comma after the last field is accepted |
| 17 | `# comment\nrecord R { "a": string } # trailing\nroot R` | comments anywhere whitespace is valid are discarded; schema parses normally |
| 18 | `to_osd(parse_schema('record R { "a" [0,3]: string? }\nroot R'))` | round-trips to `'record R {\n    "a" [0,3]: string?,\n}\nroot R\n'` |
| 19 | `to_osd(parse_schema('record R { "a": string }\nroot R'), indent=None)` | compact form `'record R { "a": string } root R\n'`, which `parse_schema` parses back to an equivalent schema |
| 20 | `record R { "data": any }` | field's type is the `AnyType` singleton (`t.any`); `record R { "data" [0,]: any }` and other cardinalities on an `any` field also parse, since cardinality is orthogonal to type |
| 21 | `record R { "data": any? }` | `SchemaError`: "'any' already includes null; 'any?' is redundant at ..." |
| 22 | `record any { "a": string }` | `SchemaError`: "'any' is a reserved type name and cannot be used as a record name at ..." |
| 23 | `record R { "data": Any }` (capitalized, no matching record) | `SchemaError`: "unknown type 'Any'" — `Any` is an ordinary `ref-type` name, not the reserved `any` keyword |
