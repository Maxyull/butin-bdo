"""Emplacements sur disque utilisés par Butin.

Tout ce que le programme écrit vit sous les dossiers standards de l'utilisateur
(via `platformdirs`), jamais à côté de l'exécutable ni dans le dossier du jeu.
Deux raisons :

1. Une installation dans « Program Files » n'est pas inscriptible par un compte
   non administrateur. Écrire la base de sessions à côté du binaire marcherait
   en développement puis échouerait chez l'utilisateur.
2. Butin ne doit jamais écrire dans le répertoire de Black Desert. Le jeu
   surveille son propre dossier, et un fichier inconnu déposé dedans est
   exactement le genre de chose qui ressemble à une modification du client.

Le dossier des données, lui, appartient à l'utilisateur
--------------------------------------------------------

Ses sessions de farm ne sont pas un cache : ce sont **ses** données, celles
qu'il voudra sauvegarder, copier sur une autre machine ou simplement retrouver.
Les enterrer dans `%LOCALAPPDATA%` reviendrait à les cacher.

Elles vont donc par défaut dans **Documents\\BDO Butin**, et l'emplacement se
change. Le chemin choisi est retenu dans un fichier repère, lui-même rangé à
l'emplacement standard : il faut bien que quelque chose de fixe dise où est le
reste.

Sous Windows, cela donne :
    cache          : %LOCALAPPDATA%\\Butin\\Cache
    repère         : %LOCALAPPDATA%\\Butin\\emplacement.json
    données        : Documents\\BDO Butin

`BUTIN_HOME` permet de tout rediriger et **gagne sur tout le reste**, ce dont
les tests se servent pour ne jamais toucher aux vrais dossiers de
l'utilisateur.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import sys
from pathlib import Path

from platformdirs import user_cache_path, user_data_path, user_documents_path

APP_NAME = "Butin"

FOLDER_NAME = "BDO Butin"
"""Nom du dossier créé dans Documents. En clair et sans accent : c'est le nom
que l'utilisateur verra dans son explorateur, et qu'il tapera peut-être.

⚠️ Renommé depuis « BDO Tracker » le 08/08/2026. Changer cette constante SEULE
ferait disparaître l'historique de tous les joueurs : les fichiers resteraient
dans l'ancien dossier et le programme regarderait ailleurs. C'est
`migrate_ancien_dossier()` qui rend ce renommage possible, et les deux ne se
séparent pas."""

ANCIEN_FOLDER_NAME = "BDO Tracker"
"""Nom d'avant le renommage du 08/08/2026.

Gardé indéfiniment. Un joueur qui n'ouvre Butin que tous les six mois doit
retrouver ses sessions le jour où il revient, pas découvrir un historique vide
parce que la migration n'a été proposée que pendant deux versions."""

_ENV_HOME = "BUTIN_HOME"
_POINTER = "emplacement.json"

_log = logging.getLogger(__name__)


def _override() -> Path | None:
    raw = os.environ.get(_ENV_HOME)
    return Path(raw) if raw else None


def _settings_dir() -> Path:
    """Emplacement standard, qui héberge le fichier repère.

    Distinct du dossier de données : il faut un endroit **fixe** pour retenir
    où l'utilisateur a déplacé le reste, sinon on ne saurait plus le retrouver.
    """
    root = _override()
    path = root / "config" if root else user_data_path(APP_NAME, appauthor=False)
    path.mkdir(parents=True, exist_ok=True)
    return path


def pointer_path() -> Path:
    """Fichier qui retient le dossier de données choisi."""
    return _settings_dir() / _POINTER


def default_storage_root() -> Path:
    """Emplacement par défaut : Documents\\BDO Butin.

    Dans Documents et non dans les données d'application, parce que ce sont les
    sessions de farm de l'utilisateur : il voudra les sauvegarder, les copier,
    ou simplement les retrouver.
    """
    return user_documents_path() / FOLDER_NAME


def storage_root() -> Path:
    """Dossier de données effectif, sans le créer.

    Trois niveaux, dans cet ordre : la redirection d'environnement, le choix de
    l'utilisateur, puis le défaut. `BUTIN_HOME` gagne sur tout, sinon un test
    qui écrirait un repère déplacerait les vraies données de la personne.
    """
    root = _override()
    if root is not None:
        return root / "data"

    repere = pointer_path()
    if repere.exists():
        try:
            data = json.loads(repere.read_text(encoding="utf-8"))
            choisi = data.get("dossier") if isinstance(data, dict) else None
            if isinstance(choisi, str) and choisi.strip():
                return Path(choisi)
        except (OSError, json.JSONDecodeError) as exc:
            # Un repère illisible ne doit pas empêcher de démarrer : on retombe
            # sur le défaut, et l'utilisateur reverra ses données au prochain
            # choix. Refuser de lancer lui retirerait aussi le moyen de corriger.
            _log.warning("repère d'emplacement illisible (%s), retour au défaut", exc)

    # ⛔ Repli sur l'ANCIEN nom de dossier, et c'est lui la vraie garantie du
    # renommage du 08/08/2026. `migrate_ancien_dossier()` renomme au lancement,
    # mais il peut échouer : dossier ouvert dans l'explorateur, antivirus,
    # disque plein. Sans ce repli, un échec ferait regarder un dossier
    # inexistant, et l'historique du joueur disparaîtrait de son écran alors
    # qu'il est intact sur le disque.
    #
    # Le renommage est donc un CONFORT ; ceci est la garantie.
    defaut = default_storage_root()
    if not defaut.exists():
        ancien = ancien_dossier_par_defaut()
        if ancien.is_dir():
            return ancien
    return defaut


def set_storage_root(path: Path) -> Path:
    """Retient un nouveau dossier de données et le crée.

    ⚠️ Ne déplace rien et ne prend effet qu'au prochain lancement. Déplacer une
    base SQLite pendant qu'elle est ouverte est le meilleur moyen de la perdre,
    et l'appelant est justement une application qui l'a ouverte.
    """
    cible = Path(path).expanduser()
    cible.mkdir(parents=True, exist_ok=True)
    repere = pointer_path()
    repere.write_text(
        json.dumps({"dossier": str(cible)}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return cible


def migrate_legacy() -> Path | None:
    """Déplace une installation antérieure vers le dossier de données actuel.

    Les versions précédentes écrivaient dans `%LOCALAPPDATA%\\Butin`. Sans ce
    déménagement, une mise à jour ferait **disparaître l'historique** de
    l'utilisateur : les fichiers seraient toujours là, mais le programme
    regarderait ailleurs, ce qui du point de vue de la personne revient au même.

    Ne fait rien si la destination contient déjà quelque chose : écraser des
    données récentes par des anciennes serait pire que le problème résolu.
    Rend le dossier d'origine s'il y a eu déménagement, sinon None.
    """
    if _override() is not None:
        return None

    ancien = user_data_path(APP_NAME, appauthor=False)
    nouveau = storage_root()
    if ancien == nouveau or not ancien.exists():
        return None

    a_deplacer = [
        fichier
        for fichier in ("sessions.sqlite3", "calibrage.json")
        if (ancien / fichier).exists() and not (nouveau / fichier).exists()
    ]
    if not a_deplacer:
        return None

    nouveau.mkdir(parents=True, exist_ok=True)
    for fichier in a_deplacer:
        shutil.move(str(ancien / fichier), str(nouveau / fichier))
    _log.info("données déplacées de %s vers %s : %s", ancien, nouveau, ", ".join(a_deplacer))
    return ancien


def ancien_dossier_par_defaut() -> Path:
    """L'emplacement d'avant le renommage, `Documents\\BDO Tracker`."""
    return user_documents_path() / ANCIEN_FOLDER_NAME


def migrate_ancien_dossier() -> Path | None:
    """Renomme `Documents\\BDO Tracker` en `Documents\\BDO Butin`.

    ⛔ Ce n'est pas un confort, c'est ce qui rend le renommage possible. Sans
    lui, changer `FOLDER_NAME` ferait **disparaître l'historique** de tout le
    monde : les fichiers resteraient sur le disque, intacts, et le programme
    regarderait à côté. Du point de vue du joueur, c'est une perte de données.

    ⭐ On renomme le DOSSIER, on ne copie pas fichier par fichier. `sessions.sqlite3`
    a besoin de venir avec `reglages.json`, `contributeur.txt`, `calibrage.json`
    ET tout `rapports/` — journaux de lecture et captures d'inventaire compris.
    Une liste de fichiers à emporter serait fausse le jour où l'on en ajoute un,
    et personne ne s'en apercevrait avant d'en avoir besoin.

    Ne fait rien dans trois cas, et chacun a sa raison :

    - le joueur a **choisi** son dossier (fichier repère) : ce n'est pas à nous
      de renommer ce qu'il a nommé ;
    - la destination **existe déjà** : il a peut-être les deux, et fusionner
      deux historiques sans savoir lequel fait foi serait pire que ne rien
      faire ;
    - `BUTIN_HOME` est posé : c'est une redirection de test, on n'y touche pas.

    Rend l'ancien chemin s'il y a eu renommage, sinon `None`. **Ne lève jamais.**
    """
    if _override() is not None:
        return None
    if pointer_path().exists():
        # Le joueur a déplacé ses données lui-même : son choix prime.
        return None

    ancien = ancien_dossier_par_defaut()
    nouveau = default_storage_root()
    if ancien == nouveau or not ancien.is_dir():
        return None
    if nouveau.exists():
        _log.info(
            "les deux dossiers existent (%s et %s), aucun renommage : "
            "fusionner deux historiques demanderait de savoir lequel fait foi",
            ancien,
            nouveau,
        )
        return None

    try:
        nouveau.parent.mkdir(parents=True, exist_ok=True)
        ancien.rename(nouveau)
    except OSError as exc:
        # Un dossier ouvert dans l'explorateur, un antivirus, un disque plein :
        # rien de tout ça ne justifie d'empêcher Butin de démarrer. On continue
        # sur l'ancien nom, qui marche encore.
        _log.warning("dossier non renommé, on garde %s : %s", ancien, exc)
        return None

    _log.info("dossier renommé de %s vers %s", ancien, nouveau)
    return ancien


def bundled_data_dir() -> Path:
    """Dossier `data/` livré AVEC le projet : butin connu, noms vérifiés,
    valeurs au marchand. Lecture seule, jamais écrit par le programme — c'est
    une donnée du dépôt, pas un état de l'utilisateur, à ne pas confondre avec
    `data_dir()` ci-dessous.

    ⚠️ Deux dispositions coexistent, et c'est voulu. En développement (checkout
    git), ce dossier vit à la racine du dépôt, trois niveaux au-dessus de ce
    fichier. Dans une application PyInstaller figée, il n'y a plus de dépôt :
    PyInstaller aplatit tout sous `sys._MEIPASS`, à l'endroit où le script de
    construction l'a copié (voir `installeur/butin.spec`, `--add-data`).

    Sans cette distinction, une installation figée afficherait tous les objets
    sans zone de farm ni valeur au marchand, **en silence** : aucune erreur ne
    le dirait, juste un produit dégradé que personne ne remarquerait avant un
    rapport de bogue.
    """
    fige = getattr(sys, "_MEIPASS", None)
    if fige is not None:
        return Path(fige) / "data"
    return Path(__file__).resolve().parents[2] / "data"


def data_dir() -> Path:
    """Dossier des données persistantes (base de sessions, calibrage)."""
    path = storage_root()
    path.mkdir(parents=True, exist_ok=True)
    return path


def cache_dir() -> Path:
    """Dossier des données reconstructibles (catalogue, prix du marché).

    Tout ce qui est ici doit pouvoir être supprimé sans perte : le programme le
    retélécharge. Rien de ce que l'utilisateur a produit ne va dans ce dossier.
    """
    root = _override()
    path = root / "cache" if root else user_cache_path(APP_NAME, appauthor=False)
    path.mkdir(parents=True, exist_ok=True)
    return path


def catalog_path() -> Path:
    """Fichier du catalogue d'objets mis en cache."""
    return cache_dir() / "items.json"


def database_path() -> Path:
    """Base SQLite des sessions de farm."""
    return data_dir() / "sessions.sqlite3"


def settings_path() -> Path:
    """Fichier des réglages de l'utilisateur (langue, région, profil de taxe).

    Dans les données et non dans le cache : le profil de taxe décrit **son
    compte** de jeu, ce qui ne se retélécharge pas. Il suit donc le dossier de
    sessions s'il le déplace, comme le calibrage, plutôt que de rester derrière
    dans les données d'application.
    """
    return data_dir() / "reglages.json"


def calibration_path() -> Path:
    """Fichier de calibrage de la zone du chat.

    Dans les données et non dans le cache, bien qu'il soit reconstructible en
    une commande : il décrit l'écran et la disposition d'interface de la
    personne, pas quelque chose qu'on retélécharge. Le supprimer oblige à
    relancer le calibrage devant le jeu, ce qui n'est pas la même chose que
    perdre un fichier qui se répare tout seul.
    """
    return data_dir() / "calibrage.json"
