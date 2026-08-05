"""Combien de lignes ont défilé, mesuré sans jamais lire une lettre.

C'est le troisième chemin du banc, et le seul totalement aveugle au texte. Il
répond à la même question que `assembly.py`, « combien de lignes sont passées »,
sans partager avec lui la moindre étape : pas d'OCR, pas de catalogue, pas de
découpage de ligne. Deux mesures indépendantes qui tombent d'accord valent une
preuve ; la même mesure faite deux fois n'en vaut aucune.

La règle de mesure, et comment elle a été trouvée
--------------------------------------------------

La première règle était la **colonne des pastilles de canal**, choisie parce
qu'elle est opaque là où le fond du journal est transparent sur le monde du jeu.
Elle avait été validée sur deux captures de scènes **différentes**, ce qui
mélangeait le bruit du décor et un vrai changement de contenu. La rafale de 300
images a permis de la vérifier sur un vrai défilement, et le verdict est sans
appel : **0 détection juste sur 37**, la pire des bandes essayées.

La raison est structurelle : les pastilles `Système` sont toutes identiques et
espacées d'exactement un pas de ligne. Un défilement d'une ligne superpose la
pastille `n` sur la pastille `n+1` et ne change donc rien. C'est justement la
colonne aveugle à ce qu'on lui demande de voir.

La règle qui marche est la **colonne du texte, comparée sur un masque de pixels
clairs**. Le texte du journal est peint en clair, le monde du jeu est sombre
(médiane 21 sur 255 sur ces captures) : le masque le fait disparaître, et il ne
reste que les lettres, qui elles défilent.

| Mesure | Détections justes | Fausses détections |
| --- | --- | --- |
| gris, colonne des pastilles | **0 / 37** | 0 / 262 |
| gris, colonne du texte | 17 / 37 | 0 / 262 |
| **masque clair, colonne du texte** | **32 / 37** | **0 / 262** |

Sur les 5 transitions qu'elle rate, elle rend **0 et non un mauvais décalage** :
juste ou muette, jamais trompeuse. Une prédiction fausse ferait recompter du
butin, une absence de prédiction fait seulement retomber sur le texte seul.

Ce que la mesure ne sait pas faire, et qui est assumé :

* elle compte **toutes** les lignes de chat, pas seulement le butin. Le journal
  est entrelacé avec la conversation des joueurs, donc ce total est une borne
  **haute** du nombre de drops, jamais une estimation ;
* elle ne voit rien tant que la fenêtre n'est pas pleine : une ligne qui
  s'ajoute sans rien pousser ne produit aucun défilement ;
* une mesure jugée non sûre est **écartée et comptée à part**, jamais remplacée
  par zéro. Zéro affirmerait que rien n'a bougé, ce qui est une information, et
  une information fausse.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ..capture.screen import GrayImage
from ..tracking.scroll import BRIGHT_THRESHOLD, estimate_text_scroll_px, rows_scrolled


@dataclass(frozen=True, slots=True)
class PixelScroll:
    """Défilement cumulé sur toute la rafale."""

    total_px: int
    rows: float
    """Lignes défilées, fractionnaires. Le reste après la virgule est en soi un
    indicateur : une hauteur de ligne mal calibrée l'éloigne d'un entier."""

    unsure: tuple[int, ...]
    """Images dont la mesure a été jugée non sûre, donc non comptée."""

    per_frame_px: tuple[int, ...]
    """Décalage retenu image par image, 0 pour la première et pour les non
    sûres. Conservé pour repérer à quel moment de la rafale ça s'est gâté."""

    row_height_px: float

    @property
    def detections(self) -> int:
        """Transitions où un défilement non nul a été jugé sûr.

        Distinct de la couverture, et c'est tout l'intérêt : une mesure peut
        être « sûre » en disant que rien n'a bougé. Zéro détection sur une
        rafale où des lignes sont manifestement apparues signifie que la règle
        de mesure ne mesure rien, pas que le journal était immobile.
        """
        return sum(1 for decalage in self.per_frame_px if decalage > 0)

    @property
    def coverage(self) -> float:
        """Part des transitions dont la mesure a été retenue, de 0 à 1."""
        transitions = max(0, len(self.per_frame_px) - 1)
        if transitions == 0:
            return 0.0
        return 1.0 - len(self.unsure) / transitions


def measure_scroll(
    images: Sequence[GrayImage],
    *,
    ruler_left_ratio: float = 0.19,
    ruler_right_ratio: float = 0.92,
    row_height_px: float = 21.6,
    max_scroll_lines: int = 8,
    bright_threshold: int = BRIGHT_THRESHOLD,
) -> PixelScroll:
    """Cumule le défilement image par image sur la colonne du texte.

    Les valeurs par défaut sont celles de `capture.loop.LoopConfig`, et c'est
    voulu : le banc doit mesurer la géométrie que la boucle utilise vraiment,
    pas une géométrie idéale qui la flatterait.
    """
    decalages: list[int] = []
    non_sures: list[int] = []
    total = 0
    max_shift = max(1, round(max_scroll_lines * row_height_px))

    precedente: GrayImage | None = None
    for index, image in enumerate(images):
        largeur = image.shape[1]
        gauche = max(0, min(largeur - 1, round(largeur * ruler_left_ratio)))
        droite = max(gauche + 1, min(largeur, round(largeur * ruler_right_ratio)))
        regle: GrayImage = image[:, gauche:droite]
        if precedente is None:
            # Première image : rien à comparer, et surtout pas un zéro qui
            # entrerait dans le taux de couverture comme une mesure réussie.
            decalages.append(0)
        else:
            mesure = estimate_text_scroll_px(
                precedente, regle, max_shift=max_shift, threshold=bright_threshold
            )
            if mesure.confident:
                total += mesure.shift_px
                decalages.append(mesure.shift_px)
            else:
                non_sures.append(index)
                decalages.append(0)
        precedente = regle

    return PixelScroll(
        total_px=total,
        rows=rows_scrolled(total, row_height_px),
        unsure=tuple(non_sures),
        per_frame_px=tuple(decalages),
        row_height_px=row_height_px,
    )
