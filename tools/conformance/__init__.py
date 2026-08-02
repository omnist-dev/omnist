"""omnist's own OML/OSD conformance test runner.

Ported from omnist-spec's conformance/orchestrator/ (issue #283) -- that
code was Python-omnist-specific despite living in the implementation-
agnostic omnist-spec repo, so it lives here now, where the code it
exercises (read_oml, parse_schema, Schema.isomorphic_to) lives. Fixtures
still come from omnist-spec, via the pinned git submodule at
vendor/omnist-spec -- see docs/conformance-harness.md there for the full
spec (CLI wrapper contract, fixture format, comparison algorithm) and
this package's README for orientation.
"""
