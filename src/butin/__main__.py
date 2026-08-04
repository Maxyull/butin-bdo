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

from . import __version__, paths
from .catalog import ItemCatalog, ItemMatcher
from .catalog.models import LOCALE_FR
from .catalog.source import CatalogError


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="butin",
        description="Suivi de butin pour Black Desert Online, en français.",
    )
    parser.add_argument("--version", action="version", version=f"Butin {__version__}")
    parser.add_argument(
        "-v", "--verbeux", action="store_true", help="affiche les messages de diagnostic"
    )

    commandes = parser.add_subparsers(dest="commande", required=True)

    catalogue = commandes.add_parser(
        "catalogue", help="état du catalogue d'objets et couverture française"
    )
    catalogue.add_argument(
        "--rafraichir",
        action="store_true",
        help="force le retéléchargement même si le cache est valide",
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
        if args.commande == "catalogue":
            return _commande_catalogue(args.rafraichir)
        if args.commande == "reconnaitre":
            return _commande_reconnaitre(args.texte)
    except CatalogError as exc:
        print(f"Erreur : {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
