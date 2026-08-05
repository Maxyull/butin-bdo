"""Images des objets, téléchargées une fois et gardées sur le disque.

Pourquoi une image
-------------------

Un joueur reconnaît son butin à l'image avant d'avoir lu le nom, exactement
comme il le reconnaît à la couleur de rareté. Sur un panneau posé sur le jeu,
lu du coin de l'œil pendant qu'on se bat, c'est la différence entre un récap
qu'on consulte et un récap qu'on comprend.

Ce que ce module ne fait PAS
-----------------------------

⛔ **Il ne fait jamais échouer quoi que ce soit.** Une image absente est un
défaut cosmétique ; un drop non compté est une erreur. Toute panne de réseau,
tout fichier illisible, toute image que la source ne connaît pas se traduit par
« pas d'icône » et rien d'autre. Aucun appel d'ici ne lève.

Il ne décide pas non plus de la mise en page : il rend un chemin sur le disque,
et c'est la couche interface qui le sert.

D'où viennent les images
-------------------------

Du même export bdocodex que les noms et les raretés, qui donne pour chaque objet
le chemin de son image (68 747 sur 68 747, mesuré le 05/08/2026). Rien de
nouveau n'est téléchargé pour les connaître : seules les images elles-mêmes le
sont, et une seule fois chacune.

Le durcissement est celui du reste du projet : HTTPS imposé, hôte en liste
blanche **revalidé après redirection**, plafond sur les octets réellement lus,
délais d'attente, écriture atomique.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterable, Mapping
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

from .. import paths

_log = logging.getLogger(__name__)

BASE_URL = "https://bdocodex.com"
ALLOWED_HOSTS = frozenset({"bdocodex.com", "www.bdocodex.com"})

TIMEOUTS = (5, 20)
"""Connexion, puis lecture. Plus courts que pour le catalogue : une icône pèse
quelques kilo-octets, et attendre cinq minutes dessus n'a aucun sens."""

MAX_BYTES = 512 * 1024
"""Plafond par image. Les vraies font 2 à 8 Ko ; un demi-mégaoctet laisse une
marge énorme tout en fermant la porte à un fichier qui remplirait le disque."""

_EXTENSIONS = frozenset({".webp", ".png", ".jpg", ".jpeg", ".gif"})
"""Extensions acceptées. Le nom du fichier écrit sur le disque vient de
l'identifiant numérique, jamais du chemin distant, mais l'extension en vient :
la restreindre évite d'écrire un `.exe` parce que la source aurait changé."""

TYPES_MIME = {
    ".webp": "image/webp",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
}


def icons_dir() -> Path:
    """Dossier des images, dans le CACHE et non dans les données.

    Tout ce qui est ici se retélécharge : le supprimer ne perd rien de ce que
    l'utilisateur a produit.
    """
    chemin = paths.cache_dir() / "icones"
    chemin.mkdir(parents=True, exist_ok=True)
    return chemin


def _extension(chemin_distant: str) -> str:
    suffixe = Path(urlparse(chemin_distant).path).suffix.lower()
    return suffixe if suffixe in _EXTENSIONS else ""


class IconStore:
    """Télécharge et range les images des objets. Ne lève jamais."""

    def __init__(
        self, root: Path | None = None, *, session: requests.Session | None = None
    ) -> None:
        self._root = root
        self._session = session
        self._lock = threading.Lock()
        """Deux drops du même objet peuvent arriver en même temps sur deux fils.
        Sans verrou, les deux téléchargeraient, et le second écraserait le
        fichier du premier pendant qu'il est peut-être en train d'être servi."""

    @property
    def root(self) -> Path:
        return self._root if self._root is not None else icons_dir()

    def local(self, item_id: int) -> Path | None:
        """Image déjà sur le disque, ou None. N'appelle jamais le réseau."""
        for extension in _EXTENSIONS:
            chemin = self.root / f"{item_id}{extension}"
            if chemin.exists():
                return chemin
        return None

    def get(self, item_id: int, remote: str) -> Path | None:
        """Image de l'objet, téléchargée au besoin. None si on n'y arrive pas.

        `remote` est le chemin donné par le catalogue. Une chaîne vide veut dire
        que la source ne connaît pas d'image, et on n'essaie même pas.
        """
        deja = self.local(item_id)
        if deja is not None:
            return deja
        if not remote:
            return None
        return self._fetch(item_id, remote)

    def preload(self, entries: Mapping[int, str] | Iterable[tuple[int, str]]) -> int:
        """Télécharge d'avance les images d'une liste d'objets.

        Pensé pour la table de butin connu, chargée au lancement dans un fil de
        fond : quand un objet tombe pendant le farm, son image est déjà là et le
        récap n'a pas de trou le temps d'un aller-retour réseau.

        Rend le nombre d'images désormais disponibles. S'arrête proprement sur
        n'importe quelle panne, sans rien propager.
        """
        paires = entries.items() if isinstance(entries, Mapping) else entries
        obtenues = 0
        for item_id, remote in paires:
            if self.get(item_id, remote) is not None:
                obtenues += 1
        _log.info("icônes disponibles : %d", obtenues)
        return obtenues

    # -- interne ---------------------------------------------------------

    def _fetch(self, item_id: int, remote: str) -> Path | None:
        extension = _extension(remote)
        if not extension:
            _log.debug("icône %s ignorée : extension inattendue (%s)", item_id, remote)
            return None

        url = urljoin(BASE_URL, remote)
        with self._lock:
            # Un autre fil a pu la télécharger pendant qu'on attendait le verrou.
            deja = self.local(item_id)
            if deja is not None:
                return deja
            octets = self._telecharger(url)
            if octets is None:
                return None
            cible = self.root / f"{item_id}{extension}"
            try:
                # Créé ici et pas à la construction : un magasin qu'on fabrique
                # sans jamais s'en servir, ce que fait toute machine sans
                # réseau, n'a aucune raison de laisser un dossier vide derrière
                # lui.
                cible.parent.mkdir(parents=True, exist_ok=True)
                temporaire = cible.with_suffix(cible.suffix + ".part")
                temporaire.write_bytes(octets)
                # Écriture atomique, et le fichier temporaire est dans le dossier
                # de destination : le remplacement n'est atomique qu'à l'intérieur
                # d'un même volume. Sans ça, une coupure laisserait un fichier
                # tronqué que `local()` prendrait pour une image valide et qui ne
                # se retéléchargerait jamais.
                temporaire.replace(cible)
            except OSError as exc:
                _log.debug("icône %s non écrite (%s)", item_id, exc)
                return None
            return cible

    def _telecharger(self, url: str) -> bytes | None:
        """Les octets de l'image, ou None. Le durcissement du reste du projet."""
        if not self._hote_autorise(url):
            return None
        http = self._session or requests.Session()
        try:
            reponse = http.get(url, timeout=TIMEOUTS, stream=True)
            if not self._hote_autorise(reponse.url):
                return None
            reponse.raise_for_status()
            morceaux: list[bytes] = []
            total = 0
            for morceau in reponse.iter_content(chunk_size=32 * 1024):
                if not morceau:
                    continue
                total += len(morceau)
                if total > MAX_BYTES:
                    _log.debug("icône refusée : plus de %d octets (%s)", MAX_BYTES, url)
                    return None
                morceaux.append(morceau)
            return b"".join(morceaux) or None
        except requests.RequestException as exc:
            # Volontairement large et volontairement muet au niveau info : la
            # source est indisponible par moments, et une image manquante ne
            # justifie pas d'alerter quelqu'un qui est en train de farmer.
            _log.debug("icône indisponible (%s) : %s", url, exc)
            return None
        finally:
            if self._session is None:
                http.close()

    @staticmethod
    def _hote_autorise(url: str) -> bool:
        analyse = urlparse(url)
        if analyse.scheme != "https" or analyse.hostname not in ALLOWED_HOSTS:
            _log.debug("icône refusée : hôte ou schéma non autorisé (%s)", url)
            return False
        return True
