"""Transformation de captures successives en drops confirmés, sans doublon.

Cette couche ne connaît ni les pixels ni le français : elle reçoit des lignes
déjà lues et déjà reconnues, et décide ce qui compte comme un vrai drop.

L'enchaînement pour chaque image :

1. `StabilityGate` attend que l'animation du journal soit terminée.
2. `estimate_scroll_px` mesure le défilement en pixels, signal indépendant du
   texte.
3. `align` déduit les lignes réellement nouvelles, en s'aidant de cette mesure.
4. `is_glitch_frame` et `is_implausible_jump` écartent les images aberrantes.
5. `LootStager` ne valide un drop qu'après plusieurs observations concordantes.

Dérivé de janhnguyen/BDO-Loot-Tracker (MIT), voir ATTRIBUTION.md.
"""

from .alignment import (
    AlignmentResult,
    align,
    is_glitch_frame,
    is_implausible_jump,
)
from .models import LootEvent, ObservedLine
from .scroll import ScrollResult, estimate_scroll_px, expected_new_lines, rows_scrolled
from .similarity import MatchConfig, digit_confusable, line_similarity
from .stability import StabilityGate, frame_difference
from .staging import LootStager, Slot

__all__ = [
    "AlignmentResult",
    "LootEvent",
    "LootStager",
    "MatchConfig",
    "ObservedLine",
    "ScrollResult",
    "Slot",
    "StabilityGate",
    "align",
    "digit_confusable",
    "estimate_scroll_px",
    "expected_new_lines",
    "frame_difference",
    "is_glitch_frame",
    "is_implausible_jump",
    "line_similarity",
    "rows_scrolled",
]
