"""Le texte lu par l'OCR, mis de côté pour être rejoué autant de fois qu'on veut.

Pourquoi séparer la lecture du reste
------------------------------------

Reconnaître 300 images coûte environ **100 secondes**, à 336 ms par image. Un
banc qui repaie ce prix à chaque exécution ne serait lancé qu'une fois, et un
banc qu'on ne relance pas ne sert plus à rien : c'est justement en le rejouant
après chaque changement du compteur qu'il gagne son utilité.

La lecture est donc faite une fois, écrite dans une **transcription**, et tout
le reste du banc travaille sur ce fichier. Effet de bord précieux : les mesures
deviennent **reproductibles au caractère près**. Deux exécutions du même banc
sur la même transcription donnent le même chiffre, ce qui n'est pas le cas si
l'OCR est relancé (le moteur n'est pas parfaitement déterministe d'une machine
à l'autre).

⚠️ Une transcription contient des pseudonymes de tiers
-------------------------------------------------------

Le journal d'acquisition est le canal `Système` de la fenêtre de chat, donc il
est **entrelacé avec la conversation des joueurs**. Une transcription contient
littéralement ce que des tiers ont écrit, avec leur pseudonyme.

Elle n'a donc rien à faire dans un dépôt public. Sa place est à côté des images,
dans `D:\\DEV\\bdo\\echantillons`, hors dépôt. Les tests de ce paquet
n'utilisent aucune transcription réelle : ils construisent leurs images de
toutes pièces, avec une vérité connue d'avance.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from ..capture.screen import GrayImage

FORMAT_VERSION = 1
"""Numéro de format, écrit en tête. Une transcription plus récente que le code
qui la relit doit être refusée plutôt que mal interprétée : elle porte un
chiffre, et un chiffre mal interprété reste un chiffre."""


@dataclass(frozen=True, slots=True)
class BenchFrame:
    """Une image de la rafale, avec ce que l'OCR y a lu.

    Les deux vont ensemble et ne peuvent pas être séparés : le rejeu a besoin
    des pixels pour mesurer le défilement et du texte pour reconnaître le
    butin. C'est exactement ce couple que la boucle reçoit en jeu.
    """

    index: int
    image: GrayImage
    lines: tuple[str, ...]
    """Rangées lues, de la plus ancienne à la plus récente, comme
    `capture.ocr.TextReader.read_text` les rend."""


@dataclass(frozen=True, slots=True)
class Transcript:
    """Le texte de toute une rafale, sans les pixels."""

    source: str
    """Préfixe des images d'origine, pour qu'une transcription ne puisse pas
    être rejouée par erreur sur une autre rafale."""

    interval_s: float
    """Pas de temps entre deux images, en secondes. Sert au rejeu à fabriquer
    une horloge fictive, pour qu'aucune mesure ne dépende de la charge machine."""

    frames: tuple[tuple[str, ...], ...]

    ocr_ms: float = 0.0
    """Coût médian d'une reconnaissance, en millisecondes, mesuré pendant la
    transcription. 0 quand il n'a pas été relevé.

    Ce n'est pas une statistique de confort : c'est ce nombre qui fixe la
    cadence que la boucle peut vraiment tenir, donc combien d'images sur la
    rafale elle aurait le droit de lire en jeu. Rejouer une rafale à une cadence
    plus rapide que celle qu'on sait payer donnerait au compteur une information
    qu'il n'aura jamais, et flatterait son résultat.
    """

    def __len__(self) -> int:
        return len(self.frames)

    def write(self, path: Path) -> None:
        """Écrit une ligne d'en-tête puis une ligne par image.

        Du JSON par ligne et non un seul objet : une rafale de 300 images se
        relit et se regarde à la main sans charger le fichier entier, et une
        écriture interrompue laisse un fichier tronqué mais lisible jusqu'à la
        coupure, plutôt qu'un fichier entièrement perdu.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        entete = {
            "version": FORMAT_VERSION,
            "source": self.source,
            "interval_s": self.interval_s,
            "frames": len(self.frames),
            "ocr_ms": self.ocr_ms,
        }
        with path.open("w", encoding="utf-8") as flux:
            flux.write(json.dumps(entete, ensure_ascii=False) + "\n")
            for index, lignes in enumerate(self.frames):
                flux.write(
                    json.dumps({"index": index, "lines": list(lignes)}, ensure_ascii=False) + "\n"
                )

    @classmethod
    def read(cls, path: Path) -> Transcript:
        """Relit une transcription, en refusant ce qu'elle ne comprend pas."""
        with path.open(encoding="utf-8") as flux:
            brut = [json.loads(ligne) for ligne in flux if ligne.strip()]
        if not brut:
            raise ValueError(f"transcription vide : {path}")

        entete = brut[0]
        version = entete.get("version")
        if version != FORMAT_VERSION:
            raise ValueError(f"transcription en version {version}, ce code lit la {FORMAT_VERSION}")

        images: list[tuple[str, ...]] = []
        for attendu, corps in enumerate(brut[1:]):
            reel = corps.get("index")
            if reel != attendu:
                # Un trou dans la numérotation décalerait tout le rejeu : la
                # mesure de défilement compare l'image n à l'image n-1, et deux
                # images qui ne se suivent pas ne défilent pas de 100 ms.
                raise ValueError(
                    f"transcription discontinue : image {attendu} attendue, {reel} lue"
                )
            images.append(tuple(str(ligne) for ligne in corps.get("lines", ())))

        return cls(
            source=str(entete.get("source", "")),
            interval_s=float(entete.get("interval_s", 0.1)),
            frames=tuple(images),
            # Champ ajouté après coup : une transcription écrite avant sa
            # création reste lisible, avec 0 qui veut dire « pas mesuré ». La
            # refuser obligerait à repayer deux minutes de reconnaissance pour
            # un champ qui ne change aucune des lignes déjà lues.
            ocr_ms=float(entete.get("ocr_ms", 0.0)),
        )

    def pair(self, images: Sequence[GrayImage]) -> tuple[BenchFrame, ...]:
        """Rassemble pixels et texte, en refusant un appariement bancal.

        Rejouer 300 textes sur 299 images décalerait toute la mesure de
        défilement d'un cran sans qu'aucune exception ne soit levée : le banc
        rendrait un chiffre, simplement faux.
        """
        if len(images) != len(self.frames):
            raise ValueError(
                f"appariement impossible : {len(images)} images pour "
                f"{len(self.frames)} transcriptions"
            )
        return tuple(
            BenchFrame(index=index, image=image, lines=lignes)
            # strict=True : les deux longueurs viennent d'être vérifiées, mais
            # une troncature silencieuse ici décalerait pixels et texte d'un
            # cran, ce qui donnerait un chiffre plausible et faux.
            for index, (image, lignes) in enumerate(zip(images, self.frames, strict=True))
        )

    @classmethod
    def from_frames(
        cls,
        frames: Iterable[Sequence[str]],
        *,
        source: str,
        interval_s: float,
        ocr_ms: float = 0.0,
    ) -> Transcript:
        return cls(
            source=source,
            interval_s=interval_s,
            frames=tuple(tuple(str(ligne) for ligne in image) for image in frames),
            ocr_ms=ocr_ms,
        )
