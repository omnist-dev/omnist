"""Exceptions (and one warning) used across omnist."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .report import WriteReport


class OmnistError(Exception):
    """Base class for all omnist errors."""


class SchemaError(OmnistError):
    """The schema text or structure is invalid."""


class ParseError(OmnistError):
    """A document could not be read from its format (outside the supported profile)."""


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
        super().__init__(message)
        self.report = report


class UnsafeXMLWarning(UserWarning):
    """``defusedxml`` isn't installed, so ``read_xml`` fell back to the
    standard library's XML parser, which is vulnerable to entity-expansion
    and external-entity (XXE) attacks on untrusted input.

    Not an exception — parsing still succeeds. ``pip install defusedxml``
    (or the ``xml`` / ``all`` extra) to remove the warning and the risk. If
    you've deliberately decided this doesn't apply (e.g. the XML is never
    from an untrusted source), suppress it with
    ``warnings.filterwarnings("ignore", category=omnist.UnsafeXMLWarning)``.
    """
