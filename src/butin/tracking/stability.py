"""Attente que la zone du journal soit stable avant de lancer l'OCR.

Extrait vers `bdo_ocr_core.stability` (dépôt `Maxyull/bdo-ocr-core`), partagé
avec rubin-bdo. Ce module ne fait plus que réexporter, pour que tout le code
et tous les tests qui importent `butin.tracking.stability` continuent de
fonctionner sans changement. Voir `D:\\DEV\\bdo\\COORDINATION.md` pour
l'historique de l'extraction et ATTRIBUTION.md pour l'origine du code.
"""

from __future__ import annotations

from bdo_ocr_core.stability import StabilityGate, frame_difference

__all__ = ["StabilityGate", "frame_difference"]
