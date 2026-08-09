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
import time
from collections.abc import Callable
from typing import Any

from . import paths, souris, transparence
from .capture.worker import CaptureWorker
from .catalog import ItemCatalog, ItemMatcher
from .fenetres import Position, position_a_restaurer
from .fenetres import enregistrer as enregistrer_position
from .market import PriceBook
from .store import SessionStore
from .ui.server import AppState, build_server

_log = logging.getLogger(__name__)

TITLE = "Butin — suivi de butin, Black Desert Online"
OVERLAY_TITLE = "Butin — en direct"
"""Le titre du panneau, et pas seulement une décoration : c'est par lui que
`souris.fenetre_par_titre` retrouve la fenêtre pour poser son style. Le changer
sans changer l'autre laisserait le réglage sans effet, en silence."""
WIDTH = 1100
HEIGHT = 820
OVERLAY_WIDTH = 430
OVERLAY_HEIGHT = 380
"""Taille de DÉPART du panneau en surimpression. Assez pour une dizaine de
drops et les trois chiffres, assez peu pour ne pas manger le champ de vision du
jeu."""

OVERLAY_HEIGHT_MAX = 900
"""Hauteur au-delà de laquelle le panneau cesse de grandir.

⛔ Une borne, parce que le nombre d'objets distincts n'en a pas. Signalé par
Maxime le 07/08/2026 : « on prend de plus en plus d'items en grindant », et la
dernière ligne était coupée. Sans plafond, un farm de plusieurs heures finirait
par couvrir l'écran du jeu — on aurait remplacé une gêne par une pire.

Au-delà, la liste défile dans le panneau plutôt que de pousser ses bords."""

MIN_SIZE = (860, 620)
"""Taille minimale de la fenêtre. En dessous, le tableau du butin se replie et
les quatre chiffres passent les uns sous les autres : lisible, mais ce n'est
plus la même lecture d'un coup d'œil."""


FENETRE_PRINCIPALE = "principale"
FENETRE_PANNEAU = "panneau"

SOURIS_ESSAIS = 25
SOURIS_DELAI_S = 0.2
"""Cinq secondes en tout, par pas de 200 ms, pour attendre que la couche
graphique ait créé la fenêtre du panneau.

⚠️ Généreux exprès : rater le réglage à l'ouverture, c'est farmer toute une
session avec la souris captée. Le coût d'attendre est nul, ces essais tournent
dans un fil démon qui ne retient personne."""

SUIVI_POSITION_S = 3.0
"""Intervalle entre deux relevés de la position d'une fenêtre.

⛔ On relève **pendant** que la fenêtre vit, et pas à sa fermeture. `butin.iss`
pose `CloseApplications=force` : c'est le Gestionnaire de redémarrage de
Windows qui ferme l'application pendant une mise à jour, et rien ne garantit
qu'un code de fermeture propre s'exécute.

Autrement dit, **le seul moment où l'on tient à se souvenir de la position est
précisément celui où la fermeture n'est pas polie.**

Trois secondes : assez fin pour ne perdre qu'un déplacement en cours, assez
espacé pour que ça reste invisible (une lecture d'attribut et, seulement si la
position a bougé, une écriture de quelques octets)."""


def _suivre_la_position(fenetre: Any, nom: str) -> threading.Event:
    """Enregistre la position de `fenetre` tant qu'elle vit. **Ne lève jamais.**

    Rend l'événement qui arrête le fil. ⚠️ L'appelant DOIT le positionner : un
    fil de fond qui survit à `run()` est un défaut que ce projet a déjà payé
    une fois (voir #37 et la note d'en-tête de `run`).
    """
    arret = threading.Event()

    def suivre() -> None:
        derniere: tuple[int, int] | None = None
        while not arret.wait(SUIVI_POSITION_S):
            try:
                courante = (int(fenetre.x), int(fenetre.y))
            except Exception as exc:
                # Fenêtre fermée, pas encore prête, ou bibliothèque qui refuse.
                # Un confort ne doit pas faire de bruit dans le journal.
                _log.debug("position de « %s » illisible : %s", nom, exc)
                continue
            if courante == derniere:
                continue
            derniere = courante
            enregistrer_position(nom, Position(*courante))

    threading.Thread(target=suivre, daemon=True, name=f"butin-position-{nom}").start()
    return arret


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
        self._arret_suivi: threading.Event | None = None

    def open(self) -> None:
        if self._window is not None:
            return
        import webview

        # ⭐ C'est LE panneau qui compte ici. Il est placé à la main, par-dessus
        # le jeu, à l'endroit précis où il ne gêne pas. Le rouvrir au centre à
        # chaque mise à jour transformait la mise à jour en un clic en une
        # corvée en deux gestes.
        depart = position_a_restaurer(FENETRE_PANNEAU)
        self._window = webview.create_window(
            OVERLAY_TITLE,
            self._url,
            width=OVERLAY_WIDTH,
            height=OVERLAY_HEIGHT,
            x=depart.x if depart else None,
            y=depart.y if depart else None,
            frameless=True,
            on_top=True,
            transparent=True,
            easy_drag=True,
        )
        self._arret_suivi = _suivre_la_position(self._window, FENETRE_PANNEAU)

    def souris_traversante(self, actif: bool) -> None:
        """Prépare le panneau : fond transparent, puis souris. **Ne lève jamais.**

        ⚠️ Le travail part dans un fil, pour deux raisons qui vont ensemble : la
        fenêtre n'existe pas encore à l'instant où pywebview rend la main (elle
        est créée par la couche graphique, plus tard), et l'appelant est une
        requête HTTP qu'on ne fait pas attendre pour un confort.

        Voir `butin.souris` et `butin.transparence` pour ce que chacun change,
        ce que ça coûte, et les mesures qui les ont établis.
        """
        if self._window is None:
            return
        threading.Thread(
            target=self._preparer_la_fenetre, args=(actif,), daemon=True, name="butin-panneau"
        ).start()

    def _preparer_la_fenetre(self, actif: bool) -> None:
        """Réessaie tant que la fenêtre n'est pas là. **Ne lève jamais.**

        ⛔ Sans cette attente, le réglage serait perdu **précisément au moment
        qui compte** : à l'ouverture du panneau, quand la session démarre. Un
        seul essai tombe systématiquement avant que la couche graphique ait créé
        la fenêtre, et le joueur retrouverait la souris captée en farmant sans
        rien comprendre.

        ⛔ **L'ordre des deux poses est contraint, et c'est mesuré** : poser la
        couleur-clé du fond efface `WS_EX_TRANSPARENT`, donc la transparence
        passe TOUJOURS avant la souris. Dans l'autre sens, le panneau
        redeviendrait capteur de souris pendant que la case afficherait encore
        « coché ». Détail et chiffres dans `butin.transparence`.

        ⚠️ La transparence n'est pas une condition de la souris : si elle échoue
        — pas de .NET, formulaire inattendu — on pose quand même la souris. Un
        panneau opaque qui laisse jouer vaut mieux qu'un panneau qui ne fait ni
        l'un ni l'autre.
        """
        for _ in range(SOURIS_ESSAIS):
            fenetre_pywebview = self._window
            if fenetre_pywebview is None:
                return
            fenetre = souris.fenetre_par_titre(OVERLAY_TITLE)
            if fenetre is not None:
                # ⛔ Dans cet ordre, jamais dans l'autre. Voir la docstring.
                transparence.rendre_le_fond_transparent(fenetre_pywebview)
                souris.laisser_passer_la_souris(fenetre, actif)
                return
            time.sleep(SOURIS_DELAI_S)
        _log.debug("panneau non préparé (fenêtre introuvable)")

    def resize(self, hauteur: int) -> None:
        """Ajuste la hauteur du panneau à son contenu. **Ne lève jamais.**

        ⛔ Un confort ne doit pas pouvoir interrompre une session de farm. Une
        fenêtre déjà fermée, une bibliothèque graphique qui refuse, et la
        capture continue exactement pareil.

        La largeur ne bouge pas : les lignes sont des noms d'objets, elles
        s'allongent rarement, et un panneau qui change de largeur à chaque drop
        serait insupportable à regarder.
        """
        fenetre = self._window
        if fenetre is None:
            return
        borne = max(OVERLAY_HEIGHT, min(int(hauteur), OVERLAY_HEIGHT_MAX))
        try:
            fenetre.resize(OVERLAY_WIDTH, borne)
        except Exception as exc:
            _log.debug("panneau non redimensionné : %s", exc)

    def close(self) -> None:
        # ⚠️ Arrêter le fil AVANT de détruire la fenêtre : sinon il lirait une
        # fenêtre partie et écrirait des positions dans le vide pendant trois
        # secondes. Un fil de fond ne doit pas survivre à ce qu'il observe.
        arret, self._arret_suivi = self._arret_suivi, None
        if arret is not None:
            arret.set()

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
    # ⛔ Le renommage du dossier D'ABORD. `migrate_legacy` déplace des fichiers
    # VERS `storage_root()` : le faire avant le renommage les déposerait dans
    # le nouveau dossier, puis le renommage échouerait parce que la destination
    # existe désormais — et l'ancien dossier, avec tout l'historique, resterait
    # sur le côté. L'ordre n'est pas cosmétique.
    renomme = paths.migrate_ancien_dossier()
    if renomme is not None:
        _log.info("dossier renommé depuis %s", renomme)

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


CHECK_UPDATE_INTERVAL_S = 300.0
"""Cinq minutes. Butin peut rester ouvert des heures pendant une session de
farm ; sans revérification périodique, une Release publiée pendant ce temps
ne serait jamais signalée avant le prochain lancement. Compromis entre
utilité (assez fréquent) et discrétion réseau (assez espacé) — aucune mesure
derrière ce chiffre, juste du bon sens, contrairement aux seuils mesurés
ailleurs dans ce dépôt (voir CLAUDE.md section 4sexies)."""


def _reverifier_periodiquement(
    verifier: Callable[[], object], *, intervalle_s: float, arret: threading.Event
) -> None:
    """Appelle `verifier` tout de suite, puis à intervalles réguliers, jusqu'à
    ce qu'`arret` soit positionné.

    `Event.wait(timeout=...)` et non `time.sleep(...)` : le premier rend la
    main DÈS QUE `arret` est positionné, même en plein milieu de l'attente. Un
    `sleep` bloquerait ce fil jusqu'au bout de l'intervalle, donc jusqu'à cinq
    minutes après la fermeture de la fenêtre — exactement le genre de fil qui
    survit à `run()` que ce projet a déjà payé cher une fois (voir la note
    d'en-tête de `run`).
    """
    while True:
        verifier()
        if arret.wait(timeout=intervalle_s):
            return


def run(
    *,
    port: int = 0,
    store: SessionStore | None = None,
    state: AppState | None = None,
    window: Any = None,
    preload: Callable[[], object] | None = None,
    check_update: Callable[[], object] | None = None,
    check_update_interval_s: float = CHECK_UPDATE_INTERVAL_S,
) -> int:
    """Ouvre la fenêtre et ne rend la main qu'à sa fermeture.

    `window`, `state`, `preload` et `check_update` existent pour les tests, et
    pour la même raison : ouvrir une vraie fenêtre demande une session
    graphique, faire tourner une vraie capture demande un écran et le moteur
    de reconnaissance, précharger les images et vérifier une mise à jour
    demandent tous les deux le réseau. L'intégration continue n'a rien de tout
    ça. `window` reçoit l'adresse locale et doit bloquer jusqu'à la fermeture,
    exactement comme le fait la vraie.

    ⚠️ `preload` et `check_update` sont injectables et pas seulement
    désactivables, parce que le problème n'est pas qu'ils coûtent cher : c'est
    qu'ils tournent dans un **fil de fond qui survit à cet appel**. Dans
    l'application c'est sans conséquence, le fil est démon et meurt avec le
    processus. Dans une suite de tests, le processus continue : le fil
    écrivait alors sur le disque pendant un autre test, qui échouait sur un
    dossier qu'il n'avait pas créé.

    ⚠️ `check_update` se répète toutes les `check_update_interval_s` secondes
    tant que la fenêtre reste ouverte, pas une seule fois au lancement : voir
    `_reverifier_periodiquement`. Le fil qui la porte est arrêté explicitement
    dans le `finally`, pour la même raison que `preload` ne doit jamais
    survivre à cet appel.
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
    # ⚠️ Même raison : un aller-retour réseau, jamais devant. Une notification
    # de mise à jour en retard d'une minute ne coûte rien ; retarder
    # l'ouverture de la fenêtre pour l'attendre coûterait tout. Répétée tant
    # que la fenêtre reste ouverte, voir `_reverifier_periodiquement`.
    arret_maj = threading.Event()
    threading.Thread(
        target=_reverifier_periodiquement,
        args=(check_update or state.check_update,),
        kwargs={"intervalle_s": check_update_interval_s, "arret": arret_maj},
        daemon=True,
        name="butin-maj",
    ).start()
    try:
        (window or _open_window)(adresse)
    finally:
        # Réveille immédiatement le fil de revérification s'il attendait
        # l'intervalle, avant même d'arrêter quoi que ce soit d'autre :
        # sinon il continuerait d'appeler GitHub jusqu'à cinq minutes après
        # la fermeture de la fenêtre.
        arret_maj.set()
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

    # ⭐ Rouvrir là où on l'avait laissée. `position_a_restaurer` refuse une
    # position tombée hors écran (deuxième moniteur débranché, résolution
    # changée) : une fenêtre invisible ressemble de l'extérieur à un logiciel
    # qui ne démarre plus.
    depart = position_a_restaurer(FENETRE_PRINCIPALE)
    fenetre = webview.create_window(
        TITLE,
        url,
        width=WIDTH,
        height=HEIGHT,
        min_size=MIN_SIZE,
        x=depart.x if depart else None,
        y=depart.y if depart else None,
    )
    arret = _suivre_la_position(fenetre, FENETRE_PRINCIPALE)
    try:
        webview.start()
    finally:
        arret.set()


def main() -> int:
    """Point d'entrée du lanceur sans console.

    Séparé de `__main__.main` exprès : celui-là analyse des arguments et écrit
    sur la sortie standard, qui n'existe pas quand Windows lance une
    application sans terminal. Ici il n'y a rien à analyser, on ouvre.
    """
    logging.basicConfig(level=logging.WARNING)
    return run()
