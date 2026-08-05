"""Compter les lignes de silver par leur montant, qui est une empreinte.

Pourquoi ce module existe
--------------------------

Le banc a besoin de corroborer sa référence par une mesure qui ne partage rien
avec elle. C'était le rôle de `pixels.py` ; mesuré sur la rafale du 05/08/2026,
**il ne détecte aucun défilement** (voir son en-tête). Sans corroboration, la
référence n'est qu'une opinion, et le banc ne conclut rien.

Celle-ci fonctionne, et repose sur une propriété du jeu plutôt que sur un
algorithme : **le montant de silver d'un drop est tiré au hasard**. Sur la
rafale, les montants vont de 1 500 à 6 700 environ, et 3 451 lectures de lignes
de silver ne portent que **60 valeurs distinctes**, soit 57 lectures par valeur.
Autrement dit chaque montant est un identifiant de fait, stable d'une image à
l'autre là où le texte autour ne l'est pas.

Compter les montants distincts, c'est donc compter les lignes de silver, **sans
aucun recalage, sans aucune position, sans aucun alignement**. C'est le seul
point commun avec `assembly.py` : le découpage d'une ligne en nom et quantité.

⚠️ Ce n'est PAS le piège du 05/08
-----------------------------------

Prendre « les lignes distinctes vues » pour la vérité terrain a déjà fait
échouer une mesure, parce que deux drops identiques à quelques secondes d'écart
sont deux lignes du journal et un seul texte distinct. Ici la situation est
inverse et il faut voir pourquoi :

* on ne compte pas des **textes**, on compte des **montants tirés au hasard**.
  Deux lignes de silver ne portent le même nombre que par collision, alors que
  deux lignes d'objet portent le même texte par construction ;
* le résultat est annoncé comme une **borne basse** et jamais comme la vérité :
  une collision fait sous-compter, elle ne peut pas faire sur-compter ;
* il ne sert qu'à **corroborer** un autre nombre, jamais à en tenir lieu.

Le nombre de collisions attendues se calcule : pour `n` lignes tirées dans une
plage de largeur `p`, il en vient environ `n(n-1)/(2p)`. Avec 48 lignes sur une
plage de 5 000, cela fait moins d'une demie. C'est ce qui rend la borne serrée
ici, et c'est aussi ce qui cesserait d'être vrai sur une rafale dix fois plus
longue : le rapport affiche donc de quoi le recalculer.
"""

from __future__ import annotations

import statistics
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from ..capture.lines import DEFAULT_FORMAT, ChatLineFormat, split_line
from ..catalog.normalize import fold


@dataclass(frozen=True, slots=True)
class Fingerprints:
    """Ce que les montants de silver disent du nombre de lignes passées."""

    distinct: int
    """Montants jamais vus sur la première image. Borne BASSE du nombre de
    lignes de silver apparues pendant la rafale."""

    baseline: int
    """Montants déjà présents sur la première image, donc appartenant au passé."""

    occurrences: int
    """Lectures de lignes de silver, toutes images confondues."""

    median_support: float
    """Nombre médian de lectures par montant. Élevé, l'empreinte est stable ;
    proche de 1, les chiffres bafouillent et la mesure ne vaut plus rien."""

    span: int
    """Écart entre le plus grand et le plus petit montant observé. Avec le
    nombre de lignes, c'est de quoi estimer les collisions attendues."""

    @property
    def expected_collisions(self) -> float:
        """Collisions attendues si les montants étaient tirés uniformément.

        Sert à savoir de combien la borne basse peut sous-compter. Au-delà de
        quelques unités, la mesure cesse d'être une corroboration utile.
        """
        lignes = self.distinct + self.baseline
        if self.span <= 0:
            return 0.0
        return lignes * (lignes - 1) / (2.0 * self.span)


def silver_fingerprints(
    frames: Sequence[Sequence[str]], *, fmt: ChatLineFormat = DEFAULT_FORMAT
) -> Fingerprints:
    """Relève les montants de silver de toutes les images.

    N'utilise volontairement pas le catalogue : une ligne de silver se
    reconnaît à son nom, pas à une recherche d'objet. Moins ce module partage
    avec la référence, plus leur accord vaut quelque chose.
    """
    vus: Counter[int] = Counter()
    premiere: set[int] = set()

    for index, frame in enumerate(frames):
        for brut in frame:
            parts = split_line(brut, fmt)
            if parts is None or fold(parts.name) not in fmt.folded_silver:
                continue
            if parts.quantity_uncertain:
                # Un montant illisible n'est pas une empreinte : le retenir
                # confondrait toutes les lignes dont le « x » a mal été lu en
                # une seule, et ferait sous-compter sans qu'on le sache.
                continue
            vus[parts.qty] += 1
            if index == 0:
                premiere.add(parts.qty)

    apres = set(vus) - premiere
    montants = sorted(vus)
    return Fingerprints(
        distinct=len(apres),
        baseline=len(premiere),
        occurrences=sum(vus.values()),
        median_support=statistics.median(vus.values()) if vus else 0.0,
        span=(montants[-1] - montants[0]) if montants else 0,
    )
