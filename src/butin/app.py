"""L'application de bureau : une vraie fenêtre, pas un onglet de navigateur.

Pourquoi une fenêtre plutôt qu'une page
----------------------------------------

Un joueur lance un logiciel, il n'ouvre pas un terminal puis une adresse dans
son navigateur. Tant que le produit demandait ça, il restait un outil de
développeur, quelle que soit la qualité de ce qu'il affichait.

Pourquoi elle enveloppe la page existante
-------------------------------------------

L'interface est déjà écrite, déjà testée, et elle marche. La réécrire en widgets
natifs coûterait tout ce travail pour rien : ce que l'utilisateur veut, c'est
une fenêtre avec une icône dans la barre des tâches, pas une autre technologie
d'affichage.

Cette fenêtre est donc la **vue système** de Windows, WebView2, pointée sur le
serveur local. Aucun navigateur ne s'ouvre, aucune adresse n'est visible, et la
page servie est exactement celle des tests.

Le port est laissé au système
-------------------------------

`port=0` demande un port libre au système. L'utilisateur n'a rien à savoir d'un
numéro de port, et deux lancements simultanés ne se disputent plus le même.

⚠️ Ce que la fermeture doit faire
----------------------------------

Fermer la fenêtre **arrête la capture et referme la session**. Sans ça, quitter
le logiciel laisserait dans la base une session ouverte pour toujours, dont la
durée continuerait de grandir : la prochaine ouverture afficherait un silver par
heure calculé sur des heures qui n'ont jamais été farmées.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

from . import paths
from .capture.worker import CaptureWorker
from .catalog import ItemCatalog, ItemMatcher
from .market import PriceBook
from .store import SessionStore
from .ui.server import AppState, build_server

_log = logging.getLogger(__name__)

TITLE = "Butin — suivi de butin, Black Desert Online"
WIDTH = 1100
HEIGHT = 820
OVERLAY_WIDTH = 430
OVERLAY_HEIGHT = 380
"""Taille du panneau en surimpression. Assez pour une dizaine de drops et les
trois chiffres, assez peu pour ne pas manger le champ de vision du jeu."""

MIN_SIZE = (860, 620)
"""Taille minimale de la fenêtre. En dessous, le tableau du butin se replie et
les quatre chiffres passent les uns sous les autres : lisible, mais ce n'est
plus la même lecture d'un coup d'œil."""


class Overlay:
    """Le panneau en surimpression, posé par-dessus le jeu.

    Sans cadre, translucide et toujours au-dessus : c'est le seul écran que le
    joueur regarde pendant qu'il farme, et il ne doit ni cacher le jeu ni passer
    derrière lui au premier clic.

    ⚠️ Une poignée de déplacement est dessinée dans la page. Sans cadre de
    fenêtre, rien n'indiquerait qu'on peut bouger le panneau, et le joueur le
    croirait cloué là où il est tombé.
    """

    def __init__(self, url: str) -> None:
        self._url = url
        self._window: Any = None

    def open(self) -> None:
        if self._window is not None:
            return
        import webview

        self._window = webview.create_window(
            "Butin — en direct",
            self._url,
            width=OVERLAY_WIDTH,
            height=OVERLAY_HEIGHT,
            frameless=True,
            on_top=True,
            transparent=True,
            easy_drag=True,
        )

    def close(self) -> None:
        fenetre, self._window = self._window, None
        if fenetre is None:
            return
        try:
            fenetre.destroy()
        except Exception as exc:
            # Fermer une fenêtre déjà partie n'est pas une panne : l'utilisateur
            # a pu la refermer lui-même. Le dire au journal suffit.
            _log.debug("fenêtre en surimpression déjà fermée : %s", exc)


def build_state(store: SessionStore | None = None) -> AppState:
    """Assemble l'état de l'application, catalogue compris.

    Un catalogue absent **dégrade** l'affichage, il ne doit pas empêcher de
    lancer : les objets s'affichent par identifiant, et l'historique reste
    consultable. En revanche la capture, elle, refusera de démarrer sans lui,
    parce qu'elle ne pourrait rien reconnaître.
    """
    # Avant toute ouverture de base : une installation antérieure écrivait
    # ailleurs, et sans ce déménagement la mise à jour ferait disparaître
    # l'historique. Les fichiers seraient toujours là, mais le programme
    # regarderait ailleurs, ce qui du point de vue de la personne revient au
    # même.
    ancien = paths.migrate_legacy()
    if ancien is not None:
        _log.info("données reprises depuis %s", ancien)

    try:
        catalog: ItemCatalog | None = ItemCatalog.load()
    except Exception as exc:
        _log.warning("catalogue indisponible, objets affichés par identifiant : %s", exc)
        catalog = None

    magasin = store or SessionStore()
    matcher = ItemMatcher(catalog) if catalog is not None else None
    return AppState(magasin, PriceBook(), catalog, CaptureWorker(magasin, matcher=matcher))


def run(
    *,
    port: int = 0,
    store: SessionStore | None = None,
    state: AppState | None = None,
    window: Any = None,
    preload: Callable[[], object] | None = None,
) -> int:
    """Ouvre la fenêtre et ne rend la main qu'à sa fermeture.

    `window`, `state` et `preload` existent pour les tests, et pour la même
    raison : ouvrir une vraie fenêtre demande une session graphique, faire
    tourner une vraie capture demande un écran et le moteur de reconnaissance,
    et précharger les images demande le réseau. L'intégration continue n'a rien
    de tout ça. `window` reçoit l'adresse locale et doit bloquer jusqu'à la
    fermeture, exactement comme le fait la vraie.

    ⚠️ `preload` est injectable et pas seulement désactivable, parce que le
    problème n'est pas qu'il coûte cher : c'est qu'il tourne dans un **fil de
    fond qui survit à cet appel**. Dans l'application c'est sans conséquence,
    le fil est démon et meurt avec le processus. Dans une suite de tests, le
    processus continue : le fil écrivait alors sur le disque pendant un autre
    test, qui échouait sur un dossier qu'il n'avait pas créé.
    """
    state = state or build_state(store)
    serveur = build_server(state, port=port)
    adresse = f"http://127.0.0.1:{serveur.server_address[1]}/"
    if state.overlay is None and window is None:
        # Seulement pour la vraie fenêtre : un test qui injecte son ouverture
        # n'a pas de couche graphique, et lui coller un panneau qui appelle
        # webview le ferait échouer là où il ne mesure rien de tel.
        state.overlay = Overlay(adresse + "overlay")

    fil = threading.Thread(target=serveur.serve_forever, daemon=True, name="butin-ui")
    fil.start()

    # ⚠️ Dans un fil de fond, et jamais devant. Précharger les images du butin
    # connu, ce sont quelques centaines d'allers-retours réseau : les faire ici
    # retarderait l'ouverture de la fenêtre d'autant, pour un gain purement
    # cosmétique. Le fil est démon, donc il ne retient jamais la fermeture.
    threading.Thread(
        target=preload or state.preload_icons, daemon=True, name="butin-icones"
    ).start()
    try:
        (window or _open_window)(adresse)
    finally:
        # Dans cet ordre, et jamais dans l'autre : arrêter la capture enregistre
        # le butin encore en attente, et refermer la session fige sa durée.
        state.stop()
        serveur.shutdown()
        serveur.server_close()
    return 0


def _open_window(url: str) -> None:
    """Ouvre la fenêtre système, ou explique comment s'en passer.

    Le repli n'est pas une politesse : la vue système de Windows peut manquer
    sur une installation ancienne, et un logiciel qui se contente de ne pas
    démarrer ne dit pas à l'utilisateur qu'une commande de plus lui rendrait le
    même service.
    """
    try:
        import webview
    except ImportError:
        raise SystemExit(
            "La fenêtre de l'application demande « pywebview », absent de cet "
            "environnement.\nInstallez-le avec « pip install pywebview », ou "
            "lancez « butin interface » pour utiliser la même interface dans un "
            "navigateur."
        ) from None

    webview.create_window(TITLE, url, width=WIDTH, height=HEIGHT, min_size=MIN_SIZE)
    webview.start()


def main() -> int:
    """Point d'entrée du lanceur sans console.

    Séparé de `__main__.main` exprès : celui-là analyse des arguments et écrit
    sur la sortie standard, qui n'existe pas quand Windows lance une
    application sans terminal. Ici il n'y a rien à analyser, on ouvre.
    """
    logging.basicConfig(level=logging.WARNING)
    return run()
