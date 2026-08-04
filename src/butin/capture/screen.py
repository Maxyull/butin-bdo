"""Capture de la zone du journal d'acquisition.

Premier maillon de la chaîne : `tracking/` ne voit du jeu que ce que ce module
lui donne. Trois décisions structurent le fichier, et chacune évite une façon
naturelle mais coûteuse de faire.

**Une seule instance mss, réutilisée d'une image à l'autre.** Construire
`mss.mss()` demande au système une nouvelle connexion d'affichage et un nouveau
contexte de périphérique. À dix images par seconde, refaire ce travail à chaque
image coûte plus cher que la capture elle-même, et sous Windows chaque instance
non fermée retient des ressources graphiques. L'instance est donc créée à la
première capture, gardée, puis libérée par `close()`, ce que le gestionnaire de
contexte fait automatiquement.

**Niveaux de gris sur 8 bits.** Le choix contre le float32 est délibéré :
`scroll.py` et `stability.py` commencent tous deux par
`np.asarray(..., dtype=np.float32)`, donc produire du float ici n'économise
aucune conversion et quadruple la mémoire de chaque image conservée en tampon.
L'OCR, lui, attend des entiers 8 bits. L'arrondi coûte au pire un demi-niveau
de gris, très en dessous du seuil `baseline_eps` de 2,0 sous lequel `scroll.py`
tient deux images pour identiques.

**Une région qui déborde de l'écran est une erreur.** mss ne refuse que les
régions de taille nulle ou négative. Une région qui sort de l'écran est capturée
sans protester et rend des pixels noirs. Un calibrage fait sur un écran puis
rejoué sur une autre machine donnerait alors un journal parfaitement vide, sans
le moindre message : le tracker compterait zéro drop et rien n'indiquerait
pourquoi. Le garde-fou de `ScreenCapture.grab` transforme ce silence en erreur.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import TracebackType
from typing import Any

import mss
import numpy as np
import numpy.typing as npt

GrayImage = npt.NDArray[np.uint8]
"""Image en niveaux de gris, 2D, telle que `tracking/` l'attend."""

# Coefficients de luminance ITU-R BT.601, dans l'ordre des canaux que mss rend,
# c'est-à-dire BGRA et non RGBA.
_WEIGHT_BLUE = 0.114
_WEIGHT_GREEN = 0.587
_WEIGHT_RED = 0.299

_REGION_KEYS = ("left", "top", "width", "height")


class CaptureError(RuntimeError):
    """Échec de capture attribuable à la configuration, pas au jeu.

    Écran demandé absent, région hors de l'écran, session déjà fermée. Ces cas
    viennent tous d'un calibrage périmé ou d'un usage incorrect de l'objet, et
    doivent remonter à l'utilisateur plutôt que produire une image inutilisable.
    """


def _read_int(data: Mapping[str, object], key: str, *, origin: str) -> int:
    """Lit un entier d'un dictionnaire venu de JSON, sans conversion tacite.

    Un booléen est refusé bien qu'il soit un entier pour Python : `true` relu
    depuis un fichier de calibrage donnerait une largeur de 1 pixel, donc une
    capture valide au sens du type et absurde au sens du sens.
    """
    if key not in data:
        raise ValueError(f"{origin} : champ « {key} » manquant")
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{origin} : champ « {key} » attendu entier, reçu {type(value).__name__}")
    return value


@dataclass(frozen=True, slots=True)
class Region:
    """Rectangle d'écran à capturer, en coordonnées absolues du bureau.

    « Absolues » veut dire relatives au bureau étendu et non à l'écran choisi :
    c'est la convention de mss, et un second écran placé à droite du principal
    commence donc à un `left` égal à la largeur du premier. Ne pas suivre cette
    convention capturerait silencieusement la mauvaise zone sur toute
    configuration multi-écran.

    Gelé parce qu'une région est un résultat de calibrage : la modifier après
    coup désynchroniserait la hauteur de ligne mesurée sur elle, dont dépend
    toute la conversion pixels vers lignes de `scroll.py`.
    """

    left: int
    top: int
    width: int
    height: int

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError(
                "région invalide : largeur et hauteur doivent être strictement "
                f"positives, reçu {self.width}x{self.height}"
            )

    @property
    def right(self) -> int:
        """Première colonne hors de la région, comme une borne de `range`."""
        return self.left + self.width

    @property
    def bottom(self) -> int:
        """Première ligne hors de la région, comme une borne de `range`."""
        return self.top + self.height

    def contains(self, other: Region) -> bool:
        """Dit si `other` tient entièrement dans cette région."""
        return (
            other.left >= self.left
            and other.top >= self.top
            and other.right <= self.right
            and other.bottom <= self.bottom
        )

    def to_mss(self) -> dict[str, int]:
        """Rend le dictionnaire que `mss.grab` attend."""
        return {"left": self.left, "top": self.top, "width": self.width, "height": self.height}

    def to_dict(self) -> dict[str, int]:
        """Rend la forme sérialisable pour le fichier de calibrage.

        Volontairement identique à `to_mss` : garder deux formes différentes
        obligerait à les convertir l'une vers l'autre, donc à écrire un endroit
        de plus où intervertir largeur et hauteur sans que rien ne le signale.
        """
        return self.to_mss()

    @classmethod
    def from_mss(cls, monitor: Mapping[str, object]) -> Region:
        """Construit une région depuis une entrée de `mss.monitors`."""
        return cls._parse(monitor, origin="écran mss")

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> Region:
        """Relit une région depuis un calibrage sauvegardé.

        Les données viennent d'un fichier que l'utilisateur peut avoir édité ou
        qu'une version antérieure a pu écrire autrement. Un champ manquant ou
        mal typé doit donc dire lequel, et non produire un `KeyError` nu au
        milieu de la boucle de capture.
        """
        return cls._parse(data, origin="calibrage")

    @classmethod
    def _parse(cls, data: Mapping[str, object], *, origin: str) -> Region:
        values = {key: _read_int(data, key, origin=origin) for key in _REGION_KEYS}
        return cls(**values)

    def describe(self) -> str:
        """Forme lisible pour les messages d'erreur."""
        return f"{self.width}x{self.height} en ({self.left}, {self.top})"


def bgra_to_gray(frame: npt.NDArray[np.uint8] | npt.NDArray[np.floating[Any]]) -> GrayImage:
    """Convertit une capture mss en niveaux de gris.

    mss rend du **BGRA**, pas du RGB : lire les canaux dans l'ordre naïf
    intervertit le rouge et le bleu, ce qui ne casse rien de visible mais fausse
    le contraste de tous les noms d'objets colorés du journal.

    Les coefficients de luminance ne sont pas de la coquetterie. Une moyenne
    naïve des trois canaux les pèse pareil, alors que l'œil, et donc le rendu du
    texte à l'écran, tire l'essentiel de sa luminosité du vert. Deux couleurs de
    rareté du jeu le montrent : un nom vert pur et un nom bleu pur tombent tous
    deux sur 85 avec une moyenne, donc deviennent le même gris, et le texte
    disparaît dans un fond de même moyenne. Avec la luminance ils valent 150 et
    29, et restent distincts du fond comme l'un de l'autre. L'OCR et la
    détection de défilement travaillent tous deux sur ces différences.

    Le canal alpha est ignoré : mss le remplit sans garantie, et un alpha nul
    pris pour de la transparence noircirait l'image entière.
    """
    pixels = np.asarray(frame, dtype=np.float32)
    if pixels.ndim != 3 or pixels.shape[2] not in (3, 4):
        raise ValueError(
            "image BGRA attendue en (hauteur, largeur, 3 ou 4 canaux), "
            f"reçu un tableau de forme {pixels.shape}"
        )
    gray: npt.NDArray[np.float32] = (
        _WEIGHT_BLUE * pixels[:, :, 0]
        + _WEIGHT_GREEN * pixels[:, :, 1]
        + _WEIGHT_RED * pixels[:, :, 2]
    )
    # Les poids somment à 1, donc le résultat reste dans [0, 255] et l'arrondi
    # ne peut pas déborder du uint8.
    rounded: GrayImage = np.rint(gray).astype(np.uint8)
    return rounded


class ScreenCapture:
    """Capture répétée d'une région sur une instance mss réutilisée.

    À utiliser comme gestionnaire de contexte. mss détient des ressources
    système qu'il ne rend qu'à `close()` : une boucle de capture qui abandonne
    l'objet au ramasse-miettes les garde jusqu'à un moment indéterminé.

    L'instance mss est créée à la première utilisation, pas dans `__init__`.
    Construire un `ScreenCapture` reste donc possible là où il n'y a pas
    d'affichage, ce dont les tests et l'analyse de configuration profitent.
    """

    def __init__(self, monitor: int = 1) -> None:
        """`monitor` suit l'indexation de mss : 0 est le bureau entier, 1 le
        premier écran physique. Le défaut est 1 et non 0 parce qu'une région
        calibrée sur le bureau entier change de sens dès qu'un écran est
        branché ou débranché."""
        self._monitor_index = monitor
        self._session: Any = None
        self._closed = False

    @property
    def monitor_index(self) -> int:
        return self._monitor_index

    @property
    def closed(self) -> bool:
        return self._closed

    def __enter__(self) -> ScreenCapture:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        """Libère l'instance mss. Sans effet si elle l'est déjà.

        Une fois fermée, la capture n'est pas réouverte à la volée : recréer
        une session en silence masquerait un objet utilisé après sa portée, et
        c'est exactement le genre de fuite que ce module cherche à éviter.
        """
        session, self._session = self._session, None
        self._closed = True
        if session is not None:
            session.close()

    def _require_session(self) -> Any:
        if self._closed:
            raise CaptureError("capture déjà fermée, construire un nouveau ScreenCapture")
        if self._session is None:
            self._session = mss.mss()
        return self._session

    def monitors(self) -> list[Region]:
        """Liste les écrans, dans l'indexation de mss.

        L'entrée 0 est le rectangle englobant tous les écrans, les suivantes
        sont les écrans physiques. C'est la convention de mss, conservée telle
        quelle pour qu'un indice affiché à l'utilisateur veuille dire la même
        chose des deux côtés.
        """
        raw: list[Mapping[str, object]] = list(self._require_session().monitors)
        return [Region.from_mss(entry) for entry in raw]

    def target_monitor(self) -> Region:
        """Rectangle de l'écran visé, en coordonnées absolues du bureau."""
        screens = self.monitors()
        # Un indice négatif serait accepté par l'indexation Python et
        # capturerait le dernier écran sans rien dire.
        if not 0 <= self._monitor_index < len(screens):
            raise CaptureError(
                f"écran {self._monitor_index} inexistant : {len(screens)} entrées "
                "disponibles, 0 étant le bureau entier"
            )
        return screens[self._monitor_index]

    def grab(self, region: Region) -> GrayImage:
        """Capture `region` et rend une image 2D en niveaux de gris.

        La forme du tableau vient de l'image rendue, jamais de la région
        demandée : la couche système peut rendre une image plus grande sur un
        écran à mise à l'échelle, et supposer les dimensions demandées
        décalerait toutes les lignes.
        """
        screen = self.target_monitor()
        if not screen.contains(region):
            raise CaptureError(
                f"la région {region.describe()} déborde de l'écran "
                f"{self._monitor_index} ({screen.describe()}) : calibrage à refaire, "
                "une capture hors écran ne rendrait que du noir"
            )
        shot = self._require_session().grab(region.to_mss())
        frame: npt.NDArray[np.uint8] = np.asarray(shot, dtype=np.uint8)
        return bgra_to_gray(frame)
