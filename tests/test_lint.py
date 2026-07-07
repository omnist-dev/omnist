"""Tests for ``omnist.ops.lint`` -- non-destructive structural diagnostics.

One crafted schema per check code, a clean schema producing zero findings,
and the exit-code contract (an info-only schema stays "ok"). ``lint`` never
mutates; these tests assert on the findings it returns, not on any changed
schema.
"""
from __future__ import annotations

from omnist import LintFinding, lint, parse_schema


def codes(findings):
    return [f.code for f in findings]


def test_unsatisfiable_record():
    # a mandatory ref cycle: neither record admits any finite document
    s = parse_schema('record A { "b": B }\nrecord B { "a": A }\nroot A')
    findings = lint(s)
    unsat = [f for f in findings if f.code == "unsatisfiable-record"]
    assert {f.location for f in unsat} == {"A", "B"}
    assert all(f.severity == "warning" for f in unsat)


def test_unreachable_record():
    s = parse_schema('record R { "x": integer }\n'
                     'record Orphan { "y": string }\nroot R')
    findings = lint(s)
    unreach = [f for f in findings if f.code == "unreachable-record"]
    assert len(unreach) == 1
    assert unreach[0].location == "Orphan"
    assert unreach[0].severity == "warning"


def test_duplicate_record():
    s = parse_schema('record Addr { "c": string }\n'
                     'record Location { "c": string }\n'
                     'record R { "a": Addr, "l": Location }\nroot R')
    findings = lint(s)
    dup = [f for f in findings if f.code == "duplicate-record"]
    assert len(dup) == 1
    assert dup[0].location == "Addr, Location"
    assert dup[0].severity == "warning"
    assert "normalize" in dup[0].message


def test_any_field_inventory():
    s = parse_schema('record R { "id": string, "data": any }\nroot R')
    findings = lint(s)
    anys = [f for f in findings if f.code == "any-field"]
    assert len(anys) == 1
    assert anys[0].location == "R.data"
    assert anys[0].severity == "info"


def test_clean_schema_has_no_findings():
    s = parse_schema('record R { "x": integer, "y" [0,1]: string }\nroot R')
    assert lint(s) == []


def test_findings_sorted_by_code_then_location():
    s = parse_schema('record A { "b": B }\nrecord B { "a": A }\n'
                     'record Orphan { "z": any }\nroot A')
    findings = lint(s)
    keys = [(f.code, f.location) for f in findings]
    assert keys == sorted(keys)


def test_any_only_schema_has_no_warning():
    """An info-only schema (just an any-field inventory) yields no warning-
    severity findings -- the exit-code contract keeps it 'ok'."""
    s = parse_schema('record R { "data": any }\nroot R')
    findings = lint(s)
    assert codes(findings) == ["any-field"]
    assert not any(f.severity == "warning" for f in findings)


def test_lint_finding_is_frozen():
    f = LintFinding("any-field", "info", "R.x", "msg")
    import pytest
    with pytest.raises(Exception):
        f.code = "other"  # type: ignore[misc]


def test_lint_does_not_mutate():
    s = parse_schema('record R { "x": integer }\n'
                     'record Orphan { "y": string }\nroot R')
    before = set(s.env)
    lint(s)
    assert set(s.env) == before
