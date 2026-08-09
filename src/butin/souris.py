"""Laisser la souris passer à travers le panneau posé sur le jeu.

Le problème, signalé par Maxime le 09/08/2026
----------------------------------------------

« Le panneau qui se met sur l'écran de jeu interfère avec la souris : je passe
dessus et ça affiche la souris, c'est chiant. »

Black Desert cache le curseur pendant qu'on joue. Une fenêtre posée par-dessus
le récupère dès que le pointeur la survole : Windows redessine la flèche, le jeu
perd le survol, et ça se produit en plein combat sans qu'on ait rien demandé.

Ce que fait ce module
----------------------

Il pose `WS_EX_TRANSPARENT` sur la fenêtre du panneau. Le test de collision de
Windows saute alors cette fenêtre : le pointeur, les clics et le survol vont à
ce qu'il y a **dessous**, c'est-à-dire au jeu. Rien d'autre ne change, le
panneau continue de s'afficher et de se rafraîchir exactement pareil.

⭐ Mesuré avant d'être écrit, le 09/08/2026, sur cette machine et sur le vrai
jeu : `WindowFromPoint` au centre du panneau rendait
`Chrome_RenderWidgetHostHWND` (le panneau) avant, et
`BlackDesertWindowClass` — la fenêtre de Black Desert elle-même — après.

⛔ Ce que ça coûte, et c'est le prix décidé par Maxime
-------------------------------------------------------

Une fenêtre que la souris traverse ne reçoit plus **aucun** clic : les boutons
Recalibrer, Pause et Arrêter du panneau deviennent inertes, et on ne peut plus
le déplacer à la souris. Tout se pilote alors depuis la fenêtre principale.

C'est réversible : le réglage « le panneau laisse passer la souris » vit dans
l'onglet Réglages, et le panneau redevient cliquable dès qu'on le décoche. Le
panneau le dit lui-même à l'écran, parce qu'un bouton qui ne répond pas se lit
comme un logiciel cassé.

⚠️ `WS_EX_LAYERED` est posé, jamais retiré
-------------------------------------------

Il est ajouté avec `WS_EX_TRANSPARENT`, mais on ne l'enlève pas en repassant en
mode cliquable : c'est lui qui porte **aussi** la couleur-clé qui rend le fond
du panneau transparent par-dessus le jeu. Le retirer rendrait le panneau opaque
en même temps qu'il redeviendrait cliquable, et personne ne ferait le lien.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

_log = logging.getLogger(__name__)

#: Index du champ des styles étendus dans les données d'une fenêtre.
GWL_EXSTYLE = -20

#: La fenêtre est composée à part. Nécessaire pour que le style suivant soit
#: pris en compte, et déjà nécessaire à la transparence du fond.
WS_EX_LAYERED = 0x00080000

#: Le test de collision saute cette fenêtre : la souris va à ce qui est dessous.
WS_EX_TRANSPARENT = 0x00000020


def _est_windows() -> bool:
    """Vrai sous Windows, lu à CHAQUE appel.

    ⚠️ Une fonction, et pas un `sys.platform != "win32"` écrit sur place : mypy
    traite les comparaisons sur `sys.platform` comme des constantes de la
    plateforme où il tourne, et l'intégration continue est sous Linux. Tout ce
    qui suivrait y serait déclaré inatteignable. Même raison, et même piège
    déjà payé, que dans `capture/priorite.py`.
    """
    return sys.platform == "win32"


def _user32() -> Any:
    """`user32` avec ses signatures DÉCLARÉES, ou `None`.

    ⛔ Les `argtypes` ne sont pas de la coquetterie ici non plus. Un `HWND` est
    un pointeur : sans déclaration, ctypes le ramène à un entier 32 bits, et
    sur un système 64 bits la poignée arrive tronquée. La fonction rendrait
    alors « échec » sans rien dire, exactement comme le pseudo-handle tronqué
    de `capture/priorite.py` qui avait livré un module ne faisant **rien**.
    """
    if not _est_windows():
        return None
    import ctypes
    from ctypes import wintypes

    # ⚠️ `getattr` et non `ctypes.windll` : `windll` n'existe pas dans les stubs
    # hors Windows, et aucun commentaire d'ignorance ne satisfait à la fois mypy
    # sous Linux et mypy sous Windows. Voir `capture/priorite.py`.
    user32 = getattr(ctypes, "windll").user32  # noqa: B009
    user32.FindWindowW.restype = wintypes.HWND
    user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    user32.GetWindowLongW.restype = ctypes.c_long
    user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.SetWindowLongW.restype = ctypes.c_long
    user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
    return user32


def fenetre_par_titre(titre: str) -> int | None:
    """La poignée de la fenêtre qui porte ce titre exact, ou `None`.

    ⚠️ Par le titre, et pas par ce que pywebview expose : `Window.native` est un
    formulaire .NET dont l'accès dépend de la version de la bibliothèque et de
    la présence de pythonnet. Le titre, lui, est posé par nous
    (`Overlay.open`), et Windows sait le retrouver sans intermédiaire.
    """
    try:
        user32 = _user32()
        if user32 is None:
            return None
        fenetre = user32.FindWindowW(None, titre)
    except (OSError, AttributeError, ValueError) as exc:
        _log.debug("fenêtre « %s » introuvable : %s", titre, exc)
        return None
    return int(fenetre) if fenetre else None


def laisser_passer_la_souris(fenetre: int, actif: bool) -> bool:
    """Fait traverser (ou non) la souris. **Ne lève jamais.**

    Rend `True` si le style demandé est en place après l'appel. Un `False`
    n'arrête rien : le panneau reste affiché et la capture continue à
    l'identique, la souris est simplement captée comme avant.
    """
    try:
        user32 = _user32()
        if user32 is None or not fenetre:
            return False
        actuel = int(user32.GetWindowLongW(fenetre, GWL_EXSTYLE))
        # ⚠️ `WS_EX_LAYERED` n'est jamais retiré : il porte aussi la
        # transparence du fond. Voir l'en-tête du module.
        vise = actuel | WS_EX_LAYERED | WS_EX_TRANSPARENT if actif else actuel & ~WS_EX_TRANSPARENT
        if vise != actuel:
            user32.SetWindowLongW(fenetre, GWL_EXSTYLE, vise)
    except (OSError, AttributeError, ValueError) as exc:
        _log.warning("souris traversante non appliquée : %s", exc)
        return False
    # ⛔ On relit au lieu de croire ce qu'on vient de poser. « On a demandé » et
    # « c'est appliqué » sont deux choses différentes, et les confondre a déjà
    # coûté une journée sur ce projet (protection de branche GitHub, priorité
    # du fil de capture).
    return traverse_la_souris(fenetre) is actif


def traverse_la_souris(fenetre: int) -> bool | None:
    """Est-ce que la souris traverse cette fenêtre ? `None` si on ne sait pas.

    Sert au diagnostic et aux tests : sans lecture, un réglage appliqué et un
    réglage ignoré sont indiscernables.
    """
    try:
        user32 = _user32()
        if user32 is None or not fenetre:
            return None
        style = int(user32.GetWindowLongW(fenetre, GWL_EXSTYLE))
    except (OSError, AttributeError, ValueError):
        return None
    return bool(style & WS_EX_TRANSPARENT)
