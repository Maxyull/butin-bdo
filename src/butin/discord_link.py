"""Rattachement du compte Discord du joueur, par le relais.

Pourquoi Butin ne parle jamais à Discord
----------------------------------------

Échanger un code OAuth contre un jeton demande le **secret** de l'application
Discord. Butin est distribué publiquement : ce secret serait lisible par
n'importe quel joueur, et le révoquer obligerait à republier l'application.
Même raisonnement que le webhook dans `report.py`, et même réponse : tout se
passe sur `rubin.maxyull.fr`, et **cette application ne connaît aucun secret**.

Butin ne fait donc que deux choses : ouvrir le navigateur sur le relais, et lui
demander ensuite « est-ce que ce contributeur a un compte rattaché, et sous
quel nom ». Il ne voit jamais de jeton Discord, n'en stocke aucun, et ne
saurait pas quoi en faire.

⛔ Le pseudonyme affiché vient TOUJOURS du relais, jamais du joueur
------------------------------------------------------------------

C'est toute la différence entre « se connecter » et « écrire son nom ». Un
champ de saisie laisserait n'importe qui signaler un bogue sous le pseudonyme
d'un autre joueur dans un salon public. Le nom rendu ici a été lu par le relais
sur l'API de Discord, après une autorisation donnée par la personne elle-même.

Il n'y a donc **volontairement aucune fonction pour poser un nom** dans ce
module. Si un jour quelqu'un en ajoute une, il aura transformé une
authentification en déclaration, sans que rien à l'écran ne change.

⚠️ Ce que le rattachement ne protège pas
-----------------------------------------

L'identifiant anonyme du contributeur (`report.contributor_id`) **est** la clé
du rattachement : le relais signe un état qui le contient. Le connaître suffit
donc à demander un rattachement pour lui. Sa seule protection est de ne jamais
quitter la machine autrement que dans un appel HTTPS au relais — c'est écrit
ici plutôt que découvert plus tard.

⚠️ L'écran d'autorisation de Discord annonce « Rubin », pas « Butin »
---------------------------------------------------------------------

Le relais n'a qu'une seule application Discord enregistrée, celle de Rubin
(`client_id` 1534871942685921280), et c'est elle qui apparaît. Un joueur de
Butin à qui l'on demande d'autoriser *Rubin* peut légitimement hésiter, donc
l'interface le dit avant d'ouvrir le navigateur au lieu de le laisser le
découvrir. Signalé à la session rubin le 07/08/2026 dans `COORDINATION.md` :
le corriger demande une seconde application côté relais, pas ici.
"""

from __future__ import annotations

import logging
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlencode, urlparse

import requests

_log = logging.getLogger(__name__)

BASE_URL = "https://rubin.maxyull.fr/v1/discord"
LOGIN_URL = f"{BASE_URL}/connexion"
ACCOUNT_URL = f"{BASE_URL}/compte"

#: Même politique que `report.py` et `update.py` : un seul hôte, revalidé
#: après redirection.
ALLOWED_HOSTS = {"rubin.maxyull.fr"}

TIMEOUT_S = 5.0


@dataclass(frozen=True)
class Compte:
    """L'état du rattachement, tel qu'il doit s'afficher.

    `nom` est le pseudonyme Discord rendu par le relais. Il vaut `None` dès que
    `rattache` est faux, et les deux ne peuvent pas se contredire : c'est
    `depuis_reponse` qui le garantit, pas l'appelant.
    """

    rattache: bool
    nom: str | None = None
    #: Vrai quand l'état n'a pas pu être vérifié (réseau, relais muet). ⛔ Ce
    #: n'est PAS « non rattaché » : afficher « connecte-toi » à quelqu'un qui
    #: l'est déjà lui ferait refaire une autorisation pour rien, et laisserait
    #: croire que le rattachement ne tient pas.
    inconnu: bool = False


COMPTE_INCONNU = Compte(rattache=False, nom=None, inconnu=True)


def _check_host(url: str, *, stage: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError(f"{stage} : schéma non https ({parsed.scheme!r})")
    if parsed.hostname not in ALLOWED_HOSTS:
        raise ValueError(f"{stage} : hôte non autorisé ({parsed.hostname!r})")


def login_url(player: str) -> str:
    """L'adresse à ouvrir dans le navigateur pour rattacher un compte.

    `urlencode` plutôt qu'une f-string : un identifiant qui contiendrait un `&`
    ou un espace couperait la requête en deux, et le relais verrait un
    identifiant tronqué qu'il refuserait sans qu'on comprenne pourquoi.
    """
    return f"{LOGIN_URL}?{urlencode({'player': player})}"


def open_login(player: str, *, opener: Callable[[str], bool] = webbrowser.open) -> bool:
    """Ouvre le navigateur sur la page de rattachement. **Ne lève jamais.**

    Le navigateur du système, pas la fenêtre de Butin : une page d'autorisation
    affichée dans une fenêtre sans barre d'adresse est exactement ce qu'on
    apprend aux gens à ne pas remplir. Là, la personne voit `discord.com` et
    son cadenas.
    """
    try:
        _check_host(login_url(player), stage="URL de connexion")
        return bool(opener(login_url(player)))
    except (ValueError, OSError, webbrowser.Error) as exc:
        _log.warning("ouverture du navigateur impossible : %s", exc)
        return False


def fetch_account(
    player: str,
    *,
    session: requests.Session | None = None,
    timeout: float = TIMEOUT_S,
) -> Compte:
    """Demande au relais si ce contributeur a un compte rattaché.

    **Ne lève jamais.** Une panne réseau rend `COMPTE_INCONNU`, jamais « non
    rattaché » : voir le commentaire du champ `inconnu`.
    """
    try:
        _check_host(ACCOUNT_URL, stage="URL du compte")
        client = session or requests.Session()
        reponse = client.get(
            ACCOUNT_URL,
            params={"player": player},
            timeout=timeout,
            headers={"User-Agent": "butin-bdo (+https://github.com/Maxyull/butin-bdo)"},
        )
        _check_host(reponse.url, stage="URL finale après redirection")
    except (requests.RequestException, ValueError) as exc:
        _log.warning("état du rattachement Discord indisponible : %s", exc)
        return COMPTE_INCONNU

    if reponse.status_code != 200:
        # 400 = identifiant mal formé, 5xx = relais en panne. Dans les deux cas
        # on ne SAIT pas, et c'est différent de savoir que non.
        _log.warning("le relais a répondu %s pour le compte Discord", reponse.status_code)
        return COMPTE_INCONNU

    try:
        donnees = reponse.json()
    except ValueError as exc:
        _log.warning("réponse illisible du relais : %s", exc)
        return COMPTE_INCONNU

    return depuis_reponse(donnees)


def depuis_reponse(donnees: object) -> Compte:
    """Traduit la réponse du relais, en se méfiant de sa forme.

    ⛔ Un nom présent avec `rattache` faux est traité comme NON rattaché. Les
    deux champs sont indépendants dans le JSON, donc ils peuvent se
    contredire ; laisser passer un nom sans rattachement afficherait
    « Connecté en tant que … » à quelqu'un qui ne l'est pas, ce qui est
    exactement le mensonge que la connexion doit empêcher.
    """
    if not isinstance(donnees, dict):
        return COMPTE_INCONNU
    if not donnees.get("rattache"):
        return Compte(rattache=False, nom=None)

    nom = donnees.get("nom")
    if not isinstance(nom, str) or not nom.strip():
        # Rattaché mais sans nom lisible : on le dit rattaché sans inventer de
        # pseudonyme. L'interface a un repli pour ce cas.
        return Compte(rattache=True, nom=None)
    return Compte(rattache=True, nom=nom.strip())
