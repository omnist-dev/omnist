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
"""
from __future__ import annotations

from .errors import ParseError

# Written as an escape, never as the raw character: an invisible U+FEFF in
# this source file would be indistinguishable from nothing (and a guard
# test byte-scans every tracked file for one).
_BOM = "\ufeff"


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
