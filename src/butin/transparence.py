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

⛔⛔ TRANSPARENT **OU** CLIQUABLE, JAMAIS LES DEUX
--------------------------------------------------

Trouvé par Maxime en farmant, le 09/08/2026 : « les boutons en direct ne
fonctionnent plus et impossible de bouger la fenêtre », **case décochée**.

Mesuré sur son panneau, en session : `WS_EX_TRANSPARENT` était bien retiré
(`traverse=False`, le réglage était donc respecté), et pourtant **chacun des
quatre points testés rendait `BlackDesertWindowClass`** — y compris la barre du
haut, là où sont les boutons.

⭐ Le mécanisme : WebView2 dessine par composition dans une fenêtre **fille**.
La surface de la fenêtre en couches, elle, ne porte que le fond du formulaire,
c'est-à-dire du magenta d'un bord à l'autre. Le test de collision de Windows ne
regarde que cette surface-là : il ne voit donc **que des trous**, pendant que
l'utilisateur voit un panneau parfaitement dessiné par-dessus.

Autrement dit, la couleur-clé rend le panneau intraversable au clic **partout**,
et aucun réglage de souris ne peut le rattraper. Les deux états sont donc
exclusifs, et c'est la case qui porte l'arbitrage :

| case cochée | fond | clics |
| --- | --- | --- |
| oui (défaut) | perce jusqu'au jeu | aucun, la souris passe |
| non | opaque sombre | boutons et déplacement retrouvés |

⚠️ **Et j'avais vu le symptôme sans le voir.** Ma mesure de #117 notait déjà
« décoché → sous le centre : AUTRE CHOSE », et je l'ai expliqué au lieu de le
creuser : « normal, un pixel transparent laisse passer ». Je n'ai pas vérifié
que les pixels OPAQUES, eux, restaient cliquables. Une mesure qui confirme ce
qu'on attend mérite la même méfiance qu'une mesure qui surprend.

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

OPAQUE = (12, 14, 19)
"""Le fond du panneau quand il n'est PAS transparent.

⛔ Ce n'est pas un choix esthétique, c'est la moitié d'un arbitrage. Voir
`rendre_le_fond_opaque` : la couleur-clé rend la fenêtre entière intraversable
au clic, donc « transparent » et « cliquable » s'excluent. Quand le joueur veut
ses boutons, on retire la clé — et il faut alors un fond, sinon le formulaire
revient à son gris clair d'origine, le « blanc très moche ».

`#0c0e13` est déjà le fond du cadre dans `overlay.html`, à l'opacité près : le
panneau garde donc la même allure, en opaque."""


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


def fond_opaque(fenetre: Any) -> bool | None:
    """Le fond est-il repeint en sombre, sans couleur-clé ? `None` si inconnu.

    ⛔ Ce n'est PAS l'inverse de `fond_transparent`, et c'est tout le piège :
    une fenêtre qui vient d'être créée n'a aucune clé — donc « pas transparente »
    — et porte quand même le gris clair d'origine. Répondre « déjà opaque » sur
    celle-là laisserait le « blanc très moche » en place en croyant l'avoir
    corrigé.
    """
    forme = _formulaire(fenetre)
    if forme is None:
        return None
    try:
        cle, fond = forme.TransparencyKey, forme.BackColor
        return bool((cle.R, cle.G, cle.B) != CLE and (fond.R, fond.G, fond.B) == OPAQUE)
    except Exception:
        return None


def rendre_le_fond_transparent(fenetre: Any) -> bool:
    """Fait du fond du panneau un trou vers le jeu. **Ne lève jamais.**

    ⛔ Rend AUSSI la fenêtre entière intraversable au clic, et ce n'est pas un
    effet de bord qu'on peut corriger : voir l'en-tête du module. N'appeler que
    lorsque le joueur a demandé la souris traversante.

    Rend `True` si la couleur-clé est en place après l'appel. Un `False` laisse
    le panneau tel qu'il était : opaque, donc simplement moins joli. Aucun
    comptage, aucune capture, aucune session n'en dépend.

    ⚠️ Idempotent, et il faut qu'il le reste : reposer `TransparencyKey` fait
    retravailler le formulaire pour rien, et c'est cet appel-là qui efface le
    style de la souris (voir l'en-tête).
    """
    return _poser_le_fond(fenetre, transparent=True)


def rendre_le_fond_opaque(fenetre: Any) -> bool:
    """Retire la couleur-clé et repeint le fond en sombre. **Ne lève jamais.**

    ⭐ C'est ce qui rend au panneau ses boutons et son déplacement : tant que la
    clé est posée, le test de collision de Windows ne voit que des trous, quel
    que soit le style de souris. Voir l'en-tête.

    ⚠️ Le fond repeint n'est pas cosmétique : sans lui, le formulaire revient à
    son gris clair d'origine, qui est le « blanc très moche » d'où vient tout ce
    module.

    Rend `True` quand le fond est repeint et la clé retirée.
    """
    return _poser_le_fond(fenetre, transparent=False)


def _poser_le_fond(fenetre: Any, *, transparent: bool) -> bool:
    """Pose fond et couleur-clé ensemble. Rend `True` si l'état visé est atteint.

    Un seul chemin pour les deux sens : le fond et la clé se posent **toujours**
    ensemble, et deux fonctions qui l'écriraient chacune de leur côté finiraient
    par diverger sur un des deux appels.
    """
    if not _est_windows():
        return False
    forme = _formulaire(fenetre)
    if forme is None:
        return False
    # ⚠️ La question n'est pas la même dans les deux sens : voir `fond_opaque`.
    if fond_transparent(fenetre) if transparent else fond_opaque(fenetre):
        return True
    try:
        from System import Action  # type: ignore[import-not-found]
        from System.Drawing import Color  # type: ignore[import-not-found]
    except ImportError as exc:
        # Sans pythonnet, pywebview n'aurait pas pu ouvrir la fenêtre non plus.
        # On ne s'en plaint donc qu'au journal de mise au point.
        _log.debug("fond du panneau inchangé, .NET indisponible : %s", exc)
        return False

    fond = Color.FromArgb(*(CLE if transparent else OPAQUE))
    # ⛔ `Color.Empty` et PAS le fond sombre : poser la clé sur la couleur qu'on
    # vient de peindre percerait exactement ce qu'on voulait rendre opaque.
    cle = fond if transparent else Color.Empty

    def poser() -> None:
        # Les deux ensemble : la clé ne perce que ce qui porte EXACTEMENT cette
        # couleur, et il faut donc que le fond du formulaire la porte. Dans
        # l'autre sens, poser un fond sombre sans retirer la clé ne rendrait
        # rien de cliquable.
        forme.BackColor = fond
        forme.TransparencyKey = cle

    try:
        # ⚠️ `Invoke` et pas un appel direct : ces propriétés appartiennent au
        # fil de la couche graphique, et y toucher depuis un autre fil est
        # refusé par .NET.
        forme.Invoke(Action(poser))
    except Exception as exc:
        _log.debug("fond du panneau inchangé : %s", exc)
        return False
    # ⛔ On relit au lieu de croire ce qu'on vient de poser.
    return bool(fond_transparent(fenetre) if transparent else fond_opaque(fenetre))
