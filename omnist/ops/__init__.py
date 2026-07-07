"""Schema operations package.

One module per algorithm from the paper (Lee & Cheung, "XML Schema Computations",
CIKM 2010).
"""

from .extract import extract
from .lint import LintFinding, lint
from .minimize import equivalence_classes, normalize
from .prune import is_empty, prune, satisfiable_set
from .subschema import compatible_with, equivalent

__all__ = [
    "compatible_with", "equivalent", "normalize", "equivalence_classes",
    "is_empty", "prune", "satisfiable_set",
    "extract",
    "lint", "LintFinding",
]
