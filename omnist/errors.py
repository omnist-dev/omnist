"""Exceptions (and one warning) used across omnist."""

from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from .report import WriteReport
    from .schema import Error


class OmnistError(Exception):
    """Base class for all omnist errors."""


class SchemaError(OmnistError):
    """The schema text or structure is invalid.

    ``code``/``path`` are optional structured attributes -- ``None`` unless
    the raiser passed them, so every existing ``raise SchemaError("msg")``
    call keeps working unchanged. Where set, ``code`` is one of
    ``omnist-spec``'s ``parse.*``/``schema.*`` taxonomy codes (see
    ``docs/08-conformance-and-errors.md`` Sec8.3.1/8.3.3 in the
    ``omnist-spec`` submodule) and ``path`` is the OSD text offset or
    record/field name the problem was found at. Unlike :class:`ParseError`,
    a single ``SchemaError`` always represents exactly one problem -- OSD
    parsing stops at the first error, so there is no ``.errors`` list to
    collect (issue #301).
    """

    def __init__(self, message: str, *, code: "Optional[str]" = None,
                 path: "Optional[str]" = None) -> None:
        """Initialize SchemaError with a human-readable message and, optionally,
        a structured machine-readable code and the path/position it applies to."""
        super().__init__(message)
        self.code = code
        self.path = path


class ParseError(OmnistError):
    """A document could not be read from its format (outside the supported profile).

    Format-syntax failures (invalid JSON/YAML/TOML/XML/OML text) carry
    ``code``/``path`` (issue #308) -- optional structured attributes, ``None``
    unless the raiser passed them, so every existing ``raise
    ParseError("msg")`` call keeps working unchanged -- but ``.errors`` stays
    empty, the same way :class:`SchemaError` distinguishes a single
    lexical/well-formedness problem from a collected list: a syntax failure
    stops parsing at the first error, so there is nothing to collect.
    Schema-conformance failures from :func:`~omnist.deserialize.materialize`
    go the other way: they carry the full structured ``.errors`` list of
    every problem found (path, message, machine-readable code), not just the
    first one, so callers -- an API server turning this into a JSON error
    response, for instance -- can inspect and report on each one
    individually instead of parsing ``str(exc)``; ``code``/``path`` stay
    unset for this case, since there's no single position to point at.
    """

    def __init__(self, message: str, errors: "Optional[List[Error]]" = None, *,
                 code: "Optional[str]" = None, path: "Optional[str]" = None) -> None:
        """Initialize ParseError with a human-readable message and either
        structured per-problem issues (materialize) or a structured
        code/path for a single syntax failure -- never both at once."""
        super().__init__(message)
        self.errors: "List[Error]" = errors or []
        self.code = code
        self.path = path


class DocumentError(OmnistError):
    """A Python value is not a legal Document, or a Document operation is invalid.

    Raised by the :class:`~omnist.document.Doc` API when an import or mutation
    would produce something outside the Document model — an unsupported Python
    type, a non-string object key, a cycle — or when an operation doesn't fit the
    node (e.g. ``get`` on a scalar).  The message carries the offending path.
    """


class DetachedNode(DocumentError):
    """A cursor was used after its node was removed from the document.

    Holding a :class:`~omnist.document.Doc` cursor and then removing that node
    (or a node above it) leaves the cursor pointing at a subtree no longer in the
    document.  Using it raises this instead of silently editing an orphan.
    """


class WriteError(OmnistError):
    """A document cannot be represented in the target format.

    Raised in ``strict=True`` mode for any recorded adjustment, and
    unconditionally (regardless of ``strict``) when the value has no legal
    representation at all in the target format -- see
    ``docs/08-conformance-and-errors.md`` Sec8.3.8/8.3.9 in the
    ``omnist-spec`` submodule -- carrying ``code="write.unsupported-value"``
    and the offending ``path`` (issues #323/#324/#325). ``code``/``path`` are
    optional structured attributes, ``None`` unless the raiser passed them,
    so every existing ``raise WriteError("msg")`` call keeps working
    unchanged. ``.report`` holds the full
    :class:`~omnist.report.WriteReport` of every adjustment that would have
    been needed (empty for an unconditional failure raised before any
    adjustment was recorded), so callers can inspect the structured list,
    not just the text.
    """

    def __init__(self, message: str, report: "WriteReport | None" = None, *,
                 code: "Optional[str]" = None, path: "Optional[str]" = None) -> None:
        """Initialize WriteError with an adjustment report and, optionally,
        a structured machine-readable code and the path it applies to."""
        super().__init__(message)
        self.report = report
        self.code = code
        self.path = path


class UnsafeXMLWarning(UserWarning):
    """Unused by ``read_xml`` as of the fix for the fail-open XML fallback
    (see issue #173) — ``defusedxml`` is now a hard requirement for XML
    support, and its absence raises ``ImportError`` instead of falling back
    to the unsafe standard-library parser with a warning. Kept exported for
    backward compatibility with any code that imports or references it
    (e.g. an existing ``warnings.filterwarnings(..., category=omnist.UnsafeXMLWarning)``
    call), but nothing in omnist raises it anymore.
    """
