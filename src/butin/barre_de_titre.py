"""Passer la barre de titre de la fenêtre en sombre.

Le problème, signalé par Maxime le 09/08/2026
----------------------------------------------

« bar en blan aussi bien moche », capture à l'appui : une barre de titre claire
posée au-dessus d'une page entièrement sombre. Windows la dessine lui-même, et
la feuille de style de la page ne l'atteint pas — pas plus que `color-scheme`,
qui ne vaut que pour ce que le moteur web dessine.

⭐ Mesuré avant d'être écrit
-----------------------------

Sur une vraie fenêtre de cette machine, luminance moyenne de la bande de titre
photographiée à l'écran :

    avant           245,2 sur 255
    attribut 20      11,0 sur 255

C'est l'attribut `DWMWA_USE_IMMERSIVE_DARK_MODE`. Il vaut **20** depuis la
version 20H1 de Windows 10 ; il valait **19** sur les versions antérieures, où
il était non documenté. Les deux sont essayés, dans cet ordre.

⚠️ Ce que ce module ne peut pas faire
--------------------------------------

**Se relire.** Contrairement à `souris` et `transparence`, il n'y a pas de
lecture fiable de cet attribut : `DwmGetWindowAttribute` le refuse. On rend
donc ce que le système a **répondu** (`S_OK`), et rien de plus — ce n'est pas
la même chose qu'une vérification, et c'est écrit ici pour que personne ne
prenne l'un pour l'autre. La preuve visuelle est la photo ci-dessus.

⚠️ Un redessin est nécessaire
------------------------------

Poser l'attribut ne repeint pas la fenêtre déjà affichée : sans un
`SetWindowPos` qui annonce un changement de cadre, la barre reste claire
jusqu'au prochain déplacement. Trouvé en mesurant, pas en lisant la
documentation.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

_log = logging.getLogger(__name__)

#: `DWMWA_USE_IMMERSIVE_DARK_MODE`, dans les deux numérotations qu'il a eues.
#: La récente d'abord : une valeur inconnue est simplement refusée, donc
#: essayer coûte un appel et jamais un mauvais réglage.
ATTRIBUTS_SOMBRES = (20, 19)

S_OK = 0

#: `SWP_FRAMECHANGED | SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER` : « recalcule ton
#: cadre, ne bouge rien d'autre ».
REDESSIN = 0x0020 | 0x0002 | 0x0001 | 0x0004


def _est_windows() -> bool:
    """Vrai sous Windows, lu à CHAQUE appel. Même raison que dans
    `butin.souris` : mypy fige `sys.platform` sur la plateforme où il tourne, et
    l'intégration continue est sous Linux."""
    return sys.platform == "win32"


def _api() -> tuple[Any, Any] | None:
    """`dwmapi` et `user32`, signatures déclarées, ou `None`.

    ⛔ `argtypes` obligatoire, même raison que partout ici : `HWND` est un
    pointeur, et sans déclaration ctypes le tronque à 32 bits sur un système
    64 bits. L'appel rendrait alors une erreur sur une fenêtre parfaitement
    valide.
    """
    if not _est_windows():
        return None
    import ctypes
    from ctypes import wintypes

    # `getattr` et non `ctypes.windll` : `windll` n'existe pas dans les stubs
    # hors Windows. Voir `butin.souris`.
    dwmapi = getattr(ctypes, "windll").dwmapi  # noqa: B009
    user32 = getattr(ctypes, "windll").user32  # noqa: B009
    dwmapi.DwmSetWindowAttribute.restype = ctypes.c_long
    dwmapi.DwmSetWindowAttribute.argtypes = [
        wintypes.HWND,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    user32.SetWindowPos.restype = wintypes.BOOL
    user32.SetWindowPos.argtypes = [
        wintypes.HWND,
        wintypes.HWND,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_uint,
    ]
    return dwmapi, user32


def rendre_sombre(fenetre: int) -> bool:
    """Demande une barre de titre sombre. **Ne lève jamais.**

    Rend `True` si le système a **accepté** l'appel. ⚠️ Accepté n'est pas
    vérifié : voir l'en-tête du module, cet attribut ne se relit pas. Un
    `False` ne coûte qu'une barre claire, rien de ce que fait le logiciel n'en
    dépend.
    """
    api = _api()
    if api is None or not fenetre:
        return False
    dwmapi, user32 = api
    import ctypes

    for attribut in ATTRIBUTS_SOMBRES:
        try:
            actif = ctypes.c_int(1)
            code = int(
                dwmapi.DwmSetWindowAttribute(
                    fenetre, attribut, ctypes.byref(actif), ctypes.sizeof(actif)
                )
            )
        except (OSError, AttributeError, ValueError) as exc:
            _log.debug("barre de titre inchangée : %s", exc)
            return False
        if code == S_OK:
            # ⚠️ Sans ce redessin, la fenêtre déjà affichée garde sa barre
            # claire jusqu'au prochain déplacement. Mesuré, pas lu.
            try:
                user32.SetWindowPos(fenetre, 0, 0, 0, 0, 0, REDESSIN)
            except (OSError, AttributeError, ValueError) as exc:
                _log.debug("barre de titre non redessinée : %s", exc)
            return True
    return False
