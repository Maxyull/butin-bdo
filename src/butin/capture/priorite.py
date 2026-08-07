"""Laisser le jeu passer devant la reconnaissance.

Le problème, signalé par Maxime le 07/08/2026
----------------------------------------------

« Le jeu est pas mal ralenti quand on lance la session. » Mesuré : la
reconnaissance coûte environ 800 ms par image sur une zone de 600x500, et elle
tourne toutes les deux secondes pendant toute la session. Sur cette machine,
`onnxruntime` est configuré à `intra_op_num_threads: -1`, c'est-à-dire **tous
les cœurs** — seize ici.

⛔ La piste évidente est mesurée et REFUSÉE
-------------------------------------------

Borner `onnxruntime` à 4 cœurs est même légèrement plus rapide (793 ms contre
845, la sur-souscription coûtant plus qu'elle ne rapporte). Mais comparé sur
cinq vraies images de la rafale du banc, avec un double passage pour distinguer
le bruit, ça **perd des lignes de butin** :

    image 050  PERDUE : [Poudre spirituelle du clair de lune].(01:45)
    image 150  PERDUE : [Poudre spirituelle du clair delune]x15(01:45)

Deux lignes sur 235, dont une qui vaut quinze unités. Le calcul en virgule
flottante d'onnxruntime dépend du découpage en threads, donc la détection
change. Gagner du confort en perdant des drops est exactement ce que la
section 1 du CLAUDE.md refuse.

⭐ Ce que fait ce module à la place
-----------------------------------

Il **ne change aucun calcul**, seulement l'ordre de passage. Le fil de capture
demande une priorité plus basse : quand le jeu et la reconnaissance veulent le
processeur en même temps, l'ordonnanceur sert le jeu d'abord. Les mêmes images
sont lues, les mêmes lignes en sortent, octet pour octet.

⚠️ Ce n'est pas une garantie de fluidité, c'est une préférence donnée à
l'ordonnanceur. Sur une machine sans cœur libre, la reconnaissance sera
simplement plus lente — ce qui est le bon sens du compromis : mieux vaut lire
un peu moins souvent que jouer mal.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

_log = logging.getLogger(__name__)

#: Constante Windows. `THREAD_PRIORITY_BELOW_NORMAL` vaut -1, un cran sous la
#: normale. ⚠️ Volontairement pas `THREAD_PRIORITY_LOWEST` (-2) ni `IDLE`
#: (-15) : sur une machine chargée, un fil en priorité minimale peut ne plus
#: être servi du tout, et un compteur qui s'arrête de compter est le mode de
#: défaillance que ce projet refuse le plus.
BELOW_NORMAL = -1

#: Ce que rend `GetThreadPriority` quand il échoue. C'est `0x7FFFFFFF`, et non
#: une priorité : sans ce test, un échec se lisait comme « priorité très haute ».
PRIORITE_ERREUR = 0x7FFFFFFF


def _est_windows() -> bool:
    """Vrai sous Windows, lu à CHAQUE appel.

    ⚠️ Une fonction, et pas un `sys.platform != "win32"` écrit sur place. mypy
    traite les comparaisons sur `sys.platform` comme des constantes de la
    plateforme où il tourne : l'intégration continue est sous Linux, donc tout
    ce qui suit le test y était déclaré **inatteignable** et le job échouait.
    Cousin du `python_version` figé dans mypy, déjà consigné dans le CLAUDE.md.

    ⚠️ Une fonction et pas une constante de module non plus : les tests
    remplacent `sys.platform` pour vérifier le chemin non-Windows, ce qu'une
    valeur calculée à l'import ne verrait jamais.
    """
    return sys.platform == "win32"


def _kernel32() -> Any:
    """`kernel32` avec ses signatures DÉCLARÉES, ou `None`.

    ⛔ Les `argtypes` et `restype` ne sont pas de la coquetterie. `GetCurrentThread`
    rend un **pseudo-handle** (`(HANDLE)-2`) ; sans `restype`, ctypes le ramène à
    un entier 32 bits, et `SetThreadPriority` reçoit un handle invalide. Mesuré
    le 07/08/2026 : la fonction rendait `False` et la priorité ne changeait
    jamais. Le module aurait été livré en ne faisant **rien**, sans que rien ne
    le dise.
    """
    if not _est_windows():
        return None
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.windll.kernel32
    kernel32.GetCurrentThread.restype = wintypes.HANDLE
    kernel32.GetCurrentThread.argtypes = []
    kernel32.SetThreadPriority.restype = wintypes.BOOL
    kernel32.SetThreadPriority.argtypes = [wintypes.HANDLE, ctypes.c_int]
    kernel32.GetThreadPriority.restype = ctypes.c_int
    kernel32.GetThreadPriority.argtypes = [wintypes.HANDLE]
    return kernel32


def abaisser_le_fil_courant() -> bool:
    """Demande une priorité plus basse pour le fil qui appelle. **Ne lève jamais.**

    Rend `True` si le système a accepté. Un `False` n'est pas une panne : la
    capture tourne exactement pareil, elle est juste servie comme avant.
    Personne ne doit s'arrêter parce qu'un confort n'a pas pu être appliqué.
    """
    if not _est_windows():
        # Butin est distribué pour Windows uniquement. Ailleurs (la CI tourne
        # sous Linux), on ne fait rien plutôt que d'inventer un équivalent qui
        # ne serait jamais exercé en vrai.
        return False

    try:
        kernel32 = _kernel32()
        if kernel32 is None:
            return False
        return bool(kernel32.SetThreadPriority(kernel32.GetCurrentThread(), BELOW_NORMAL))
    except (OSError, AttributeError, ValueError) as exc:
        _log.warning("priorité du fil de capture inchangée : %s", exc)
        return False


def priorite_du_fil_courant() -> int | None:
    """La priorité du fil appelant, ou `None` si on ne peut pas la lire.

    Sert aux tests et au diagnostic : sans elle, « on a demandé » et « ça a été
    appliqué » seraient indiscernables, ce qui est précisément la confusion qui
    a rendu la protection de branche GitHub inutile pendant une journée.
    """
    try:
        kernel32 = _kernel32()
        if kernel32 is None:
            return None
        valeur = int(kernel32.GetThreadPriority(kernel32.GetCurrentThread()))
    except (OSError, AttributeError, ValueError):
        return None
    return None if valeur == PRIORITE_ERREUR else valeur
