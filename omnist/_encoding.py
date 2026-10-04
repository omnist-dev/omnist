"""Encoding-level input normalization shared by every read surface.

Kept in its own leaf module (imports nothing from the package except the
error types) so that ``oml``, ``osd``, ``formats`` and the CLI can all apply
the same rules without any of them having to import each other. Three
rules of Sec2.5 live here and nowhere else:

* **D-14** -- :func:`decode_utf8`: bytes MUST be valid UTF-8.
* **D-15** -- :func:`strip_bom`: exactly one leading ``U+FEFF`` is consumed.
* **D-21** -- :func:`strip_bom` with ``reject_second=True``: a second mark
  still at offset zero is rejected (the codecs; OML and OSD reject it on
  their own grammar, as a stray character).

and one rule of Sec2.4.2:

* **D-23** -- :func:`check_input_size`: the input is at most
  ``max_input_bytes`` bytes, counted before the BOM is stripped and before
  decoding, else ``document.limit.input-size`` at ``$``.
"""
from __future__ import annotations

from typing import Any, Union

from ._paths import edge_paths
from .errors import ParseError, WriteError

# D-24 gives no reference default; this implementation's is 64 MiB. It is a
# bound on parse cost (a byte cap is the only thing that bounds a codec
# library's superlinear cases), not a promise that an input this big parses
# quickly: PyYAML takes seconds on a 1 MB mapping.
DEFAULT_MAX_INPUT_BYTES = 64 * 1024 * 1024

# Written as an escape, never as the raw character: an invisible U+FEFF in
# this source file would be indistinguishable from nothing (and a guard
# test byte-scans every tracked file for one).
_BOM = "\ufeff"


def validate_max_input_bytes(value: Any) -> None:
    """Refuse a non-integer or a non-positive ``max_input_bytes``.

    ``TypeError`` for a wrong type (``bool`` is not accepted as an int),
    ``ValueError`` for a value below 1. There is no ceiling: D-24 lets an
    implementation choose any finite value."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"max_input_bytes must be an int, not {type(value).__name__}")
    if value < 1:
        raise ValueError(f"max_input_bytes must be at least 1, not {value}")


def input_size_error(max_input_bytes: int) -> ParseError:
    """The D-23 refusal: ``document.limit.input-size`` at ``$``."""
    return ParseError(
        f"input exceeds the maximum input size ({max_input_bytes} bytes)",
        code="document.limit.input-size", path="$")


def check_input_size(data: Union[str, bytes], max_input_bytes: int) -> None:
    """Sec2.4.2 D-23: refuse an input of more than ``max_input_bytes`` bytes,
    accept one of exactly that many.

    Bytes, not characters: a ``str`` is measured as its UTF-8 encoding (``e``
    with an acute accent is two, a leading U+FEFF is three, a lone surrogate
    three as ``surrogatepass`` would write it), and the length is taken
    before the mark is stripped (D-15) and before any decoding, so this
    check precedes every other diagnostic."""
    validate_max_input_bytes(max_input_bytes)
    if isinstance(data, bytes):
        size = len(data)
    else:
        n = len(data)
        # every character is at least one byte and at most four, so the exact
        # (linear) encode is only needed in between
        if n > max_input_bytes:
            raise input_size_error(max_input_bytes)
        if n * 4 <= max_input_bytes:
            return
        size = len(data.encode("utf-8", "surrogatepass"))
    if size > max_input_bytes:
        raise input_size_error(max_input_bytes)


def _encodes(s: str) -> bool:
    if s.isascii():
        return True
    try:
        s.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def check_encodable(node: Any) -> None:
    """Sec7.3 C-9: every writer fails, unconditionally, on a string value or an
    edge label with no UTF-8 encoding -- a lone surrogate, or a surrogate-escape
    artefact (U+DC80..U+DCFF) from ``errors="surrogateescape"`` -- with
    ``write.unsupported-value``. Emitting it as an escape (``\\ud800``) is not
    an alternative: only a failure complies.

    The path is the Document path of the node *holding* the string: the leaf
    for a value (indexed per E-10), the node that holds the edge for a label
    (Sec8.4 cannot quote a label, so the label is never put in the path).
    Stops at the first offender, in document order; iterative, so a node
    deeper than the writers' own depth limit is still refused by *their*
    depth check, not by a ``RecursionError`` here."""
    stack: list[tuple[str, Any]] = [("$", node)]
    while stack:
        path, n = stack.pop()
        if not isinstance(n, list):
            if isinstance(n, str) and not _encodes(n):
                raise WriteError(
                    f"{path}: a string value with no UTF-8 encoding (a lone surrogate or a "
                    "surrogate escape) cannot be written", code="write.unsupported-value",
                    path=path)
            continue
        edges = list(edge_paths(path, n))
        for label, _child, _p in edges:
            if not _encodes(label):
                raise WriteError(
                    f"{path}: an edge label with no UTF-8 encoding (a lone surrogate or a "
                    "surrogate escape) cannot be written", code="write.unsupported-value",
                    path=path)
        stack.extend((p, child) for _label, child, p in reversed(edges))


def decode_utf8(data: bytes) -> str:
    """Decode ``data`` as strict UTF-8, per Sec2.5 rule D-14.

    A malformed sequence raises :class:`~omnist.errors.ParseError` with
    ``code="parse.invalid-encoding"`` and ``path="1:1"`` -- always ``1:1``,
    wherever the bad byte sits, because what failed is the decoding of the
    input as a whole and there is no decoded text to take a position from.
    Nothing is repaired: no ``U+FFFD``, no surrogate escapes. At most one
    diagnostic results however many malformed sequences the input holds.

    This is the entry point every byte-oriented caller (the CLI's file and
    stdin reads) goes through. A ``str``-typed reader may treat its input as
    already decoded, so it never calls this.
    """
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ParseError(
            f"input is not valid UTF-8 ({exc.reason} at byte {exc.start})",
            code="parse.invalid-encoding", path="1:1") from exc


def strip_bom(text: str, *, reject_second: bool = False) -> str:
    """Remove a single leading byte-order mark, per Sec2.5 rule D-15.

    ``U+FEFF`` at offset zero is consumed and contributes nothing to the
    Document or Schema: the result is identical to the same input without
    it. The rule is uniform across OML, OSD and every codec deliberately --
    a BOM carries no data (UTF-8 has no byte-order ambiguity to mark), so
    treating it as content on *some* surfaces is how two implementations
    build different Documents from one file.

    Exactly one mark is stripped, and only at offset zero. A ``U+FEFF``
    anywhere else is ordinary content with no special meaning and is left
    alone.

    D-21: a second mark still at offset zero of what remains MUST NOT be
    swallowed. OML and OSD reject it on their own grammar (an unexpected
    token at ``1:1``), so they leave ``reject_second`` false. The four
    codecs cannot rely on their libraries -- PyYAML and expat both discard
    a leading mark before any grammar sees it -- so they pass
    ``reject_second=True`` and the check happens here, on the text, before
    the library is handed anything: ``parse.codec-syntax`` at ``1:1``
    (E-24).
    """
    if not text.startswith(_BOM):
        return text
    text = text[1:]
    if reject_second and text.startswith(_BOM):
        raise ParseError(
            "a second leading U+FEFF byte-order mark follows the one that was "
            "stripped (D-21: exactly one is consumed)",
            code="parse.codec-syntax", path="1:1")
    return text
