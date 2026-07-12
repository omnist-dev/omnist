"""Freeze the public API surface promised by ``docs/stability.md``.

The stability policy says every name in ``omnist.__all__`` is stable: it
stays importable, its signature stays call-compatible, and (for the
NamedTuple exports) its field names stay the same. This test is the
mechanical enforcement of that promise. It has no opinion on whether the
API is *good* — only on whether it silently *changed*.

What is frozen, and why:

* ``FROZEN_ALL`` — the exact name set of ``omnist.__all__``. Adding a name
  means adding it here too (a new public export is an intentional,
  reviewable act). Removing or renaming a name is a breaking change and
  must go through the deprecation cycle in ``docs/stability.md`` before
  this set is updated.

* ``FROZEN_FUNCTION_SIGNATURES`` — the ``str(inspect.signature(...))`` of
  every plain function exported in ``__all__`` (``doc``, ``record``,
  ``read_json``, ``parse_schema``, etc). This catches an added/removed/
  reordered/retyped parameter.

* ``FROZEN_METHOD_SIGNATURES`` — for each exported *class*, the
  signatures of ``__init__`` (when the class defines its own, i.e. it
  isn't just inheriting ``Exception.__init__`` unchanged) plus the public
  methods and classmethods a caller actually invokes (``Doc.add``,
  ``Doc.from_json``, ``Schema.validate``, ``Schema.compatible_with``,
  ``WriteReport.add``, and so on). Deliberately NOT frozen here:

  - Plain marker/exception classes with no overridden ``__init__``
    (``OmnistError``, ``SchemaError``, ``DocumentError``, ``DetachedNode``,
    ``UnsafeXMLWarning``) — there is no signature of theirs to drift; their
    presence and base-class relationship is exercised elsewhere (and their
    names are still covered by ``FROZEN_ALL``).
  - Properties (``Doc.value``, ``Doc.is_leaf``, ``ValidationResult.ok``,
    ``WriteReport.errors``/``warnings``) and plain data attributes
    (``Scalar.name``, ``Field.label``, ``Doc.path``, ...) — these have no
    call signature to freeze; a rename would already break every caller
    and is caught by normal test failures elsewhere in the suite.
  - Dunder protocol methods (``__eq__``, ``__repr__``, ``__hash__``,
    ...) other than ``__init__`` — not part of the documented call
    surface per ``docs/api.md``.

* ``FROZEN_NAMEDTUPLE_FIELDS`` — for the three NamedTuple exports
  (``Error``, ``Adjustment``, ``Format``), the ``_fields`` tuple, since
  these are used positionally and by attribute name rather than through a
  hand-written ``__init__``.

* Non-callable, non-NamedTuple exports (the scalar singletons ``STRING``,
  ``INTEGER``, ... and the ``t`` namespace) have no signature at all.
  Their *presence* is covered by ``FROZEN_ALL``; their values are not
  re-frozen here to avoid duplicating ``docs/api.md``.

On failure, the message points at ``docs/stability.md``: an intentional
change to a stable surface means updating the frozen expectation in this
file AND following the deprecation cycle described there (deprecate in one
minor release, remove no earlier than the next).
"""

from __future__ import annotations

import inspect

import omnist

STABILITY_POINTER = (
    "This is a stable public-API surface per docs/stability.md. "
    "If this change is intentional: (a) update the frozen expectation in "
    "tests/test_public_api.py to match, AND (b) follow the deprecation "
    "cycle in docs/stability.md (deprecate for one minor release with a "
    "CHANGELOG entry, remove no earlier than the following minor release) "
    "before the old surface actually disappears."
)

# ---------------------------------------------------------------------------
# 1. The name set of omnist.__all__
# ---------------------------------------------------------------------------

FROZEN_ALL = {
    # errors
    "OmnistError", "SchemaError", "ParseError", "WriteError", "DocumentError",
    "DetachedNode", "UnsafeXMLWarning",
    # document
    "Doc", "doc",
    # schema model
    "Schema", "Record", "Scalar", "Ref", "Field", "ValidationResult", "Error",
    "AnyType",
    # builders
    "record", "ref", "field", "schema", "nullable", "t",
    "STRING", "INTEGER", "NUMBER", "BOOLEAN", "DATE", "TIME", "DATETIME",
    # osd
    "parse_schema", "to_osd",
    # operations (compatible_with / equivalent / normalize are Schema methods)
    "infer", "infer_with_report", "AnyFallback", "materialize",
    "lint", "LintFinding",
    # codecs
    "read_json", "write_json", "read_yaml", "write_yaml",
    "read_toml", "write_toml", "read_xml", "write_xml",
    "read_oml", "write_oml",
    "check_json", "check_yaml", "check_toml", "check_xml", "check_oml",
    # adjustment reports
    "WriteReport", "Adjustment", "finish_write",
    # format registry
    "Format", "register_format", "get_format", "formats",
}


def test_all_name_set_is_frozen():
    current = set(omnist.__all__)
    missing = FROZEN_ALL - current
    added = current - FROZEN_ALL
    assert not missing and not added, (
        f"omnist.__all__ changed: missing={sorted(missing)!r} "
        f"added={sorted(added)!r}. {STABILITY_POINTER}"
    )


# ---------------------------------------------------------------------------
# 2. Plain function signatures
# ---------------------------------------------------------------------------

FROZEN_FUNCTION_SIGNATURES = {
    "doc": "(value: 'Any') -> 'Doc'",
    "record": "(*fields: 'Field') -> 'Record'",
    "ref": "(name: 'str') -> 'Ref'",
    "field": "(label: 'str', type: 'Type', min: 'int' = 1, max: 'Optional[int]' = 1) -> 'Field'",
    "schema": "(root: 'Union[Ref, str]', **env: 'Record') -> 'Schema'",
    "nullable": "(scalar: 'Scalar') -> 'Scalar'",
    "parse_schema": "(text: 'str') -> 'Schema'",
    "to_osd": "(schema: 'Schema', *, indent: 'Optional[int]' = 4) -> 'str'",
    "infer": (
        "(samples: 'List[Any]', root_name: 'str' = 'Root', *, "
        "allow_any: 'bool' = False) -> 'Schema'"
    ),
    "infer_with_report": (
        "(samples: 'List[Any]', root_name: 'str' = 'Root', *, "
        "allow_any: 'bool' = False) -> 'tuple[Schema, list[AnyFallback]]'"
    ),
    "materialize": "(node: 'Any', schema: 'Schema') -> 'Any'",
    "lint": "(s: 'Schema') -> 'List[LintFinding]'",
    "read_json": "(text: 'str', *, schema: \"Optional['Schema']\" = None) -> 'Any'",
    "write_json": (
        "(node: 'Any', *, indent: 'Optional[int]' = None, strict: 'bool' = False, "
        "report: 'Optional[WriteReport]' = None) -> 'str'"
    ),
    "read_yaml": "(text: 'str', *, schema: \"Optional['Schema']\" = None) -> 'Any'",
    "write_yaml": (
        "(node: 'Any', *, strict: 'bool' = False, report: 'Optional[WriteReport]' = None) -> 'str'"
    ),
    "read_toml": "(text: 'str', *, schema: \"Optional['Schema']\" = None) -> 'Any'",
    "write_toml": (
        "(node: 'Any', *, strict: 'bool' = False, report: 'Optional[WriteReport]' = None) -> 'str'"
    ),
    "read_xml": "(text: 'str', *, schema: \"Optional['Schema']\" = None) -> 'Any'",
    "write_xml": (
        "(node: 'Any', *, strict: 'bool' = False, report: 'Optional[WriteReport]' = None) -> 'str'"
    ),
    "read_oml": "(text: 'str', *, schema: 'Optional[Any]' = None) -> 'Any'",
    "write_oml": "(node: 'Any', *, indent: 'Optional[int]' = 2, arrays: 'bool' = False) -> 'str'",
    "check_json": "(node: 'Any') -> 'WriteReport'",
    "check_yaml": "(node: 'Any') -> 'WriteReport'",
    "check_toml": "(node: 'Any') -> 'WriteReport'",
    "check_xml": "(node: 'Any') -> 'WriteReport'",
    "check_oml": "(node: 'Any') -> \"'WriteReport'\"",
    "finish_write": (
        "(text: 'str', rep: 'WriteReport', *, strict: 'bool' = False, "
        "report: 'Optional[WriteReport]' = None) -> 'str'"
    ),
    "register_format": "(fmt: 'Format') -> 'None'",
    "get_format": "(name: 'str') -> 'Format'",
    "formats": "() -> 'List[str]'",
}


def test_function_signatures_are_frozen():
    mismatches = []
    for name, expected in FROZEN_FUNCTION_SIGNATURES.items():
        obj = getattr(omnist, name)
        actual = str(inspect.signature(obj))
        if actual != expected:
            mismatches.append(f"{name}: expected {expected!r}, got {actual!r}")
    assert not mismatches, (
        "Public function signature(s) changed:\n"
        + "\n".join(mismatches)
        + f"\n{STABILITY_POINTER}"
    )


def test_frozen_function_signature_names_match_all_functions():
    """Guard the frozen table itself against silently going stale: every
    plain-function export in __all__ must have an entry above, and vice
    versa."""
    actual_functions = {
        name for name in omnist.__all__
        if inspect.isfunction(getattr(omnist, name))
    }
    assert actual_functions == set(FROZEN_FUNCTION_SIGNATURES), (
        f"Function export set changed: now {sorted(actual_functions)!r}, "
        f"frozen table covers {sorted(FROZEN_FUNCTION_SIGNATURES)!r}. "
        f"{STABILITY_POINTER}"
    )


# ---------------------------------------------------------------------------
# 3. Class __init__ and public-method signatures
# ---------------------------------------------------------------------------

FROZEN_METHOD_SIGNATURES = {
    "ParseError": {
        "__init__": "(self, message: str, errors: 'Optional[List[Error]]' = None) -> None",
    },
    "WriteError": {
        "__init__": "(self, message: str, report: 'WriteReport | None' = None) -> None",
    },
    "Doc": {
        "__init__": "(self, node: 'Any', path: 'str' = '$') -> 'None'",
        "add": "(self, label: 'str', value: 'Any') -> \"'Doc'\"",
        "check_format": "(self, name: 'str') -> \"'WriteReport'\"",
        "check_json": "(self) -> \"'WriteReport'\"",
        "check_oml": "(self) -> \"'WriteReport'\"",
        "check_toml": "(self) -> \"'WriteReport'\"",
        "check_xml": "(self) -> \"'WriteReport'\"",
        "check_yaml": "(self) -> \"'WriteReport'\"",
        "child": "(self, label: 'str') -> \"'Doc'\"",
        "count": "(self, label: 'str') -> 'int'",
        "edges": "(self) -> \"List[Tuple[str, 'Doc']]\"",
        "from_format": "(name: 'str', text: 'str') -> \"'Doc'\"",
        "from_json": "(text: 'str', *, schema: \"Optional['Schema']\" = None) -> \"'Doc'\"",
        "from_oml": "(text: 'str', *, schema: \"Optional['Schema']\" = None) -> \"'Doc'\"",
        "from_toml": "(text: 'str', *, schema: \"Optional['Schema']\" = None) -> \"'Doc'\"",
        "from_xml": "(text: 'str', *, schema: \"Optional['Schema']\" = None) -> \"'Doc'\"",
        "from_yaml": "(text: 'str', *, schema: \"Optional['Schema']\" = None) -> \"'Doc'\"",
        "get": "(self, label: 'str') -> \"List['Doc']\"",
        "get_one": "(self, label: 'str') -> \"'Doc'\"",
        "labels": "(self) -> 'List[str]'",
        "of": "(value: 'Any') -> \"'Doc'\"",
        "remove": "(self, label: 'str') -> \"'Doc'\"",
        "set": "(self, label: 'str', value: 'Any') -> \"'Doc'\"",
        "to_data": "(self) -> 'Any'",
        "to_format": "(self, name: 'str', **o: 'Any') -> 'str'",
        "to_grouped": "(self) -> 'Any'",
        "to_json": "(self, **o: 'Any') -> 'str'",
        "to_oml": "(self, **o: 'Any') -> 'str'",
        "to_toml": "(self, **o: 'Any') -> 'str'",
        "to_xml": "(self, **o: 'Any') -> 'str'",
        "to_yaml": "(self, **o: 'Any') -> 'str'",
        "validate": "(self, schema: \"'Schema'\") -> \"'ValidationResult'\"",
    },
    "Schema": {
        "__init__": "(self, root: 'Ref', env: 'Optional[Dict[str, Record]]' = None) -> 'None'",
        "accepts": "(self, doc: 'Any') -> 'bool'",
        "check_refs": "(self) -> 'None'",
        "compatible_with": "(self, other: \"'Schema'\") -> 'bool'",
        "equivalent": "(self, other: \"'Schema'\") -> 'bool'",
        "extract": "(self, *labels: 'str') -> \"'Schema'\"",
        "is_empty": "(self) -> 'bool'",
        "normalize": "(self) -> \"'Schema'\"",
        "prune": "(self) -> \"'Schema'\"",
        "resolve": "(self, t: 'Type') -> 'Union[Record, Scalar, AnyType]'",
        "to_osd": "(self, *, indent: 'Optional[int]' = 4) -> 'str'",
        "validate": "(self, doc: 'Any') -> 'ValidationResult'",
    },
    "Record": {
        "__init__": "(self, fields: 'List[Field]') -> 'None'",
        "field": "(self, label: 'str') -> 'Optional[Field]'",
    },
    "Scalar": {
        "__init__": "(self, name: 'str', nullable: 'bool' = False) -> 'None'",
    },
    "Ref": {
        "__init__": "(self, name: 'str') -> 'None'",
    },
    "Field": {
        "__init__": (
            "(self, label: 'str', type: 'Type', min: 'int' = 1, "
            "max: 'Optional[int]' = 1) -> 'None'"
        ),
        "cardinality_str": "(self) -> 'str'",
    },
    "ValidationResult": {
        "__init__": "(self) -> 'None'",
        "add": "(self, path: 'str', message: 'str', code: 'str') -> 'None'",
    },
    "AnyFallback": {
        "__init__": "(self, location: 'str', reason: 'str') -> None",
    },
    "LintFinding": {
        "__init__": "(self, code: 'str', severity: 'str', location: 'str', message: 'str') -> None",
    },
    "WriteReport": {
        "__init__": "(self) -> 'None'",
        "add": "(self, path: 'str', code: 'str', message: 'str', severity: 'str') -> 'None'",
    },
}


def test_class_method_signatures_are_frozen():
    mismatches = []
    for class_name, methods in FROZEN_METHOD_SIGNATURES.items():
        cls = getattr(omnist, class_name)
        for method_name, expected in methods.items():
            attr = getattr(cls, method_name)
            actual = str(inspect.signature(attr))
            if actual != expected:
                mismatches.append(
                    f"{class_name}.{method_name}: expected {expected!r}, got {actual!r}"
                )
    assert not mismatches, (
        "Public class method signature(s) changed:\n"
        + "\n".join(mismatches)
        + f"\n{STABILITY_POINTER}"
    )


# ---------------------------------------------------------------------------
# 4. NamedTuple field names
# ---------------------------------------------------------------------------

FROZEN_NAMEDTUPLE_FIELDS = {
    "Error": ("path", "message", "code"),
    "Adjustment": ("path", "code", "message", "severity"),
    "Format": ("name", "read", "write", "check"),
}


def test_namedtuple_fields_are_frozen():
    mismatches = []
    for name, expected in FROZEN_NAMEDTUPLE_FIELDS.items():
        actual = getattr(omnist, name)._fields
        if actual != expected:
            mismatches.append(f"{name}: expected {expected!r}, got {actual!r}")
    assert not mismatches, (
        "NamedTuple field names changed:\n"
        + "\n".join(mismatches)
        + f"\n{STABILITY_POINTER}"
    )
