"""Normalisation de texte OCR pour la reconnaissance d'objets en français.

Extrait vers `bdo_ocr_core.normalize` (dépôt `Maxyull/bdo-ocr-core`), partagé
avec rubin-bdo qui a le même besoin de replier des lectures OCR françaises
vers une forme comparable. Ce module ne fait plus que réexporter, pour que
tout le code et tous les tests qui importent `butin.catalog.normalize`
continuent de fonctionner sans changement. Voir `D:\\DEV\\bdo\\COORDINATION.md`
pour l'historique de l'extraction et ATTRIBUTION.md pour l'origine du code.
"""

from __future__ import annotations

from bdo_ocr_core.normalize import fold, fold_digits, is_meaningful, strip_accents

__all__ = ["fold", "fold_digits", "is_meaningful", "strip_accents"]
