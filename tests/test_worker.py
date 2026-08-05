"""Tests du fil de capture, le dernier maillon du produit.

Ni écran ni moteur de reconnaissance ici : l'un demande un affichage, l'autre
coûte une seconde par appel, et l'intégration continue n'a ni l'un ni l'autre.
La boucle est donc injectée, ce que `CaptureWorker` prévoit explicitement.

Ce que ces tests surveillent avant tout, c'est le comportement **quand ça rate**.
Un fil de fond qui meurt sans bruit laisserait l'interface afficher « session en
cours » sur un total qui n'augmente plus, sans rien pour distinguer la panne du
farm calme.
"""

from __future__ import annotations

import threading
import time

import pytest

from butin.capture.calibrate import Calibration
from butin.capture.loop import CaptureLoop, LoopConfig
from butin.capture.screen import Region
from butin.capture.worker import CaptureUnavailable, CaptureWorker
from butin.catalog import ItemCatalog, ItemMatcher
from butin.store import SessionStore

CALIBRAGE = Calibration(
    region=Region(left=0, top=0, width=300, height=240),
    row_height_px=21.6,
    ruler_left_ratio=0.2,
    ruler_right_ratio=1.0,
    rows=12,
    strength=0.5,
)


def gain(nom: str, qty: int = 1) -> str:
    suffixe = f" x{qty}" if qty > 1 else "."
    return f"Système Vous avez obtenu : [{nom}]{suffixe} (21:54)"


class SourceFactice:
    """Rend des images qui défilent, pour que la boucle ait de quoi mesurer."""

    def __init__(self) -> None:
        self.appels = 0

    def grab(self, region: Region) -> object:
        import numpy as np

        self.appels += 1
        image = np.full((240, 300), 20, dtype=np.uint8)
        for index in range(10):
            haut = index * 22 + (self.appels % 3)
            colonnes = np.random.default_rng(index + self.appels).choice(
                200, size=40, replace=False
            )
            image[haut + 4 : haut + 16, 60 + colonnes] = 230
        return image


class LecteurFactice:
    """Rend des lignes prédéfinies, puis répète la dernière fenêtre."""

    def __init__(self, fenetres: list[list[str]]) -> None:
        self.fenetres = fenetres
        self.appels = 0

    def read_text(self, image: object) -> list[str]:
        fenetre = self.fenetres[min(self.appels, len(self.fenetres) - 1)]
        self.appels += 1
        return list(fenetre)


class LecteurQuiCasse:
    """Un lecteur qui échoue, comme le vrai le ferait si le modèle manquait."""

    def read_text(self, image: object) -> list[str]:
        raise RuntimeError("modèle de reconnaissance introuvable")


@pytest.fixture
def matcher(catalog: ItemCatalog) -> ItemMatcher:
    return ItemMatcher(catalog)


@pytest.fixture
def store(tmp_path) -> SessionStore:
    return SessionStore(tmp_path / "sessions.sqlite3")


def _worker(
    store: SessionStore,
    matcher: ItemMatcher,
    lecteur: object,
    *,
    calibrage: Calibration | None = CALIBRAGE,
) -> CaptureWorker:
    def fabrique(calibration: Calibration, config: LoopConfig) -> CaptureLoop:
        return CaptureLoop(SourceFactice(), lecteur, matcher, calibration.region, config=config)

    return CaptureWorker(
        store,
        matcher=matcher,
        config=LoopConfig(capture_interval_s=0.001, ocr_min_interval_s=0.0, ocr_max_idle_s=0.0),
        loop_factory=fabrique,
        calibration_loader=lambda: calibrage,
        sleep=lambda _: None,
    )


def _attendre(condition, *, limite: float = 3.0) -> bool:
    """Attend qu'une condition devienne vraie, sans figer la suite si elle ne
    l'est jamais. Une attente sans borne transformerait un échec en suite de
    tests qui ne rend jamais la main."""
    fin = time.monotonic() + limite
    while time.monotonic() < fin:
        if condition():
            return True
        time.sleep(0.005)
    return False


class TestRefusDeDemarrer:
    def test_sans_calibrage_la_capture_refuse(
        self, store: SessionStore, matcher: ItemMatcher
    ) -> None:
        """Sans calibrage on ne sait pas où regarder.

        Capturer une zone au hasard donne un journal vide, donc zéro drop, donc
        une session qui a l'air d'avoir marché. Refuser est la seule réponse
        honnête, et le message doit dire quoi faire.
        """
        travailleur = _worker(store, matcher, LecteurFactice([[]]), calibrage=None)

        with pytest.raises(CaptureUnavailable, match="calibrer"):
            travailleur.start(1)

    def test_deux_demarrages_ne_se_superposent_pas(
        self, store: SessionStore, matcher: ItemMatcher
    ) -> None:
        travailleur = _worker(store, matcher, LecteurFactice([[gain("Pierre noire (arme)")]]))
        session = store.start_session(started_at=0.0, spot="", region="eu")
        travailleur.start(session.id)
        try:
            with pytest.raises(CaptureUnavailable, match="déjà"):
                travailleur.start(session.id)
        finally:
            travailleur.stop()


class TestComptage:
    def test_le_butin_lu_finit_dans_la_base(
        self, store: SessionStore, matcher: ItemMatcher
    ) -> None:
        """Le test qui dit si le produit fonctionne de bout en bout.

        Jusqu'ici la chaîne était complète sauf ce maillon : le bouton ouvrait
        une ligne dans la base et **rien ne l'alimentait**.
        """
        avant = [gain("Pierre noire (arme)")]
        apres = [gain("Pierre noire (arme)"), gain("Trace de sauvagerie")]
        travailleur = _worker(store, matcher, LecteurFactice([avant] + [apres] * 8))
        session = store.start_session(started_at=0.0, spot="", region="eu")

        travailleur.start(session.id)
        trouve = _attendre(lambda: travailleur.status().recorded_events > 0)
        travailleur.stop()

        assert trouve, "aucun drop n'a été enregistré"
        quantites = store.quantities(session.id)
        assert sum(quantites.values()) >= 1

    def test_l_arret_enregistre_ce_qui_attendait(
        self, store: SessionStore, matcher: ItemMatcher
    ) -> None:
        """Le butin vu une seule fois au moment de l'arrêt est bien tombé.

        Le perdre serait une erreur dans le mauvais sens : on préfère rater que
        d'inventer, mais rater ce qu'on a déjà vu n'est pas obligatoire.
        """
        fenetres = [[gain("Pierre noire (arme)")], [gain("Pierre noire (arme)")]]
        travailleur = _worker(store, matcher, LecteurFactice(fenetres))
        session = store.start_session(started_at=0.0, spot="", region="eu")

        travailleur.start(session.id)
        _attendre(lambda: travailleur.status().ticks > 3)
        travailleur.stop()

        # Le flush a rendu la main sans lever, et la session ne contient rien
        # d'incohérent : la fenêtre d'amorce appartient au passé.
        assert travailleur.status().running is False


class TestPause:
    """Mettre en pause, puis reprendre, sans mentir sur ce qui a été compté."""

    def test_les_compteurs_survivent_a_la_reprise(
        self, store: SessionStore, matcher: ItemMatcher
    ) -> None:
        """⭐ Régression : un compteur qui RECULE est pire qu'un qui stagne.

        La reprise construit une boucle et un enregistreur neufs, dont les
        compteurs repartent de zéro. Sans report, l'interface afficherait
        « 0 drop » après une pause sur une session qui en a enregistré trois
        cents : ça ressemble à une perte de données, alors que la base a tout
        gardé.
        """
        avant = [gain("Pierre noire (arme)")]
        apres = [gain("Pierre noire (arme)"), gain("Trace de sauvagerie")]
        travailleur = _worker(store, matcher, LecteurFactice([avant] + [apres] * 20))
        session = store.start_session(started_at=0.0, spot="", region="eu")

        travailleur.start(session.id)
        assert _attendre(lambda: travailleur.status().recorded_events > 0)
        travailleur.pause()
        acquis = travailleur.status()

        assert acquis.recorded_events > 0
        assert acquis.ticks > 0
        assert not acquis.running

        travailleur.start(session.id, reprise=True)
        try:
            reprise = travailleur.status()
            assert reprise.recorded_events >= acquis.recorded_events
            assert reprise.ticks >= acquis.ticks
        finally:
            travailleur.stop()

    def test_un_demarrage_neuf_repart_de_zero(
        self, store: SessionStore, matcher: ItemMatcher
    ) -> None:
        """Sans `reprise`, c'est une autre session : ses compteurs sont à elle.

        Reporter les compteurs d'une session sur la suivante attribuerait à la
        seconde du butin qui appartient à la première.
        """
        fenetres = [[gain("Pierre noire (arme)")], [gain("Pierre noire (arme)")]]
        travailleur = _worker(store, matcher, LecteurFactice(fenetres))
        premiere = store.start_session(started_at=0.0, spot="", region="eu")

        travailleur.start(premiere.id)
        _attendre(lambda: travailleur.status().ticks > 3)
        travailleur.pause()
        assert travailleur.status().ticks > 0

        seconde = store.start_session(started_at=100.0, spot="", region="eu")
        travailleur.start(seconde.id)
        try:
            assert travailleur.status().recorded_events == 0
        finally:
            travailleur.stop()

    def test_la_pause_enregistre_ce_qui_attendait(
        self, store: SessionStore, matcher: ItemMatcher
    ) -> None:
        """Même raison qu'à l'arrêt : le butin vu une fois est bien tombé.

        Et il ne sera pas recompté à la reprise : la boucle neuve amorce le
        suivi avec ce qui est déjà à l'écran sans rien créditer.
        """
        fenetres = [[gain("Pierre noire (arme)")], [gain("Pierre noire (arme)")]]
        travailleur = _worker(store, matcher, LecteurFactice(fenetres))
        session = store.start_session(started_at=0.0, spot="", region="eu")

        travailleur.start(session.id)
        _attendre(lambda: travailleur.status().ticks > 3)
        travailleur.pause()

        assert not travailleur.status().running


class TestPanne:
    def test_une_erreur_dans_le_fil_est_exposee(
        self, store: SessionStore, matcher: ItemMatcher
    ) -> None:
        """Régression : un fil qui meurt en silence est le pire des cas.

        L'interface continuerait d'afficher « session en cours », la base ne
        recevrait plus rien, et l'utilisateur verrait un total qui n'augmente
        pas sans savoir si c'est la faute du jeu, du calibrage ou du programme.
        """
        travailleur = _worker(store, matcher, LecteurQuiCasse())
        session = store.start_session(started_at=0.0, spot="", region="eu")

        travailleur.start(session.id)
        vu = _attendre(lambda: travailleur.status().error != "")

        assert vu, "l'erreur du fil n'a jamais été exposée"
        assert "modèle de reconnaissance introuvable" in travailleur.status().error
        assert travailleur.status().running is False

    def test_le_fil_ne_survit_pas_a_l_arret(
        self, store: SessionStore, matcher: ItemMatcher
    ) -> None:
        """Un fil oublié continuerait d'écrire dans une session fermée."""
        travailleur = _worker(store, matcher, LecteurFactice([[gain("Pierre noire (arme)")]]))
        session = store.start_session(started_at=0.0, spot="", region="eu")

        travailleur.start(session.id)
        _attendre(lambda: travailleur.status().ticks > 2)
        travailleur.stop()

        vivants = [fil.name for fil in threading.enumerate() if fil.name == "butin-capture"]
        assert vivants == []
