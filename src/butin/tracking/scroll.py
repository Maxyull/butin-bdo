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

Deux mesures, et il faut prendre la bonne
------------------------------------------

`estimate_scroll_px` compare les niveaux de gris. C'est la mesure d'origine,
héritée du projet amont, et elle convient à un contenu **opaque**. Butin ne s'en
sert plus nulle part ; elle est conservée parce que c'est elle, et non la
suivante, qui a sa place dans le socle OCR partagé avec l'autre projet du
dossier, dont le contenu n'est pas forcément transparent.

`estimate_text_scroll_px` compare des **masques de pixels clairs**. C'est celle
qu'il faut pour le journal du jeu, dont le fond est transparent sur le monde.
Mesuré par le banc d'essai le 05/08/2026 sur 300 images de vrai farm, contre le
défilement que la référence sait exact :

| Mesure | Détections justes | Fausses détections |
| --- | --- | --- |
| gris, colonne des pastilles | **0 / 37** | 0 / 262 |
| gris, colonne du texte | 17 / 37 | 0 / 262 |
| **masque clair, colonne du texte** | **32 / 37** | **0 / 262** |

La différence tient à ce que chaque mesure regarde. En niveaux de gris, le
décor qui bouge derrière le texte pèse plus lourd que les lettres, parce qu'il
occupe toute la surface. Un masque de pixels clairs le fait disparaître : le
texte du journal est peint en clair, le monde du jeu est sombre (médiane 21 sur
255 sur ces captures). Ne restent que les lettres, et elles, elles défilent.

⛔ **La colonne des pastilles de canal ne peut pas fonctionner**, quelle que
soit la mesure. Les pastilles sont toutes identiques et espacées d'exactement
un pas de ligne : un défilement d'une ligne superpose la pastille `n` sur la
pastille `n+1` et ne change donc rien. C'est précisément la colonne aveugle au
défilement d'une ligne.

La propriété qui compte, et qui est vérifiée : sur les 5 transitions que la
nouvelle mesure rate, elle rend **0 et non un mauvais décalage**. Elle est
juste ou muette, jamais trompeuse. Une prédiction fausse ferait recompter du
butin ; une absence de prédiction fait seulement retomber sur le texte seul.
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


BRIGHT_THRESHOLD = 115
"""Niveau au-dessus duquel un pixel est tenu pour du texte.

Mesuré, pas choisi : sur les captures du journal, la médiane de la zone est à
**21 sur 255**, parce que le chat est transparent sur un décor de nuit. Le texte,
lui, est peint en clair. Le seuil sépare donc deux populations très éloignées,
et le banc d'essai donne le même résultat de 100 à 130 : c'est un plateau, pas
une valeur critique.
"""

BRIGHT_MIN_GAIN = 0.02
"""Part du désaccord qu'un décalage doit expliquer pour être tenu pour sûr.

Une part et non une différence brute, et c'est la mesure qui l'impose. Trois
populations relevées sur les 300 images du banc :

| Situation | Part du désaccord expliquée |
| --- | --- |
| les 32 décalages justes | **0,030 au minimum**, 0,297 en médiane |
| les 262 transitions sans défilement | **0** |
| une image de bruit uniforme | **0,006** |

Un critère en différence brute laissait passer l'image de bruit : sur des
pixels tirés au hasard, il existe toujours un décalage qui améliore un peu le
recouvrement, et « un peu » suffisait. Rapporté à ce qu'il reste à expliquer,
ce hasard vaut 0,006 quand un vrai défilement vaut 0,030 au pire.

0,02 se place entre les deux, à trois fois le bruit et à une fois et demie
sous la plus faible vraie détection.
"""

BRIGHT_MIN_OVERLAP = 0.30
"""Recouvrement absolu qu'un décalage retenu doit atteindre.

Le gain relatif dit qu'un décalage explique mieux qu'aucun décalage ; il ne dit
pas que les deux images montrent le même texte. Sur deux contenus sans aucun
rapport, il existe toujours un décalage qui gagne un peu, et sur une petite
surface ce hasard suffit à franchir le seuil.

Mesuré sur les 300 images : les 32 décalages justes atteignent **0,433 au
minimum** et 0,605 en médiane. Deux contenus sans rapport plafonnent autour de
0,1. La valeur retenue laisse 44 % de marge sous la plus faible vraie détection.

C'est bas exprès : deux lectures d'une même ligne ne partagent pas tous leurs
pixels, parce que le décor derrière le texte transparent change lequel de ses
pixels franchit le seuil de clarté. Exiger un recouvrement élevé rejetterait
des détections correctes.
"""


def bright_mask(frame: GrayFrame, *, threshold: int = BRIGHT_THRESHOLD) -> npt.NDArray[np.bool_]:
    """Ne garde que les pixels clairs, c'est-à-dire le texte.

    C'est l'étape qui fait toute la différence sur un fond transparent : elle
    retire le décor du jeu, qui bouge pour ses propres raisons et qui, en
    niveaux de gris, pèse plus lourd que les lettres.

    ⚠️ À ne pas confondre avec la binarisation, écartée pour l'OCR après mesure.
    Là-bas il fallait des glyphes **lisibles**, et un seuil global mangeait le
    contour ou le texte selon le décor. Ici on ne lit rien : on cherche une
    signature spatiale stable d'une image à l'autre, et un masque grossier suffit
    parfaitement. Le même outil, deux problèmes différents, deux verdicts opposés.
    """
    mask: npt.NDArray[np.bool_] = np.asarray(frame) > threshold
    return mask


def _overlap_ratio(previous: npt.NDArray[np.bool_], current: npt.NDArray[np.bool_]) -> float:
    """Part des pixels de texte communs aux deux masques, de 0 à 1.

    Intersection sur union, et non nombre de pixels identiques : deux masques
    presque vides seraient « identiques » à 99 % sur leurs pixels éteints, ce
    qui ferait de n'importe quel décalage un excellent décalage.
    """
    union = float(np.logical_or(previous, current).sum())
    if union == 0.0:
        return 0.0
    return float(np.logical_and(previous, current).sum()) / union


def estimate_text_scroll_px(
    previous: GrayFrame,
    current: GrayFrame,
    *,
    max_shift: int | None = None,
    threshold: int = BRIGHT_THRESHOLD,
    min_gain: float = BRIGHT_MIN_GAIN,
    min_overlap: float = BRIGHT_MIN_OVERLAP,
) -> ScrollResult:
    """Estime le défilement sur les pixels de texte seuls.

    À utiliser sur le journal du jeu, dont le fond est transparent. Voir
    l'en-tête du module pour la mesure qui impose ce choix.

    `score` et `baseline_score` portent une **dissemblance** (1 moins le
    recouvrement), pour garder la convention de `ScrollResult` où plus bas vaut
    mieux. Les inverser ici rendrait les deux mesures incomparables dans un
    journal de diagnostic.
    """
    a = bright_mask(previous, threshold=threshold)
    b = bright_mask(current, threshold=threshold)

    if a.ndim != 2 or a.shape != b.shape or a.shape[0] < 4:
        return ScrollResult(shift_px=0, score=0.0, baseline_score=0.0, confident=False)

    height = int(a.shape[0])
    limit = height // 2 if max_shift is None else max_shift
    limit = max(1, min(limit, height - 1))

    baseline = _overlap_ratio(a, b)
    best_shift, best_ratio = 0, baseline
    for shift in range(1, limit + 1):
        # Défilement de `shift` vers le haut : current[:h-shift] doit
        # ressembler à previous[shift:].
        ratio = _overlap_ratio(a[shift:], b[: height - shift])
        if ratio > best_ratio:
            best_ratio, best_shift = ratio, shift

    # Rapporté à ce qu'il RESTE à expliquer, et non au recouvrement total :
    # gagner 0,02 quand on part de 0,03 est une découverte, gagner 0,02 quand on
    # part de 0,95 est du bruit d'arrondi. Voir `BRIGHT_MIN_GAIN`.
    marge = 1.0 - baseline
    explique = (best_ratio - baseline) / marge if marge > 0 else 0.0

    # ⚠️ « Rien n'a bougé » est une information, pas un doute, et il faut que la
    # sûreté puisse le dire. Sinon chaque tour sans défilement, qui est le cas
    # le plus fréquent, marquerait l'accumulation comme non fiable et la boucle
    # ne prédirait plus jamais rien : exactement la panne qu'on vient de
    # corriger, réintroduite par l'autre bout.
    #
    # Ce qui distingue « zéro » de « je ne sais pas », c'est le recouvrement
    # sans décalage : au-dessus du plancher, les deux images montrent bien le
    # même texte et n'avoir trouvé aucun décalage est une réponse.
    #
    # Pour un décalage non nul il faut les deux conditions. Le gain relatif dit
    # que le décalage explique mieux que rien ; le recouvrement absolu dit que
    # les deux images montrent le même texte. La première seule laisse passer
    # deux contenus sans rapport, où un décalage gagne toujours un peu par
    # hasard.
    if best_shift == 0:
        confident = baseline >= min_overlap
    else:
        confident = explique >= min_gain and best_ratio >= min_overlap
    return ScrollResult(
        shift_px=best_shift,
        score=1.0 - best_ratio,
        baseline_score=1.0 - baseline,
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
