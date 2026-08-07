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
from ..autoupdate import install_update
from ..bundle import decrire_le_contenu as _decrire_archive
from ..bundle import ouvrir_le_dossier as _ouvrir_le_dossier
from ..bundle import preparer as _preparer_archive
from ..capture.calibrate import Calibration, CalibrationError
from ..capture.inventaire import capturer as _capturer_inventaire
from ..capture.worker import CaptureUnavailable, CaptureWorker
from ..catalog import IconStore, ItemCatalog, ItemMatcher
from ..catalog.icons import TYPES_MIME
from ..discord_link import fetch_account as _compte_discord
from ..discord_link import open_login as _ouvrir_connexion_discord
from ..market import PriceBook
from ..report import contributor_id as _identifiant_contributeur
from ..report import send_report as _envoyer_rapport
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

    def resize(self, hauteur: int) -> None:
        """Ajuste la hauteur du panneau à son contenu.

        Implémentation par défaut vide : un panneau qui ne sait pas se
        redimensionner reste parfaitement utilisable, il montre simplement
        moins d'objets à la fois. Les tests s'en servent tels quels.
        """


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
                    "verdict": session.verdict,
                    "ecart": session.ecart,
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

        # ⭐ L'ANCIEN calibrage est relu AVANT d'être écrasé. Sans ça, on ne
        # peut pas dire « celui d'avant était meilleur », qui est justement le
        # cas vécu : Maxime a recalibré en cours de session et remplacé une
        # zone de 22 rangées à force 0,53 par une de 5 rangées à force 0,16.
        # Ses objets n'étaient plus lus du tout, et rien ne le lui disait.
        try:
            precedent = Calibration.load()
        except ValueError:
            precedent = None

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
            "doutes": calibrage.doutes(precedent),
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

    def recalibrate(self, *, monitor: int = 1) -> dict[str, Any]:
        """Recalibre la zone PENDANT une session, sans perdre le butin déjà
        compté ni redémarrer la session.

        ⭐ Compose deux mécanismes qui existent déjà et sont déjà testés
        séparément : `pause()` verse les compteurs de la tranche qui s'achève
        dans les totaux sans y toucher, `resume()`-style relance avec une
        boucle NEUVE (`reprise=True`), dont la première lecture amorce le
        suivi avec ce que la zone affiche à l'écran sans rien compter.
        Recalibrer, c'est juste écrire une nouvelle zone entre les deux :
        `calibrate()` la sauve sur disque, et `CaptureWorker.start()` la
        relit à cet instant via son `calibration_loader`.

        ⚠️ Ne touche NI à `session.is_paused` NI à la durée : ce n'est pas une
        pause, c'est une coupure de quelques secondes de la même farme,
        traitée comme n'importe quel autre trou de cadence de la boucle.

        ⚠️ Si la session était DÉJÀ en pause au moment du clic, la capture
        n'est PAS relancée : la relancer ferait tourner le fil en écrivant du
        butin alors que `session.is_paused` resterait vrai en base, une
        session qui capture en croyant être en pause. La zone neuve est
        quand même enregistrée sur disque, prête pour la prochaine reprise
        explicite (bouton Reprendre), exactement comme aujourd'hui pour
        « Calibrer la zone » utilisé avant de farmer.

        ⚠️ Tenu sous verrou de bout en bout, écran compris (~2 à 4 s) : c'est
        ce qui empêche un `pause()`/`stop()` concurrent de s'intercaler entre
        la suspension et la relance et de retomber dans le même piège. Les
        autres méthodes de cycle de vie (`start`, `stop`, `pause`, `resume`)
        font déjà ce compromis pour la même raison.
        """
        with self.lock:
            if self.session_id is None:
                raise CaptureUnavailable("aucune session en cours : rien à recalibrer")
            session_id = self.session_id
            capture_active = self.worker is not None and self.worker.running

            if capture_active and self.worker is not None:
                self.worker.pause()

            try:
                resultat = self.calibrate(monitor=monitor)
            finally:
                # Que le calibrage réussisse ou non, la capture qui tournait
                # avant doit repartir : une tentative ratée ne doit pas
                # laisser la session ouverte sans rien qui l'alimente, en
                # silence — le mode de défaillance que la section 1 du
                # CLAUDE.md refuse partout ailleurs. `not self.worker.running`
                # protège le cas (rare) où `pause()` n'aurait pas vraiment
                # arrêté le fil dans son délai : on ne tente alors pas de
                # relancer par-dessus un fil déjà vivant, comme `resume()`
                # le fait déjà.
                if capture_active and self.worker is not None and not self.worker.running:
                    self.worker.start(session_id, reprise=True)

            return resultat

    def send_report(self, message: str) -> dict[str, Any]:
        """Envoie un rapport de bogue au relais, avec le contexte technique.

        ⚠️ **Hors verrou, volontairement.** L'envoi part sur le réseau et peut
        durer jusqu'à dix secondes ; tenir le verrou d'`AppState` pendant ce
        temps figerait tout le reste, dont le rafraîchissement de l'écran et
        le bouton d'arrêt de session. Même raison que l'ouverture du panneau.
        Le contexte est lu par `snapshot()`, qui prend le verrou pour lui seul
        et le rend aussitôt.

        Le contexte est joint parce qu'un rapport sans version ni zone
        calibrée oblige à un aller-retour, et qu'un joueur qui vient de perdre
        une session de farm ne le fera pas.
        """
        etat = self.snapshot()
        reglages = etat.get("reglages") or {}
        capture = etat.get("capture") or {}
        contexte: dict[str, object] = {
            "version": etat.get("version", "inconnue"),
            "zone calibrée": reglages.get("calibrage") or "aucune",
            "session en cours": "oui" if etat.get("session") else "non",
            "capture en cours": "oui" if capture.get("en_cours") else "non",
            "lectures": capture.get("lectures", 0),
            "panne de capture": capture.get("erreur") or "aucune",
        }
        resultat = _envoyer_rapport(message, contexte=contexte)
        return {"envoye": resultat.envoye, "message": resultat.raison}

    def capturer_l_inventaire(self, session_id: int | None = None) -> dict[str, Any]:
        """Fige l'écran, pour garder la seule vérité qui n'est pas de l'OCR.

        ⚠️ **Hors verrou**, comme le reste de ce qui touche à l'écran.

        ⛔ Elle prend l'écran **tel qu'il est**. Si l'inventaire n'est pas
        ouvert, l'image n'en contiendra pas — c'est écrit à côté du bouton
        plutôt que découvert en ouvrant le fichier trois jours plus tard.

        Sans session précisée, on rattache à la dernière : le geste normal est
        « j'arrête, je compare », donc juste après.
        """
        cible = session_id if session_id is not None else self._derniere_session()
        if cible is None:
            return {
                "capture": False,
                "message": "Aucune session à rattacher : lance un farm d'abord.",
            }
        resultat = _capturer_inventaire(cible)
        return {"capture": resultat.reussie, "message": resultat.message, "session": cible}

    def _derniere_session(self) -> int | None:
        """L'identifiant de la session la plus récente, ou `None`."""
        with self.lock:
            if self.session_id is not None:
                return self.session_id
        sessions = self.store.sessions(limit=1)
        return int(sessions[0].id) if sessions else None

    def redimensionner_le_panneau(self, hauteur: int) -> dict[str, Any]:
        """Fait suivre au panneau la hauteur de son contenu.

        ⚠️ **Hors verrou**, comme l'ouverture du panneau : redimensionner passe
        par la couche graphique, et tenir le verrou d'`AppState` pendant ce
        temps figerait tout le reste, dont le bouton d'arrêt de session.

        Demandé par Maxime le 07/08/2026 : « on prend de plus en plus d'items
        en grindant », et la dernière ligne était coupée. La borne haute vit
        dans `app.py`, avec sa raison.
        """
        panneau = self.overlay
        if panneau is None:
            return {"redimensionne": False}
        panneau.resize(int(hauteur))
        return {"redimensionne": True}

    def preparer_l_archive(self) -> dict[str, Any]:
        """Rassemble journaux, réglages, calibrage et capture dans un zip.

        ⚠️ **Hors verrou**, comme `send_report` : la capture d'écran et la
        compression durent, et tenir le verrou d'`AppState` figerait le
        rafraîchissement et le bouton d'arrêt de session.

        ⛔ **Rien n'est envoyé.** L'archive est écrite chez le joueur et
        l'explorateur s'ouvre dessus : c'est lui qui la dépose. Elle contient
        les messages des autres joueurs, puisque la reconnaissance lit la zone
        de chat telle quelle. Voir l'en-tête de `bundle.py`.
        """
        etat = self.snapshot()
        apercu = self._apercu_de_la_zone()
        archive = _preparer_archive(etat=etat, apercu=apercu)
        _ouvrir_le_dossier(archive.chemin)
        return {
            "nom": archive.chemin.name,
            "octets": archive.octets,
            "contenu": _decrire_archive(archive),
            "message": (
                f"Archive prête : {archive.chemin.name} "
                f"({max(archive.octets // 1024, 1)} Ko). "
                "Le dossier s'est ouvert, dépose le fichier dans le salon Discord."
            ),
        }

    def _apercu_de_la_zone(self) -> bytes | None:
        """Une image de la zone calibrée, ou `None`. **Ne lève jamais.**

        ⭐ La zone calibrée, PAS l'écran entier. Un écran entier emporterait le
        jeu, les autres fenêtres ouvertes et tout ce qui traîne dessus, alors
        que ce qui sert à comprendre un défaut de comptage tient dans la bande
        que la reconnaissance lit. Le moins de vie privée possible pour la même
        information.

        ⚠️ Sans calibrage, on ne rend rien plutôt qu'un écran entier par
        défaut : ce serait exactement le contraire de la règle ci-dessus.
        """
        try:
            from ..capture.calibrate import Calibration, draw_preview
            from ..capture.screen import ScreenCapture

            calibrage = Calibration.load()
            if calibrage is None:
                return None
            with ScreenCapture() as capture:
                image = capture.grab(capture.target_monitor())
            return draw_preview(image, calibrage)
        except Exception as exc:
            # Volontairement large : c'est un confort. Une machine sans écran,
            # un pilote graphique fâché ou un calibrage illisible ne doivent
            # pas empêcher de joindre les journaux, qui sont l'essentiel.
            _log.warning("capture de la zone impossible pour l'archive : %s", exc)
            return None

    def compte_discord(self) -> dict[str, Any]:
        """L'état du rattachement Discord, tel qu'il doit s'afficher.

        ⚠️ **Hors verrou**, comme `send_report` : c'est un appel réseau, et
        tenir le verrou d'`AppState` pendant plusieurs secondes figerait le
        rafraîchissement de l'écran et le bouton d'arrêt de session.

        ⛔ `inconnu` n'est pas `rattache: false`. L'interface doit garder ce
        qu'elle affichait plutôt que d'annoncer « pas connecté » à quelqu'un
        qui l'est : une coupure réseau lui ferait sinon refaire une
        autorisation pour rien, et douter que le rattachement tienne.
        """
        compte = _compte_discord(_identifiant_contributeur())
        return {"rattache": compte.rattache, "nom": compte.nom, "inconnu": compte.inconnu}

    def connecter_discord(self) -> dict[str, Any]:
        """Ouvre le navigateur du système sur la page de rattachement.

        Le navigateur du système, pas la fenêtre de Butin : une page
        d'autorisation sans barre d'adresse est exactement ce qu'on apprend aux
        gens à ne pas remplir. Là, la personne voit `discord.com` et son
        cadenas.

        Rien n'est attendu ici : le rattachement se termine dans le navigateur,
        et c'est `compte_discord()` qui l'apprendra ensuite. Bloquer sur une
        réponse qui n'arrive jamais est le défaut que la session rubin a
        constaté le 06/08/2026 et corrigé en ajoutant `/v1/discord/compte`.
        """
        ouvert = _ouvrir_connexion_discord(_identifiant_contributeur())
        if ouvert:
            return {
                "ouvert": True,
                "message": "Autorise Butin dans ton navigateur, puis reviens ici.",
            }
        return {
            "ouvert": False,
            "message": "Impossible d'ouvrir le navigateur. Vérifie ta connexion, puis réessaie.",
        }

    def loot_a_controler(self, session_id: int) -> list[dict[str, Any]]:
        """Ce que la session a compté, objet par objet, pour le contrôle.

        Trié du plus nombreux au moins nombreux, et ce n'est pas cosmétique :
        Maxime l'a dit d'expérience, « c'est surtout sur les tokens qu'on loote
        beaucoup » que le compteur se trompe. Mettre les grosses quantités en
        tête rend vérifiable en trois lignes ce qui compte vraiment, au lieu
        d'exiger une saisie complète que personne ne ferait.
        """
        with self.lock:
            langue = self.settings.language
        quantites = self.store.quantities(session_id)
        deja = self.store.item_controls(session_id)

        par_objet: dict[int, int] = {}
        for (item_id, _niveau), qte in quantites.items():
            par_objet[item_id] = par_objet.get(item_id, 0) + qte

        lignes = [
            {
                "item_id": item_id,
                "nom": self._name(item_id, langue),
                "compte": compte,
                # `None` et non `compte` : ne pas savoir n'est pas savoir que
                # c'est juste. Pré-remplir avec le compte ferait valider d'un
                # clic ce que personne n'a regardé.
                "reel": deja[item_id][1] if item_id in deja else None,
            }
            for item_id, compte in par_objet.items()
        ]
        # Trié sur `par_objet` plutôt que sur la valeur relue du dictionnaire :
        # celle-ci est typée « ce que peut contenir un JSON », donc pas un
        # entier aux yeux du vérificateur, et la contraindre à cet endroit
        # masquerait un vrai problème le jour où elle n'en serait plus un.
        lignes.sort(key=lambda ligne: -par_objet[int(str(ligne["item_id"]))])
        return lignes

    def set_verdict(self, session_id: int, verdict: str, ecart: int | None) -> dict[str, Any]:
        """Enregistre le contrôle du joueur, et le remonte au salon Discord.

        ⭐ Pourquoi l'envoyer et pas seulement l'écrire : un écart constaté chez
        quelqu'un est la SEULE mesure qui puisse contredire à la fois le
        compteur et le banc d'essai, qui lisent les mêmes pixels avec le même
        moteur et peuvent donc se tromper ensemble. Gardée sur sa machine, elle
        ne sert à personne.

        ⚠️ L'envoi peut échouer sans que ça remette en cause l'enregistrement :
        le verdict est écrit d'abord, et il le reste. Perdre le constat parce
        que le réseau a hoqueté serait perdre la seule donnée qui vaut.
        """
        self.store.set_verdict(session_id, verdict, ecart)

        session = self.store.get_session(session_id)
        if session is None:
            return {"verdict": verdict, "ecart": ecart, "envoye": False, "message": ""}

        quantites = self.store.quantities(session_id)
        compte = sum(quantites.values())
        if verdict == "exact":
            titre = f"Contrôle : EXACT ({compte} unités)"
        else:
            signe = "de trop" if (ecart or 0) > 0 else "de moins"
            titre = f"Contrôle : ÉCART de {abs(ecart or 0)} unités {signe} (compté {compte})"

        controles = self.store.item_controls(session_id)
        contexte: dict[str, object] = {
            "spot": session.spot or "inconnu",
            "durée": f"{session.duration_s(time.time()) / 60:.1f} min",
            "objets distincts": len(quantites),
            "unités comptées": compte,
            "écart annoncé": "aucun" if verdict == "exact" else ecart,
        }
        # ⭐ Le DÉTAIL par objet, pas seulement le total. Un écart global ne dit
        # pas OÙ ça dérape, alors que c'est toute la question : le compteur se
        # trompe sur certains objets et pas sur d'autres, et savoir lesquels
        # est ce qui permet de chercher au bon endroit.
        with self.lock:
            langue = self.settings.language
        for item_id, (compte_objet, reel) in sorted(
            controles.items(), key=lambda paire: -abs(paire[1][0] - paire[1][1])
        ):
            if compte_objet == reel:
                continue
            nom = self._name(item_id, langue)
            contexte[f"écart · {nom}"] = f"compté {compte_objet}, réel {reel}"
        non_verifies = len(quantites) - len(controles)
        if non_verifies > 0:
            # Dit explicitement ce qui n'a PAS été regardé : sans ça, un
            # contrôle partiel se lirait comme un contrôle complet.
            contexte["objets non vérifiés"] = non_verifies
        resultat = _envoyer_rapport(titre, contexte=contexte)
        return {
            "verdict": verdict,
            "ecart": ecart,
            "envoye": resultat.envoye,
            "message": resultat.raison,
        }

    def install_update(self) -> dict[str, Any]:
        """Télécharge et lance l'installeur de la version disponible.

        ⚠️ **Hors verrou**, comme l'envoi de rapport : le téléchargement pèse
        des dizaines de mégaoctets et peut durer une minute. Tenir le verrou
        d'`AppState` figerait tout le reste, dont le bouton d'arrêt de session.

        ⛔ **Ne ferme rien.** L'installeur possède le cycle
        fermeture-réouverture, voir `autoupdate.launch_installer`.
        """
        info = self.update_info
        if info is None or not info.disponible:
            return {"lance": False, "message": "Aucune mise à jour disponible."}
        lance, message = install_update(info.version)
        return {"lance": lance, "message": message}


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
        # ⚠️ `X-Content-Type-Options: nosniff` est envoyé plus bas : un type
        # inconnu part donc en `application/octet-stream` et le navigateur
        # REFUSE de l'afficher, au lieu de deviner. C'est le bon comportement,
        # mais ça veut dire que tout nouveau format servi ici doit être déclaré
        # dans cette table, sinon il se télécharge au lieu de s'afficher.
        types = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css",
            ".js": "text/javascript",
            ".png": "image/png",
            ".svg": "image/svg+xml",
            ".ico": "image/x-icon",
        }
        self.send_response(200)
        self.send_header("Content-Type", types.get(chemin.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(corps)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(corps)

    def _verdict(self) -> None:
        """`POST /api/historique/<id>/verdict`.

        Un verdict inconnu ou un identifiant illisible rend 400 : c'est une
        requête malformée, pas une panne. Un écart nul avec le verdict
        « ecart » est refusé aussi — annoncer un écart de zéro veut dire
        « exact », et laisser passer les deux façons de dire la même chose
        rendrait les relevés incomparables entre eux.
        """
        brut = self.path[len("/api/historique/") : -len("/verdict")]
        try:
            session_id = int(brut)
        except ValueError:
            self._send_json({"erreur": "identifiant de session invalide"}, status=400)
            return

        corps = self._read_json()
        verdict = str(corps.get("verdict", ""))
        if verdict not in ("exact", "ecart"):
            self._send_json({"erreur": "verdict attendu : exact ou ecart"}, status=400)
            return

        if self.state.store.get_session(session_id) is None:
            self._send_json({"erreur": "session introuvable"}, status=404)
            return

        ecart: int | None = None
        if verdict == "ecart":
            # ⭐ On reçoit les nombres RÉELS, pas un écart. Demander un écart
            # revenait à demander au joueur de faire la soustraction, donc de
            # se tromper — exactement le raisonnement des cases à cocher du
            # profil de taxe, où on ne demande pas le pourcentage.
            reels = corps.get("reels")
            if not isinstance(reels, dict) or not reels:
                self._send_json({"erreur": "il faut au moins un objet contrôlé"}, status=400)
                return
            comptes: dict[int, int] = {
                int(str(ligne["item_id"])): int(str(ligne["compte"]))
                for ligne in self.state.loot_a_controler(session_id)
            }
            controles: dict[int, tuple[int, int]] = {}
            for cle, valeur in reels.items():
                try:
                    item_id = int(cle)
                    reel = int(valeur)
                except (TypeError, ValueError):
                    self._send_json({"erreur": f"nombre illisible pour « {cle} »"}, status=400)
                    return
                if reel < 0:
                    self._send_json({"erreur": "un inventaire n'est jamais négatif"}, status=400)
                    return
                if item_id not in comptes:
                    # Un objet que la session n'a pas compté n'a rien à faire
                    # dans son contrôle : accepter le ferait entrer un écart
                    # sur une quantité qui n'existe pas.
                    self._send_json(
                        {"erreur": f"l'objet {item_id} n'a pas été compté dans cette session"},
                        status=400,
                    )
                    return
                controles[item_id] = (comptes[item_id], reel)
            ecart = self.state.store.set_item_controls(session_id, controles)

        self._send_json(self.state.set_verdict(session_id, verdict, ecart))

    def _objets_a_controler(self) -> None:
        """`GET /api/historique/<id>/objets` : ce que la session a compté."""
        brut = self.path[len("/api/historique/") : -len("/objets")]
        try:
            session_id = int(brut)
        except ValueError:
            self._send_json({"erreur": "identifiant de session invalide"}, status=400)
            return
        if self.state.store.get_session(session_id) is None:
            self._send_json({"erreur": "session introuvable"}, status=404)
            return
        self._send_json({"objets": self.state.loot_a_controler(session_id)})

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
        elif self.path == "/butin.png":
            # La marque du logiciel : favicon des deux fenêtres, et logo dans
            # l'en-tête. Servie depuis `static/` comme les pages, donc elle
            # suit la distribution figée sans réglage supplémentaire.
            self._send_file("butin.png")
        elif self.path == "/api/etat":
            self._send_json(self.state.snapshot())
        elif self.path == "/api/historique":
            self._send_json({"sessions": self.state.history()})
        elif self.path == "/api/discord":
            self._send_json(self.state.compte_discord())
        elif self.path.startswith("/api/historique/") and self.path.endswith("/objets"):
            self._objets_a_controler()
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
        elif self.path == "/api/session/recalibrer":
            try:
                self._send_json(self.state.recalibrate())
            except (CaptureUnavailable, CalibrationError) as exc:
                # 409 comme les autres refus explicables : pas de session en
                # cours, ou la fenêtre de chat introuvable cette fois-ci.
                self._send_json({"erreur": str(exc)}, status=409)
        elif self.path == "/api/session/arreter":
            self.state.stop()
            self._send_json(self.state.snapshot())
        elif self.path.startswith("/api/historique/") and self.path.endswith("/verdict"):
            self._verdict()
        elif self.path == "/api/maj":
            # Toujours 200, comme /api/rapport : le corps porte `lance` et un
            # message affichable. Le serveur local a fait son travail même
            # quand le telechargement echoue.
            self._send_json(self.state.install_update())
        elif self.path == "/api/rapport":
            message = str(self._read_json().get("message", ""))
            # Toujours 200, même quand l'envoi échoue : le corps porte
            # `envoye` et un message écrit pour être affiché tel quel. Un code
            # d'erreur HTTP ferait afficher « erreur serveur » à la page alors
            # que le serveur local a parfaitement fait son travail, et que la
            # cause est chez le relais ou sur le réseau du joueur.
            self._send_json(self.state.send_report(message))
        elif self.path == "/api/inventaire":
            # Toujours 200 : le corps porte `capture` et un message
            # affichable tel quel, comme /api/rapport et /api/archive.
            self._send_json(self.state.capturer_l_inventaire())
        elif self.path == "/api/panneau/taille":
            hauteur = self._read_json().get("hauteur", 0)
            try:
                self._send_json(self.state.redimensionner_le_panneau(int(hauteur)))
            except (TypeError, ValueError):
                self._send_json({"erreur": "hauteur invalide"}, status=400)
        elif self.path == "/api/archive":
            # Toujours 200, comme /api/rapport : le corps porte le nom de
            # l'archive, son contenu détaillé et ce qui a manqué.
            self._send_json(self.state.preparer_l_archive())
        elif self.path == "/api/discord/connexion":
            # Toujours 200, même raison que /api/rapport : le corps porte
            # `ouvert` et un message affichable tel quel.
            self._send_json(self.state.connecter_discord())
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
