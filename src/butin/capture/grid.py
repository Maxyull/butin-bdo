"""Trouver la grille de l'inventaire dans une capture d'écran entière.

Pourquoi cette brique existe
-----------------------------

⭐ L'inventaire compté à la main est la **seule** vérité de ce logiciel qui ne
passe par aucune reconnaissance d'écran. Le compteur et le banc d'essai lisent
les mêmes pixels avec le même moteur : ils peuvent se tromper ensemble, et seul
un inventaire peut les contredire tous les deux.

`capture/inventaire.py` fige l'image. Ce module est la marche suivante : y
retrouver la grille, pour pouvoir un jour lire ce qu'il y a dans les cases sans
demander à personne de recopier des nombres.

⚠️ Deux pièges connus d'avance, et ils décident de la méthode
--------------------------------------------------------------

1. **L'inventaire se déplace.** Le joueur pose sa fenêtre où il veut, et il la
   déplace. Toute coordonnée en dur serait fausse chez le suivant, et fausse
   chez lui à la session d'après.
2. **Une même icône apparaît ailleurs à l'écran** : l'équipement, la barre de
   raccourcis, une infobulle. Chercher les icônes une par une compterait comme
   du butin ce qui est équipé.

D'où la règle : on ne cherche ni une position ni une icône, on cherche la
**régularité des cases**. C'est la seule chose que la grille de l'inventaire
possède et que le reste de l'écran n'a pas.

La technique, et pourquoi c'est celle-là
------------------------------------------

C'est la généralisation à deux directions de ce qui a trouvé la fenêtre de chat
dans `calibrate.py`, et le piège qu'elle évite est exactement le même.

⛔ **Un minimum global n'est pas une périodicité.** Sur un dégradé lisse, plus
le décalage est petit, plus les deux copies se ressemblent : le plus petit gagne
toujours, sans que rien ne se répète. Mesuré ici aussi, et le naïf perdait :
une simple autocorrélation par fenêtre sur les 14 captures réelles donnait
**0,60 sur celle qui contient un inventaire et jusqu'à 0,88 sur celles qui n'en
contiennent pas** — c'est-à-dire l'inverse de ce qu'on lui demande. On cherche
donc un **creux local** : un pas qui fait nettement mieux que ses voisins à
trois crans.

Et une case d'inventaire se répète dans **les deux** directions au **même** pas,
ce qui n'arrive à peu près nulle part ailleurs dans un écran de jeu. On exige
donc un creux **de chaque côté séparément**, et on retient le plus faible des
deux. Voir `_carte_des_creux` : additionner les deux désaccords, qui était la
première idée, laissait passer une image simplement rayée.

⛔⛔ CE DÉTECTEUR NE MARCHE QUE SUR UN INVENTAIRE PRESQUE VIDE
--------------------------------------------------------------

**Ne pas le brancher en l'état.** La deuxième capture réelle l'a réfuté, le
08/08/2026, et le mécanisme de l'échec est limpide une fois vu.

| Capture | Emplacements occupés | Force | Verdict |
| --- | --- | --- | --- |
| `inventaire-0016` | **13 sur 76** | **2,92** | trouvé |
| `inventaire-0018` | **51 sur 192** | **0,24** | **manqué** |
| `inventaire-0014` (menu Échap) | pas d'inventaire | 0,31 | refusé, juste |
| 12 captures d'échantillon | pas d'inventaire | 0,25 à 0,38 | refusés, justes |

⛔ **0,24 est SOUS le pire des faux positifs.** Aucun seuil ne peut séparer ces
deux populations : abaisser `MIN_STRENGTH` jusqu'à voir l'inventaire plein
ferait passer les treize écrans qui n'en contiennent aucun.

**Ce que la méthode mesurait vraiment**, et ce n'est pas ce qu'annonçait la
première version de cet en-tête : la ressemblance d'une case à sa voisine. Sur
un inventaire presque vide, des dizaines d'emplacements **rigoureusement
identiques** donnent un creux énorme. Sur un inventaire rempli, chaque case
porte une icône différente et il ne reste rien à faire ressembler.

⭐ Et c'est le cas rempli qui compte : on lit un inventaire **après** une
session de farm, précisément parce qu'il s'est rempli.

⚠️ **La leçon, quatrième occurrence dans ce projet** : une suite verte et une
mesure juste ne disent rien d'un cas que les données ne contiennent pas. Le
14 sur 14 était vrai, et sa portée était « treize refus et un accord sur une
grille vide ». L'en-tête le disait d'ailleurs — « qu'il dise oui à tous les
inventaires reste à vérifier sur une deuxième capture » — et la réponse est
non.

Ce qui reste acquis, mesuré sur les deux captures
---------------------------------------------------

Deux choses tombent juste **même sur l'inventaire plein**, et elles serviront à
ce qui remplacera la force :

- le **pas** : 48 px dans les deux cas, corroboré par une mesure indépendante
  des bords de case au gradient (48,7 px sur sept intervalles) ;
- la **position** : le sommet de la carte tombe dans la grille dans les deux
  cas, (2336, 756) et (2202, 728).

C'est donc la mesure de **confiance** qui est à refaire, pas la géométrie.

Ce qui a été essayé pour la remplacer, et n'a pas suffi
--------------------------------------------------------

La piste juste est de mesurer les **séparateurs** plutôt que les cases : la
gouttière entre deux emplacements est sombre et régulière quoi qu'il y ait
dedans. Un peigne dans le profil de bords, exigé saillant en pas et accordé
dans les deux directions, trouve bien 48 px au bon endroit sur les **deux**
captures. Mais il ne sépare pas :

| Fenêtre | Inventaire plein | Pire faux |
| --- | --- | --- |
| 4 cases (200 px) | 1,03 | 0,99 |
| 8 cases (400 px) | 0,39, et **au mauvais endroit** | 0,52 |

Élargir la fenêtre dilue le signal au lieu de le renforcer. Consigné pour ne
pas le refaire à l'identique ; il faudra autre chose que ce score-là.

⚠️ Il n'y a que **deux** captures positives. La prochaine idée se mesure contre
les deux, pas contre celle qui l'arrange.

⛔ Ce que ce module NE fait pas encore, et pourquoi
----------------------------------------------------

Il rend **où** est la grille et **à quel pas**, pas ses bords exacts ni le
contenu des cases.

Poser les bords au pixel près a été essayé et **volontairement laissé de côté**.
Trois règles ont été mesurées sur la vraie capture, où la grille fait 8 × 8
cases à partir de (2151, 523) :

| Règle | Colonnes rendues |
| --- | --- |
| étendre tant que la force reste au-dessus d'une fraction du sommet | 1 |
| suivre les droites de bord tant qu'elles dépassent un seuil | 10 |
| `calibrate._vertical_extent`, pas contre demi-pas | 6,8 |

Aucune ne tombe juste, et il n'existe **qu'une seule** capture d'inventaire
réelle sur cette machine. Choisir entre elles sur cette image reviendrait à
régler un seuil contre un échantillon unique — précisément ce que
`docs/banc-essai.md` interdit : un réglage ne se retient que s'il a un mécanisme
explicable ET qu'il domine sur plusieurs conditions. Il en faut une deuxième.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from .screen import GrayImage, Region

REDUCTION = 2
"""Facteur de réduction avant la recherche.

La carte coûte une comparaison d'image entière par pas envisagé. À demi-
résolution le travail est divisé par quatre, et le pas cherché reste très
au-dessus du pixel : 48 px deviennent 24, ce qui ne perd rien. Les bords sont
ensuite relus en pleine résolution.
"""

VOISIN = 3
"""Distance, en crans de `LAGS`, à laquelle on compare pour juger d'un creux.

Assez loin pour qu'un vrai puits ressorte, assez près pour que la tendance de
fond ne fausse pas la mesure. Même valeur et même raison que dans
`calibrate._column_periodicity`.
"""

LAGS = np.arange(15 - VOISIN, 41 + VOISIN)
"""Pas envisagés, en pixels de l'image réduite.

⚠️ Les `VOISIN` premiers et derniers ne peuvent JAMAIS être retenus : un creux
se juge contre ses voisins à trois crans, et les extrémités n'en ont pas des
deux côtés. La plage **utilisable** est donc `15..40`, soit **30 à 80 px** à
l'écran, et la déclaration porte la marge plutôt que de laisser croire à une
couverture qu'elle n'a pas.

Écrite ainsi et pas en chiffres bruts parce que la première version annonçait
30 à 80 px en ne pouvant rendre que 36 à 74 : un test à 32 px l'a montré, pas
une relecture.

Mesuré à 48 px sur un écran 2560 × 1440. La plage couvre largement les échelles
d'interface du jeu de part et d'autre, sans descendre là où le bruit du décor
commence à se répéter tout seul.
"""

PLANCHER_RELATIF = 0.02
"""Plancher du dénominateur, en fraction du désaccord médian de l'image.

⛔ Sans lui, la force n'a pas d'échelle. Le creux est un rapport
`(voisins − écart) / écart` : sur une image de synthèse, où une zone est
rigoureusement uniforme, l'écart au bon pas tombe à zéro et le rapport part à
plusieurs millions. Un seuil posé sur des captures réelles, où le bruit du
capteur garde l'écart au-dessus de zéro, ne veut alors plus rien dire ailleurs.

Deux pour cent de la médiane : assez bas pour ne rien changer aux captures
réelles, assez haut pour que le rapport reste borné là où le motif est parfait.

⭐ Le « ne rien changer » est **mesuré**, pas supposé : rejoué avec et sans
plancher sur sept captures réelles, la force est identique à **0,00 %** sur les
sept. Sur une grille de synthèse, sans plancher, elle atteignait 1,9 × 10⁷.
"""

MIN_STRENGTH = 1.5
"""Force en dessous de laquelle on déclare qu'il n'y a pas d'inventaire.

Posé entre les deux populations connues au moment où il a été écrit : **2,92**
sur l'inventaire presque vide, **0,38 au plus** sur les treize captures sans
inventaire.

⛔ **Et il ne suffit pas.** L'inventaire REMPLI mesure **0,24**, c'est-à-dire
sous le pire des faux positifs. Voir l'en-tête du module : aucune valeur de ce
seuil ne peut séparer les deux, et l'abaisser ferait passer les treize écrans
qui ne contiennent aucun inventaire. Ce n'est pas le seuil qu'il faut régler,
c'est la mesure qu'il faut remplacer.

⛔ **Ne pas l'abaisser « pour voir ».** C'est exactement le geste que
`docs/banc-essai.md` interdit : un réglage ne se retient que s'il a un
mécanisme explicable, et celui-là n'en a aucun — il échangerait un faux négatif
contre treize faux positifs.

Il penche volontairement du côté du refus. Refuser à tort se voit tout de suite
— le joueur relance en ayant ouvert son inventaire — alors qu'accepter à tort
ferait lire une grille qui n'existe pas, et rendrait des objets que personne ne
possède. C'est l'erreur que la section 1 du guide refuse en premier.
"""

FloatFrame = npt.NDArray[np.float32]


@dataclass(frozen=True, slots=True)
class Lattice:
    """Un treillis de cases trouvé dans une capture d'écran."""

    pitch_px: int
    """Pas entre deux cases, en pixels de l'écran."""

    strength: float
    """Force du creux retenu. Voir `MIN_STRENGTH` pour les deux populations
    mesurées auxquelles elle se compare."""

    band: Region
    """Zone où le treillis est **certain**, jamais la grille entière.

    ⚠️ La différence compte. La carte est lissée sur quatre pas et culmine là où
    le motif est le plus parfait, c'est-à-dire sur les cases **vides**, qui sont
    rigoureusement identiques. Une rangée d'icônes toutes différentes se répète
    moins bien tout en faisant partie de la même grille. Cette bande dit donc
    « ici, à coup sûr », pas « la grille s'arrête là ».
    """

    def describe(self) -> str:
        return f"{self.band.describe()}, cases de {self.pitch_px} px, force {self.strength:.2f}"


def _lisse(image: FloatFrame, cote: int) -> FloatFrame:
    """Moyenne glissante carrée, appliquée ligne puis colonne.

    Séparable exprès : deux passes en O(n) valent mieux qu'une convolution 2D
    pour un noyau uniforme, et la carte en demande une par pas envisagé.
    """
    noyau = np.ones(cote) / cote
    par_ligne = np.apply_along_axis(lambda r: np.convolve(r, noyau, mode="same"), 1, image)
    return np.apply_along_axis(lambda c: np.convolve(c, noyau, mode="same"), 0, par_ligne)


def _creux(empilees: FloatFrame, plancher: float) -> FloatFrame:
    """De la pile des désaccords par pas, la force du creux en chaque point."""
    creux = np.full(empilees.shape, -1.0, dtype=np.float32)
    for index in range(VOISIN, len(LAGS) - VOISIN):
        voisins = np.minimum(empilees[index - VOISIN], empilees[index + VOISIN])
        creux[index] = (voisins - empilees[index]) / np.maximum(empilees[index], plancher)
    return creux


def _carte_des_creux(image: FloatFrame) -> tuple[FloatFrame, npt.NDArray[np.int_]]:
    """En chaque point : la force du creux, et le pas qui le produit.

    ⭐ Les deux directions sont mesurées **séparément**, et on retient le
    **minimum** de leurs deux creux. C'est le cœur de la méthode, et ce n'est
    pas la même chose que d'additionner les deux désaccords avant de comparer.

    ⛔ La première version les additionnait, en affirmant dans son en-tête que
    « un décor qui ne se répète que dans un sens garde un gros terme dans
    l'autre ». C'était faux, et un test l'a montré : une image RAYÉE
    horizontalement est **uniforme** le long des rayures, donc son terme
    horizontal vaut zéro partout, donc la somme creuse aussi bien qu'une vraie
    grille. Une bande de vie, une liste, une bordure d'interface auraient
    chacune passé pour un inventaire.

    Le minimum, lui, exige les deux : une direction plate rend un creux nul et
    condamne le point, quelle que soit la beauté de l'autre.
    """
    hauteur, largeur = image.shape
    verticaux, horizontaux = [], []
    for pas in LAGS:
        haut = np.zeros((hauteur, largeur), dtype=np.float32)
        haut[: hauteur - pas, :] = np.abs(image[pas:, :] - image[: hauteur - pas, :])
        cote = np.zeros((hauteur, largeur), dtype=np.float32)
        cote[:, : largeur - pas] = np.abs(image[:, pas:] - image[:, : largeur - pas])
        # Lissé sur quatre pas : en dessous, une seule case bien alignée suffit
        # à faire un pic, et le décor en fabrique par accident.
        verticaux.append(_lisse(haut, int(4 * pas)))
        horizontaux.append(_lisse(cote, int(4 * pas)))

    empiles_v = np.stack(verticaux)
    empiles_h = np.stack(horizontaux)
    # Le plancher est tiré de l'image elle-même : voir `PLANCHER_RELATIF`.
    plancher = max(
        1e-6, PLANCHER_RELATIF * float(np.median(np.concatenate((empiles_v, empiles_h))))
    )

    creux = np.minimum(_creux(empiles_v, plancher), _creux(empiles_h, plancher))
    return creux.max(axis=0), LAGS[creux.argmax(axis=0)]


def find_lattice(gray: GrayImage) -> Lattice | None:
    """Cherche une grille de cases dans une capture d'écran entière.

    Rend `None` quand il n'y en a pas, ce qui est l'état **normal** d'une
    capture prise sans inventaire ouvert : ce n'est pas une erreur, c'est une
    réponse.

    ⛔ L'appelant doit le DIRE. Une capture sans inventaire et un inventaire
    vide se ressemblent une fois réduits à un tableau de zéro objet, et c'est le
    mode de défaillance que ce projet refuse partout : le joueur croirait avoir
    fait le geste qu'on lui demandait.
    """
    frame = np.asarray(gray)
    if frame.ndim != 2:
        raise ValueError(
            f"image en niveaux de gris attendue, reçu un tableau de forme {frame.shape}"
        )

    reduite = frame[::REDUCTION, ::REDUCTION].astype(np.float32)
    if min(reduite.shape) <= int(LAGS[-1]) + 1:
        return None

    force, pas_par_point = _carte_des_creux(reduite)
    sommet = float(force.max())
    if sommet < MIN_STRENGTH:
        return None

    lignes, colonnes = np.nonzero(force >= MIN_STRENGTH)
    index = int(force.argmax())
    y, x = divmod(index, force.shape[1])
    gauche = int(colonnes.min()) * REDUCTION
    haut = int(lignes.min()) * REDUCTION
    return Lattice(
        pitch_px=int(pas_par_point[y, x]) * REDUCTION,
        strength=sommet,
        band=Region(
            left=gauche,
            top=haut,
            width=(int(colonnes.max()) + 1) * REDUCTION - gauche,
            height=(int(lignes.max()) + 1) * REDUCTION - haut,
        ),
    )
