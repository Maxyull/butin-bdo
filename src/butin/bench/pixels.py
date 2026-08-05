"""Combien de lignes ont défilé, mesuré sans jamais lire une lettre.

C'est le troisième chemin du banc, et le seul totalement aveugle au texte. Il
répond à la même question que `assembly.py`, « combien de lignes sont passées »,
sans partager avec lui la moindre étape : pas d'OCR, pas de catalogue, pas de
découpage de ligne. Deux mesures indépendantes qui tombent d'accord valent une
preuve ; la même mesure faite deux fois n'en vaut aucune.

⚠️ Ce que le banc a mesuré le 05/08/2026 : cette règle ne fonctionne pas
------------------------------------------------------------------------

La règle retenue jusque-là était la **colonne des pastilles de canal**, choisie
parce qu'elle est opaque là où le fond du journal est transparent sur le monde
du jeu. Elle avait été validée sur deux captures de scènes **différentes**, ce
qui mélangeait le bruit du décor et un vrai changement de contenu. La rafale de
300 images permet enfin de la vérifier sur un vrai défilement, et le résultat
est net :

| Bande mesurée | Détections sûres | Décalage juste à ±3 px |
| --- | --- | --- |
| pastilles, 0 à 90 px | 0 / 20 | **0 / 20** |
| une seule pastille, 10 à 45 px | 0 / 20 | 0 / 20 |
| colonne du texte, 170 à 710 px | 0 / 20 | 9 / 20 |
| zone entière | 0 / 20 | 5 / 20 |

**Zéro détection sûre sur les 299 transitions**, et la colonne des pastilles est
la pire des quatre. La raison est structurelle, et évidente une fois vue : les
pastilles sont **toutes identiques et régulièrement espacées de 21 px**. Un
défilement d'exactement une ligne superpose la pastille `n` sur la pastille
`n+1`, donc ne change rien. Cette colonne est justement celle qui ne peut pas
voir le défilement d'une ligne.

Les colonnes du texte, elles, voient le bon décalage une fois sur deux, mais
jamais assez nettement pour franchir le critère de sûreté : le décor transparent
qui bouge derrière pèse plus lourd que les lettres.

Conséquence pour le compteur, et elle est lourde : `expected_new` reste toujours
à `None`, l'alignement travaille sur le texte seul, et surtout la boucle ne
déclenche plus l'OCR que sur son minuteur de repli de 2 secondes. Le module est
gardé, il mesure ce qu'il peut et **compte ses non-détections** ; c'est
`fingerprints.py` qui corrobore la référence en attendant une règle de mesure
qui marche.

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
from ..tracking.scroll import estimate_scroll_px, rows_scrolled


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
    ruler_left: int = 0,
    ruler_width: int = 90,
    row_height_px: float = 21.0,
) -> PixelScroll:
    """Cumule le défilement image par image sur la colonne des pastilles.

    Les valeurs par défaut sont celles de `capture.loop.LoopConfig`, et c'est
    voulu : le banc doit mesurer la géométrie que la boucle utilise vraiment,
    pas une géométrie idéale qui la flatterait.
    """
    decalages: list[int] = []
    non_sures: list[int] = []
    total = 0

    precedente: GrayImage | None = None
    for index, image in enumerate(images):
        regle: GrayImage = image[:, ruler_left : ruler_left + ruler_width]
        if precedente is None:
            # Première image : rien à comparer, et surtout pas un zéro qui
            # entrerait dans le taux de couverture comme une mesure réussie.
            decalages.append(0)
        else:
            mesure = estimate_scroll_px(precedente, regle)
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
