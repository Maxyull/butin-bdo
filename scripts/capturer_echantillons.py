"""Capture une rafale d'écrans en PNG natif, pour calibrer l'OCR.

Pourquoi pas une vidéo, ni un partage d'écran
----------------------------------------------

Le texte du journal d'acquisition fait 16 pixels de haut sur un fond
transparent. C'est exactement ce que la compression vidéo détruit en premier :
elle lisse les détails fins et garde les grandes zones. Calibrer des seuils sur
une image compressée donnerait des valeurs qui ne correspondent plus aux vrais
pixels en jeu.

Un partage d'écran a le même défaut en pire : l'image est redimensionnée avant
d'arriver, donc la géométrie mesurée (le pas de 21 px entre deux lignes) ne veut
plus rien dire.

`mss` écrit du PNG en résolution native, sans perte et sans mise à l'échelle.
C'est la seule forme sur laquelle un calibrage tient.

Ce qu'il faut capturer
-----------------------

**De la densité, pas de la durée.** Trente secondes pendant qu'un pack meurt et
fait défiler le journal valent mieux que vingt minutes tranquilles. Deux choses
restent à vérifier et n'ont besoin que de ça :

1. la **colonne des pastilles** comme règle de mesure du défilement, validée
   pour l'instant sur deux captures de scènes différentes, ce qui mélange le
   bruit du décor et un vrai changement de contenu ;
2. le **mur de lignes identiques**, quand le même objet tombe plusieurs fois
   d'affilée : le seul cas que l'alignement textuel ne sait pas trancher.

⚠️ Les images vont hors dépôt, dans `D:\\DEV\\bdo\\echantillons`. Une capture de
Black Desert contient le chat de guilde, donc des pseudonymes de tiers, plus le
nom de famille et la position du personnage.

Usage
-----

    python scripts/capturer_echantillons.py --delai 8 --images 25 --pas 1.0
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import mss
from PIL import Image

DESTINATION = Path(r"D:\DEV\bdo\echantillons")
PREFIXE = "farm"


def capturer(
    *,
    delai_s: float,
    images: int,
    pas_s: float,
    moniteur: int,
    destination: Path,
    decoupe: tuple[int, int, int, int] | None = None,
) -> list[Path]:
    """Prend `images` captures espacées de `pas_s`, après `delai_s` de répit.

    Le délai initial n'est pas un confort : il faut le temps de revenir dans le
    jeu. Une rafale qui démarre immédiatement ne capture que le bureau.
    """
    destination.mkdir(parents=True, exist_ok=True)
    horodatage = time.strftime("%Y%m%d-%H%M%S")

    print(f"Départ dans {delai_s:.0f} s. Reviens dans le jeu et fais tomber du butin.")
    time.sleep(delai_s)

    ecrits: list[Path] = []
    with mss.mss() as session:
        zone = session.monitors[moniteur]
        print(f"Écran {moniteur} : {zone['width']}x{zone['height']}")
        if decoupe is not None:
            # Ne capturer que la zone utile plutôt que l'écran entier. Les
            # pixels restent NATIFS, aucun redimensionnement : seuls les bords
            # sont retirés. Une rafale de 300 images passe ainsi de 2 Go à
            # environ 60 Mo, ce qui rend une longue série possible.
            gauche, haut, droite, bas = decoupe
            zone = {
                "left": zone["left"] + gauche,
                "top": zone["top"] + haut,
                "width": droite - gauche,
                "height": bas - haut,
            }
            print(f"Zone réduite : {zone['width']}x{zone['height']}")

        for index in range(images):
            debut = time.perf_counter()
            brut = session.grab(zone)
            # « raw » et non « RGB » : mss rend du BGRA, et laisser Pillow
            # deviner intervertirait le rouge et le bleu, donc fausserait le
            # contraste des noms d'objets colorés du journal.
            image = Image.frombytes("RGB", brut.size, brut.bgra, "raw", "BGRX")
            chemin = destination / f"_{PREFIXE}-{horodatage}-{index:03d}.png"
            image.save(chemin, format="PNG", compress_level=1)
            ecrits.append(chemin)
            print(f"  {index + 1}/{images}  {chemin.name}")

            # Le pas est compté depuis le DÉBUT de la capture, pas après :
            # sinon le temps d'écriture s'ajoute à chaque tour et l'intervalle
            # réel dérive, ce qui fausserait toute mesure de défilement.
            reste = pas_s - (time.perf_counter() - debut)
            if reste > 0 and index < images - 1:
                time.sleep(reste)

    return ecrits


def main(argv: list[str] | None = None) -> int:
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument("--delai", type=float, default=8.0, help="secondes avant la rafale")
    parseur.add_argument("--images", type=int, default=25, help="nombre de captures")
    parseur.add_argument("--pas", type=float, default=1.0, help="secondes entre deux captures")
    parseur.add_argument("--moniteur", type=int, default=1, help="écran, 1 = principal")
    parseur.add_argument("--dossier", type=Path, default=DESTINATION)
    parseur.add_argument(
        "--zone",
        type=int,
        nargs=4,
        metavar=("GAUCHE", "HAUT", "DROITE", "BAS"),
        help="ne capturer que cette zone, en pixels natifs, sans redimensionner",
    )
    args = parseur.parse_args(argv)

    ecrits = capturer(
        delai_s=args.delai,
        images=args.images,
        pas_s=args.pas,
        moniteur=args.moniteur,
        destination=args.dossier,
        decoupe=tuple(args.zone) if args.zone else None,
    )
    total = sum(chemin.stat().st_size for chemin in ecrits)
    print(f"\n{len(ecrits)} images, {total / 1024 / 1024:.0f} Mo, dans {args.dossier}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
