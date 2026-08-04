"""Attente que la zone du journal soit stable avant de lancer l'OCR.

Le journal d'acquisition fait apparaître les nouvelles lignes en fondu sur
quelques images. Une reconnaissance lancée au milieu de cette animation lit du
texte à moitié transparent et produit des résultats aberrants, qui polluent
ensuite l'alignement et le vote.

Ce garde-fou mesure le changement d'une image à l'autre et ne déclare la zone
stable qu'après plusieurs images consécutives sans mouvement.

Dérivé de `core/stability.py` de janhnguyen/BDO-Loot-Tracker (MIT).

Volontairement prudent : une image jugée instable ne fait que retarder l'OCR
d'un tour, soit environ un dixième de seconde. Elle ne perd jamais de butin,
puisque la ligne reste affichée une quinzaine de secondes. Le coût d'une
attente inutile est donc négligeable devant celui d'une lecture pourrie.
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

from .scroll import GrayFrame


def frame_difference(previous: GrayFrame, current: GrayFrame) -> float:
    """Différence absolue moyenne par pixel entre deux images, de 0 à 255.

    Renvoie l'infini si les images ne sont pas comparables. Une valeur infinie
    ne franchit aucun seuil, donc une image de taille inattendue est
    automatiquement traitée comme instable plutôt que comme identique.
    """
    a = np.asarray(previous, dtype=np.float32)
    b = np.asarray(current, dtype=np.float32)
    if a.shape != b.shape or a.size == 0:
        return float("inf")
    return float(np.mean(np.abs(a - b)))


class StabilityGate:
    """Déclare la zone stable après N images consécutives sans changement."""

    def __init__(self, diff_threshold: float = 3.0, min_stable_frames: int = 2) -> None:
        self._diff_threshold = diff_threshold
        self._min_stable_frames = max(1, min_stable_frames)
        self._previous: npt.NDArray[np.float32] | None = None
        self._stable_run = 0
        self._last_diff = float("inf")

    @property
    def last_diff(self) -> float:
        return self._last_diff

    @property
    def stable_run(self) -> int:
        return self._stable_run

    def reset(self) -> None:
        self._previous = None
        self._stable_run = 0
        self._last_diff = float("inf")

    def update(self, gray: GrayFrame) -> bool:
        """Fournit la dernière image et dit si la zone est stable.

        La toute première image après une remise à zéro n'est jamais stable :
        il n'existe encore aucune image de référence à laquelle la comparer, et
        déclarer stable une image jamais comparée serait une affirmation sans
        fondement.
        """
        frame = np.asarray(gray, dtype=np.float32)

        if self._previous is None:
            self._previous = frame
            self._stable_run = 0
            self._last_diff = float("inf")
            return False

        diff = frame_difference(self._previous, frame)
        self._last_diff = diff
        self._previous = frame

        if diff <= self._diff_threshold:
            self._stable_run += 1
        else:
            self._stable_run = 0

        return self._stable_run >= self._min_stable_frames
