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
from typing import Any

from ..capture.calibrate import Calibration, CalibrationError
from ..capture.worker import CaptureUnavailable, CaptureWorker
from ..catalog import ItemCatalog, ItemMatcher
from ..market import PriceBook, Region
from ..store import SessionStore, compute
from ..store.stats import MARKET_RATE_BASE

_log = logging.getLogger(__name__)

# Boucle locale uniquement. Voir la note de sécurité en tête de module avant de
# toucher à cette valeur.
HOST = "127.0.0.1"
DEFAULT_PORT = 8771

STATIC = Path(__file__).resolve().parent / "static"

# Plafond de taille d'un corps de requête. Les nôtres font quelques dizaines
# d'octets : au-delà, c'est autre chose et on refuse plutôt que de lire.
MAX_BODY = 64 * 1024


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
    ) -> None:
        self.store = store
        self.book = book
        self.worker = worker
        """Ce qui fait tourner la capture. Optionnel pour que l'interface reste
        consultable sans écran ni moteur de reconnaissance, ce dont les tests et
        une machine sans affichage profitent."""
        self.catalog = catalog
        """Sert à nommer les objets. C'est tout l'objet du sélecteur de langue :
        sans lui, il ne changerait rien de visible."""
        self.lock = threading.Lock()
        self.language = "fr"
        self.region = Region.EU
        self.market_rate = MARKET_RATE_BASE
        self.session_id: int | None = None

    # -- lecture ---------------------------------------------------------

    def snapshot(self, *, now: float | None = None) -> dict[str, Any]:
        maintenant = time.time() if now is None else now
        with self.lock:
            session_id = self.session_id
            reglages = {
                "langue": self.language,
                "region": self.region.value,
                "taux_marche": self.market_rate,
            }
            taux = self.market_rate
            langue = self.language

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

        if session_id is None:
            return {
                "reglages": reglages,
                "session": None,
                "stats": None,
                "butin": [],
                "capture": capture,
            }

        session = self.store.get_session(session_id)
        if session is None:
            return {
                "reglages": reglages,
                "session": None,
                "stats": None,
                "butin": [],
                "capture": capture,
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
            "capture": capture,
        }

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
        with self.lock:
            langue = data.get("langue")
            if langue in ("fr", "us"):
                self.language = langue
            region = data.get("region")
            if isinstance(region, str):
                try:
                    self.region = Region(region)
                except ValueError:
                    _log.warning("région inconnue ignorée : %r", region)
            taux = data.get("taux_marche")
            if isinstance(taux, (int, float)) and 0 < float(taux) <= 1:
                self.market_rate = float(taux)

    def calibrate(self, *, monitor: int = 1) -> dict[str, Any]:
        """Cherche la fenêtre de chat et enregistre la zone. Rend ce qu'elle contient.

        ⚠️ Rend un **extrait de ce qui a été lu**, et pas seulement « c'est
        calibré ». La détection cherche ce qui se répète verticalement ; elle ne
        sait pas d'où vient l'image. Un essai réel a calibré très proprement sur
        une capture du chat ouverte dans une visionneuse : tout était juste sauf
        que ce n'était pas le jeu. Personne ne confond les deux quand les lignes
        lues sont sous ses yeux.
        """
        from ..capture.calibrate import find_chat, measure_width
        from ..capture.lines import parse_frame
        from ..capture.ocr import TextReader
        from ..capture.screen import ScreenCapture

        with ScreenCapture(monitor=monitor) as capture:
            ecran = capture.target_monitor()
            image = capture.grab(ecran)

        calibrage = find_chat(image, origin=(ecran.left, ecran.top))
        lecteur = TextReader()
        calibrage = measure_width(image, calibrage, lecteur)
        calibrage.save()

        zone = calibrage.region
        rangees = lecteur.read_text(image[zone.top : zone.bottom, zone.left : zone.right])
        gains = 0
        if self.catalog is not None:
            gains = len(parse_frame(list(rangees), ItemMatcher(self.catalog)))
        return {
            "zone": calibrage.describe(),
            "rangees": calibrage.rows,
            "extrait": [ligne[:90] for ligne in rangees[:4]],
            "gains": gains,
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
                started_at=maintenant, spot=spot, region=self.region.value
            )
            if self.worker is not None:
                try:
                    self.worker.start(session.id)
                except Exception:
                    self.store.end_session(session.id, ended_at=maintenant)
                    raise
            self.session_id = session.id
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
        elif self.path == "/api/etat":
            self._send_json(self.state.snapshot())
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
        elif self.path == "/api/calibrer":
            try:
                self._send_json(self.state.calibrate())
            except CalibrationError as exc:
                # 409 comme le refus de démarrer : ce n'est pas une panne du
                # serveur, c'est une condition que l'utilisateur peut lever.
                self._send_json({"erreur": str(exc)}, status=409)
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
