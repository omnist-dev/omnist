"""Encoding-level input normalization shared by every read surface.

Kept in its own leaf module (imports nothing from the package) so that
``oml``, ``osd`` and ``formats`` can all apply the same rule without any
of them having to import each other.
"""
from __future__ import annotations

_BOM = "﻿"


def strip_bom(text: str) -> str:
    """Remove a single leading byte-order mark, per Sec2.5 rule D-15.

    ``U+FEFF`` at offset zero is consumed and contributes nothing to the
    Document or Schema: the result is identical to the same input without
    it. The rule is uniform across OML, OSD and every codec deliberately --
    a BOM carries no data (UTF-8 has no byte-order ambiguity to mark), so
    treating it as content on *some* surfaces is how two implementations
    build different Documents from one file.

    Exactly one mark is stripped, and only at offset zero. A ``U+FEFF``
    anywhere else -- including a second one immediately following the
    first -- is ordinary content with no special meaning, and is left
    alone for the parser to handle as it would any other character.
    """
    return text[1:] if text.startswith(_BOM) else text
