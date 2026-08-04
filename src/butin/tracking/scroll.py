"""Détection du défilement par comparaison de pixels.

Signal **indépendant du texte**, et c'est tout son intérêt. L'alignement
textuel (`alignment.py`) est aveugle dans un cas précis mais fréquent : quand
plusieurs lignes identiques se suivent. En farm, dix « Pierre noire (arme) x1 »
d'affilée est la situation normale, pas un cas limite. Le texte ne peut alors
pas dire de combien de crans la fenêtre a défilé, alors que les pixels le
peuvent.

Le principe est simple : on cherche le décalage vertical `s` qui explique le
mieux la différence entre deux images. Si la nouvelle image a défilé de `s`
pixels vers le haut, alors sa ligne `r` doit ressembler à la ligne `r + s` de
l'ancienne.

Dérivé de `core/scroll_detect.py` de janhnguyen/BDO-Loot-Tracker (MIT).

La prudence est asymétrique et voulue : en cas de doute, `expected_new_lines`
renvoie None plutôt qu'une estimation approximative. L'alignement textuel se
débrouille alors seul, ce qui est le comportement par défaut. Une mauvaise
prédiction serait pire que pas de prédiction, puisqu'elle ferait écarter le
recouvrement correct au profit d'un faux.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

GrayFrame = npt.NDArray[np.floating] | npt.NDArray[np.integer]


@dataclass(frozen=True, slots=True)
class ScrollResult:
    """Estimation du défilement entre deux images."""

    shift_px: int
    """Meilleur décalage vers le haut, en pixels. 0 signifie aucun défilement."""

    score: float
    """Différence moyenne par pixel au décalage retenu. Plus bas, mieux c'est."""

    baseline_score: float
    """Différence moyenne sans aucun décalage, pour comparaison."""

    confident: bool
    """Vrai quand le décalage explique nettement mieux l'image que l'absence
    de décalage. Un décalage qui ne fait pas beaucoup mieux que rien n'est pas
    une détection, c'est du bruit."""


def estimate_scroll_px(
    previous: GrayFrame,
    current: GrayFrame,
    *,
    max_shift: int | None = None,
    baseline_eps: float = 2.0,
    improve_ratio: float = 0.5,
) -> ScrollResult:
    """Estime de combien de pixels `current` a défilé vers le haut.

    `baseline_eps` : en dessous de cette différence moyenne, les deux images
    sont tenues pour identiques et aucun défilement n'est rapporté. Sans ce
    seuil, le bruit de compression ou un effet visuel du jeu suffiraient à
    faire croire à un défilement d'un pixel.

    `improve_ratio` : un décalage n'est retenu comme sûr que si son résidu
    passe sous cette fraction du résidu sans décalage. Un décalage qui
    n'améliore que marginalement n'explique rien.
    """
    a = np.asarray(previous, dtype=np.float32)
    b = np.asarray(current, dtype=np.float32)

    # Images incompatibles ou trop petites pour que la question ait un sens.
    if a.ndim != 2 or a.shape != b.shape or a.shape[0] < 4:
        return ScrollResult(shift_px=0, score=0.0, baseline_score=0.0, confident=False)

    height = int(a.shape[0])
    limit = height // 2 if max_shift is None else max_shift
    limit = max(1, min(limit, height - 1))

    baseline = float(np.mean(np.abs(a - b)))
    if baseline < baseline_eps:
        # Rien n'a bougé. Signalé comme sûr : c'est une information, pas une
        # absence d'information.
        return ScrollResult(shift_px=0, score=baseline, baseline_score=baseline, confident=True)

    best_shift, best_score = 0, baseline
    for shift in range(1, limit + 1):
        # Défilement de `shift` vers le haut : current[:h-shift] doit
        # ressembler à previous[shift:].
        score = float(np.mean(np.abs(a[shift:] - b[: height - shift])))
        if score < best_score:
            best_score, best_shift = score, shift

    confident = best_shift > 0 and best_score < baseline * improve_ratio
    return ScrollResult(
        shift_px=best_shift,
        score=best_score,
        baseline_score=baseline,
        confident=confident,
    )


def rows_scrolled(shift_px: int, row_height_px: float) -> float:
    """Convertit un décalage en pixels en nombre de lignes, fractionnaire."""
    if row_height_px <= 0:
        return 0.0
    return shift_px / row_height_px


def expected_new_lines(
    scroll: ScrollResult,
    row_height_px: float,
    max_lines: int,
    *,
    tolerance: float = 0.35,
) -> int | None:
    """Traduit un défilement en nombre attendu de nouvelles lignes.

    Renvoie None dès qu'il y a le moindre doute, et c'est délibéré. Trois
    causes de refus :

    * la détection de défilement n'est pas sûre ;
    * la hauteur de ligne n'est pas connue (calibrage non fait) ;
    * l'estimation tombe entre deux lignes, à plus de `tolerance` d'un entier.
      Un défilement de 1,5 ligne n'existe pas physiquement : soit le calibrage
      de la hauteur de ligne est faux, soit la détection s'est trompée. Dans
      les deux cas, arrondir donnerait une prédiction fausse qui écarterait le
      bon recouvrement.

    L'appelant retombe alors sur l'alignement textuel seul, ce qui reste le
    fonctionnement normal.
    """
    if not scroll.confident or row_height_px <= 0:
        return None
    rows = rows_scrolled(scroll.shift_px, row_height_px)
    nearest = round(rows)
    if abs(rows - nearest) > tolerance:
        return None
    return int(max(0, min(max_lines, nearest)))
