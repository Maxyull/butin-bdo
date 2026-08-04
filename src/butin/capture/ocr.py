"""Lecture du texte de la zone du journal, par rapidocr.

Ce module rend du **texte**, pas du sens : il ne sait pas ce qu'est un drop.
`lines.py` s'occupe de découper ce texte en objet et quantité.

Tous les réglages ci-dessous ont été mesurés le 04/08/2026 sur trois vraies
captures du client français (`D:\\DEV\\bdo\\echantillons`, hors dépôt), avec le
même contenu de journal sur trois fonds différents : décor moyen, décor sombre,
et rocher clair, ce dernier étant le cas difficile puisque le fond du chat est
transparent sur le monde du jeu. Le barème est le nombre de gains parmi 10 que
`lines.split_line` retrouve exactement, nom et quantité compris.

| Prétraitement          | fond moyen | fond sombre | fond clair | OCR    |
| ---------------------- | ---------- | ----------- | ---------- | ------ |
| aucun                  | 3          | 4           | 2          | 306 ms |
| x2                     | 7          | 8           | 4          | 333 ms |
| **x2 + contraste**     | **9**      | **9**       | **6**      | 333 ms |
| x2 + binarisation      | 2          | 4           | 2          | 258 ms |
| x3 + contraste         | 8          | 8           | 6          | 537 ms |

Ce que ces chiffres tranchent, et qu'aucune intuition n'aurait donné :

**L'agrandissement x2 est gratuit.** Le détecteur de rapidocr est réglé en
`limit_type: min`, `limit_side_len: 736` : il remet lui-même le petit côté de
l'image à 736 px avant d'inférer. Notre zone fait 385 px de haut, donc il
l'agrandissait déjà de 1,9. Le faire nous-mêmes au Lanczos avant qu'il découpe
les vignettes de reconnaissance ne coûte rien en temps d'OCR, seulement 8 ms de
prétraitement, et fait passer les lectures exactes de 3 à 9 sur 10.

**Agrandir plus est une perte sèche.** À x3 l'image dépasse le seuil du
détecteur, le temps monte de 60 % et la lecture baisse. Le bon facteur est
celui qui amène la hauteur juste au-dessus de 736 px, pas davantage.

**Rétrécir la zone ne fait pas gagner de temps, ça en coûte.** Mesuré sur la
même capture : 385 px de haut coûtent 333 ms, 250 px en coûtent 722 et 65 px en
coûtent 661. La règle du petit côté est la coupable, elle agrandit d'autant plus
que la zone est plate, et la largeur explose avec.

**La binarisation est le piège évident.** Elle semble taillée pour du texte, et
elle est le pire des cinq essais : 2 gains sur 10 sur le fond clair. Le texte du
jeu est peint avec un contour sombre et une transparence, donc un seuil global
mange soit le contour soit le texte selon le décor derrière.

Deux autres décisions viennent de la même campagne :

**Classifieur d'orientation coupé.** Il a retourné une ligne entière à 180
degrés sur une image binarisée, rendant « ... x3 (21:54) » en
« (ts: iz) ex ... ». Le chat n'est jamais tourné, donc ce classifieur ne peut
rien corriger, seulement casser, et le vote de `tracking/staging.py` ne sait pas
détecter une ligne retournée : elle ressemble à une lecture normale.

**Moteur chargé une seule fois.** 160 à 320 ms par chargement mesurés, contre
330 ms pour une image entière. Le recharger à chaque tour doublerait le coût de
la boucle pour rien.
"""

from __future__ import annotations

import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np
import numpy.typing as npt
from PIL import Image

from .screen import GrayImage

DEFAULT_SCALE = 2
"""Facteur d'agrandissement avant reconnaissance. Voir la table du module."""

DETECTOR_MIN_SIDE = 736
"""Petit côté auquel le détecteur ramène toute image, réglage de rapidocr.

Noté ici parce que c'est ce nombre, et non une intuition sur la finesse du
texte, qui explique pourquoi x2 est gratuit et x3 coûteux sur une zone de
385 px de haut. Il change si la configuration du moteur change.
"""


class OcrEngine(Protocol):
    """Ce que ce module attend d'un moteur, et rien de plus.

    Réduit à l'appel unique de rapidocr pour que les tests fournissent un double
    sans dépendre du modèle ONNX. La contrainte est réelle : l'intégration
    continue tourne sans les captures et sans GPU, et une suite qui charge un
    modèle de 15 Mo à chaque test cesse d'être lancée.
    """

    def __call__(self, image: npt.NDArray[np.uint8]) -> tuple[Any, Any]: ...


@dataclass(frozen=True, slots=True)
class TextBox:
    """Un fragment de texte détecté, dans les coordonnées de l'image d'entrée.

    « De l'image d'entrée » est le point important : les coordonnées sont
    ramenées à l'échelle de l'image reçue, jamais celle de l'image agrandie
    envoyée au moteur. `tracking/scroll.py` mesure les défilements sur l'image
    d'origine et `expected_new_lines` divise ce défilement par une hauteur de
    ligne. Rendre des coordonnées deux fois trop grandes ferait croire à un
    défilement de moitié, donc ferait recompter du butin déjà compté, sans
    qu'aucune erreur ne soit levée.
    """

    text: str
    left: int
    top: int
    right: int
    bottom: int
    confidence: float

    @property
    def height(self) -> int:
        return self.bottom - self.top

    @property
    def center_y(self) -> float:
        return (self.top + self.bottom) / 2.0


@dataclass(frozen=True, slots=True)
class TextLine:
    """Une rangée de texte, recomposée à partir des fragments détectés."""

    text: str
    top: int
    bottom: int
    confidence: float
    """Le plus faible des fragments de la rangée.

    Pas la moyenne : une rangée ne vaut que son morceau le moins bien lu, et
    c'est souvent le nom de l'objet qui est le morceau douteux. Une moyenne
    noierait ce doute sous quatre fragments parfaitement lus.
    """

    boxes: tuple[TextBox, ...]

    @property
    def height(self) -> int:
        return self.bottom - self.top

    @property
    def center_y(self) -> float:
        return (self.top + self.bottom) / 2.0


def upscale(gray: GrayImage, factor: int) -> GrayImage:
    """Agrandit l'image d'un facteur entier, au Lanczos.

    Lanczos et non le plus proche voisin : le texte du journal fait une dizaine
    de pixels de haut, et un agrandissement en blocs rend les diagonales du
    « x » de quantité et les accents en escalier, ce que le modèle lit moins
    bien qu'un bord lissé.
    """
    if factor <= 1:
        return np.asarray(gray, dtype=np.uint8)
    source = Image.fromarray(np.asarray(gray, dtype=np.uint8))
    height, width = gray.shape[:2]
    enlarged = source.resize((width * factor, height * factor), Image.Resampling.LANCZOS)
    result: GrayImage = np.asarray(enlarged, dtype=np.uint8)
    return result


def stretch_contrast(
    gray: GrayImage, *, low_percentile: float = 2.0, high_percentile: float = 98.0
) -> GrayImage:
    """Étire l'histogramme entre deux centiles.

    Sur des centiles et non sur le minimum et le maximum : il suffit d'un seul
    pixel blanc, une étincelle de sort ou le reflet d'une armure, pour que le
    maximum soit 255 et que l'étirement ne fasse plus rien du tout. Les centiles
    rendent la mesure insensible à ces quelques pixels.

    Sans cette étape, le fond clair perd trois gains sur dix et le fond sombre
    deux. C'est l'étape qui rattrape le fait que le chat est transparent sur le
    décor : le contraste local entre le texte et ce qu'il y a derrière varie
    d'une image à l'autre, alors que le texte, lui, ne change pas.
    """
    frame = np.asarray(gray, dtype=np.uint8)
    low, high = np.percentile(frame, [low_percentile, high_percentile])
    if high - low < 1.0:
        # Zone uniforme : chat masqué, écran de chargement, fondu au noir.
        # Étirer un bruit de 1 niveau le transformerait en fausse texture.
        return frame
    stretched = (frame.astype(np.float32) - float(low)) * (255.0 / float(high - low))
    result: GrayImage = np.clip(stretched, 0, 255).astype(np.uint8)
    return result


def preprocess(gray: GrayImage, *, scale: int = DEFAULT_SCALE, contrast: bool = True) -> GrayImage:
    """Prépare une image de `screen.py` pour le moteur.

    L'ordre compte : agrandir d'abord, étirer ensuite. Étirer avant agrandit
    aussi le bruit du décor, que l'interpolation étale ensuite sur les lettres.
    """
    frame = np.asarray(gray, dtype=np.uint8)
    if frame.ndim != 2:
        raise ValueError(
            f"image en niveaux de gris attendue, reçu un tableau de forme {frame.shape}"
        )
    enlarged = upscale(frame, scale)
    return stretch_contrast(enlarged) if contrast else enlarged


def _default_tolerance(boxes: Sequence[TextBox]) -> float:
    """Écart vertical en dessous duquel deux fragments sont sur la même rangée.

    Calé sur des mesures, pas au jugé. Sur les trois captures, à l'échelle
    d'entrée : les fragments d'une même rangée ont des centres écartés d'au plus
    1,6 px, deux rangées voisines sont écartées d'au moins 19,7 px, et la
    hauteur médiane d'un fragment est de 14 px. La moitié de cette hauteur, 7 px,
    tombe donc à quatre fois le pire écart intra-rangée et au tiers du plus
    petit pas entre rangées. Il n'existe pas de valeur limite à discuter, les
    deux populations ne se touchent pas.
    """
    heights = [float(box.height) for box in boxes if box.height > 0]
    if not heights:
        return 1.0
    return statistics.median(heights) / 2.0


def group_boxes(boxes: Sequence[TextBox], *, tolerance: float | None = None) -> list[TextLine]:
    """Recompose les rangées : haut vers le bas, puis gauche vers la droite.

    Indispensable, et pas seulement cosmétique. Le détecteur rend la pastille de
    canal et le message comme deux fragments séparés : 35 fragments pour 17
    rangées sur la capture de référence. Trié sur la seule ordonnée, « Système »
    ressort **après** le message qu'il introduit, et `tracking/alignment.py`,
    qui suppose l'ordre du plus ancien au plus récent, aligne alors des lignes
    qui n'existent pas. Rien ne lève d'erreur : le tracker compte simplement
    faux.

    Le haut vers le bas est le bon sens pour ce journal : le chat empile les
    nouveaux messages en bas, donc la première rangée est la plus ancienne.

    Chaque rangée est ancrée sur son premier fragment, jamais sur le précédent.
    Comparer de proche en proche laisse une suite de petits écarts avaler une
    rangée entière, ce qui est le mode de défaillance classique du regroupement
    par voisinage.
    """
    if not boxes:
        return []
    ordered = sorted(boxes, key=lambda box: (box.center_y, box.left))
    limit = _default_tolerance(ordered) if tolerance is None else tolerance

    rows: list[list[TextBox]] = [[ordered[0]]]
    for box in ordered[1:]:
        anchor = rows[-1][0].center_y
        if box.center_y - anchor <= limit:
            rows[-1].append(box)
        else:
            rows.append([box])
    return [_assemble(row) for row in rows]


def _assemble(row: list[TextBox]) -> TextLine:
    row.sort(key=lambda box: box.left)
    return TextLine(
        text=" ".join(box.text for box in row if box.text),
        top=min(box.top for box in row),
        bottom=max(box.bottom for box in row),
        confidence=min(box.confidence for box in row),
        boxes=tuple(row),
    )


def boxes_from_result(
    result: Any, *, scale: int = DEFAULT_SCALE, min_confidence: float = 0.0
) -> list[TextBox]:
    """Traduit la sortie brute de rapidocr en `TextBox`.

    Chaque entrée est `[quadrilatère, texte, score]`. Le quadrilatère a quatre
    sommets et n'est pas garanti rectangle, d'où le passage par la boîte
    englobante : le texte du chat n'est pas incliné, et un rectangle suffit à
    dire sur quelle rangée il se trouve.

    Une sortie vide se présente comme `None` et non comme une liste vide. Ce
    n'est pas une anomalie : c'est ce que rend une zone sans texte, chat replié
    ou écran de chargement.
    """
    if not result:
        return []
    divisor = float(max(1, scale))
    boxes: list[TextBox] = []
    for entry in result:
        quad, text, score = entry[0], str(entry[1]), float(entry[2])
        if score < min_confidence:
            continue
        xs = [float(point[0]) / divisor for point in quad]
        ys = [float(point[1]) / divisor for point in quad]
        boxes.append(
            TextBox(
                text=text,
                left=round(min(xs)),
                top=round(min(ys)),
                right=round(max(xs)),
                bottom=round(max(ys)),
                confidence=score,
            )
        )
    return boxes


def _build_default_engine() -> OcrEngine:
    """Construit le moteur rapidocr, importé tard exprès.

    L'import tire onnxruntime et les modèles : plusieurs centaines de
    millisecondes et une trentaine de mégaoctets. Importer `ocr.py` pour lire
    une constante ou pour la CLI ne doit pas payer ça.
    """
    from rapidocr_onnxruntime import RapidOCR

    engine: OcrEngine = RapidOCR(use_cls=False)
    return engine


class TextReader:
    """Lit les rangées de texte d'une image, sur un moteur chargé une fois.

    Le moteur est construit à la première lecture puis conservé. Même
    raisonnement que l'instance mss de `screen.py` : dans une boucle, ce qui est
    reconstruit à chaque tour finit par coûter plus cher que le travail utile.

    `engine_factory` existe pour les tests, qui fournissent un double et ne
    chargent jamais le modèle.
    """

    def __init__(
        self,
        *,
        scale: int = DEFAULT_SCALE,
        contrast: bool = True,
        min_confidence: float = 0.0,
        engine_factory: Callable[[], OcrEngine] | None = None,
    ) -> None:
        """`min_confidence` vaut 0 par défaut, et ce n'est pas de la négligence.

        rapidocr écarte déjà ses détections sous 0,5. Au-dessus, écarter un
        fragment ne supprime pas une rangée, ça la **tronque** : le nom perd un
        morceau et devient un autre nom, qui peut très bien exister au
        catalogue. Mesuré sur les trois captures, le pire score observé est
        0,91 et la médiane 0,97 : il n'y a rien à filtrer ici, et le doute est
        mieux transmis par `TextLine.confidence` que par une suppression.
        """
        self._scale = max(1, scale)
        self._contrast = contrast
        self._min_confidence = min_confidence
        self._factory = engine_factory or _build_default_engine
        self._engine: OcrEngine | None = None

    @property
    def scale(self) -> int:
        return self._scale

    @property
    def loaded(self) -> bool:
        """Vrai si le moteur est déjà en mémoire."""
        return self._engine is not None

    def _require_engine(self) -> OcrEngine:
        if self._engine is None:
            self._engine = self._factory()
        return self._engine

    def warmup(self) -> None:
        """Charge le moteur et paie la première inférence tout de suite.

        La toute première inférence d'une session onnxruntime alloue ses arènes
        mémoire et coûte plusieurs fois les suivantes. La payer au démarrage
        évite que la première image d'une session de farm, celle qui contient
        déjà l'écran plein de lignes, soit justement la plus lente.
        """
        self._require_engine()(np.zeros((64, 192), dtype=np.uint8))

    def read(self, gray: GrayImage) -> list[TextLine]:
        """Lit une image de `screen.py` et rend les rangées, de haut en bas."""
        prepared = preprocess(gray, scale=self._scale, contrast=self._contrast)
        result, _elapsed = self._require_engine()(prepared)
        boxes = boxes_from_result(result, scale=self._scale, min_confidence=self._min_confidence)
        return group_boxes(boxes)

    def read_text(self, gray: GrayImage) -> list[str]:
        """Rend seulement le texte des rangées, prêt pour `lines.parse_frame`."""
        return [line.text for line in self.read(gray)]
