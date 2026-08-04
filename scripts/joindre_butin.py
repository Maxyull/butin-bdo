"""Joint la liste de butin curée à la main aux noms français de bdocodex.

Pourquoi ce script existe
-------------------------

Deux constats mesurés ont conduit ici, et ils se renforcent :

1. Le catalogue du marché (veliainn) ne reconnaît **qu'un objet sur huit** du
   butin réellement lu à l'écran. C'est une base de prix, pas une base d'objets.
2. Confronté à la liste de trash loot curée à la main par
   janhnguyen/BDO-Loot-Tracker, le même catalogue ne joint que **5 %** des 417
   entrées.

La cause est la même dans les deux sens : le trash loot ne s'échange pas à
l'hôtel des ventes, il se vend au marchand. Un catalogue de marché ne peut donc
pas le contenir, quelle que soit sa qualité.

bdocodex publie la base **complète**, 68 000 objets contre 8 300, dans les deux
langues. C'est la seule source capable de fournir un nom français pour un objet
lié au personnage.

Ce que le script produit
------------------------

`data/butin-connu.json` : pour chaque objet de la liste curée, son identifiant,
son nom anglais, son nom français, sa valeur en silver et la zone où il tombe.

Les trois dernières colonnes viennent du travail manuel de l'amont et n'existent
nulle part ailleurs. La **zone** est ce qui donne enfin des données au mécanisme
de restriction par spot de `catalog/matcher.py`, qui était jusqu'ici construit à
vide.

Sources et licences
-------------------

- `items/items.csv` de janhnguyen/BDO-Loot-Tracker, sous licence MIT, cité dans
  ATTRIBUTION.md.
- bdocodex, base de données communautaire publique. Une seule requête par
  langue, mise en cache localement, jamais rejouée sans nécessité.

Usage
-----

    python scripts/joindre_butin.py --csv <chemin> [--rafraichir]
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from butin.catalog.normalize import fold

BDOCODEX_URL = "https://bdocodex.com/query.php?a=items&l={lang}"

# bdocodex nomme l'anglais « us », comme le catalogue de veliainn. Les deux
# emploient le même code, ce qui évite une table de correspondance.
LANGS = ("fr", "us")

# Le nom utile est dans la troisième colonne, enveloppé de balises. Le
# `<span></span>` vide sert au rendu du site et n'apparaît pas toujours.
_NAME_RE = re.compile(r"<b>(?:<span[^>]*>\s*</span>)?(.*?)</b>", re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")

# Niveau d'amélioration encodé dans le nom par la liste amont : « I PRI: Deboreka
# Earring ». Ce n'est PAS le nom de l'objet, c'est de la présentation.
#
# Point de modélisation important : dans Black Desert, le niveau d'amélioration
# n'est pas une identité d'objet. Un Deboreka de base et son PRI portent le même
# identifiant, l'amélioration est une propriété. Plusieurs lignes de la liste
# amont pointent donc sur le même identifiant avec des valeurs différentes, et
# les écraser l'une par l'autre ferait perdre 75 des 417 entrées en silence.
_LEVEL_RE = re.compile(r"^(?:[IVX]+\s+)?(PRI|DUO|TRI|TET|PEN)\s*:\s*", re.IGNORECASE)


def separer_niveau(nom: str) -> tuple[str, str]:
    """Sépare le niveau d'amélioration du nom. Renvoie (nom, niveau)."""
    trouve = _LEVEL_RE.match(nom)
    if trouve is None:
        return (nom.strip(), "")
    return (nom[trouve.end() :].strip(), trouve.group(1).upper())


ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "cache"
OUTPUT = ROOT / "data" / "butin-connu.json"


def telecharger(lang: str, *, rafraichir: bool) -> Path:
    """Récupère la base bdocodex d'une langue, en cache local.

    Le fichier fait environ 35 Mo. Il est mis en cache et jamais retéléchargé
    sans `--rafraichir` : rejouer une requête de cette taille à chaque
    exécution du script serait impoli envers un service communautaire gratuit.
    """
    CACHE.mkdir(parents=True, exist_ok=True)
    cible = CACHE / f"bdocodex-items-{lang}.json"
    if cible.exists() and not rafraichir:
        return cible

    import requests

    reponse = requests.get(
        BDOCODEX_URL.format(lang=lang),
        timeout=(10, 300),
        headers={"User-Agent": "butin-bdo (+https://github.com/Maxyull/butin-bdo)"},
    )
    reponse.raise_for_status()
    cible.write_bytes(reponse.content)
    return cible


def charger_noms(chemin: Path) -> dict[int, str]:
    """Extrait `identifiant -> nom` d'un export bdocodex.

    Le nom arrive enveloppé de HTML destiné au rendu du site. On le déshabille
    plutôt que de demander une autre forme : c'est le seul point d'entrée
    public, et le HTML y est stable depuis longtemps.
    """
    brut = json.loads(chemin.read_text(encoding="utf-8-sig"))
    noms: dict[int, str] = {}
    for ligne in brut["aaData"]:
        try:
            item_id = int(ligne[0])
        except (TypeError, ValueError):
            continue
        trouve = _NAME_RE.search(str(ligne[2]))
        if trouve is None:
            continue
        nom = html.unescape(_TAG_RE.sub("", trouve.group(1))).strip()
        if nom:
            noms[item_id] = nom
    return noms


def lire_liste_curee(chemin: Path) -> list[dict[str, str]]:
    """Lit la liste de butin curée à la main.

    Les lignes de section (`--- Trash Loot ---`) séparent visuellement le
    fichier et ne sont pas des objets. L'en-tête non plus.
    """
    entrees: list[dict[str, str]] = []
    with chemin.open(newline="", encoding="utf-8-sig") as fichier:
        for ligne in csv.reader(fichier):
            if not ligne or not ligne[0] or ligne[0].startswith("---"):
                continue
            if ligne[0].strip().lower() == "name":
                continue
            entrees.append(
                {
                    "nom_en": ligne[0].strip(),
                    "valeur": ligne[1].strip() if len(ligne) > 1 else "",
                    "zone": ligne[2].strip() if len(ligne) > 2 else "",
                }
            )
    return entrees


def indexer_par_nom(noms: dict[int, str]) -> dict[str, list[int]]:
    """Index nom replié -> identifiants, du plus petit au plus grand.

    Une liste et non une valeur : plusieurs objets partagent un même nom. Les
    trier rend le départage reproductible d'une exécution à l'autre.
    """
    index: dict[str, list[int]] = {}
    for item_id, nom in noms.items():
        replie = fold(nom)
        if replie:
            index.setdefault(replie, []).append(item_id)
    for ids in index.values():
        ids.sort()
    return index


def joindre(
    entrees: list[dict[str, str]],
    index_en: dict[str, list[int]],
    noms_fr: dict[int, str],
) -> tuple[dict[str, dict[str, Any]], list[str], list[tuple[str, list[int]]]]:
    """Joint chaque entrée curée à son identifiant puis à son nom français."""
    joints: dict[str, dict[str, Any]] = {}
    absents: list[str] = []
    ambigus: list[tuple[str, list[int]]] = []

    for entree in entrees:
        nom, niveau = separer_niveau(entree["nom_en"])
        ids = index_en.get(fold(nom))
        if not ids:
            absents.append(entree["nom_en"])
            continue
        if len(ids) > 1:
            ambigus.append((nom, ids))
        item_id = ids[0]
        nom_fr = noms_fr.get(item_id, "")
        if not nom_fr:
            absents.append(entree["nom_en"])
            continue

        # Les valeurs s'accumulent par niveau d'amélioration au lieu de
        # s'écraser : voir le commentaire de _LEVEL_RE.
        fiche = joints.setdefault(
            str(item_id),
            {"en": nom, "fr": nom_fr, "zone_en": "", "valeurs": {}, "ambigu": len(ids) > 1},
        )
        fiche["valeurs"][niveau or "base"] = _entier(entree["valeur"])
        if entree["zone"] and not fiche["zone_en"]:
            fiche["zone_en"] = entree["zone"]
    return joints, absents, ambigus


def _entier(texte: str) -> int:
    try:
        return int(texte.replace(",", "").replace(" ", ""))
    except ValueError:
        return 0


def main(argv: list[str] | None = None) -> int:
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument(
        "--csv",
        type=Path,
        required=True,
        help="chemin vers items.csv de janhnguyen/BDO-Loot-Tracker",
    )
    parseur.add_argument(
        "--rafraichir",
        action="store_true",
        help="retélécharge bdocodex même si le cache est présent",
    )
    args = parseur.parse_args(argv)

    fichiers = {lang: telecharger(lang, rafraichir=args.rafraichir) for lang in LANGS}
    noms_fr = charger_noms(fichiers["fr"])
    noms_en = charger_noms(fichiers["us"])
    print(f"bdocodex : {len(noms_fr)} noms français, {len(noms_en)} noms anglais")

    entrees = lire_liste_curee(args.csv)
    print(f"liste curée : {len(entrees)} entrées")

    joints, absents, ambigus = joindre(entrees, indexer_par_nom(noms_en), noms_fr)
    total = len(entrees)
    lignes_jointes = total - len(absents)
    print(f"\nlignes jointes : {lignes_jointes}  ({lignes_jointes / total:.0%})")
    print(f"objets distincts : {len(joints)}")
    print(f"ambigus   : {len(ambigus)}")
    print(f"absents   : {len(absents)}  ({len(absents) / total:.0%})")

    avec_zone = sum(1 for v in joints.values() if v["zone_en"])
    zones = Counter(v["zone_en"] for v in joints.values() if v["zone_en"])
    print(f"avec zone : {avec_zone} objets, {len(zones)} zones distinctes")

    if absents:
        print("\npremiers absents :")
        for nom in absents[:15]:
            print(f"   {nom}")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(
            {
                "version": 1,
                "_lisez_moi": [
                    "Butin connu : nom anglais, nom français, valeur silver et zone.",
                    "Généré par scripts/joindre_butin.py, ne pas éditer à la main.",
                    "Valeur et zone viennent de janhnguyen/BDO-Loot-Tracker (MIT),",
                    "les noms de bdocodex. Voir ATTRIBUTION.md.",
                    "Les zones sont en anglais : leur traduction reste à faire.",
                ],
                "items": dict(sorted(joints.items(), key=lambda kv: int(kv[0]))),
            },
            ensure_ascii=False,
            indent=1,
            sort_keys=False,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"\nécrit : {OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
