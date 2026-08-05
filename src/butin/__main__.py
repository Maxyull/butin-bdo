"""Interface en ligne de commande.

Volontairement réduite. Elle existe pour vérifier le noyau sans interface
graphique : contrôler l'état du catalogue, et tester la reconnaissance d'un nom
lu à l'écran. C'est l'outil qui sert pendant le recoupement des noms français,
objet par objet.

L'interface graphique viendra par-dessus ces mêmes briques, jamais à leur place.
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import TYPE_CHECKING

from . import __version__, paths
from .catalog import ItemCatalog, ItemMatcher
from .catalog.models import LOCALE_FR
from .catalog.source import CatalogError

if TYPE_CHECKING:
    # Ces trois-là tirent numpy, mss et le paquet du moteur OCR. Les importer
    # pour de bon ferait payer tout ça à `butin --version`, et empêcherait la
    # ligne de commande de démarrer sur une machine sans affichage.
    from .capture.calibrate import Calibration
    from .capture.ocr import TextReader
    from .capture.screen import GrayImage


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="butin",
        description="Suivi de butin pour Black Desert Online, en français.",
    )
    parser.add_argument("--version", action="version", version=f"Butin {__version__}")
    parser.add_argument(
        "-v", "--verbeux", action="store_true", help="affiche les messages de diagnostic"
    )

    # Sans sous-commande, on ouvre l'application. C'est ce que fait un logiciel :
    # on le lance, il s'ouvre. Les sous-commandes restent pour le diagnostic et
    # pour une machine sans affichage.
    commandes = parser.add_subparsers(dest="commande", required=False)

    application = commandes.add_parser("app", help="ouvre la fenêtre de l'application")
    application.add_argument(
        "--port",
        type=int,
        default=0,
        help="port du serveur local, 0 pour laisser le système en choisir un libre",
    )

    catalogue = commandes.add_parser(
        "catalogue", help="état du catalogue d'objets et couverture française"
    )
    catalogue.add_argument(
        "--rafraichir",
        action="store_true",
        help="force le retéléchargement même si le cache est valide",
    )

    calibrer = commandes.add_parser(
        "calibrer", help="trouve la fenêtre de chat sur l'écran et enregistre la zone"
    )
    calibrer.add_argument(
        "--delai",
        type=float,
        default=5.0,
        help="secondes avant la capture, le temps de revenir dans le jeu",
    )
    calibrer.add_argument("--ecran", type=int, default=1, help="écran à examiner, 1 = principal")
    calibrer.add_argument(
        "--sans-ocr",
        action="store_true",
        help="ne mesure pas la largeur utile du texte, plus rapide mais zone trop large",
    )

    interface = commandes.add_parser(
        "interface", help="sert la même interface dans un navigateur, sans fenêtre"
    )
    interface.add_argument(
        "--port", type=int, default=8771, help="port d'écoute sur la boucle locale"
    )

    reconnaitre = commandes.add_parser(
        "reconnaitre", help="teste la reconnaissance d'un nom tel que l'OCR le lirait"
    )
    reconnaitre.add_argument("texte", help="le texte à reconnaître, entre guillemets")

    return parser


def _charger(rafraichir: bool = False) -> ItemCatalog:
    if rafraichir:
        paths.catalog_path().unlink(missing_ok=True)
    return ItemCatalog.load()


def _commande_catalogue(rafraichir: bool) -> int:
    catalogue = _charger(rafraichir)
    couverture = catalogue.coverage(LOCALE_FR)
    print(f"Objets              : {len(catalogue)}")
    print(f"Couverture française : {couverture:.1%}")
    print(f"Cache                : {paths.catalog_path()}")

    # Une couverture qui s'effondre signale que la source amont a changé de
    # format ou perdu la locale française, bien avant que des utilisateurs ne
    # remontent des drops non reconnus.
    if couverture < 0.90:
        print(
            "\nAttention : couverture française anormalement basse. "
            "La source amont a peut-être changé de format.",
            file=sys.stderr,
        )
        return 1
    return 0


def _commande_calibrer(delai: float, ecran: int, sans_ocr: bool) -> int:
    """Cherche le chat sur l'écran et enregistre ce qu'il faut pour le lire.

    Le délai n'est pas un confort : le calibrage doit voir le **jeu**, avec son
    journal d'acquisition affiché. Lancé sans délai depuis un terminal, il
    photographie le terminal.
    """
    import time

    from .capture.calibrate import (
        CALIBRATION_FRAMES,
        CalibrationError,
        calibrate_frames,
        combine,
        find_chat,
    )
    from .capture.screen import ScreenCapture

    print(f"Capture dans {delai:.0f} s. Reviens dans le jeu, journal d'acquisition visible.")
    time.sleep(delai)

    images = []
    with ScreenCapture(monitor=ecran) as capture:
        zone = capture.target_monitor()
        for index in range(CALIBRATION_FRAMES):
            if index:
                time.sleep(0.4)
            images.append(capture.grab(zone))
    image = images[-1]

    from .capture.ocr import TextReader

    lecteur = TextReader()
    try:
        if sans_ocr:
            # Sans reconnaissance, la largeur reste celle de la géométrie. La
            # médiane vaut quand même : c'est le cadrage qui varie le plus.
            calibrage = combine([find_chat(vue, origin=(zone.left, zone.top)) for vue in images])
        else:
            print(f"Mesure sur {CALIBRATION_FRAMES} images…")
            calibrage = calibrate_frames(images, lecteur, origin=(zone.left, zone.top))
    except CalibrationError as exc:
        print(f"Échec du calibrage : {exc}", file=sys.stderr)
        return 1

    chemin = calibrage.save()
    print(f"Zone du chat : {calibrage.describe()}")
    print(f"Enregistré dans {chemin}")

    # Un calibrage vrai mais fragile doit se voir : sur peu de rangées, la
    # géométrie est juste et la largeur utile ne veut pas dire grand-chose.
    if calibrage.rows < 10:
        print(
            f"\nAttention : seulement {calibrage.rows} rangées visibles. "
            "Recalibrer avec un journal plus rempli donnerait une zone plus sûre.",
            file=sys.stderr,
        )
    if sans_ocr:
        print(
            "\nAttention : sans mesure de la largeur, la zone prend toute la largeur "
            "de l'écran. Utilisable pour un essai, coûteux en reconnaissance.",
            file=sys.stderr,
        )
        return 0
    return _montrer_la_zone(image, calibrage, lecteur)


def _montrer_la_zone(image: GrayImage, calibrage: Calibration, lecteur: TextReader) -> int:
    """Affiche ce que la zone contient, pour qu'on voie sur quoi on a calibré.

    ⚠️ Nécessaire, et trouvé en essayant la commande pour de bon. La détection
    cherche ce qui **se répète verticalement** ; elle ne sait pas d'où vient
    l'image. Un premier essai hors du jeu a calibré, très proprement, sur une
    **capture du chat ouverte dans une visionneuse d'images** : zone trouvée,
    pas de ligne juste, 19 lignes de gain lues. Tout était correct sauf que ce
    n'était pas le jeu.

    Aucune heuristique ne distingue le chat du jeu d'une image du chat du jeu :
    ce sont les mêmes pixels. Ce qui reste possible, et suffisant, c'est de
    **montrer ce qui a été lu**. Un terminal, une mauvaise fenêtre ou un mauvais
    écran se reconnaissent d'un coup d'œil, et le cas de la capture affichée se
    règle par la consigne : avoir le jeu devant soi.

    Zéro ligne de gain déclenche un avertissement explicite, parce que c'est la
    seule chose qu'on puisse affirmer : la zone ne contient pas de journal.
    """
    from .capture.lines import parse_frame

    region = calibrage.region
    zone = image[region.top : region.bottom, region.left : region.right]
    rangees = lecteur.read_text(zone)

    print("\nCe que la zone contient :")
    for ligne in rangees[:4] or ["(aucun texte lu)"]:
        print(f"  {ligne[:90]}")

    try:
        matcher = ItemMatcher(_charger())
    except CatalogError:
        # Sans catalogue on ne peut pas compter les gains, mais l'extrait
        # ci-dessus suffit déjà à voir si on regarde le bon endroit.
        return 0

    gains = len(parse_frame(list(rangees), matcher))
    if gains == 0:
        print(
            "\nAttention : aucune ligne du journal d'acquisition dans cette zone. "
            "Si l'extrait ci-dessus n'est pas le chat du jeu, la zone est FAUSSE : "
            "revenez dans le jeu, journal visible, et relancez « butin calibrer ».",
            file=sys.stderr,
        )
        return 1

    print(f"\n{gains} lignes de gain reconnues dans la zone.")
    return 0


def _commande_reconnaitre(texte: str) -> int:
    catalogue = _charger()
    match = ItemMatcher(catalogue).resolve(texte)
    if match is None:
        print(f"« {texte} » : aucune correspondance sûre")
        return 1
    print(f"« {texte} »")
    print(f"  objet   : {match.item.name()}")
    print(f"  id      : {match.item.item_id}")
    print(f"  méthode : {match.method.value}")
    print(f"  score   : {match.score:.1f}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbeux else logging.WARNING,
        format="%(levelname)s %(name)s : %(message)s",
    )

    try:
        if args.commande in (None, "app"):
            from .app import run

            return run(port=getattr(args, "port", 0))
        if args.commande == "catalogue":
            return _commande_catalogue(args.rafraichir)
        if args.commande == "interface":
            from .ui import serve

            serve(port=args.port)
            return 0
        if args.commande == "calibrer":
            return _commande_calibrer(args.delai, args.ecran, args.sans_ocr)
        if args.commande == "reconnaitre":
            return _commande_reconnaitre(args.texte)
    except CatalogError as exc:
        print(f"Erreur : {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
