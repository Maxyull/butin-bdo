"""Rassemble en une archive tout ce qu'il faut pour comprendre un bogue.

Pourquoi une archive plutôt qu'un message
------------------------------------------

Le bouton « Signaler un bogue » envoie du texte, et c'est bien pour « le
compteur ne bouge pas ». Ça ne suffit pas pour « il compte trop » : la réponse
est dans le journal de lecture, ligne par ligne, et personne ne va copier
quinze mille lignes dans un salon Discord.

⛔ Cette archive n'est JAMAIS envoyée toute seule
-------------------------------------------------

Elle est écrite sur le disque du joueur, et **c'est lui qui la dépose**. Deux
raisons, dans cet ordre :

1. **Elle contient les messages des autres joueurs.** La reconnaissance lit la
   zone de chat telle quelle : le canal Système est entrelacé avec la
   conversation, donc le journal contient des pseudonymes et des phrases de
   tiers qui n'ont rien demandé. Le décider à leur place serait le genre de
   chose qu'on ne peut pas rattraper une fois faite.
2. Elle peut peser plusieurs mégaoctets, ce que le relais de rapports ne prend
   pas : il attend du texte.

`decrire_le_contenu()` existe pour que l'interface puisse **montrer** ce qui
part avant que le joueur ne décide. Une archive qu'on dépose sans savoir ce
qu'il y a dedans est un formulaire signé en blanc.

⛔ Ce qui n'y entre jamais
---------------------------

`contributeur.txt`. Cet identifiant **est** la clé du rattachement Discord : le
relais signe un état qui le contient, donc le connaître suffit à rattacher
**son** compte au numéro de quelqu'un d'autre et à s'attribuer ses rapports.
Il n'a rien à faire dans un fichier qu'on dépose dans un salon public.

`test_rien_de_sensible_n_entre_dans_l_archive` le vérifie sur le contenu réel
de l'archive, pas sur l'intention.
"""

from __future__ import annotations

import json
import logging
import platform
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import __version__, paths
from .diagnostic import dossier_des_rapports

_log = logging.getLogger(__name__)

#: Nom du fichier interdit d'archive. Voir l'en-tête du module.
FICHIER_INTERDIT = "contributeur.txt"

#: Journaux les plus récents à joindre. Trois couvre « ça s'est mal passé la
#: fois d'avant aussi », sans faire une archive de cent mégaoctets sur une
#: machine qui farme tous les jours.
JOURNAUX_JOINTS = 3

#: Plafond par journal. Au-delà, il est tronqué et l'archive le DIT : une
#: troncature muette ferait chercher une cause dans un fichier amputé.
MAX_OCTETS_JOURNAL = 8 * 1024 * 1024


@dataclass(frozen=True)
class Archive:
    """Ce que l'interface doit afficher après la préparation."""

    chemin: Path
    octets: int
    contenu: list[str]
    """Un libellé lisible par fichier joint. C'est ce qu'on montre au joueur
    AVANT qu'il ne dépose l'archive quelque part."""

    avertissements: list[str]
    """Ce qui n'a pas pu être joint, ou ce qui a été tronqué. Jamais silencieux."""


def dossier_des_archives(racine: Path | None = None) -> Path:
    return dossier_des_rapports(racine)


def _horodatage(maintenant: float | None = None) -> str:
    return time.strftime("%Y%m%d-%H%M%S", time.localtime(maintenant or time.time()))


def contexte(etat: dict[str, Any] | None = None) -> dict[str, Any]:
    """Le contexte technique, sans rien qui identifie la machine.

    ⚠️ Ni nom d'utilisateur, ni chemin absolu, ni adresse. `platform.platform()`
    donne la version de Windows, qui sert vraiment (une régression de capture
    peut être propre à une version), et rien de plus.
    """
    donnees: dict[str, Any] = {
        "version de Butin": __version__,
        "système": platform.platform(),
        "python": platform.python_version(),
        "préparée le": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
    }
    if etat:
        reglages = etat.get("reglages") or {}
        capture = etat.get("capture") or {}
        donnees.update(
            {
                "zone calibrée": reglages.get("calibrage") or "aucune",
                "langue": reglages.get("langue", "?"),
                "région": reglages.get("region", "?"),
                "session en cours": "oui" if etat.get("session") else "non",
                "capture en cours": "oui" if capture.get("en_cours") else "non",
                "lectures": capture.get("lectures", 0),
                "panne de capture": capture.get("erreur") or "aucune",
            }
        )
    return donnees


def journaux_recents(racine: Path | None = None, limite: int = JOURNAUX_JOINTS) -> list[Path]:
    """Les journaux de session les plus récents, du plus récent au plus ancien."""
    dossier = dossier_des_rapports(racine)
    if not dossier.is_dir():
        return []
    fichiers = [f for f in dossier.glob("session-*.jsonl") if f.is_file()]
    fichiers.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    return fichiers[:limite]


def _joindre(
    archive: zipfile.ZipFile,
    source: Path,
    nom: str,
    contenu: list[str],
    avertissements: list[str],
) -> None:
    """Ajoute un fichier, en tronquant plutôt qu'en abandonnant."""
    try:
        octets = source.read_bytes()
    except OSError as exc:
        avertissements.append(f"{nom} : illisible ({exc.strerror or exc})")
        return

    if len(octets) > MAX_OCTETS_JOURNAL:
        octets = octets[:MAX_OCTETS_JOURNAL]
        avertissements.append(
            f"{nom} : TRONQUÉ à {MAX_OCTETS_JOURNAL // (1024 * 1024)} Mo, la fin du journal manque"
        )
    archive.writestr(nom, octets)
    contenu.append(f"{nom} ({len(octets) // 1024} Ko)")


def preparer(
    *,
    etat: dict[str, Any] | None = None,
    apercu: bytes | None = None,
    racine: Path | None = None,
    maintenant: float | None = None,
) -> Archive:
    """Écrit l'archive et rend ce qu'il faut afficher. **Ne lève jamais.**

    Même garantie que `send_report` : préparer un rapport de bogue ne doit pas
    planter l'application au moment où l'on signale un bogue. Ce qui manque est
    signalé dans `avertissements` plutôt que de tout faire échouer — une
    archive sans capture d'écran reste très utile.
    """
    dossier = dossier_des_archives(racine)
    chemin = dossier / f"rapport-{_horodatage(maintenant)}.zip"
    contenu: list[str] = []
    avertissements: list[str] = []

    try:
        dossier.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(chemin, "w", zipfile.ZIP_DEFLATED) as archive:
            infos = contexte(etat)
            archive.writestr(
                "contexte.txt",
                "\n".join(f"{cle} : {valeur}" for cle, valeur in infos.items()),
            )
            contenu.append("contexte.txt (version, système, calibrage)")

            for journal in journaux_recents(racine):
                _joindre(archive, journal, f"journaux/{journal.name}", contenu, avertissements)
            if not journaux_recents(racine):
                avertissements.append(
                    "aucun journal de session : lance une session de farm avant de "
                    "préparer l'archive, c'est le fichier le plus utile"
                )

            for source, nom in (
                (paths.settings_path(), "reglages.json"),
                (paths.calibration_path(), "calibrage.json"),
            ):
                if source.is_file():
                    _joindre(archive, source, nom, contenu, avertissements)
                else:
                    avertissements.append(f"{nom} : absent")

            if apercu:
                archive.writestr("zone-calibree.png", apercu)
                contenu.append(f"zone-calibree.png ({len(apercu) // 1024} Ko)")
            else:
                avertissements.append(
                    "pas de capture de la zone : calibre d'abord, ou l'écran n'était pas accessible"
                )
    except OSError as exc:
        _log.warning("archive de diagnostic impossible : %s", exc)
        return Archive(
            chemin=chemin,
            octets=0,
            contenu=[],
            avertissements=[f"archive impossible à écrire : {exc.strerror or exc}"],
        )

    try:
        taille = chemin.stat().st_size
    except OSError:
        taille = 0
    return Archive(chemin=chemin, octets=taille, contenu=contenu, avertissements=avertissements)


def decrire_le_contenu(archive: Archive) -> str:
    """Une phrase par ligne, pour montrer au joueur ce qu'il s'apprête à déposer."""
    lignes = list(archive.contenu)
    if archive.avertissements:
        lignes.append("")
        lignes.extend(f"⚠️ {a}" for a in archive.avertissements)
    return "\n".join(lignes)


def ouvrir_le_dossier(chemin: Path) -> bool:
    """Ouvre l'explorateur sur l'archive. **Ne lève jamais.**

    Le joueur vient de cliquer, il doit voir le fichier : lui donner un chemin
    à recopier à la main est le meilleur moyen qu'il abandonne.
    """
    import subprocess

    try:
        # `explorer /select,` ouvre le dossier ET met le fichier en évidence.
        # ⚠️ `explorer` rend un code de sortie non nul même quand il réussit :
        # on ne le teste donc pas, sous peine d'annoncer un échec à chaque fois.
        subprocess.Popen(["explorer", f"/select,{chemin}"], close_fds=True)  # noqa: S603, S607
        return True
    except (OSError, ValueError) as exc:
        _log.warning("ouverture du dossier impossible : %s", exc)
        return False


def charge_utile(archive: Archive) -> str:
    """Le résumé texte qui accompagne l'archive dans le salon Discord.

    Le relais n'accepte que du texte : l'archive se dépose à la main, mais le
    message, lui, peut partir tout seul et dire qu'elle existe. Sans ça, une
    archive déposée sans contexte oblige à un aller-retour.
    """
    return json.dumps(
        {"archive": archive.chemin.name, "octets": archive.octets, "contenu": archive.contenu},
        ensure_ascii=False,
    )
