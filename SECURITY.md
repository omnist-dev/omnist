# Security Policy

Omnist is **alpha** (see [CONTRIBUTING.md](CONTRIBUTING.md)). There is one
supported line: `master` / the latest tagged pre-release. Fixes land there;
older tags don't get backports.

## Reporting a vulnerability

Please **don't** open a public issue for a security problem. Use GitHub's
private vulnerability reporting instead:
<https://github.com/omnist-dev/omnist/security/advisories/new>

If that's not available to you, open an issue asking for a way to reach the
maintainer privately, without describing the issue itself.

## Trust model: what each format assumes about its input

Omnist reads and writes JSON, YAML, TOML, and XML — formats whose parsers
have a long history of being used as attack surface (entity expansion,
quadratic blowup, alias bombs, code execution via unsafe deserialization). If
you call any `read_*` function on input you don't control, the following is
what's actually been considered and tested, and what hasn't.

- **No format ever executes code or constructs arbitrary Python objects.**
  YAML uses `yaml.safe_load` specifically (never `yaml.load`/`UnsafeLoader`),
  JSON/TOML use the standard library, and XML never resolves external
  entities. There's no `eval`, `exec`, or `pickle` anywhere in a read path.

- **YAML anchors/aliases are bounded before they are expanded.** `read_yaml`
  measures the anchor/alias graph in one iterative pass, in time linear in
  the input, and refuses an input whose expansion factor exceeds 50
  (`document.limit.alias-expansion`) or whose expanded size exceeds
  1,000,000 slots (`document.limit.expanded-size`, only for an input that
  has an alias or merge key); both are options, capped at 10,000 and
  10,000,000. A "billion laughs" payload is refused in milliseconds. A
  self-referential anchor is refused with the first code, and a malformed
  merge is a `parse.codec-syntax` error. See
  [docs/formats/yaml.md](docs/formats/yaml.md#alias-limits). PyYAML's own
  parse is still pure Python and costs seconds per megabyte: bound the
  input size before calling `read_*`.

- **XML parsing prefers `defusedxml`, which hardens against XXE and
  entity-expansion attacks.** It's an optional dependency (the `xml`/`all`
  extra); if it isn't installed, `read_xml` falls back to the standard
  library's parser — which has *no* such hardening — and emits an
  `UnsafeXMLWarning` every time this happens, specifically so this isn't a
  silent gap. See [docs/formats/xml.md](docs/formats/xml.md).
  **If you parse untrusted XML, install `defusedxml`.**

- **Deeply/adversarially nested input raises a clean exception instead of
  crashing the process.** `Doc` construction, the functional codecs, and the
  OSD parser all bound recursion well under Python's stack limit, so
  a maliciously deep document or schema raises `DocumentError`/`SchemaError`
  rather than an uncatchable `RecursionError`.

- **What's *not* specifically defended against: large flat input.** A very
  large (but not deeply nested, not alias-heavy) document — a multi-gigabyte
  JSON array, say — will consume time and memory roughly proportional to its
  size, the same as any parser for that format. There's no built-in input
  size limit; if you need one, enforce it before calling `read_*` (e.g. check
  `len(text)` or a `Content-Length` header against a budget you choose).

- **None of the above is fuzzed or property-tested against this codebase's
  current model.** The test suite (`tests/test_canonical.py`) is example- and
  case-based, not randomized; `hypothesis` is listed as a dev dependency but
  isn't currently wired into any test. Treat this document as "here's what's
  been considered and manually verified," not a guarantee backed by fuzzing.

## Versioning and disclosure

Once a fix lands, it ships in the next tagged pre-release; given the alpha
stage there's no separate embargo/disclosure timeline yet. This will be
revisited before a 1.0.
