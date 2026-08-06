"""Envoi d'un rapport de bogue vers le salon Discord, par un relais.

Pourquoi un relais et pas le webhook directement
------------------------------------------------

Butin est **distribué publiquement** : l'installeur part chez des joueurs. Une
URL de webhook Discord embarquée dedans serait lisible par n'importe lequel
d'entre eux, donc le salon deviendrait spammable, et l'URL ne serait pas
révocable sans republier l'application entière.

Le webhook vit donc sur `rubin.maxyull.fr`, qui est déjà l'API du chronomètre
de quêtes, et **cette application ne le connaît jamais**. Elle POSTe un rapport
à `/v1/rapport`, le serveur le relaie. Tranché par Maxime le 06/08/2026 après
comparaison des trois options (webhook en clair, relais, webhook saisi par le
joueur). Voir `D:\\DEV\\bdo\\COORDINATION.md`.

Ce que ce module garantit
-------------------------

**Rien ne part sans un geste explicite du joueur.** Aucun envoi automatique,
aucun envoi au démarrage, aucun envoi sur erreur. C'est un bouton.

**`send_report` ne lève jamais.** Un rapport de bogue qui plante l'application
au moment où on signale un bogue serait une plaisanterie. Toute panne descend
en `ReportResult(envoye=False, raison=…)`, avec un message destiné à être
affiché tel quel.

**L'identifiant du contributeur est anonyme et stable.** Il sert uniquement à
distinguer deux rapports du même joueur. Il est tiré au sort une fois, gardé
sur le disque, et ne contient rien de la machine : ni nom d'utilisateur, ni
adresse, ni identifiant matériel. Le serveur n'en fait rien d'autre que
l'afficher tronqué (`joueur anonyme xxxxxxxx`) faute de rattachement Discord,
que Butin ne propose pas.
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import requests

from . import paths

_log = logging.getLogger(__name__)

RELAY_URL = "https://rubin.maxyull.fr/v1/rapport"
# Même politique que `update.py` et `MarketClient` : un seul hôte en liste
# blanche, revalidé après redirection.
ALLOWED_HOSTS = {"rubin.maxyull.fr"}
TIMEOUT_S = 10.0

#: Aligné sur `MAX_REPORT_LENGTH` du relais. Couper ici plutôt que de se faire
#: refuser en 413 après coup : le joueur voit le compteur pendant qu'il écrit.
MAX_MESSAGE = 1800

#: Format imposé par le relais (`PLAYER_PATTERN`) : 8 à 64 caractères parmi
#: `[0-9A-Za-z_-]`. 32 caractères hexadécimaux tombent dedans avec de la marge.
_ID_BYTES = 16

#: Le fichier vit à côté des sessions, pas dans `reglages.json` : ce n'est pas
#: une préférence, c'est une identité. La mêler aux réglages ferait perdre
#: l'identifiant à chaque fois qu'un fichier de réglages illisible retombe sur
#: les défauts, ce que ce projet fait exprès (voir `store/settings.py`).
CONTRIBUTOR_FILE = "contributeur.txt"


@dataclass(frozen=True)
class ReportResult:
    """Ce qu'il faut afficher au joueur, et rien de plus."""

    envoye: bool
    raison: str


def contributor_path(root: Path | None = None) -> Path:
    return (root or paths.storage_root()) / CONTRIBUTOR_FILE


def contributor_id(root: Path | None = None) -> str:
    """Rend l'identifiant anonyme, en le créant au premier appel.

    Un identifiant relu mais invalide est remplacé : mieux vaut un nouvel
    identifiant qu'un envoi refusé en 422 que le joueur ne saurait pas
    interpréter.
    """
    chemin = contributor_path(root)
    try:
        existant = chemin.read_text(encoding="utf-8").strip()
    except OSError:
        existant = ""

    if 8 <= len(existant) <= 64 and all(c.isalnum() or c in "_-" for c in existant):
        return existant

    nouveau = secrets.token_hex(_ID_BYTES)
    try:
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text(nouveau, encoding="utf-8")
    except OSError as exc:
        # Pas de disque, pas de dossier : on envoie quand même. Le rapport
        # compte plus que la continuité de l'identifiant.
        _log.warning("identifiant de contributeur non enregistré : %s", exc)
    return nouveau


def compose(message: str, contexte: dict[str, object] | None = None) -> str:
    """Assemble le corps du rapport, contexte technique compris.

    Le contexte est joint automatiquement parce qu'un rapport sans version ni
    zone calibrée oblige à un aller-retour, et qu'un joueur qui vient de perdre
    une session de farm ne le fera pas. Il est visible dans le champ avant
    l'envoi : rien n'est joint en douce.
    """
    corps = message.strip()
    if contexte:
        lignes = [f"- {cle} : {valeur}" for cle, valeur in contexte.items()]
        corps = f"{corps}\n\n_Contexte_\n" + "\n".join(lignes)
    if len(corps) > MAX_MESSAGE:
        corps = corps[: MAX_MESSAGE - 1] + "…"
    return corps


def _check_host(url: str, *, stage: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError(f"{stage} : schéma non https ({parsed.scheme!r})")
    if parsed.hostname not in ALLOWED_HOSTS:
        raise ValueError(f"{stage} : hôte non autorisé ({parsed.hostname!r})")


def send_report(
    message: str,
    *,
    contexte: dict[str, object] | None = None,
    url: str = RELAY_URL,
    session: requests.Session | None = None,
    timeout: float = TIMEOUT_S,
    root: Path | None = None,
) -> ReportResult:
    """Envoie le rapport au relais. **Ne lève jamais.**

    Chaque code de retour du relais a son message, parce qu'ils veulent dire
    des choses très différentes pour le joueur : « recommence », « c'est trop
    long », « ce n'est pas encore branché côté serveur, ce n'est pas ta faute ».
    """
    corps = compose(message, contexte)
    if not corps.strip():
        return ReportResult(False, "Le rapport est vide.")

    try:
        _check_host(url, stage="URL demandée")
        client = session or requests.Session()
        reponse = client.post(
            url,
            json={"joueur": contributor_id(root), "contenu": corps, "app": "butin"},
            timeout=timeout,
            headers={"User-Agent": "butin-bdo (+https://github.com/Maxyull/butin-bdo)"},
        )
        _check_host(reponse.url, stage="URL finale après redirection")
    except (requests.RequestException, ValueError) as exc:
        _log.warning("envoi du rapport impossible : %s", exc)
        return ReportResult(False, "Envoi impossible : vérifie ta connexion, puis réessaie.")

    if reponse.status_code in (200, 202):
        return ReportResult(True, "Rapport envoyé, merci.")
    if reponse.status_code == 503:
        # Le relais tourne mais son webhook n'est pas configuré. Le dire
        # franchement : le joueur n'y peut rien et n'a pas à réessayer.
        return ReportResult(False, "L'envoi de rapports n'est pas encore activé côté serveur.")
    if reponse.status_code == 413:
        return ReportResult(False, f"Rapport trop long, {MAX_MESSAGE} caractères au maximum.")
    if reponse.status_code == 422:
        return ReportResult(False, "Rapport refusé : il est vide ou mal formé.")
    _log.warning("le relais a répondu %s", reponse.status_code)
    return ReportResult(False, f"Le serveur a répondu {reponse.status_code}. Réessaie plus tard.")
