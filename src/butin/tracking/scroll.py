"""Détection du défilement par comparaison de pixels.

Extrait vers `bdo_ocr_core.scroll` (dépôt `Maxyull/bdo-ocr-core`), partagé
avec rubin-bdo. Ce module ne fait plus que réexporter, pour que tout le code
et tous les tests qui importent `butin.tracking.scroll` continuent de
fonctionner sans changement. Voir `D:\\DEV\\bdo\\COORDINATION.md` pour
l'historique de l'extraction et ATTRIBUTION.md pour l'origine du code.
"""

from __future__ import annotations

from bdo_ocr_core.scroll import (
    BRIGHT_MIN_GAIN,
    BRIGHT_MIN_OVERLAP,
    BRIGHT_THRESHOLD,
    GrayFrame,
    ScrollResult,
    bright_mask,
    estimate_scroll_px,
    estimate_text_scroll_px,
    expected_new_lines,
    rows_scrolled,
)

__all__ = [
    "BRIGHT_MIN_GAIN",
    "BRIGHT_MIN_OVERLAP",
    "BRIGHT_THRESHOLD",
    "GrayFrame",
    "ScrollResult",
    "bright_mask",
    "estimate_scroll_px",
    "estimate_text_scroll_px",
    "expected_new_lines",
    "rows_scrolled",
]
