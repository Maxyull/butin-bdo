"""Interface web locale.

Pourquoi le web et pas une fenêtre native
------------------------------------------

Trois raisons, dans l'ordre d'importance :

1. **Zéro dépendance ajoutée.** Tout vient de la bibliothèque standard. Une
   boîte à outils graphique pèse plus de cent mégaoctets et devrait être
   embarquée dans l'installeur, pour une interface qui tient en une page.
2. **Vérifiable.** Une page web se charge, se lit et se teste. Une fenêtre
   native ne se vérifie qu'à l'œil, sur la machine de celui qui la code.
3. **Modifiable par l'utilisateur.** Le fichier de la page est en clair à côté
   du programme.

Sécurité : écoute sur la boucle locale, et nulle part ailleurs
--------------------------------------------------------------

Le serveur se lie à `127.0.0.1` et **jamais** à `0.0.0.0`. La différence n'est
pas cosmétique : la seconde exposerait l'historique de farm à tout le réseau
local, donc à un réseau partagé ou à un point d'accès public, sans que rien ne
le signale à l'utilisateur.

Il n'y a ni authentification ni jeton, et c'est cohérent **uniquement** parce
que rien d'extérieur ne peut atteindre le port. Si quelqu'un change l'adresse
d'écoute un jour, il devra ajouter les deux.

Aucun en-tête `Access-Control-Allow-Origin` n'est émis : la politique de même
origine du navigateur empêche alors une page web quelconque, ouverte dans un
autre onglet, d'interroger ce serveur à l'insu de l'utilisateur.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Protocol

from .. import __version__, paths
from ..capture.calibrate import Calibration, CalibrationError
from ..capture.worker import CaptureUnavailable, CaptureWorker
from ..catalog import IconStore, ItemCatalog, ItemMatcher
from ..catalog.icons import TYPES_MIME
from ..market import PriceBook
from ..store import SessionStore, Settings, compute
from ..update import UpdateInfo, check_for_update

_log = logging.getLogger(__name__)

# Boucle locale uniquement. Voir la note de sécurité en tête de module avant de
# toucher à cette valeur.
HOST = "127.0.0.1"
DEFAULT_PORT = 8771

STATIC = Path(__file__).resolve().parent / "static"

# Plafond de taille d'un corps de requête. Les nôtres font quelques dizaines
# d'octets : au-delà, c'est autre chose et on refuse plutôt que de lire.
MAX_BODY = 64 * 1024


class OverlayWindow(Protocol):
    """Ce que l'état attend d'un panneau en surimpression.

    Réduit à ouvrir et fermer : la couche interface ne doit rien savoir de la
    bibliothèque de fenêtres, sans quoi elle deviendrait impossible à tester
    sans session graphique.
    """

    def open(self) -> None: ...

    def close(self) -> None: ...


class AppState:
    """État partagé entre les requêtes.

    Verrouillé parce que le serveur est multi-fils : deux requêtes simultanées
    qui démarreraient une session laisseraient une session orpheline ouverte
    pour toujours dans la base.
    """

    def __init__(
        self,
        store: SessionStore,
        book: PriceBook,
        catalog: ItemCatalog | None = None,
        worker: CaptureWorker | None = None,
        overlay: OverlayWindow | None = None,
        icons: IconStore | None = None,
    ) -> None:
        self.store = store
        self.book = book
        self.worker = worker
        self.overlay = overlay
        """Panneau en surimpression, ouvert avec la session et fermé avec elle.

        Optionnel : sans lui l'application reste utilisable, la fenêtre
        principale montrant les mêmes chiffres. C'est aussi ce qui permet aux
        tests de vérifier le cycle sans ouvrir de fenêtre.
        """
        """Ce qui fait tourner la capture. Optionnel pour que l'interface reste
        consultable sans écran ni moteur de reconnaissance, ce dont les tests et
        une machine sans affichage profitent."""
        self.catalog = catalog
        """Sert à nommer les objets. C'est tout l'objet du sélecteur de langue :
        sans lui, il ne changerait rien de visible."""
        self.icons = icons if icons is not None else IconStore()
        """Images des objets. Toujours présent, parce qu'il ne fait jamais
        échouer quoi que ce soit : sans réseau il rend simplement None, et la
        page se passe de l'image."""
        self.update_info: UpdateInfo | None = None
        """Résultat de la dernière vérification de mise à jour, ou None tant
        qu'aucune n'a eu lieu ou qu'elle a échoué. Rempli en fond par
        `check_update()`, jamais sur le fil qui répond aux requêtes : voir
        `update.py` pour pourquoi un problème réseau ici ne doit jamais
        retarder l'ouverture de la fenêtre."""
        self.lock = threading.Lock()
        self.settings = Settings.load()
        """Langue, région et profil de taxe, relus au lancement.

        ⚠️ Relus et non repartis du défaut : le taux de taxe est une propriété
        du compte du joueur, et le défaut sous-estime de 23 % ce que touche
        quelqu'un qui a un abonnement. Une erreur systématique, invisible à
        l'écran, et qui ressemble à un farm pauvre.
        """
        self.session_id: int | None = None

    # -- lecture ---------------------------------------------------------

    def _settings_dict(self) -> dict[str, Any]:
        """Les réglages tels que la page les lit. À appeler sous verrou.

        ⚠️ `taux_marche` est **rendu et jamais reçu** : il se déduit des trois
        cases du profil de taxe. Pouvoir écrire les deux ferait un réglage qui
        ment, la prochaine case cochée écrasant le taux saisi à la main sans
        rien dire.
        """
        taxe = self.settings.tax
        return {
            "langue": self.settings.language,
            "region": self.settings.region.value,
            "taux_marche": self.settings.market_rate,
            "taxe": {
                "abonnement": taxe.value_pack,
                "anneau_marchand": taxe.merchant_ring,
                "renommee": taxe.family_fame,
            },
        }

    def _update_dict(self) -> dict[str, Any] | None:
        """`None` tant que la vérification n'a pas encore répondu ou a
        échoué : la page ne montre alors rien, elle n'affiche pas un
        bandeau vide. Voir `update.py`."""
        info = self.update_info
        if info is None:
            return None
        return {"disponible": info.disponible, "version": info.version, "url": info.url}

    def snapshot(self, *, now: float | None = None) -> dict[str, Any]:
        maintenant = time.time() if now is None else now
        with self.lock:
            session_id = self.session_id
            reglages = self._settings_dict()
            taux = self.settings.market_rate
            langue = self.settings.language

        capture = self.worker.status().to_dict() if self.worker is not None else None
        # L'état du calibrage se lit à chaque rafraîchissement plutôt que d'être
        # gardé en mémoire : le fichier peut être supprimé ou refait pendant que
        # la page est ouverte, et afficher « calibré » sur un fichier disparu
        # renverrait l'utilisateur vers la mauvaise cause quand rien ne compte.
        try:
            calibrage = Calibration.load()
        except ValueError:
            calibrage = None
        reglages["calibrage"] = calibrage.describe() if calibrage is not None else ""
        reglages["dossier"] = str(paths.storage_root())
        reglages["dossier_defaut"] = str(paths.default_storage_root())

        if session_id is None:
            return {
                "reglages": reglages,
                "session": None,
                "stats": None,
                "butin": [],
                "derniers": [],
                "capture": capture,
                "maj": self._update_dict(),
                "version": __version__,
            }

        session = self.store.get_session(session_id)
        if session is None:
            return {
                "reglages": reglages,
                "session": None,
                "stats": None,
                "butin": [],
                "derniers": [],
                "capture": capture,
                "maj": self._update_dict(),
                "version": __version__,
            }

        quantites = self.store.quantities(session_id)
        stats = compute(
            quantites,
            self.book,
            duration_s=session.duration_s(maintenant),
            silver_direct=session.silver_direct,
            market_rate=taux,
            now=maintenant,
        )
        return {
            "reglages": reglages,
            "session": {
                "id": session.id,
                "spot": session.spot,
                "duree_s": session.duration_s(maintenant),
                "en_cours": session.is_open,
                "en_pause": session.is_paused,
            },
            "stats": {
                "total": stats.total,
                "par_heure": round(stats.per_hour),
                "net_marche": stats.net_market,
                "brut_marche": stats.gross_market,
                "marchand": stats.vendor,
                "silver_direct": stats.silver_direct,
                "objets_inconnus": stats.unknown_items,
                "prix_perimes": stats.stale_prices,
                "couverture": round(stats.coverage, 3),
                "complet": stats.is_complete,
            },
            "butin": self._loot_rows(quantites, maintenant, langue),
            "derniers": self._recent_rows(session_id, maintenant, langue),
            "capture": capture,
            "maj": self._update_dict(),
            "version": __version__,
        }

    def icon(self, item_id: int) -> Path | None:
        """Image de l'objet sur le disque, téléchargée au besoin, ou None.

        Le chemin distant vient du catalogue. Sans catalogue on ne peut que
        servir ce qui est déjà là : c'est le cas d'une machine sans réseau, où
        la page doit rester consultable.
        """
        item = self.catalog.get(item_id) if self.catalog is not None else None
        return self.icons.get(item_id, item.icon if item is not None else "")

    def preload_icons(self) -> int:
        """Télécharge d'avance les images du butin connu.

        ⚠️ À appeler dans un fil de fond. C'est quelques centaines d'allers-
        retours réseau : les faire au premier plan retarderait l'ouverture de la
        fenêtre d'autant, pour un gain purement cosmétique.

        Le butin connu et pas le catalogue entier : 362 objets contre 68 747.
        Ce sont ceux qui tombent réellement, donc ceux dont le récap aura besoin
        pendant le farm. Tout autre objet est téléchargé au moment où il tombe.
        """
        if self.catalog is None:
            return 0
        from ..catalog.zones import known_loot_ids

        entrees = {}
        for item_id in known_loot_ids():
            item = self.catalog.get(item_id)
            if item is not None and item.icon:
                entrees[item_id] = item.icon
        return self.icons.preload(entrees)

    def check_update(self) -> UpdateInfo | None:
        """Interroge GitHub une fois et retient le résultat. Voir `update.py`
        pour pourquoi c'est une simple notification, jamais un remplacement
        automatique, et pourquoi un échec ne doit rien empêcher.

        ⚠️ À appeler dans un fil de fond, comme `preload_icons` : c'est un
        aller-retour réseau, et le faire au premier plan retarderait
        l'ouverture de la fenêtre d'autant.
        """
        self.update_info = check_for_update(__version__)
        return self.update_info

    def history(self, *, limit: int = 30) -> list[dict[str, Any]]:
        """Les sessions passées, avec ce qu'elles ont rapporté.

        ⚠️ Hors de `snapshot`, et c'est délibéré. La page principale se
        rafraîchit chaque seconde ; recalculer les statistiques de trente
        sessions à ce rythme coûterait trente requêtes de cumul par seconde pour
        un écran que personne ne regarde pendant qu'il farme. L'historique est
        donc chargé quand on l'ouvre, et seulement là.
        """
        maintenant = time.time()
        with self.lock:
            taux, langue = self.settings.market_rate, self.settings.language

        lignes: list[dict[str, Any]] = []
        for session in self.store.sessions(limit=limit):
            quantites = self.store.quantities(session.id)
            stats = compute(
                quantites,
                self.book,
                duration_s=session.duration_s(maintenant),
                silver_direct=session.silver_direct,
                market_rate=taux,
                now=maintenant,
            )
            lignes.append(
                {
                    "id": session.id,
                    "spot": session.spot,
                    "debut": session.started_at,
                    "duree_s": session.duration_s(maintenant),
                    "en_cours": session.is_open,
                    "total": stats.total,
                    "par_heure": round(stats.per_hour),
                    "objets": sum(quantites.values()),
                    "complet": stats.is_complete,
                }
            )
        _ = langue
        return lignes

    def session_detail(self, session_id: int) -> dict[str, Any] | None:
        """Le butin d'une session passée, comme la page principale l'affiche.

        Rend None sur un identifiant inconnu plutôt qu'un dictionnaire vide :
        « cette session n'existe pas » et « cette session n'a rien rapporté »
        sont deux réponses différentes, et les confondre ferait passer une
        erreur d'adressage pour une soirée sans butin.
        """
        session = self.store.get_session(session_id)
        if session is None:
            return None
        maintenant = time.time()
        with self.lock:
            langue = self.settings.language
        quantites = self.store.quantities(session_id)
        return {
            "id": session.id,
            "spot": session.spot,
            "debut": session.started_at,
            "duree_s": session.duration_s(maintenant),
            "butin": self._loot_rows(quantites, maintenant, langue),
        }

    def _recent_rows(self, session_id: int, maintenant: float, langue: str) -> list[dict[str, Any]]:
        """Les derniers drops, tels qu'ils sont tombés.

        Le total cumulé ne montre pas ce qui vient d'arriver : il grandit, c'est
        tout. Ce fil-là est la seule chose qui dise « ça, c'est tombé il y a
        trois secondes », et c'est ce qu'on regarde en farmant.
        """
        lignes: list[dict[str, Any]] = []
        for ligne in self.store.recent_loot(session_id):
            prix = self.book.price(ligne.item_id, sid=ligne.sid, now=maintenant)
            lignes.append(
                {
                    "item_id": ligne.item_id,
                    "nom": self._name(ligne.item_id, langue),
                    "quantite": ligne.qty,
                    "valeur": prix.value * ligne.qty,
                    "rarete": self._grade(ligne.item_id),
                    "il_y_a_s": max(0.0, round(maintenant - ligne.at, 1)),
                }
            )
        return lignes

    def _grade(self, item_id: int) -> int:
        """Rareté de l'objet, de 0 à 4, pour la couleur du nom.

        C'est le code couleur du jeu lui-même : blanc, vert, bleu, jaune,
        orange. Un joueur reconnaît un drop rare à sa couleur avant d'avoir lu
        son nom, et la donnée était déjà dans le catalogue sans être utilisée.
        """
        if self.catalog is None:
            return 0
        item = self.catalog.get(item_id)
        return item.grade if item is not None else 0

    def _name(self, item_id: int, langue: str) -> str:
        """Nom de l'objet dans la langue choisie.

        Repli sur l'identifiant plutôt que sur une chaîne vide : une ligne sans
        nom serait indistinguable des autres dans le tableau, alors qu'un
        « #44118 » se cherche et se corrige.
        """
        if self.catalog is None:
            return f"#{item_id}"
        item = self.catalog.get(item_id)
        return item.name(langue) if item is not None else f"#{item_id}"

    def _loot_rows(
        self, quantites: dict[tuple[int, int], int], maintenant: float, langue: str
    ) -> list[dict[str, Any]]:
        lignes: list[dict[str, Any]] = []
        for (item_id, sid), qty in quantites.items():
            prix = self.book.price(item_id, sid=sid, now=maintenant)
            lignes.append(
                {
                    "item_id": item_id,
                    "sid": sid,
                    "nom": self._name(item_id, langue),
                    "quantite": qty,
                    "valeur_unitaire": prix.value,
                    "valeur_totale": prix.value * qty,
                    "source": prix.source.value,
                }
            )
        lignes.sort(key=lambda ligne: ligne["valeur_totale"], reverse=True)
        return lignes

    # -- écriture --------------------------------------------------------

    def set_settings(self, data: dict[str, Any]) -> None:
        """Applique ce que la page envoie, et l'écrit sur le disque.

        Le tri du valide et de l'invalide est entièrement dans `Settings`, pour
        que le fichier et l'API ne puissent pas diverger sur ce qu'ils
        acceptent. Ici il ne reste que la traduction des noms français de l'API
        vers les noms anglais du code.

        ⚠️ L'écriture se fait **hors du verrou**. Toucher au disque en le tenant
        bloquerait le rafraîchissement d'une seconde de la page, et le panneau
        posé sur le jeu avec, pour un réglage qu'on change trois fois par an.
        """
        taxe = data.get("taxe")
        taxe = taxe if isinstance(taxe, dict) else {}
        with self.lock:
            self.settings = self.settings.updated(
                language=data.get("langue"),
                region=data.get("region"),
                value_pack=taxe.get("abonnement"),
                merchant_ring=taxe.get("anneau_marchand"),
                family_fame=taxe.get("renommee"),
            )
            a_ecrire = self.settings
        try:
            a_ecrire.save()
        except OSError as exc:
            # Un disque plein ne doit pas faire échouer le réglage qui vient
            # d'être appliqué : il tient pour cette session, et l'utilisateur le
            # verra revenir au défaut au prochain lancement, ce que l'affichage
            # permanent du taux rend visible.
            _log.warning("réglages non enregistrés (%s)", exc)

    def set_storage(self, chemin: str) -> dict[str, Any]:
        """Retient un nouveau dossier de données, effectif au prochain lancement.

        ⚠️ Rien n'est déplacé, et c'est délibéré : la base SQLite est ouverte à
        cet instant précis par le programme qui répond à cette requête.
        Déplacer un fichier de base pendant qu'il est ouvert est le meilleur
        moyen de le perdre, et perdre l'historique de quelqu'un pour lui rendre
        service serait absurde.
        """
        vise = chemin.strip()
        if not vise:
            raise ValueError("dossier vide")
        cible = paths.set_storage_root(Path(vise))
        return {"dossier": str(cible), "redemarrage": True}

    def calibrate(self, *, monitor: int = 1) -> dict[str, Any]:
        """Cherche la fenêtre de chat et enregistre la zone. Rend ce qu'elle contient.

        ⚠️ Rend un **extrait de ce qui a été lu**, et pas seulement « c'est
        calibré ». La détection cherche ce qui se répète verticalement ; elle ne
        sait pas d'où vient l'image. Un essai réel a calibré très proprement sur
        une capture du chat ouverte dans une visionneuse : tout était juste sauf
        que ce n'était pas le jeu. Personne ne confond les deux quand les lignes
        lues sont sous ses yeux.
        """
        import base64

        from ..capture.calibrate import CALIBRATION_FRAMES, calibrate_frames, draw_preview
        from ..capture.lines import parse_frame
        from ..capture.ocr import TextReader
        from ..capture.screen import ScreenCapture

        # ⭐ PLUSIEURS images, pas une. Mesuré sur une vraie session : la
        # largeur trouvée va de 468 à 542 px d'une image à l'autre, et trois
        # calibrages successifs d'un joueur qui n'avait rien touché ont rendu
        # 476, 560 puis 731 px. Une zone une fois et demie trop large ralentit
        # la reconnaissance pendant TOUTE la session, en silence, donc le
        # compteur rate des lignes sans que rien ne le dise.
        images = []
        with ScreenCapture(monitor=monitor) as capture:
            ecran = capture.target_monitor()
            for index in range(CALIBRATION_FRAMES):
                if index:
                    # Espacées, pour ne pas mesurer cinq fois le même instant :
                    # c'est la variation qui donne la médiane son intérêt.
                    time.sleep(0.4)
                images.append(capture.grab(ecran))

        lecteur = TextReader()
        calibrage = calibrate_frames(images, lecteur, origin=(ecran.left, ecran.top))
        calibrage.save()
        image = images[-1]

        zone = calibrage.region
        rangees = lecteur.read_text(image[zone.top : zone.bottom, zone.left : zone.right])
        gains = 0
        if self.catalog is not None:
            gains = len(parse_frame(list(rangees), ItemMatcher(self.catalog)))
        apercu = base64.b64encode(draw_preview(image, calibrage)).decode("ascii")
        return {
            "zone": calibrage.describe(),
            "rangees": calibrage.rows,
            "extrait": [ligne[:90] for ligne in rangees[:4]],
            "gains": gains,
            "apercu": f"data:image/png;base64,{apercu}",
        }

    def start(self, spot: str, *, now: float | None = None) -> int:
        """Ouvre une session et lance la capture. Rien de tout ça sans l'autre.

        ⚠️ Si la capture refuse de démarrer, la session est **refermée** avant de
        propager l'erreur. Une session ouverte que rien n'alimente ressemble à
        une session normale dont le farm n'aurait rien donné : c'est le mode de
        défaillance que ce projet refuse, et le laisser ici l'introduirait à
        l'endroit le plus visible du produit.
        """
        maintenant = time.time() if now is None else now
        with self.lock:
            if self.session_id is not None:
                # Démarrer deux fois laisserait la première session ouverte pour
                # toujours, donc une durée qui gonfle sans fin.
                return self.session_id
            session = self.store.start_session(
                started_at=maintenant, spot=spot, region=self.settings.region.value
            )
            if self.worker is not None:
                try:
                    self.worker.start(session.id)
                except Exception:
                    self.store.end_session(session.id, ended_at=maintenant)
                    raise
            self.session_id = session.id

        # Hors du verrou : ouvrir une fenêtre passe par la couche graphique,
        # qui peut prendre son temps. Le garder verrouillé bloquerait toutes les
        # autres requêtes, dont celles qui rafraîchissent l'écran.
        if self.overlay is not None:
            self.overlay.open()
        return session.id

    def stop(self, *, now: float | None = None) -> None:
        """Arrête la capture PUIS ferme la session.

        Dans cet ordre : `CaptureWorker.stop` enregistre le butin encore en
        attente, et l'écrire après la fermeture le rattacherait à une session
        dont la durée est déjà figée.
        """
        maintenant = time.time() if now is None else now
        with self.lock:
            if self.session_id is None:
                return
            if self.worker is not None:
                self.worker.stop()
            self.store.end_session(self.session_id, ended_at=maintenant)
            self.session_id = None

        if self.overlay is not None:
            self.overlay.close()

    def pause(self, *, now: float | None = None) -> None:
        """Suspend la capture et arrête de compter le temps.

        Dans cet ordre, et pour la même raison que l'arrêt : la pause enregistre
        le butin encore en attente, qui est bien tombé avant la pause.

        ⚠️ Le panneau **reste ouvert**. Le fermer laisserait le joueur devant son
        jeu sans rien qui dise que le suivi est suspendu, et une reprise oubliée
        est du farm perdu qu'aucun écran ne signalerait.
        """
        maintenant = time.time() if now is None else now
        with self.lock:
            if self.session_id is None:
                return
            if self.worker is not None:
                self.worker.pause()
            self.store.pause_session(self.session_id, at=maintenant)

    def resume(self, *, now: float | None = None) -> None:
        """Reprend la capture là où la pause l'avait laissée.

        ⚠️ La capture est relancée AVANT que l'horloge reparte, et si elle refuse
        la session **reste en pause** : une session qui recompte le temps sans
        que rien ne l'alimente est exactement la panne silencieuse que ce projet
        refuse, au même titre qu'une session ouverte sans capture.

        La boucle repart neuve, donc sa première lecture amorce le suivi avec ce
        qui est déjà à l'écran sans rien compter. C'est ce qui empêche la reprise
        de recréditer les dernières lignes du journal.
        """
        maintenant = time.time() if now is None else now
        with self.lock:
            if self.session_id is None:
                return
            if self.worker is not None and not self.worker.running:
                self.worker.start(self.session_id, reprise=True)
            self.store.resume_session(self.session_id, at=maintenant)


class Handler(BaseHTTPRequestHandler):
    """Routes de l'interface. Volontairement peu nombreuses."""

    server_version = "Butin"
    state: AppState

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        # Le journal par défaut écrit sur la sortie d'erreur à chaque requête,
        # ce qui noie tout le reste quand la page rafraîchit chaque seconde.
        _log.debug("%s - %s", self.address_string(), format % args)

    # -- utilitaires -----------------------------------------------------

    def _send_json(self, payload: Any, *, status: int = 200) -> None:
        corps = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corps)))
        # Interdit au navigateur de deviner un autre type que celui annoncé.
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(corps)

    def _send_detail(self, brut: str) -> None:
        """Sert le détail d'une session, en refusant un identifiant qui n'en est pas un.

        Le chemin vient du réseau : le convertir sans vérifier laisserait
        remonter une `ValueError` jusqu'au gestionnaire, qui rendrait une erreur
        serveur là où la bonne réponse est « cette adresse n'existe pas ».
        """
        try:
            session_id = int(brut)
        except ValueError:
            self._send_json({"erreur": "identifiant de session invalide"}, status=400)
            return
        detail = self.state.session_detail(session_id)
        if detail is None:
            self._send_json({"erreur": "session introuvable"}, status=404)
            return
        self._send_json(detail)

    def _send_icon(self, brut: str) -> None:
        """Sert l'image d'un objet, en la téléchargeant si on ne l'a pas encore.

        404 quand il n'y en a pas, et c'est suffisant : la page cache une image
        qui ne charge pas. Une icône manquante est cosmétique, elle ne doit ni
        signaler une panne ni interrompre l'affichage du drop.
        """
        try:
            item_id = int(brut)
        except ValueError:
            self._send_json({"erreur": "identifiant d'objet invalide"}, status=400)
            return
        chemin = self.state.icon(item_id)
        if chemin is None:
            self._send_json({"erreur": "pas d'image pour cet objet"}, status=404)
            return
        corps = chemin.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", TYPES_MIME.get(chemin.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(corps)))
        self.send_header("X-Content-Type-Options", "nosniff")
        # Une image d'objet ne change pas d'un patch à l'autre, et la page en
        # redemande une par ligne à chaque rafraîchissement, donc chaque seconde.
        self.send_header("Cache-Control", "public, max-age=86400")
        self.end_headers()
        self.wfile.write(corps)

    def _send_file(self, name: str) -> None:
        chemin = (STATIC / name).resolve()
        # Garde-fou de traversée : sans lui, une requête « /../../secrets » se
        # servirait dans le disque entier.
        if not chemin.is_file() or STATIC.resolve() not in chemin.parents:
            self._send_json({"erreur": "introuvable"}, status=404)
            return
        corps = chemin.read_bytes()
        types = {".html": "text/html; charset=utf-8", ".css": "text/css", ".js": "text/javascript"}
        self.send_response(200)
        self.send_header("Content-Type", types.get(chemin.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(corps)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(corps)

    def _read_json(self) -> dict[str, Any]:
        try:
            taille = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return {}
        if taille <= 0 or taille > MAX_BODY:
            return {}
        try:
            data = json.loads(self.rfile.read(taille).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    # -- routes ----------------------------------------------------------

    def do_GET(self) -> None:
        if self.path in ("/", "/index.html"):
            self._send_file("index.html")
        elif self.path == "/overlay":
            self._send_file("overlay.html")
        elif self.path == "/api/etat":
            self._send_json(self.state.snapshot())
        elif self.path == "/api/historique":
            self._send_json({"sessions": self.state.history()})
        elif self.path.startswith("/api/historique/"):
            self._send_detail(self.path.removeprefix("/api/historique/"))
        elif self.path.startswith("/icone/"):
            self._send_icon(self.path.removeprefix("/icone/"))
        else:
            self._send_json({"erreur": "introuvable"}, status=404)

    def do_POST(self) -> None:
        if self.path == "/api/reglages":
            self.state.set_settings(self._read_json())
            self._send_json(self.state.snapshot())
        elif self.path == "/api/session/demarrer":
            spot = str(self._read_json().get("spot") or "")
            try:
                self.state.start(spot)
            except CaptureUnavailable as exc:
                # 409 et non 500 : ce n'est pas une panne du serveur, c'est une
                # condition que l'utilisateur peut lever lui-même, et le message
                # dit laquelle.
                self._send_json({"erreur": str(exc)}, status=409)
                return
            self._send_json(self.state.snapshot())
        elif self.path == "/api/dossier":
            try:
                self._send_json(self.state.set_storage(str(self._read_json().get("dossier", ""))))
            except (ValueError, OSError) as exc:
                # Un chemin refusé par le système, un lecteur absent, un droit
                # manquant : autant de choses que l'utilisateur peut corriger,
                # à condition qu'on lui dise laquelle.
                self._send_json({"erreur": f"dossier impossible : {exc}"}, status=400)
        elif self.path == "/api/calibrer":
            try:
                self._send_json(self.state.calibrate())
            except CalibrationError as exc:
                # 409 comme le refus de démarrer : ce n'est pas une panne du
                # serveur, c'est une condition que l'utilisateur peut lever.
                self._send_json({"erreur": str(exc)}, status=409)
        elif self.path == "/api/session/pause":
            self.state.pause()
            self._send_json(self.state.snapshot())
        elif self.path == "/api/session/reprendre":
            try:
                self.state.resume()
            except CaptureUnavailable as exc:
                # 409 comme le refus de démarrer, et pour la même raison : la
                # session reste en pause, l'utilisateur peut lever la cause et
                # recliquer. Répondre 200 lui ferait croire que ça recompte.
                self._send_json({"erreur": str(exc)}, status=409)
                return
            self._send_json(self.state.snapshot())
        elif self.path == "/api/session/arreter":
            self.state.stop()
            self._send_json(self.state.snapshot())
        else:
            self._send_json({"erreur": "introuvable"}, status=404)


def build_server(state: AppState, port: int = DEFAULT_PORT) -> ThreadingHTTPServer:
    """Construit le serveur, lié à la boucle locale uniquement."""
    handler = type("BoundHandler", (Handler,), {"state": state})
    return ThreadingHTTPServer((HOST, port), handler)


def serve(*, port: int = DEFAULT_PORT, store: SessionStore | None = None) -> None:
    """Lance l'interface jusqu'à interruption."""
    try:
        catalog: ItemCatalog | None = ItemCatalog.load()
    except Exception as exc:
        # Le catalogue sert à NOMMER les objets, pas à les compter. Son absence
        # dégrade l'affichage, elle ne doit pas empêcher de lancer l'interface.
        _log.warning("catalogue indisponible, les objets seront affichés par identifiant : %s", exc)
        catalog = None
    magasin = store or SessionStore()
    matcher = ItemMatcher(catalog) if catalog is not None else None
    state = AppState(
        magasin,
        PriceBook(),
        catalog,
        # Le catalogue sert à NOMMER les objets pour l'affichage ; ici il sert à
        # les RECONNAÎTRE. Sans lui la capture ne peut rien compter, donc elle
        # refusera de démarrer plutôt que d'ouvrir une session vide.
        CaptureWorker(magasin, matcher=matcher),
    )
    serveur = build_server(state, port)
    print(f"Butin : interface sur http://{HOST}:{port}")
    try:
        serveur.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        serveur.server_close()
        state.book.save()
