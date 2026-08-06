"""Télécharge et installe une mise à jour, en un clic.

Pourquoi ce module contredit `update.py` sans le contredire
------------------------------------------------------------

`update.py` refusait l'installation automatique, et sa raison tenait : un
`.exe` Windows **ne peut pas se réécrire pendant qu'il tourne**. C'est toujours
vrai, et ce module ne le contredit pas — il ne remplace rien lui-même. Il
télécharge un **second** programme, l'installeur Inno Setup produit par
`installeur/butin.iss`, et le lance. C'est l'installeur qui sait fermer Butin
proprement (Gestionnaire de redémarrage de Windows, `CloseApplications=force`)
et le relancer une fois les fichiers remplacés.

Demandé par Maxime le 06/08/2026 : un clic doit suffire, et le logiciel doit se
rouvrir tout seul, comme Rubin. La décision « notification seule » de #46 est
donc levée, en connaissance de cause : ce qui l'avait motivée était le
remplacement à chaud, que personne ne tente ici.

⛔ Le piège que Rubin a payé en vrai, à ne pas refaire
------------------------------------------------------

**Butin ne doit PAS se fermer après avoir lancé l'installeur.** Rubin le
faisait, et le bouton de mise à jour a cessé de relancer l'application :
fermer avant que le Gestionnaire de redémarrage ait enregistré le processus
lui retire l'objet qu'il devait rouvrir. L'installeur possède tout le cycle
fermeture-réouverture, du début à la fin. `launch_installer` rend donc la main
immédiatement, sans rien fermer et sans attendre.

Pourquoi vérifier l'empreinte avant de lancer quoi que ce soit
--------------------------------------------------------------

`requests` valide déjà le certificat TLS de GitHub, donc le fichier reçu vient
bien de là. Mais un fichier arrivé **intact** n'est pas forcément le **bon**
fichier : une construction interrompue, un octet perdu, ou une release mal
publiée produiraient un binaire corrompu qu'on s'apprête à exécuter avec les
droits de l'utilisateur. Rien n'est écrit sur le disque tant que l'empreinte
n'a pas été vérifiée en mémoire.
"""

from __future__ import annotations

import hashlib
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Final
from urllib.parse import urlparse

import requests

_log = logging.getLogger(__name__)

TIMEOUT_S: Final = 120.0
USER_AGENT: Final = "butin-bdo (+https://github.com/Maxyull/butin-bdo)"

#: Le dépôt qui porte les releases. Les noms de fichiers sont les nôtres, fixés
#: par `OutputBaseFilename` dans `installeur/butin.iss` : l'URL se construit
#: donc sans requête supplémentaire à l'API GitHub, qui a ses propres limites
#: de débit et que `update.py` interroge déjà toutes les cinq minutes.
REPO: Final = "Maxyull/butin-bdo"

#: Même politique que `update.py` et `MarketClient` : liste blanche d'hôtes,
#: revalidée après redirection. GitHub sert les fichiers de release depuis
#: `objects.githubusercontent.com`, d'où le second hôte.
ALLOWED_HOSTS: Final = frozenset(
    {"github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com"}
)

#: Un installeur pèse quelques dizaines de mégaoctets (77 Mo pour la 0.1.0).
#: Au-delà de ce plafond, c'est autre chose et on refuse plutôt que de lire.
MAX_BYTES: Final = 400 * 1024 * 1024


def installer_url(version: str) -> str:
    """L'adresse de l'installeur d'une version, sur GitHub Releases."""
    version = version.lstrip("vV")
    return (
        f"https://github.com/{REPO}/releases/download/v{version}/butin-{version}-installation.exe"
    )


def _check_host(url: str, *, stage: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError(f"{stage} : schéma non https ({parsed.scheme!r})")
    if parsed.hostname not in ALLOWED_HOSTS:
        raise ValueError(f"{stage} : hôte non autorisé ({parsed.hostname!r})")


def download_installer(
    version: str,
    destination: Path,
    *,
    session: requests.Session | None = None,
    timeout: float = TIMEOUT_S,
) -> bool:
    """Télécharge l'installeur et vérifie son empreinte avant de l'écrire.

    Rend `False` sur tout échec (réseau, empreinte absente ou différente),
    **ne lève jamais** : une mise à jour ratée doit rester une ligne d'état,
    jamais une trace qui inquiète pour rien au milieu d'une session de farm.
    """
    url = installer_url(version)
    client = session or requests.Session()
    entetes = {"User-Agent": USER_AGENT}
    try:
        _check_host(url, stage="URL demandée")
        reponse = client.get(url, headers=entetes, timeout=timeout)
        _check_host(reponse.url, stage="URL finale après redirection")
        reponse.raise_for_status()
        empreinte = client.get(f"{url}.sha256", headers=entetes, timeout=timeout)
        _check_host(empreinte.url, stage="URL finale de l'empreinte")
        empreinte.raise_for_status()
    except (requests.RequestException, ValueError) as exc:
        _log.warning("téléchargement de la mise à jour impossible : %s", exc)
        return False

    contenu = reponse.content
    if len(contenu) > MAX_BYTES:
        _log.warning("installeur de %d octets, au-delà du plafond", len(contenu))
        return False

    # Le fichier `.sha256` suit le format de `sha256sum` : l'empreinte, deux
    # espaces, le nom du fichier. Seul le premier mot compte.
    texte = empreinte.text or ""
    attendue = texte.split()[0].strip().lower() if texte.split() else ""
    reelle = hashlib.sha256(contenu).hexdigest()
    if not attendue or reelle != attendue:
        _log.warning("empreinte de l'installeur incorrecte, rien n'est écrit")
        return False

    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(contenu)
    except OSError as exc:
        _log.warning("écriture de l'installeur impossible : %s", exc)
        return False
    return True


def launch_installer(installer: Path) -> None:
    """Lance l'installeur en silence, et laisse Windows fermer puis rouvrir Butin.

    ⛔ **Ne ferme pas Butin, volontairement.** `/RESTARTAPPLICATIONS` s'appuie
    sur `CloseApplications=force` posé dans `butin.iss` : c'est l'installeur,
    via le Gestionnaire de redémarrage de Windows, qui ferme l'application et
    la relance. Se fermer avant qu'il ait enregistré le processus lui retire
    l'objet à rouvrir — le bogue exact que Rubin a trouvé en jouant.

    `/NORESTART` porte sur **Windows**, jamais sur Butin : rien ici ne
    redémarre l'ordinateur.

    Le processus est lancé détaché et la fonction rend la main tout de suite.
    """
    subprocess.Popen(  # noqa: S603
        [
            str(installer),
            "/VERYSILENT",
            "/SUPPRESSMSGBOXES",
            "/NORESTART",
            "/RESTARTAPPLICATIONS",
        ],
        close_fds=True,
    )


def install_update(
    version: str,
    *,
    session: requests.Session | None = None,
    dossier: Path | None = None,
) -> tuple[bool, str]:
    """Enchaîne téléchargement, vérification et lancement. **Ne lève jamais.**

    Rend un message écrit pour être affiché tel quel. L'installeur va dans le
    dossier temporaire du système et non dans `Documents\\BDO Tracker` : ce
    n'est pas une donnée de l'utilisateur, et Windows le nettoiera.
    """
    racine = dossier or Path(tempfile.gettempdir())
    cible = racine / f"butin-{version.lstrip('vV')}-installation.exe"

    if not download_installer(version, cible, session=session):
        return False, "Téléchargement impossible. Réessaie, ou passe par la page des versions."

    try:
        launch_installer(cible)
    except OSError as exc:
        _log.warning("lancement de l'installeur impossible : %s", exc)
        return (
            False,
            "L'installeur n'a pas pu démarrer. Lance-le à la main depuis le dossier temporaire.",
        )

    return True, "Mise à jour lancée. Butin va se fermer puis se rouvrir tout seul."
