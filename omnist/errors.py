"""Exceptions (and one warning) used across omnist."""

from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from .report import WriteReport
    from .schema import Error


class OmnistError(Exception):
    """Base class for all omnist errors."""


class SchemaError(OmnistError):
    """The schema text or structure is invalid."""


class ParseError(OmnistError):
    """A document could not be read from its format (outside the supported profile).

    Format-syntax failures (invalid JSON/YAML/TOML/XML text) carry only the
    message -- ``.errors`` is empty. Schema-conformance failures from
    :func:`~omnist.deserialize.materialize` carry the full structured list of
    every problem found (path, message, machine-readable code), not just the
    first one, so callers -- an API server turning this into a JSON error
    response, for instance -- can inspect and report on each one
    individually instead of parsing ``str(exc)``.
    """

    def __init__(self, message: str, errors: "Optional[List[Error]]" = None) -> None:
        """Initialize ParseError with a human-readable message and structured issues."""
        super().__init__(message)
        self.errors: "List[Error]" = errors or []


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
    """A document cannot be represented losslessly in the target format.

    Raised only in ``strict=True`` mode.  ``.report`` holds the full
    :class:`~omnist.report.WriteReport` of every adjustment that would have
    been needed, so callers can inspect the structured list, not just the text.
    """

    def __init__(self, message: str, report: "WriteReport | None" = None) -> None:
        """Initialize WriteError with an adjustment report."""
        super().__init__(message)
        self.report = report


class UnsafeXMLWarning(UserWarning):
    """Unused by ``read_xml`` as of the fix for the fail-open XML fallback
    (see issue #173) — ``defusedxml`` is now a hard requirement for XML
    support, and its absence raises ``ImportError`` instead of falling back
    to the unsafe standard-library parser with a warning. Kept exported for
    backward compatibility with any code that imports or references it
    (e.g. an existing ``warnings.filterwarnings(..., category=omnist.UnsafeXMLWarning)``
    call), but nothing in omnist raises it anymore.
    """
