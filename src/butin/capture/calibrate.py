"""Trouver la fenêtre de chat sur l'écran, sans rien demander à l'utilisateur.

Pourquoi c'est bloquant
------------------------

Jusqu'ici la zone du journal était **codée en dur**, relevée à la main sur un
écran 2560 x 1440. Personne d'autre ne pouvait s'en servir, et une zone mal
cadrée donne un journal parfaitement vide **sans dire pourquoi** : le compteur
affiche zéro drop et rien n'indique que c'est le cadrage qui est faux. C'est
exactement le mode de défaillance qu'un utilisateur ne peut pas diagnostiquer.

Le signal : les pastilles de canal, enfin utiles
-------------------------------------------------

⭐ La propriété qui a **disqualifié** les pastilles pour la mesure de défilement
est celle qui les rend parfaites ici. Elles sont **toutes identiques et espacées
d'exactement un pas de ligne** : pour un défilement d'une ligne, ça les rend
aveugles ; pour reconnaître le chat dans un écran de jeu, ça en fait la seule
chose de l'image qui se répète verticalement avec une période nette.

On cherche donc la colonne dont l'image **ressemble le plus à elle-même décalée
d'un cran**, et le cran en question est le pas de ligne. Les deux inconnues se
trouvent d'un coup.

Trois pièges, et ce qui les évite
-----------------------------------

**Un minimum global n'est pas une périodicité.** Sur un dégradé lisse, plus le
décalage est petit, plus les deux copies se ressemblent : le plus petit décalage
gagne toujours, sans que rien ne se répète. On cherche donc un **creux local**,
c'est-à-dire un décalage qui fait nettement mieux que ses voisins. Sur les 12
captures d'écran réelles, le critère naïf désignait n'importe quoi dans 10 cas ;
le creux local sépare les trois captures où le chat est visible (force 0,26 à
0,60) des neuf où il est masqué (0,06 au plus).

**Ressembler à soi-même ne suffit pas, il faut du contenu.** Un ciel uniforme
ressemble parfaitement à lui-même décalé de n'importe quoi. Les rangées retenues
doivent donc à la fois s'accorder avec leur voisine d'un pas ET porter du
contraste.

**Le pas n'est pas entier.** Mesuré sur de vrais défilements, il vaut 21,6 px et
non 22 : les décalages observés sont 22, 43, 65, 86 et 108 px pour une à cinq
lignes. Arrondir coûte 2 % par ligne, ce qui ne se voit pas sur une ligne et
dérive d'une ligne entière au bout de cinquante. D'où l'interpolation sous-pixel.

La largeur, elle, se mesure par l'OCR
---------------------------------------

Le bord droit est le seul des quatre inconnues que la géométrie ne donne pas
proprement. Le contraste entre les bandes de texte et les interlignes s'éteint
progressivement à mesure que les lignes se terminent, et sur un décor clair il
s'éteint bien avant la fin du texte : réglé sur trois captures, le critère
rendait 447 px sur l'une et 1 725 sur l'autre, avec des montants tronqués
(« x10.00 » pour « x10,000,000 ») d'un côté et quatre fois le coût d'OCR de
l'autre.

`measure_width` répond directement à la question posée, en lisant une fois une
zone volontairement large et en regardant **jusqu'où va le texte**. Le calibrage
est une opération unique : il peut payer une reconnaissance, là où la boucle
ne le peut pas.

Ne sont retenues que les rangées de texte **calées sur la phase des lignes du
journal**, celle que la géométrie vient de trouver. C'est ce qui distingue une
ligne de chat d'un panneau du décor qui traînerait dans la zone, sans rien
supposer de la langue du client.

Une marge est ensuite ajoutée, volontairement asymétrique : une zone trop large
coûte du temps d'OCR, une zone trop étroite **tronque les noms d'objets**, et un
nom tronqué est un drop perdu en silence.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np
import numpy.typing as npt

from .. import paths
from .ocr import TextLine
from .screen import GrayImage, Region

FloatFrame = npt.NDArray[np.float32]
"""Image de travail. Le calibrage compare des moyennes, donc il travaille en
flottant du début à la fin plutôt que de reconvertir à chaque étape."""

FloatProfile = npt.NDArray[np.floating[Any]]
"""Profil 1D dérivé de l'image.

⚠️ Précision volontairement non fixée. Selon la version de numpy, la moyenne
d'un tableau `float32` est annotée `float32` ou `float64`, et figer l'une des
deux fait échouer l'analyse de types sur les interpréteurs où l'autre est
déduite. C'est arrivé sur le job 3.12 alors que 3.10 et 3.11 passaient.
"""

LAGS = np.arange(14, 42)
"""Pas de ligne envisagés, en pixels. De 14 à 41 couvre l'échelle d'interface du
jeu de la plus petite à la plus grande, très au-delà des 21,6 px mesurés."""

MIN_STRENGTH = 0.15
"""Force de périodicité en dessous de laquelle on déclare ne pas avoir trouvé.

Posée entre deux populations mesurées sur 12 captures d'écran réelles, dont la
vérité terrain a été établie par l'OCR : **0,26 à 0,60** là où le chat est
visible et lisible, **0,06 au plus** là où il est masqué. Le seuil est à quatre
fois le bruit et à un tiers sous la plus faible vraie détection.
"""

MIN_ROWS = 5
"""Rangées qu'il faut avoir trouvées pour croire à un chat.

Quatre pastilles alignées peuvent arriver par accident sur un décor ; une
douzaine, non. C'est aussi le minimum en dessous duquel la phase des rangées ne
se moyenne pas correctement.
"""

LEFT_TOLERANCE = 3.0
"""Écart de départ toléré entre deux lignes du journal, en pas de ligne.

Les lignes du journal commencent toutes à la même abscisse, celle de la
pastille de canal ; le décor, non. Trois pas laissent passer une pastille plus
large sans accepter un panneau planté au milieu de l'écran.
"""

GAP_TOLERANCE = 2.0
"""Blanc au-delà duquel on considère que la ligne du journal est finie, en pas
de ligne.

⚠️ Nécessaire parce que le regroupement des fragments par l'OCR travaille par
**rangée** : du texte du décor situé à la même hauteur qu'une ligne du chat, mais
trois cents pixels plus loin, est rendu dans la même rangée. Sans cette coupure,
la largeur mesurée était celle de l'écran entier.
"""

PHASE_TOLERANCE = 0.25
"""Écart de phase toléré, en fraction du pas. Un quart de pas, soit environ 5 px
sur les 21,6 mesurés : assez pour absorber l'imprécision du regroupement des
fragments par l'OCR, trop peu pour accepter une rangée décalée d'une demi-ligne.
"""

RIGHT_MARGIN = 0.25
"""Marge ajoutée à droite, en fraction de la largeur détectée.

Asymétrique et assumée : élargir coûte du temps d'OCR, rétrécir **tronque les
noms d'objets**, et un nom tronqué est un drop perdu en silence.
"""


class CalibrationError(RuntimeError):
    """Le chat n'a pas été trouvé, et on dit lequel des critères a manqué.

    Une exception plutôt qu'un `None` : un calibrage raté qui passe inaperçu
    produit un journal vide, c'est-à-dire un compteur à zéro qu'on prendrait
    pour une session sans butin.
    """


@dataclass(frozen=True, slots=True)
class Calibration:
    """Tout ce que la boucle a besoin de savoir sur l'écran de l'utilisateur."""

    region: Region
    row_height_px: float
    ruler_left_ratio: float
    ruler_right_ratio: float

    rows: int
    """Rangées de chat détectées. Sert au diagnostic : un calibrage sur trois
    rangées est vrai mais fragile."""

    strength: float
    """Force de la périodicité retenue. Plus c'est haut, plus le chat se
    détachait nettement du décor au moment du calibrage."""

    def to_dict(self) -> dict[str, object]:
        return {
            "region": self.region.to_dict(),
            "row_height_px": self.row_height_px,
            "ruler_left_ratio": self.ruler_left_ratio,
            "ruler_right_ratio": self.ruler_right_ratio,
            "rows": self.rows,
            "strength": self.strength,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> Calibration:
        region = data.get("region")
        if not isinstance(region, dict):
            raise ValueError("calibrage : champ « region » manquant ou mal formé")

        def nombre(cle: str, defaut: float | None = None) -> float:
            """Lit un champ numérique, en disant lequel manque plutôt qu'un KeyError.

            Le fichier de calibrage peut avoir été édité à la main ou écrit par
            une version antérieure : une erreur doit nommer le champ fautif, pas
            remonter au milieu de la boucle de capture.
            """
            valeur = data.get(cle)
            if valeur is None:
                if defaut is None:
                    raise ValueError(f"calibrage : champ « {cle} » manquant")
                return defaut
            if isinstance(valeur, bool) or not isinstance(valeur, (int, float)):
                raise ValueError(
                    f"calibrage : champ « {cle} » attendu numérique, reçu {type(valeur).__name__}"
                )
            return float(valeur)

        return cls(
            region=Region.from_dict(region),
            row_height_px=nombre("row_height_px"),
            ruler_left_ratio=nombre("ruler_left_ratio"),
            ruler_right_ratio=nombre("ruler_right_ratio"),
            rows=int(nombre("rows", 0.0)),
            strength=nombre("strength", 0.0),
        )

    def save(self, path: Path | None = None) -> Path:
        """Écrit le calibrage sur le disque, en JSON lisible à la main.

        Lisible exprès : c'est le fichier qu'on demandera à quelqu'un de coller
        dans un rapport de bogue quand son journal reste vide.
        """
        cible = path or paths.calibration_path()
        cible.parent.mkdir(parents=True, exist_ok=True)
        cible.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return cible

    @classmethod
    def load(cls, path: Path | None = None) -> Calibration | None:
        """Relit le calibrage, ou None s'il n'a jamais été fait.

        None et non une exception : ne pas être calibré est l'état normal au
        premier lancement, pas une erreur. C'est l'appelant qui décide quoi en
        dire. Un fichier présent mais illisible, lui, lève : il vaut mieux
        s'arrêter que capturer la mauvaise zone.
        """
        source = path or paths.calibration_path()
        if not source.exists():
            return None
        return cls.from_dict(json.loads(source.read_text(encoding="utf-8")))

    def describe(self) -> str:
        return (
            f"{self.region.describe()}, pas {self.row_height_px:.1f} px, "
            f"{self.rows} rangées, force {self.strength:.2f}"
        )


def _column_periodicity(
    frame: FloatFrame,
) -> tuple[npt.NDArray[np.int_], npt.NDArray[np.float64]]:
    """Pour chaque colonne, le pas qui la répète le mieux et la force du creux.

    « Creux » et non « minimum » : voir l'en-tête du module. La comparaison porte
    sur les voisins à trois crans, assez loin pour qu'un vrai puits ressorte,
    assez près pour que la tendance de fond ne fausse pas la mesure.
    """
    height = frame.shape[0]
    if height <= int(LAGS[-1]) + 1:
        raise CalibrationError(
            f"image trop petite pour chercher un pas de ligne : {frame.shape}, "
            f"il en faut au moins {int(LAGS[-1]) + 2} rangées"
        )

    ecarts = np.stack([np.abs(frame[lag:] - frame[: height - lag]).mean(axis=0) for lag in LAGS])
    creux = np.full(ecarts.shape, -1.0)
    for index in range(3, len(LAGS) - 3):
        voisins = np.minimum(ecarts[index - 3], ecarts[index + 3])
        creux[index] = np.where(
            ecarts[index] > 1e-6, (voisins - ecarts[index]) / np.maximum(ecarts[index], 1e-6), 0.0
        )
    meilleur = creux.argmax(axis=0)
    return LAGS[meilleur], creux.max(axis=0)


def _refine_pitch(image: FloatFrame, left: int, right: int, coarse: int) -> float:
    """Affine le pas au sous-pixel, par interpolation parabolique.

    Le pas réel vaut 21,6 px et la recherche est entière : sans cette étape le
    calibrage rendrait 22, ce qui dérive d'une ligne entière au bout de
    cinquante. Trois points suffisent, la courbe d'écart est lisse autour de son
    minimum.
    """
    frame = image[:, left : right + 1]
    height = frame.shape[0]

    def ecart(lag: int) -> float:
        if lag < 1 or lag >= height:
            return float("inf")
        return float(np.abs(frame[lag:] - frame[: height - lag]).mean())

    avant, milieu, apres = ecart(coarse - 1), ecart(coarse), ecart(coarse + 1)
    denominateur = avant - 2.0 * milieu + apres
    if not np.isfinite(denominateur) or abs(denominateur) < 1e-9:
        return float(coarse)
    correction = 0.5 * (avant - apres) / denominateur
    # Une correction de plus d'un demi-pixel signifierait que le minimum entier
    # n'était pas le bon : on ne la suit pas, on garde l'entier.
    if abs(correction) > 0.5:
        return float(coarse)
    return float(coarse) + correction


def _vertical_extent(profile: FloatProfile, pitch: int) -> tuple[int, int]:
    """Plage de rangées où le profil se répète vraiment au pas `pitch`.

    Compare l'accord au pas entier à l'accord au demi-pas. Un vrai motif de
    lignes s'accorde bien mieux au pas qu'au demi-pas ; un décor quelconque, et
    un aplat uniforme, s'accordent pareil aux deux. C'est ce qui distingue « ça
    se répète » de « c'est plat ».
    """
    fenetre = 5 * pitch
    taille = len(profile)
    if taille <= fenetre + pitch:
        return (0, taille)

    plein = np.abs(profile[pitch:] - profile[:-pitch])
    demi = np.abs(profile[pitch // 2 :] - profile[: -(pitch // 2)])
    noyau = np.ones(fenetre) / fenetre
    plein_liss = np.convolve(plein, noyau, mode="valid")
    demi_liss = np.convolve(demi, noyau, mode="valid")
    commun = min(len(plein_liss), len(demi_liss))
    score = np.where(
        demi_liss[:commun] > 1e-6,
        (demi_liss[:commun] - plein_liss[:commun]) / np.maximum(demi_liss[:commun], 1e-6),
        0.0,
    )

    dedans = np.where(score > 0.35)[0]
    if len(dedans) == 0:
        return (0, 0)
    # La fenêtre glissante situe la zone à sa largeur près : elle se déclenche
    # dès qu'elle contient assez de chat, donc jusqu'à une fenêtre trop tôt.
    # Les bords sont ensuite recalés rangée par rangée, sinon le calibrage
    # embarque quatre rangées de décor au-dessus du journal.
    grossier_haut = int(dedans.min())
    grossier_bas = min(taille, int(dedans.max()) + fenetre)
    return _snap(plein, demi, grossier_haut, grossier_bas, pitch)


def _snap(
    plein: FloatProfile,
    demi: FloatProfile,
    haut: int,
    bas: int,
    pitch: int,
) -> tuple[int, int]:
    """Resserre une plage approximative sur les rangées qui se répètent vraiment.

    Une rangée « dedans » ressemble nettement mieux à sa voisine d'un pas qu'à
    sa voisine d'un demi-pas. Le critère est lissé sur un pas entier avant
    d'être appliqué : rangée par rangée il est trop bruité, et un accident isolé
    fixerait la bordure au mauvais endroit.

    Sans ce recalage, la fenêtre glissante situe la zone à sa largeur près :
    elle se déclenche dès qu'elle contient assez de chat, donc jusqu'à cinq
    rangées trop tôt, et le calibrage embarque du décor au-dessus du journal.
    """
    commun = min(len(plein), len(demi))
    if commun <= pitch:
        return (haut, bas)
    noyau = np.ones(pitch) / pitch
    plein_liss = np.convolve(plein[:commun], noyau, mode="same")
    demi_liss = np.convolve(demi[:commun], noyau, mode="same")
    dedans = plein_liss < 0.6 * demi_liss

    debut, fin = haut, min(bas, commun)
    while debut < fin and not dedans[debut]:
        debut += 1
    while fin > debut and not dedans[fin - 1]:
        fin -= 1
    if fin - debut < pitch * MIN_ROWS:
        return (haut, bas)
    return (debut, min(bas, fin + pitch))


def find_chat(gray: GrayImage, *, origin: tuple[int, int] = (0, 0)) -> Calibration:
    """Trouve la fenêtre de chat dans une capture d'écran entière.

    `origin` est le coin de l'écran capturé dans le bureau étendu, pour que la
    région rendue soit directement utilisable par `screen.ScreenCapture`. Sur un
    second moniteur, l'oublier ferait capturer la même zone sur le premier.

    Lève `CalibrationError` dès qu'un critère manque, avec lequel. Un calibrage
    qui échoue en silence donnerait un journal vide, donc un compteur à zéro
    qu'on prendrait pour une session sans butin.

    Le bord droit rendu est **provisoire** : il prend toute la largeur restante
    de l'écran. C'est `measure_width` qui le ramène à la largeur réellement
    occupée par le texte, ce que la géométrie seule ne sait pas faire.
    """
    if np.asarray(gray).ndim != 2:
        raise CalibrationError(
            f"image en niveaux de gris attendue, reçu un tableau de forme {np.asarray(gray).shape}"
        )
    frame: FloatFrame = np.asarray(gray, dtype=np.float32)

    pas_par_colonne, force = _column_periodicity(frame)
    lisse = np.convolve(force, np.ones(8) / 8, mode="same")
    sommet = int(lisse.argmax())
    if lisse[sommet] < MIN_STRENGTH:
        raise CalibrationError(
            f"aucune fenêtre de chat trouvée : périodicité maximale {lisse[sommet]:.2f}, "
            f"il en faut {MIN_STRENGTH}. Le chat est-il affiché et le journal "
            "d'acquisition visible ?"
        )

    seuil = lisse[sommet] * 0.5
    gauche = sommet
    while gauche > 0 and lisse[gauche - 1] >= seuil:
        gauche -= 1
    droite_pastilles = sommet
    while droite_pastilles < len(lisse) - 1 and lisse[droite_pastilles + 1] >= seuil:
        droite_pastilles += 1

    pas = int(np.median(pas_par_colonne[gauche : droite_pastilles + 1]))
    profil = frame[:, gauche : droite_pastilles + 1].mean(axis=1)
    haut, bas = _vertical_extent(profil, pas)
    rangees = (bas - haut) // pas
    if rangees < MIN_ROWS:
        raise CalibrationError(
            f"fenêtre de chat trop courte : {rangees} rangées trouvées, il en faut {MIN_ROWS}. "
            "Le journal d'acquisition contient-il des lignes ?"
        )

    droite = int(frame.shape[1]) - 1
    largeur = droite - gauche + 1
    region = Region(
        left=origin[0] + gauche,
        top=origin[1] + haut,
        width=largeur,
        height=bas - haut,
    )
    # La règle de mesure du défilement commence APRÈS les pastilles : elles sont
    # identiques d'une rangée à l'autre, donc invisibles au défilement d'une
    # ligne. Voir `tracking/scroll.py`.
    apres_pastilles = (droite_pastilles - gauche + 4) / largeur
    return Calibration(
        region=region,
        row_height_px=_refine_pitch(frame, gauche, droite_pastilles, pas),
        ruler_left_ratio=min(0.9, max(0.0, apres_pastilles)),
        ruler_right_ratio=1.0,
        rows=rangees,
        strength=float(lisse[sommet]),
    )


class BoxSource(Protocol):
    """Ce que `measure_width` attend d'un lecteur de texte.

    Réduit aux rangées et à leurs coordonnées : le calibrage ne lit pas le sens
    du texte, seulement jusqu'où il va. Les tests fournissent un double et ne
    chargent jamais le modèle.
    """

    def read(self, gray: GrayImage) -> list[TextLine]: ...


def _line_end(ligne: TextLine, pitch: float) -> int:
    """Abscisse de fin d'une ligne du journal, en s'arrêtant au premier blanc.

    Les fragments sont parcourus de gauche à droite tant qu'ils se suivent. Le
    premier écart de plus de `GAP_TOLERANCE` pas signale qu'on a quitté la ligne
    et qu'on lit du décor situé à la même hauteur.
    """
    boites = sorted(ligne.boxes, key=lambda boite: boite.left)
    fin = boites[0].right
    for boite in boites[1:]:
        if boite.left - fin > GAP_TOLERANCE * pitch:
            break
        fin = max(fin, boite.right)
    return fin


def measure_width(
    gray: GrayImage,
    calibration: Calibration,
    reader: BoxSource,
    *,
    margin: float = RIGHT_MARGIN,
) -> Calibration:
    """Ramène la zone à la largeur que le texte occupe vraiment.

    Attend l'écran ENTIER et une calibration dont le bord droit est provisoire,
    tel que `find_chat` le rend. Rend une nouvelle calibration, resserrée.

    Ne retient que les rangées lues dont le centre tombe sur la **phase des
    lignes du journal**, trouvée par la géométrie. Une enseigne du décor qui
    traînerait dans la zone n'est pas calée sur cette phase, donc ne compte pas.
    Aucune hypothèse sur la langue : c'est de la position, pas du vocabulaire.

    Si aucune rangée ne tombe sur la phase, la zone est laissée telle quelle.
    Trop large coûte du temps ; trop étroite perdrait des drops.
    """
    region = calibration.region
    frame = np.asarray(gray, dtype=np.uint8)
    zone: GrayImage = frame[region.top : region.bottom, region.left : region.right]

    pas = calibration.row_height_px
    lues = [ligne for ligne in reader.read(zone) if ligne.boxes]
    if not lues:
        return calibration

    # Phase des lignes du journal, déduite des rangées elles-mêmes plutôt que
    # supposée : toutes tombent au même reste modulo le pas, parce qu'elles sont
    # les rangées d'une même liste. Une enseigne du décor qui traînerait dans la
    # zone n'a aucune raison de tomber sur ce reste.
    restes = np.array([(ligne.center_y % pas) / pas for ligne in lues])
    ecarts = np.abs(restes[:, None] - restes[None, :])
    circulaires = np.minimum(ecarts, 1.0 - ecarts)
    voisins = (circulaires <= PHASE_TOLERANCE).sum(axis=1)
    reference = restes[int(voisins.argmax())]

    ecart = np.minimum(np.abs(restes - reference), 1.0 - np.abs(restes - reference))
    candidates = [ligne for ligne, e in zip(lues, ecart, strict=True) if e <= PHASE_TOLERANCE]
    if not candidates:
        return calibration

    # Les lignes du journal commencent toutes à la même abscisse, celle de la
    # pastille de canal. Une enseigne du décor, non.
    depart = min(min(boite.left for boite in ligne.boxes) for ligne in candidates)
    alignees = [
        ligne
        for ligne in candidates
        if min(boite.left for boite in ligne.boxes) <= depart + LEFT_TOLERANCE * pas
    ]
    if not alignees:
        return calibration

    sur_la_phase = [_line_end(ligne, pas) for ligne in alignees]
    utile = max(sur_la_phase)
    largeur = min(region.width, max(1, int(utile * (1.0 + margin))))
    serree = Region(left=region.left, top=region.top, width=largeur, height=region.height)
    return Calibration(
        region=serree,
        row_height_px=calibration.row_height_px,
        ruler_left_ratio=min(0.9, calibration.ruler_left_ratio * region.width / largeur),
        ruler_right_ratio=calibration.ruler_right_ratio,
        rows=calibration.rows,
        strength=calibration.strength,
    )
