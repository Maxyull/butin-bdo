"""Vérifie si une version plus récente de Butin est publiée sur GitHub.

Pourquoi une notification, jamais un remplacement automatique
-------------------------------------------------------------

Remplacer un exécutable EN COURS D'EXÉCUTION demande un programme séparé :
Windows refuse qu'on écrase le `.exe` qui tourne. Et un logiciel qui se
télécharge et s'installe tout seul, sans un clic de l'utilisateur, est
justement ce qui inquiète un antivirus. Décidé avec Maxime le 06/08/2026 :
Butin PRÉVIENT seulement. Le lien pointe vers la Release GitHub, la personne
télécharge et installe elle-même le nouvel installeur.

Pourquoi cette vérification ne peut jamais empêcher le logiciel de démarrer
-----------------------------------------------------------------------------

Même philosophie que `market.client` et `catalog.icons` : un problème réseau
dégrade l'affichage (pas de bandeau), il ne bloque jamais l'ouverture de la
fenêtre. `check_for_update` ne lève donc rien vers l'appelant : l'exception
interne `UpdateCheckError` existe pour que les tests distinguent « pas de
mise à jour disponible » de « la vérification a échoué », deux choses qu'un
simple `None` confondrait.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from urllib.parse import urlparse

import requests

_log = logging.getLogger(__name__)

RELEASES_URL = "https://api.github.com/repos/Maxyull/butin-bdo/releases/latest"
# Boucle locale mise à part (server.py), c'est le seul hôte que ce dépôt
# appelle sans passer par un cache : la liste blanche est donc réduite à lui
# seul, comme MarketClient le fait pour arsha.io.
ALLOWED_HOSTS = {"api.github.com"}
TIMEOUT_S = 3.0
# Une réponse de Release GitHub tient en quelques kilo-octets ; au-delà,
# c'est autre chose et on refuse plutôt que de lire, même politique que
# MarketClient et IconStore.
MAX_BYTES = 64 * 1024


class UpdateCheckError(Exception):
    """La vérification a échoué : réseau, dépôt sans Release, réponse illisible."""


@dataclass(frozen=True)
class UpdateInfo:
    disponible: bool
    version: str
    url: str


def _check_host(url: str, *, stage: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise UpdateCheckError(f"{stage} : schéma non https ({parsed.scheme!r})")
    if parsed.hostname not in ALLOWED_HOSTS:
        raise UpdateCheckError(f"{stage} : hôte non autorisé ({parsed.hostname!r})")


def _parse_version(version: str) -> tuple[int, ...]:
    """Tuple comparable terme à terme.

    Une pré-version `.devN` trie AVANT la version publiée du même numéro
    (`0.1.0.dev0 < 0.1.0`), ce qui suffit à ce que `docs/versionnage.md`
    déclare (SemVer + PEP 440, dev en pré-version seulement) : ce n'est pas un
    analyseur PEP 440 général, et n'a pas besoin de l'être ici.
    """
    coeur, _, dev = version.lstrip("vV").partition(".dev")
    try:
        parts = tuple(int(p) for p in coeur.split("."))
    except ValueError as exc:
        raise UpdateCheckError(f"version illisible : {version!r}") from exc
    if dev:
        return (*parts, 0, int(dev) if dev.isdigit() else 0)
    return (*parts, 1, 0)


def _fetch_latest(*, session: requests.Session, timeout: float) -> tuple[str, str]:
    _check_host(RELEASES_URL, stage="URL demandée")
    try:
        reponse = session.get(
            RELEASES_URL,
            timeout=timeout,
            headers={
                "User-Agent": "butin-bdo (+https://github.com/Maxyull/butin-bdo)",
                "Accept": "application/vnd.github+json",
            },
        )
        _check_host(reponse.url, stage="URL finale après redirection")
        reponse.raise_for_status()
        payload = reponse.content[: MAX_BYTES + 1]
    except requests.RequestException as exc:
        raise UpdateCheckError(f"requête impossible : {exc}") from exc

    if len(payload) > MAX_BYTES:
        raise UpdateCheckError("réponse anormalement volumineuse")

    try:
        donnees = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpdateCheckError(f"réponse illisible : {exc}") from exc

    tag = donnees.get("tag_name") if isinstance(donnees, dict) else None
    url = donnees.get("html_url") if isinstance(donnees, dict) else None
    if not tag or not url:
        raise UpdateCheckError("réponse sans tag_name ou html_url")
    return str(tag), str(url)


def check_for_update(
    current_version: str,
    *,
    session: requests.Session | None = None,
    timeout: float = TIMEOUT_S,
) -> UpdateInfo | None:
    """Rend `None` sur tout échec, jamais une exception : voir la note d'en-tête.

    `session` est injectable pour les tests, comme `MarketClient` : aucun test
    de ce module ne doit toucher le réseau.
    """
    try:
        tag, url = _fetch_latest(session=session or requests.Session(), timeout=timeout)
        plus_recente = _parse_version(tag) > _parse_version(current_version)
    except UpdateCheckError as exc:
        _log.debug("vérification de mise à jour impossible : %s", exc)
        return None
    return UpdateInfo(disponible=plus_recente, version=tag.lstrip("vV"), url=url)
