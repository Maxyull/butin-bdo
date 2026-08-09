"""Rendre le fond du panneau vraiment transparent par-dessus le jeu.

⛔ Ce que la mesure a montré, le 09/08/2026
--------------------------------------------

Le panneau se déclare transparent depuis toujours (`transparent=True`), et
`overlay.html` s'ouvre sur un commentaire disant que c'est « la seule raison
d'être de cette page ». **Ça n'a jamais marché sous Windows.**

Photographié par-dessus le vrai jeu : sous la boîte du récap, un **aplat clair**
recouvre le décor. C'est le « blanc très moche » signalé par Maxime.

La cause est dans pywebview : avec `transparent=True`, il pose bien
`DefaultBackgroundColor = Transparent` sur la vue web, mais il ne touche
**jamais** au fond du formulaire qui la porte. La vue devient donc transparente
sur… la couleur par défaut d'un formulaire Windows, un gris très clair. On
voyait le fond du cadre, pas le jeu.

⭐ Ce que fait ce module
------------------------

Il pose une **couleur-clé** sur le formulaire : ce fond-là devient un trou, et
le jeu apparaît au travers. Rephotographié après : le décor et l'interface du
jeu sont visibles sous la boîte du récap.

⚠️ Magenta, et ce n'est pas un caprice : la couleur-clé fait disparaître
**tout** pixel qui porte exactement cette valeur, y compris dans la page. La
palette de Butin est faite d'ors, d'ardoises et de gris ; le magenta pur n'y
apparaît nulle part, et n'a aucune chance d'y entrer par accident.

⛔ L'ORDRE EST CONTRAINT, et c'est mesuré
------------------------------------------

Poser la couleur-clé **efface** `WS_EX_TRANSPARENT`, le style qui laisse passer
la souris. Mesuré à la poignée près, sur la même fenêtre :

    souris traversante   style=0x000d0028  traverse=True
    apres la couleur-cle style=0x000d0008  traverse=False

La transparence se pose donc **avant** la souris, jamais après. Dans l'autre
sens, le panneau redeviendrait capteur de souris sans que rien ne le dise —
et le réglage afficherait toujours « coché ». Voir `app.Overlay`.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

_log = logging.getLogger(__name__)

CLE = (255, 0, 255)
"""Le magenta pur, la couleur qui devient un trou. Voir l'en-tête du module
pour la raison du choix."""


def _est_windows() -> bool:
    """Vrai sous Windows, lu à CHAQUE appel. Même raison que dans
    `butin.souris` : mypy fige `sys.platform` sur la plateforme où il tourne, et
    l'intégration continue est sous Linux."""
    return sys.platform == "win32"


def _formulaire(fenetre: Any) -> Any:
    """Le formulaire .NET derrière une fenêtre pywebview, ou `None`.

    ⚠️ `native` n'est renseigné qu'une fois la fenêtre créée par la couche
    graphique, ce qui arrive **après** `create_window`. Un `None` ici n'est donc
    pas une panne, c'est « pas encore » : l'appelant réessaie.
    """
    return getattr(fenetre, "native", None)


def fond_transparent(fenetre: Any) -> bool | None:
    """La couleur-clé est-elle en place ? `None` si on ne peut pas savoir.

    Lire au lieu de croire, comme partout ailleurs ici : sans cette question, un
    fond posé et un fond ignoré donneraient exactement le même code de retour.
    """
    forme = _formulaire(fenetre)
    if forme is None:
        return None
    try:
        cle = forme.TransparencyKey
        return bool((cle.R, cle.G, cle.B) == CLE)
    except Exception:
        return None


def rendre_le_fond_transparent(fenetre: Any) -> bool:
    """Fait du fond du panneau un trou vers le jeu. **Ne lève jamais.**

    Rend `True` si la couleur-clé est en place après l'appel. Un `False` laisse
    le panneau tel qu'il était : opaque, donc simplement moins joli. Aucun
    comptage, aucune capture, aucune session n'en dépend.

    ⚠️ Idempotent, et il faut qu'il le reste : reposer `TransparencyKey` fait
    retravailler le formulaire pour rien, et c'est cet appel-là qui efface le
    style de la souris (voir l'en-tête).
    """
    if not _est_windows():
        return False
    forme = _formulaire(fenetre)
    if forme is None:
        return False
    if fond_transparent(fenetre):
        return True
    try:
        from System import Action  # type: ignore[import-not-found]
        from System.Drawing import Color  # type: ignore[import-not-found]
    except ImportError as exc:
        # Sans pythonnet, pywebview n'aurait pas pu ouvrir la fenêtre non plus.
        # On ne s'en plaint donc qu'au journal de mise au point.
        _log.debug("fond du panneau inchangé, .NET indisponible : %s", exc)
        return False

    couleur = Color.FromArgb(*CLE)

    def poser() -> None:
        # Les deux ensemble : la clé ne perce que ce qui porte EXACTEMENT cette
        # couleur, et il faut donc que le fond du formulaire la porte.
        forme.BackColor = couleur
        forme.TransparencyKey = couleur

    try:
        # ⚠️ `Invoke` et pas un appel direct : ces propriétés appartiennent au
        # fil de la couche graphique, et y toucher depuis un autre fil est
        # refusé par .NET.
        forme.Invoke(Action(poser))
    except Exception as exc:
        _log.debug("fond du panneau inchangé : %s", exc)
        return False
    return bool(fond_transparent(fenetre))
