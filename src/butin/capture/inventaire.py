"""Garder une image de l'inventaire, pour pouvoir contredire le compteur.

Pourquoi une image, et pas une lecture
---------------------------------------

⭐ L'inventaire est la **seule** vérité de ce logiciel qui ne passe par aucune
reconnaissance d'écran. Le compteur et le banc d'essai lisent les mêmes pixels
avec le même moteur : ils peuvent se tromper ensemble, et seul un inventaire
compté à la main peut les contredire tous les deux.

Jusqu'ici, cette vérité n'existait que dans la tête du joueur, recopiée à la
main dans le bouton « Écart ». Une session finie sans ce geste était perdue
pour toujours : l'inventaire, lui, continue de bouger.

Ce module ne fait donc qu'une chose, et il la fait bien : **il fige l'image**.

⛔ Ce qu'il ne fait PAS, et pourquoi
-------------------------------------

**Il ne lit pas la grille.** Reconnaître quel objet occupe quelle case demande
de reconnaître les icônes. C'est faisable — `catalog/icons.py` télécharge déjà
les vraies icônes du jeu, donc la recherche se limite aux quelques objets que
la session a comptés — mais ça se met au point contre de **vraies** captures
d'inventaire, et il n'en existe aucune sur disque tant que ce module n'a pas
tourné. C'est la marche suivante, pas celle-ci.

⛔ **Il ne touche jamais au jeu.** Pas de frappe clavier dans la barre de
recherche du jeu, pas de clic, rien. Injecter des entrées dans un client de
Black Desert est sanctionné par un bannissement, et aucun confort ne vaut le
compte de quelqu'un.

⛔ **Il n'envoie rien.** L'image part avec l'archive de diagnostic si le joueur
la dépose, et pas autrement. Une capture d'écran entier montre bien plus qu'un
inventaire : le nom du personnage, la position, ce qui traîne à l'écran.

⚠️ La capture ne peut pas deviner
----------------------------------

Elle prend l'écran tel qu'il est. Si l'inventaire n'est pas ouvert, l'image ne
contiendra pas d'inventaire, et c'est écrit à l'écran avant de cliquer plutôt
que découvert après coup en ouvrant le fichier.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ..diagnostic import dossier_des_rapports

_log = logging.getLogger(__name__)

#: Préfixe des captures d'inventaire, à côté des journaux de session.
#: Le même dossier que tout le reste du diagnostic : le joueur n'a qu'un seul
#: endroit à connaître, et l'archive n'a qu'un seul endroit à balayer.
PREFIXE = "inventaire"


@dataclass(frozen=True)
class Capture:
    """Ce que l'interface doit afficher après la capture."""

    chemin: Path | None
    octets: int
    message: str

    @property
    def reussie(self) -> bool:
        return self.chemin is not None


Moment = Literal["avant", "apres"]
"""Les deux bouts d'une session, et il en faut **deux**.

⛔ Il n'y en avait qu'un jusqu'au 08/08/2026, et c'est ce qui a rendu la seule
mesure sans OCR de ce logiciel **inutilisable**. Une capture par session, la
seconde écrasant la première : impossible de tenir un avant ET un après.

Le 08/08, faute de mieux, une session a été mesurée en prenant comme « avant »
la capture de la session PRÉCÉDENTE, à une heure quarante-deux d'écart. Le
verdict annoncé était un sur-comptage de **×4,7**. Le vrai, une fois le bon
point de départ connu, est de **+2,6 %**. Deux ordres de grandeur, et une
conclusion fausse annoncée avec assurance.

Comparer deux sessions n'est pas une mesure. Il faut les deux bouts de la même.
"""


def chemin_pour(
    session_id: int, racine: Path | None = None, *, moment: Moment | None = None
) -> Path:
    """Où vit la capture d'un bout de session.

    Sans `moment`, l'ancien nom : c'est celui des captures déjà sur le disque
    des joueurs, et `captures_existantes` doit continuer à les trouver. Une
    version qui cesserait de voir les fichiers d'avant les perdrait pour
    l'archive sans rien dire.

    Avec `moment`, un fichier par bout. Recapturer le MÊME bout remplace :
    quelqu'un qui range son sac puis recommence corrige son geste, il n'en
    ajoute pas un troisième dont personne ne saurait lequel fait foi.

    ⚠️ `moment` est **après** `racine` et réservé au mot-clé, ce qui n'est pas
    un détail de style : la première version l'avait glissé en deuxième
    position, et tous les appels existants passaient `racine` là. Ils
    écrivaient donc dans un fichier dont le nom contenait un chemin. Attrapé
    par les tests, jamais par la relecture.
    """
    suffixe = f"-{moment}" if moment else ""
    return dossier_des_rapports(racine) / f"{PREFIXE}-{session_id:04d}{suffixe}.png"


DELAI_S = 6.0
"""Secondes entre le clic et la capture.

⛔ Sans ce délai, la fonctionnalité ne pouvait PAS marcher, et c'est une faute
de conception que personne n'a vue avant que Maxime n'essaie.

Pour cliquer sur le bouton, la fenêtre de Butin doit être au premier plan — et
elle recouvre le jeu. La capture prenait donc **Butin devant l'inventaire**.
Ma propre capture de test du 08/08/2026 le montrait déjà, jeu visible et
inventaire fermé, et j'en avais tiré « il faudra penser à l'ouvrir » au lieu de
« le geste demandé est impossible ».

Six secondes : le temps de basculer sur le jeu et d'ouvrir l'inventaire sans se
presser. Plus court oblige à courir, plus long donne envie de faire autre chose
en attendant.
"""


def capturer(
    session_id: int,
    *,
    moment: Moment | None = None,
    racine: Path | None = None,
    monitor: int = 1,
    delai_s: float = DELAI_S,
    dormir: Callable[[float], None] = time.sleep,
) -> Capture:
    """Enregistre l'écran entier dans le dossier des rapports. **Ne lève jamais.**

    Attend `delai_s` AVANT de capturer, pour laisser le temps de revenir au jeu
    et d'ouvrir l'inventaire. Voir `DELAI_S`.

    Même garantie que partout ailleurs : c'est un confort de diagnostic, il ne
    doit pas pouvoir interrompre quoi que ce soit. Une machine sans écran, un
    pilote graphique fâché, un disque plein descendent en message affichable.
    """
    destination = chemin_pour(session_id, racine, moment=moment)
    if delai_s > 0:
        dormir(delai_s)
    try:
        from PIL import Image

        from .screen import ScreenCapture

        with ScreenCapture(monitor=monitor) as capture:
            ecran = capture.target_monitor()
            # ⚠️ On passe par mss directement plutôt que par `grab`, qui rend
            # du niveau de gris. Les icônes d'objets se distinguent surtout par
            # leur COULEUR : les aplatir maintenant rendrait la lecture
            # automatique de la grille beaucoup plus difficile plus tard, pour
            # une place disque qu'on a.
            brut = capture._require_session().grab(ecran.to_mss())
            image = Image.frombytes("RGB", brut.size, brut.bgra, "raw", "BGRX")

        destination.parent.mkdir(parents=True, exist_ok=True)
        image.save(destination, format="PNG", optimize=True)
    except Exception as exc:
        # Volontairement large : mss, PIL et le système de fichiers lèvent
        # chacun leur propre famille, et aucune ne justifie d'interrompre le
        # joueur qui vient de finir sa session.
        _log.warning("capture d'inventaire impossible : %s", exc)
        return Capture(None, 0, f"Capture impossible : {exc}")

    try:
        octets = destination.stat().st_size
    except OSError:
        octets = 0
    return Capture(
        destination,
        octets,
        f"Inventaire enregistré ({max(octets // 1024, 1)} Ko). "
        "Il part avec l'archive de diagnostic.",
    )


def captures_existantes(racine: Path | None = None) -> list[Path]:
    """Les captures d'inventaire, de la plus récente à la plus ancienne.

    Sert à `bundle.py` : sans ça, l'image serait écrite sur le disque et
    n'atteindrait jamais personne, ce qui est le sort de tout diagnostic qu'on
    range sans le joindre.
    """
    dossier = dossier_des_rapports(racine)
    if not dossier.is_dir():
        return []
    fichiers = [f for f in dossier.glob(f"{PREFIXE}-*.png") if f.is_file()]
    fichiers.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    return fichiers
