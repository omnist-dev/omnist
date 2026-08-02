"""The comparison referee -- omnist-spec's docs/conformance-harness.md
Sec4.

Uses omnist's own library to parse OML/OSD text and judge structural
equality. This module is deliberately small: it does no CLI invocation
and no fixture-format parsing -- see cli_runner.py and runner.py for
those. Ported from omnist-spec's conformance/orchestrator/referee.py
(issue #283) with no change to the comparison logic itself.
"""
from __future__ import annotations

from omnist import parse_schema, read_oml


def compare_document(actual_oml_text: str, expected_oml_text: str) -> bool:
    """Structural, order-sensitive equality (Doc.__eq__ already provides
    this -- see the conformance-harness spec Sec4, no new library code
    needed for Document comparison)."""
    actual = read_oml(actual_oml_text)
    expected = read_oml(expected_oml_text)
    return bool(actual == expected)


def compare_schema(actual_osd_text: str, expected_osd_text: str, mode: str) -> bool:
    """Sec4/6.2: two legitimate meanings, chosen per operation.

    mode="exact": every record name and every field's label/type/cardinality
    must match (normalize/prune/extract -- output naming is spec-determined).
    mode="isomorphic": same structure up to a renaming of records (infer --
    generated record names are implementation-derived, never canonical).
    """
    actual = parse_schema(actual_osd_text)
    expected = parse_schema(expected_osd_text)
    if mode == "exact":
        return actual == expected
    if mode == "isomorphic":
        return actual.isomorphic_to(expected)
    raise ValueError(f"unknown comparison mode {mode!r}; expected 'exact' or 'isomorphic'")
