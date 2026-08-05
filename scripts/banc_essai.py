"""Lance le banc d'essai sur une rafale de captures réelles.

Ce script ne contient aucune mesure : tout est dans `butin.bench`, qui est
testé. Il ne fait que trois choses qu'un paquet ne doit pas faire — lire des
fichiers sur ce disque, appeler l'OCR, et afficher.

Usage
-----

    python -X utf8 scripts/banc_essai.py

La première exécution reconnaît les 300 images, ce qui prend environ deux
minutes, et écrit une **transcription** à côté d'elles. Les suivantes la
relisent et rendent le rapport en quelques secondes. `--relire` force une
nouvelle reconnaissance, à faire seulement si les réglages d'OCR ont changé.

⚠️ Les images ET la transcription restent hors dépôt : elles contiennent le chat
de guilde, donc des pseudonymes de tiers, le nom de famille et la position du
personnage. Le dépôt est public.

Le `-X utf8` n'est pas décoratif : sans lui, Windows écrit la sortie en cp1252
et le rapport, qui est en français, s'arrête sur la première ligne accentuée.
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from dataclasses import replace
from pathlib import Path

import numpy as np
from PIL import Image

from butin.bench import (
    assemble,
    build_report,
    measure_scroll,
    replay,
    replay_realtime,
    silver_fingerprints,
)
from butin.bench.transcript import Transcript
from butin.capture.loop import LoopConfig
from butin.capture.ocr import TextReader
from butin.capture.screen import GrayImage
from butin.catalog import ItemCatalog, ItemMatcher

ECHANTILLONS = Path(r"D:\DEV\bdo\echantillons")
RAFALE = "_farm-20260805-014459"
PAS_S = 0.10


def charger_images(dossier: Path, prefixe: str) -> tuple[list[Path], list[GrayImage]]:
    """Charge la rafale en niveaux de gris, dans l'ordre des index.

    Le tri est celui des noms de fichiers, qui portent un index sur trois
    chiffres. Un tri par date de modification donnerait un ordre presque bon,
    et un presque-bon ordre fausserait toute la mesure de défilement.
    """
    chemins = sorted(dossier.glob(f"{prefixe}-*.png"))
    if not chemins:
        raise SystemExit(f"aucune image « {prefixe}-*.png » dans {dossier}")
    images = [np.asarray(Image.open(chemin).convert("L"), dtype=np.uint8) for chemin in chemins]
    return chemins, images


def transcrire(images: list[GrayImage], source: str, pas_s: float) -> Transcript:
    """Fait lire la rafale par le vrai lecteur de la boucle, et se chronomètre.

    Le chronomètre n'est pas décoratif : le coût d'une reconnaissance fixe la
    cadence que la boucle peut tenir en jeu, donc combien d'images de cette
    rafale elle aurait le droit de lire. Le mesurer ici évite de rejouer le banc
    à une vitesse qu'on ne sait pas payer.

    Médiane et non moyenne : les toutes premières images paient encore
    l'allocation des tampons du moteur, et une moyenne les étalerait sur les
    trois cents.
    """
    lecteur = TextReader()
    lecteur.warmup()
    frames: list[list[str]] = []
    durees: list[float] = []
    for index, image in enumerate(images):
        debut = time.perf_counter()
        frames.append(lecteur.read_text(image))
        durees.append((time.perf_counter() - debut) * 1000.0)
        if (index + 1) % 25 == 0 or index + 1 == len(images):
            print(
                f"  {index + 1}/{len(images)} images  "
                f"({statistics.median(durees):.0f} ms par image)",
                file=sys.stderr,
            )
    return Transcript.from_frames(
        frames, source=source, interval_s=pas_s, ocr_ms=statistics.median(durees)
    )


def main(argv: list[str] | None = None) -> int:
    parseur = argparse.ArgumentParser(description="Banc d'essai du compteur de butin.")
    parseur.add_argument("--dossier", type=Path, default=ECHANTILLONS)
    parseur.add_argument("--rafale", default=RAFALE, help="préfixe des images de la rafale")
    parseur.add_argument("--pas", type=float, default=PAS_S, help="secondes entre deux images")
    parseur.add_argument(
        "--relire", action="store_true", help="refait la reconnaissance au lieu de la relire"
    )
    parseur.add_argument(
        "--ocr-ms",
        type=float,
        default=None,
        help="coût d'une reconnaissance, en ms ; par défaut celui mesuré à la transcription",
    )
    parseur.add_argument(
        "--async-ocr",
        action="store_true",
        help=(
            "rejoue en TEMPS RÉEL, reconnaissance sur un fil à part "
            "(LoopConfig.async_ocr). Paie le vrai coût de l'OCR à chaque lecture "
            "et dure donc au moins la durée réelle de la rafale (une minute pour "
            "600 images à 100 ms), contre quelques secondes pour le rejeu simulé. "
            "Sert à mesurer si le découplage aide, ce qu'aucun rejeu simulé ne "
            "peut faire : lui n'attend jamais en vrai, donc rien n'y sépare "
            "les deux modes."
        ),
    )
    args = parseur.parse_args(argv)

    _, images = charger_images(args.dossier, args.rafale)
    print(f"{len(images)} images {images[0].shape[1]}x{images[0].shape[0]}", file=sys.stderr)

    chemin = args.dossier / f"_butin-transcription-{args.rafale.lstrip('_')}.jsonl"
    if args.relire or not chemin.exists():
        print("Reconnaissance en cours…", file=sys.stderr)
        transcription = transcrire(images, source=args.rafale, pas_s=args.pas)
        transcription.write(chemin)
        print(f"Transcription écrite : {chemin}", file=sys.stderr)
    else:
        transcription = Transcript.read(chemin)
        print(f"Transcription relue : {chemin}", file=sys.stderr)

    frames = transcription.pair(images)
    matcher = ItemMatcher(ItemCatalog.load())

    # La cadence de lecture est calée sur le coût MESURÉ de la reconnaissance,
    # et non sur la valeur par défaut de la boucle. Celle-ci vient d'une zone de
    # 520 x 385 ; une zone plus grande coûte davantage, et rejouer plus vite
    # qu'on ne sait payer donnerait au compteur des images qu'il n'aurait jamais
    # en jeu.
    cout_ms = args.ocr_ms if args.ocr_ms is not None else transcription.ocr_ms
    reglage = LoopConfig()
    if cout_ms > 0:
        reglage = LoopConfig(ocr_min_interval_s=cout_ms / 1000.0)
        print(f"Cadence de lecture : {cout_ms:.0f} ms par image", file=sys.stderr)

    if args.async_ocr:
        reglage = replace(reglage, async_ocr=True)
        duree_min = len(images) * args.pas
        print(
            f"Mode asynchrone : rejeu en TEMPS RÉEL, au moins {duree_min:.0f} s "
            "(le vrai coût de l'OCR, pas une transcription rejouée)…",
            file=sys.stderr,
        )
        lecteur_reel = TextReader()
        lecteur_reel.warmup()
        resultat_replay = replay_realtime(
            frames, matcher, lecteur_reel, config=reglage, interval_s=args.pas
        )
    else:
        resultat_replay = replay(frames, matcher, config=reglage, interval_s=args.pas)

    rapport = build_report(
        resultat_replay,
        assemble([frame.lines for frame in frames]),
        measure_scroll(
            images,
            ruler_left_ratio=reglage.ruler_left_ratio,
            ruler_right_ratio=reglage.ruler_right_ratio,
            row_height_px=reglage.row_height_px,
            max_scroll_lines=reglage.max_scroll_lines,
            bright_threshold=reglage.bright_threshold,
        ),
        silver_fingerprints([frame.lines for frame in frames]),
        matcher,
        frames=len(frames),
        interval_s=args.pas,
    )
    print(rapport.render())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
