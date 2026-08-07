"""Retrouver les fenêtres là où on les avait laissées.

Le cas qui a motivé ça
-----------------------

Une mise à jour ferme Butin et le rouvre. Le panneau en surimpression, lui, a
été placé **à la main**, par-dessus le jeu, à l'endroit précis où il ne gêne
pas. Le rouvrir au centre de l'écran oblige à le replacer à chaque version, et
la mise à jour en un clic devient une corvée en deux gestes.

⛔ Pourquoi ça ne peut PAS s'enregistrer seulement à la fermeture
------------------------------------------------------------------

C'est le piège de ce module, et il est propre à notre cas. `butin.iss` pose
`CloseApplications=force` : c'est le Gestionnaire de redémarrage de Windows qui
ferme l'application pendant l'installation, et rien ne garantit qu'un code de
fermeture propre s'exécute.

Autrement dit, **le seul moment où l'on veut se souvenir de la position est
précisément celui où la fermeture n'est pas polie.** La position est donc
enregistrée en continu pendant que la fenêtre vit, pas au revoir.

⛔ Pourquoi une position enregistrée ne se restaure pas les yeux fermés
------------------------------------------------------------------------

Un deuxième écran débranché, une résolution changée, un portable rebranché
ailleurs : la position d'hier peut tomber hors de tout écran. Restaurer
aveuglément ouvrirait la fenêtre **invisible**, et de l'extérieur ça ressemble
exactement à un logiciel qui ne démarre plus.

`position_valable` vérifie donc qu'un coin manipulable de la fenêtre tombe sur
un écran réel. Dans le doute, on repart du défaut : une fenêtre au mauvais
endroit se déplace en une seconde, une fenêtre invisible se désinstalle.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from . import paths

_log = logging.getLogger(__name__)

FICHIER = "fenetres.json"
"""À côté des réglages, mais dans son PROPRE fichier.

Ce n'est pas une préférence que l'utilisateur choisit, c'est une trace de ce
qu'il a fait. Les mêler ferait perdre la position à chaque fois qu'un fichier
de réglages illisible retombe sur les défauts, ce que `store/settings.py` fait
exprès."""

#: Marge, depuis le coin haut gauche, du point qui doit tomber sur un écran.
#: Elle vise la zone qu'on attrape pour déplacer une fenêtre : si CE point est
#: visible, la fenêtre est récupérable même mal placée.
MARGE_X = 60
MARGE_Y = 20


@dataclass(frozen=True)
class Position:
    x: int
    y: int

    def to_dict(self) -> dict[str, int]:
        return {"x": self.x, "y": self.y}


def chemin(racine: Path | None = None) -> Path:
    return (racine or paths.storage_root()) / FICHIER


def charger(racine: Path | None = None) -> dict[str, Position]:
    """Les positions retenues, par nom de fenêtre. **Ne lève jamais.**

    Un fichier absent, illisible ou incohérent rend un dictionnaire vide : les
    fenêtres s'ouvrent alors où elles s'ouvraient avant ce module, ce qui est
    exactement le bon repli.
    """
    source = chemin(racine)
    try:
        donnees = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        _log.debug("positions de fenêtres non relues : %s", exc)
        return {}

    if not isinstance(donnees, dict):
        return {}
    positions: dict[str, Position] = {}
    for nom, valeur in donnees.items():
        if not isinstance(valeur, dict):
            continue
        try:
            positions[str(nom)] = Position(int(valeur["x"]), int(valeur["y"]))
        except (KeyError, TypeError, ValueError):
            # Une entrée abîmée n'invalide pas les autres : perdre la position
            # du panneau parce que celle de la fenêtre principale est cassée
            # serait gratuit.
            continue
    return positions


def enregistrer(nom: str, position: Position, racine: Path | None = None) -> bool:
    """Écrit la position d'une fenêtre. **Ne lève jamais.**

    Relit l'existant pour ne pas effacer l'autre fenêtre : les deux écrivent
    dans le même fichier, à quelques secondes d'écart.
    """
    destination = chemin(racine)
    positions = charger(racine)
    positions[nom] = position
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps({n: p.to_dict() for n, p in positions.items()}, indent=2),
            encoding="utf-8",
        )
    except OSError as exc:
        _log.debug("position de fenêtre non enregistrée : %s", exc)
        return False
    return True


def position_valable(position: Position, ecrans: list[tuple[int, int, int, int]]) -> bool:
    """Vrai si un coin manipulable de la fenêtre tombe sur un écran réel.

    ⛔ Le garde-fou de tout le module. Un écran débranché ou une résolution
    changée peut placer la position d'hier hors de tout affichage : restaurer
    aveuglément ouvrirait la fenêtre **invisible**, ce qui ressemble de
    l'extérieur à un logiciel qui ne démarre plus.

    `ecrans` est une liste de `(gauche, haut, largeur, hauteur)` en coordonnées
    absolues du bureau — ce que rend `ScreenCapture.monitors()`.
    """
    if not ecrans:
        # On ne sait pas où sont les écrans : on ne restaure pas. Le défaut est
        # toujours visible, la position d'hier ne l'est peut-être plus.
        return False
    poignee_x = position.x + MARGE_X
    poignee_y = position.y + MARGE_Y
    return any(
        gauche <= poignee_x < gauche + largeur and haut <= poignee_y < haut + hauteur
        for gauche, haut, largeur, hauteur in ecrans
    )


def ecrans_du_bureau() -> list[tuple[int, int, int, int]]:
    """Les rectangles des écrans, ou une liste vide. **Ne lève jamais.**

    Vide veut dire « on ne sait pas », et `position_valable` refuse alors de
    restaurer plutôt que de parier.
    """
    try:
        from .capture.screen import ScreenCapture

        with ScreenCapture() as capture:
            return [(e.left, e.top, e.width, e.height) for e in capture.monitors()]
    except Exception as exc:
        _log.debug("écrans non listés : %s", exc)
        return []


def position_a_restaurer(nom: str, racine: Path | None = None) -> Position | None:
    """La position à réutiliser pour cette fenêtre, ou `None`.

    `None` veut dire « ouvre-la où tu veux », et c'est toujours une réponse
    acceptable.
    """
    position = charger(racine).get(nom)
    if position is None:
        return None
    if not position_valable(position, ecrans_du_bureau()):
        _log.info("position enregistrée hors écran, on repart du défaut : %s", position)
        return None
    return position
