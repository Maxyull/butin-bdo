"""Reconstruction de la suite des lignes, par un chemin étranger au compteur.

Ce module produit la **référence** à laquelle le compteur est comparé. Tout son
intérêt est dans ce qu'il refuse d'utiliser.

Ce qu'il n'utilise pas, et pourquoi
------------------------------------

* **Aucun score flou.** Deux lectures sont la même ligne si elles sont
  strictement égales. `tracking/similarity.py` est volontairement ignoré : une
  référence qui partagerait la tolérance du compteur partagerait aussi ses
  erreurs, et l'accord des deux ne voudrait plus rien dire.
* **Aucune mesure de pixels.** Le défilement est mesuré séparément dans
  `pixels.py`, et sert à corroborer ce module de l'extérieur. Le lui donner en
  entrée détruirait cette corroboration.
* **Aucun garde-fou.** Ni image aberrante écartée, ni saut jugé
  invraisemblable. Là où le compteur protège son total, la référence encaisse et
  laisse une trace, parce qu'une trace est examinable et une protection non.

La seule tolérance, et pourquoi elle n'en est pas une
------------------------------------------------------

L'égalité porte sur le texte **débarrassé de ses espaces**, et rien d'autre.

Ce n'est pas une commodité, c'est ce que la mesure impose. Sur la rafale du
05/08/2026, deux lectures d'une même ligne physique à 100 ms d'intervalle sont
identiques au caractère près dans **31 %** des cas seulement, et dans **70 %**
une fois les espaces retirés. La différence est presque entièrement du
découpage : le moteur rend « obtenu : » ou « obtenu: », « Vous avez » ou
« Vousavez », selon la façon dont il a groupé ses fragments sur cette image-là.

Autrement dit l'espacement ne vient pas du jeu, il vient du lecteur. L'égalité
stricte sur le texte brut mesurerait la stabilité de rapidocr, pas l'identité
des lignes : sur les 300 images, elle a fait échouer le recalage sur **268
d'entre elles**. Retirer les espaces reste une égalité exacte, sans seuil et
sans score ; ce qui est comparé est simplement la bonne chose.

Les 30 % qui diffèrent encore sont du bruit de glyphe (« lunel » pour « lune »).
Ils ne sont pas rattrapés, et n'ont pas besoin de l'être : avec 24 lignes par
image, le bon placement marque environ +10 quand tous les autres sont largement
négatifs. La marge est suffisante, et la garder large est ce qui empêche le
recalage de se tromper.

Ce qu'il utilise, et que le compteur n'a pas
---------------------------------------------

**Toutes les images, pas une sur quatre.** En jeu, la reconnaissance coûte
336 ms et la boucle ne peut en lire qu'environ trois par seconde ; le banc, lui,
n'est pas pressé et relit les 300 images de la rafale. Chaque ligne physique est
donc vue des dizaines de fois au lieu de trois ou quatre, et son texte est
tranché au vote sur toutes ces lectures.

C'est ce qui rend l'égalité stricte utilisable malgré un OCR qui bafouille : une
lecture abîmée est minoritaire face à trente lectures nettes de la même ligne.

Le principe du recalage
------------------------

Le journal est une file : la fenêtre montre toujours les `w` dernières lignes.
Placer une image dans la suite reconstruite revient donc à choisir un seul
nombre, `n`, le nombre de lignes que cette image ajoute. Le reste s'en déduit ::

    suite reconstruite   ┌───────────────────────── len(suite)
                         │
      ... A B C D E F G  │
              └─────────┼──┐
      image :   C D E F G  H I      n = 2 (H et I sont nouvelles)
                └───────┘
                recouvrement noté et voté

Pour chaque `n` possible, on compte les positions où le texte de l'image égale
le texte majoritaire déjà reconstruit, moins celles où il en diffère. Le bon
`n` fait s'aligner une vingtaine de lignes d'un coup ; un mauvais `n` n'aligne
rien. À égalité, on retient le plus petit `n`, qui est l'hypothèse la plus
sobre.

⚠️ Ce module n'est PAS la vérité, c'est une deuxième opinion. Il a ses propres
biais, mesurés et figés dans les tests : un OCR qui bafouille au point que la
majorité bascule le fait sur-compter. C'est pour ça qu'il expose `support` et
`agreement` par ligne, et que le rapport refuse de conclure quand `pixels.py`
ne le corrobore pas.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

_ESPACES = re.compile(r"\s+")


def canon(texte: str) -> str:
    """Forme sur laquelle porte l'égalité : le texte sans aucun espace.

    Voir l'en-tête du module pour la mesure qui impose ce choix. Volontairement
    exposée : le rapport doit pouvoir dire sur quoi il a comparé, et un test
    doit pouvoir vérifier que rien de plus n'est toléré.
    """
    return _ESPACES.sub("", texte)


@dataclass(frozen=True, slots=True)
class AssembledLine:
    """Une ligne physique du journal, telle que le recalage la reconstitue."""

    text: str
    """Texte majoritaire sur toutes les lectures de cette position."""

    support: int
    """Nombre d'images où cette ligne a été lue.

    Une ligne vue trente fois est un fait ; une ligne vue une seule fois est
    une hypothèse. Le rapport compte les secondes séparément plutôt que de les
    noyer dans le total.
    """

    agreement: float
    """Part des lectures qui donnent le texte majoritaire, de 0 à 1."""

    first_frame: int
    last_frame: int

    @property
    def fragile(self) -> bool:
        """Vrai pour une ligne vue une seule fois, donc invérifiable."""
        return self.support <= 1


@dataclass(frozen=True, slots=True)
class Assembly:
    """La suite reconstruite, avec de quoi juger sa solidité."""

    lines: tuple[AssembledLine, ...]

    baseline: int
    """Lignes déjà à l'écran sur la première image.

    Elles appartiennent au passé et ne sont comptées par personne : le compteur
    les marque validées à l'amorce, la référence les exclut ici. Sans cette
    symétrie, la comparaison démarrerait avec un écart d'une fenêtre entière.
    """

    added: tuple[int, ...]
    """Nombre de lignes ajoutées par chaque image, dans l'ordre."""

    replaced: tuple[int, ...]
    """Images dont AUCUNE ligne n'a été reconnue dans la suite en cours.

    Le recalage a alors déclaré la fenêtre entière nouvelle, faute de mieux.
    C'est le mode de défaillance de ce module, et il est signalé plutôt que
    corrigé : ces images sont exactement les cas à regarder à la main.
    """

    empty: tuple[int, ...]
    """Images sans aucune ligne lue. Ignorées, jamais comptées comme un vide."""

    @property
    def stream(self) -> tuple[AssembledLine, ...]:
        """Les lignes réellement apparues pendant la rafale."""
        return self.lines[self.baseline :]

    @property
    def fragile_count(self) -> int:
        return sum(1 for ligne in self.stream if ligne.fragile)


def _majority(votes: Counter[str]) -> tuple[str, float]:
    """Texte le plus lu, et la part qu'il représente.

    `max` sur les couples plutôt que `most_common` : à égalité de voix,
    `most_common` suit l'ordre d'insertion, ce qui est stable mais implicite.
    Ici le départage est écrit : le plus voté, puis le plus long, puis l'ordre
    alphabétique. Une référence dont le résultat dépendrait d'un détail
    d'implémentation d'une version de Python ne serait pas une référence.
    """
    total = sum(votes.values())
    texte = max(votes.items(), key=lambda couple: (couple[1], len(couple[0]), couple[0]))[0]
    return texte, votes[texte] / total if total else 0.0


def _score(
    best: Sequence[str],
    frame: Sequence[str],
    start: int,
) -> tuple[int, int]:
    """(accords, désaccords niés) sur la partie commune, à ce placement.

    ⚠️ Le nombre d'accords domine, et les désaccords ne servent qu'à départager.
    Un premier essai les soustrayait, ce qui paraissait plus prudent et était
    faux : mesuré sur la rafale du 05/08/2026, **13 images sur 300** ont un
    contenu strictement inchangé et un bruit de glyphe suffisant pour que les
    désaccords l'emportent (« duclair », « （01:45) »). Le placement correct
    tombait alors sous zéro, le placement sans aucun recouvrement gagnait avec
    zéro, et la référence déclarait 24 lignes nouvelles là où il n'en était
    apparu aucune. À elles seules, ces 13 images gonflaient la référence de 312
    lignes sur 374.

    Compter les accords ne souffre pas de ce défaut : sur des lignes presque
    toutes distinctes, un mauvais placement en trouve zéro, quel que soit le
    bruit.
    """
    accords = 0
    desaccords = 0
    for offset, texte in enumerate(frame):
        position = start + offset
        if 0 <= position < len(best):
            if best[position] == texte:
                accords += 1
            else:
                desaccords += 1
    return accords, -desaccords


def _resoudre(
    formes: Counter[str], bruts: Counter[str], premier: int, dernier: int
) -> AssembledLine:
    """Choisit le texte représentatif d'une position, et mesure son assise.

    L'accord se mesure sur les formes canoniques, parce que c'est là qu'est la
    question posée : les lectures désignent-elles la même ligne ? Le texte rendu
    est ensuite le brut le plus fréquent **parmi ceux qui portent cette forme**.

    Prendre le brut le plus fréquent sans ce filtre choisirait parfois une
    lecture minoritaire dont l'espacement, par hasard, s'est répété : le texte
    rendu contredirait alors le vote qui l'a élu.
    """
    forme, accord = _majority(formes)
    fideles = {texte: n for texte, n in bruts.items() if canon(texte) == forme}
    retenus = fideles or dict(bruts)
    texte = max(retenus.items(), key=lambda couple: (couple[1], len(couple[0]), couple[0]))[0]
    return AssembledLine(
        text=texte,
        support=sum(formes.values()),
        agreement=accord,
        first_frame=premier,
        last_frame=dernier,
    )


def assemble(frames: Sequence[Sequence[str]]) -> Assembly:
    """Reconstruit la suite des lignes du journal à partir de toutes les images.

    La première image sert d'amorce : son contenu est le passé, il entre dans la
    suite mais pas dans `stream`.
    """
    # Deux votes par position, et c'est nécessaire. Le recalage compare des
    # formes canoniques, mais la référence doit rendre un texte que le
    # découpage de ligne sait analyser : « [Pieces]x1,845(01:45) » recollé sans
    # ses espaces ne ressemble plus à la formule d'annonce.
    votes: list[Counter[str]] = []
    raws: list[Counter[str]] = []
    best: list[str] = []
    first_seen: list[int] = []
    last_seen: list[int] = []

    baseline = 0
    added: list[int] = []
    replaced: list[int] = []
    empty: list[int] = []

    def poser(frame: Sequence[str], start: int, index: int) -> None:
        for offset, texte in enumerate(frame):
            position = start + offset
            forme = canon(texte)
            if position < len(votes):
                votes[position][forme] += 1
                raws[position][texte] += 1
                best[position] = _majority(votes[position])[0]
                last_seen[position] = index
            else:
                votes.append(Counter({forme: 1}))
                raws.append(Counter({texte: 1}))
                best.append(forme)
                first_seen.append(index)
                last_seen.append(index)

    for index, frame in enumerate(frames):
        if not frame:
            # Chat replié, écran de chargement, zone mal cadrée. Une image sans
            # texte ne dit pas que le journal s'est vidé, elle ne dit rien.
            empty.append(index)
            added.append(0)
            continue

        if not votes:
            baseline = len(frame)
            poser(frame, 0, index)
            added.append(0)
            continue

        # Le bas de la fenêtre est toujours la ligne la plus récente : choisir
        # combien de lignes l'image ajoute fixe entièrement son placement.
        formes = [canon(ligne) for ligne in frame]
        meilleur_n = 0
        meilleur_score: tuple[int, int] = (-1, 0)
        for nouvelles in range(len(frame) + 1):
            debut = len(votes) + nouvelles - len(frame)
            if debut < 0:
                # La fenêtre montre plus de lignes que la suite n'en contient :
                # possible seulement au tout début, quand elle s'est agrandie.
                continue
            score = _score(best, formes, debut)
            # Strictement supérieur, et les `nouvelles` parcourues en ordre
            # croissant : à égalité c'est donc le plus petit nombre de lignes
            # nouvelles qui gagne, l'hypothèse la plus sobre.
            if score > meilleur_score:
                meilleur_score, meilleur_n = score, nouvelles

        if meilleur_score[0] == 0:
            # Aucune ligne reconnue : la référence a perdu le fil. Elle n'ajoute
            # rien, faute de savoir quoi ajouter, et le signale pour que
            # l'image soit regardée à la main plutôt que moyennée.
            replaced.append(index)

        debut = len(votes) + meilleur_n - len(frame)
        poser(frame, max(0, debut), index)
        added.append(meilleur_n)

    lignes = tuple(
        _resoudre(votes[position], raws[position], first_seen[position], last_seen[position])
        for position in range(len(votes))
    )

    return Assembly(
        lines=lignes,
        baseline=baseline,
        added=tuple(added),
        replaced=tuple(replaced),
        empty=tuple(empty),
    )
