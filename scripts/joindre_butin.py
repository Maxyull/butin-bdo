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

# Traduction des zones de farm, recoupée le 06/08/2026. bdocodex n'a pas de
# pages de zone dédiées ; sa carte du monde (bdocodex.com/{fr,us}/worldmap/)
# expose ses marqueurs par un même identifiant numérique en anglais et en
# français, ce qui vaut jointure directe. garmoth s'est révélé inutilisable
# comme source de zones : son contenu reste en anglais quel que soit le
# paramétrage. bdolytics.com (même principe que bdocodex : extraction directe
# des chaînes du client de jeu, déjà une source de `data/noms-verifies.json`)
# a servi de deuxième référence, recoupée avec bdocodex, et a comblé les
# zones absentes de la carte de bdocodex (petits camps non marqués comme
# nœud de carte).
#
# 66 des 94 zones sont recoupées par bdocodex ET bdolytics (accord mot pour
# mot). Les 28 suivantes ne reposent que sur bdolytics seul, faute de
# marqueur correspondant sur la carte de bdocodex — moins solide que la règle
# à deux sources de `noms-verifies.json`, mais bdolytics a le même statut de
# source primaire (extraction du client) que bdocodex, pas une traduction
# tierce : Centaurus Herd, Cyclops Land, Dark Energy Floodlands, Erethea's
# Limbo, Fadus Habitat, Forest Ronaros Area, Fortunate Golden Pig Cave, Gyfin
# Rhasia Temple (Under), Hystria Ruins, Kratuga Ancient Ruins, Murrowak's
# Labyrinth, Sherekhan Necropolis (Day)/(Night), Sycraia Ruins (Lower)/
# (Upper), Traitor's Graveyard, Vessel of Inquisition, Winter Tree Fossil,
# [Dehkia] Cyclops Land, [Dehkia] Hystria Ruins, [Elvia] Altar Imps, [Elvia]
# Swamp Fogans, [Elvia] Swamp Nagas.
#
# Les préfixes [Dehkia] / [Dekhia] / [Elvia] sont des noms propres non
# traduits en français, confirmés par le forum officiel NA/EU FR et par
# bdolytics lui-même (qui les écrit tels quels dans ses chaînes françaises).
# « [Dekhia] Aakman » reproduit une coquille déjà présente dans zone_en
# (« Dekhia » pour « Dehkia ») : gardée à l'identique plutôt que corrigée en
# silence, ce n'est pas le rôle de cette table.
ZONE_FR: dict[str, str] = {
    "Abandoned Iron Mine": "Mine de fer abandonnée",
    "Abandoned Monastery": "Monastère abandonné",
    "Aetherion Castle": "Château d'Aetherion",
    "Ash Forest": "Forêt de cendres",
    "Bashim Base": "Camp Bashim",
    "Basilisk Den": "Tanière des basilics",
    "Blood Wolf Settlement": "Repaire des Loups sanglants",
    "Bumblin' Buccaneers": "Pirates bric-à-brac",
    "Cadry Ruins": "Ruines de Cadry",
    "Catfishman Camp": "Camp des hommes poissons-chats",
    "Centaurus Herd": "Horde Centaure",
    "City of the Dead": "Cité des morts",
    "Crescent Shrine": "Sanctuaire du croissant",
    "Crypt of Resting Thoughts": "Crypte des pensées endormies",
    "Cyclops Land": "Terres des cyclopes",
    "Dark Energy Floodlands": "Zone débordant d'énergie noire",
    "Darkseekers' Retreat": "Refuge des disciples des ténèbres",
    "Desert Naga Temple": "Temple des nagas du désert",
    "Dokkebi Forest": "Forêt des Dokkebis",
    "Elric Shrine": "Sanctuaire d'Elric",
    "Erethea's Limbo": "Oubli d'Erethea",
    "Fadus Habitat": "Territoire des Fadus",
    "Forest Ronaros Area": "Zone des Ronaros forestiers",
    "Fortunate Golden Pig Cave": "Grotte des cochons dorés de la chance",
    "Gahaz Bandit's Lair": "Repaire des bandits de Gahaz",
    "Golden Pig Cave": "Grotte des cochons dorés",
    "Gyfin Rhasia Temple (Under)": "Temple de Gyfin Rhasia (sous-sol)",
    "Gyfin Rhasia Temple (Upper)": "Temple de Gyfin Rhasia",
    "Hasrah Cliff": "Falaise d'Hasrah",
    "Helms Post": "Poste des helms",
    "Hexe Sanctuary": "Sanctuaire d'Hexe",
    "Honglim Base": "Base de Honglim",
    "Hystria Ruins": "Ruines d'Hystria",
    "Kratuga Ancient Ruins": "Ruines anciennes de Kratuga",
    "Manes Hideout": "Planque des Manes",
    "Mansha Forest": "Forêt des Manshas",
    "Manshaum Forest": "Forêt Manshaum",
    "Mirumok Ruins": "Ruines Mirumok",
    "Murrowak's Labyrinth": "Dédale de Murrowak",
    "Navarn Steppe": "Steppe de Navarn",
    "Nymphamaré Castle": "Château de Nymphamaré",
    "Olun's Valley": "Vallée d'Olun",
    "Orbita Castle": "Château d'Orbita",
    "Orzekea": "Orzekea",
    "Padix Island": "Île de Padix",
    "Polly's Forest": "Forêt de Polly",
    "Protty Cave": "Grotte aux Prottys",
    "Rhutum Outstation": "Poste avancé des rhutums",
    "Roud Sulfur Mine": "Mine de soufre de Roud",
    "Sausan Garrison": "Garnison des sausans",
    "Sherekhan Necropolis (Day)": "Nécropole des Sherekhans (jour)",
    "Sherekhan Necropolis (Night)": "Nécropole des Sherekhans (nuit)",
    "Soldier's Cemetery": "Cimetière des soldats",
    "Star's End": "Astralle",
    "Sycraia Ruins (Lower)": "Zone inférieure des Ruines de Sycraia",
    "Sycraia Ruins (Upper)": "Zone supérieure des Ruines de Sycraia",
    "Tenebraum Castle": "Château de Tenebraum",
    "Thornwood Forest": "Forêt d'Arbrépine",
    "Titium Valley": "Vallée de Titium",
    "Traitor's Graveyard": "Cimetière du Traître",
    "Tshira Ruins": "Ruines de Tshira",
    "Tungrad Ruins": "Ruines de Tungrad",
    "Tunkuta": "Tunkuta",
    "Vessel of Inquisition": "Socle de l'inquisition",
    "Wandering Rogue Den": "Repaire des bandits errants",
    "Waragon Nest": "Nid de waragons",
    "Winter Tree Fossil": "Fossile d'arbre d'hiver",
    "Yzrahid Highlands": "Hautes terres d'Yzrahid",
    "Zephyros Castle": "Château de Zephyros",
    "[Dehkia] Ash Forest": "[Dehkia] Forêt de cendres",
    "[Dehkia] Cadry Ruins": "[Dehkia] Ruines de Cadry",
    "[Dehkia] Crescent Shrine": "[Dehkia] Sanctuaire du croissant",
    "[Dehkia] Cyclops Land": "[Dehkia] Terres des cyclopes",
    "[Dehkia] Gyfin Rhasia Temple (Upper)": "[Dehkia] Temple de Gyfin Rhasia",
    "[Dehkia] Hystria Ruins": "[Dehkia] Ruines d'Hystria",
    "[Dehkia] Mirumok Ruins": "[Dehkia] Ruines Mirumok",
    "[Dehkia] Olun's Valley": "[Dehkia] Vallée d'Olun",
    "[Dehkia] Pila Ku Jail": "[Dehkia] Prison de Pila Ku",
    "[Dehkia] Thornwood Forest": "[Dehkia] Forêt d'Arbrépine",
    "[Dehkia] Tunkuta": "[Dehkia] Tunkuta",
    "[Dekhia] Aakman": "[Dekhia] Aakman",
    "[Elvia] Altar Imps": "[Elvia] Éfrit de l'autel",
    "[Elvia] Biraghi Den": "[Elvia] Repaire de Biraghi",
    "[Elvia] Bloody Monastery": "[Elvia] Monastère sanglant",
    "[Elvia] Castle Ruins": "[Elvia] Ruines du château",
    "[Elvia] Hexe Sanctuary": "[Elvia] Sanctuaire d'Hexe",
    "[Elvia] Orc Camp": "[Elvia] Camp des Orcs",
    "[Elvia] Primal Giant Post": "[Elvia] Poste des géants originels",
    "[Elvia] Quint Hill": "[Elvia] Colline de Quint",
    "[Elvia] Rhutum Outstation": "[Elvia] Poste avancé des rhutums",
    "[Elvia] Roud Sulfur Mine": "[Elvia] Mine de soufre de Roud",
    "[Elvia] Saunil Camp": "[Elvia] Camp des saunils",
    "[Elvia] Swamp Fogans": "[Elvia] Fogan des marais",
    "[Elvia] Swamp Nagas": "[Elvia] Naga des marais",
}


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
            {
                "en": nom,
                "fr": nom_fr,
                "zone_en": "",
                "zone_fr": "",
                "valeurs": {},
                "ambigu": len(ids) > 1,
            },
        )
        fiche["valeurs"][niveau or "base"] = _entier(entree["valeur"])
        if entree["zone"] and not fiche["zone_en"]:
            fiche["zone_en"] = entree["zone"]
            fiche["zone_fr"] = ZONE_FR.get(entree["zone"], "")
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
    non_traduites = sorted(z for z in zones if z not in ZONE_FR)
    if non_traduites:
        print(f"zones sans traduction dans ZONE_FR ({len(non_traduites)}) :")
        for zone in non_traduites:
            print(f"   {zone}")

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
                    "zone_fr vient de la table ZONE_FR du script (bdocodex + bdolytics,",
                    "recoupées le 06/08/2026, voir son commentaire pour la couverture",
                    "exacte des 94 zones). Vide si aucune traduction n'est encore",
                    "connue pour cette zone.",
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
