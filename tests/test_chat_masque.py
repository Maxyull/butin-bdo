"""Tests de l'alerte « je ne vois plus le chat ».

⭐ Le cas fondateur est réel. Session 0014 du 07/08/2026, calibrage impeccable
(force 0,61, 23 rangées, 1 127 s) : Maxime ouvre le menu Échap, qui recouvre le
chat.

    plage aveugle : de t=771,8 à t=1018,9  →  247 secondes d'affilée
    total aveugle : 251,9 s, soit 22,4 % de la session
    manquant      : 560 objets sur 4 080

Butin a continué d'afficher son total et son silver par heure comme si de rien
n'était. **C'est la panne qui ne se voit pas** : le fil tourne, le calibrage est
bon, et un compteur qui n'augmente plus ressemble à un farm calme.
"""

from __future__ import annotations

from butin.capture.worker import SECONDES_AVANT_ALERTE, CaptureStatus


def _etat(secondes: float, *, running: bool = True) -> CaptureStatus:
    return CaptureStatus(
        running=running,
        ticks=100,
        ocr_reads=50,
        skipped_frames=0,
        lost_resolved=0,
        recorded_events=601,
        recorded_silver=0,
        secondes_sans_texte=secondes,
    )


class TestLeSeuilVientDesDonnees:
    def test_les_247_secondes_du_menu_echap_declenchent_l_alerte(self) -> None:
        """⛔ Le cas qui a coûté 560 objets."""
        assert _etat(247.0).chat_masque is True

    def test_les_4_9_secondes_du_demarrage_ne_declenchent_RIEN(self) -> None:
        """⛔ L'autre moitié, et c'est elle qui rend l'alerte utilisable.

        Au démarrage, le chat était encore vide pendant 4,9 s. Une alerte qui
        se déclencherait là serait vue à chaque session, donc apprise par cœur
        et ignorée le jour où elle compte.
        """
        assert _etat(4.9).chat_masque is False

    def test_le_seuil_separe_les_deux_populations_avec_de_la_marge(self) -> None:
        """Facteur six en dessous, facteur huit au-dessus.

        Les seuls silences observés sur une session réelle d'un quart d'heure
        sont 4,9 s et 247 s. Il n'y a rien entre les deux, et le seuil est posé
        dans ce vide plutôt qu'au bord de l'un d'eux.
        """
        assert 4.9 * 5 < SECONDES_AVANT_ALERTE < 247.0 / 5

    def test_juste_sous_le_seuil_rien_ne_se_declenche(self) -> None:
        assert _etat(SECONDES_AVANT_ALERTE - 0.1).chat_masque is False

    def test_au_seuil_exact_l_alerte_part(self) -> None:
        assert _etat(SECONDES_AVANT_ALERTE).chat_masque is True


class TestCeQuiNeDoitPasAlerter:
    def test_une_capture_arretee_n_alerte_jamais(self) -> None:
        """Plus personne ne regarde : l'alerte n'aurait plus de sens.

        `status()` remet le compteur à zéro quand le fil ne tourne plus, sans
        quoi une session arrêtée afficherait « je ne vois plus le chat » pour
        l'éternité.
        """
        assert _etat(0.0, running=False).chat_masque is False

    def test_zero_seconde_de_silence_n_alerte_pas(self) -> None:
        assert _etat(0.0).chat_masque is False


class TestCeQueLInterfaceRecoit:
    def test_les_deux_champs_partent_dans_le_dictionnaire(self) -> None:
        """Régression de câblage : la propriété peut exister et ne pas sortir.

        L'interface ne lit que `to_dict()`. Une valeur calculée qui n'y figure
        pas est une valeur que personne ne verra jamais.
        """
        donnees = _etat(247.0).to_dict()
        assert donnees["chat_masque"] is True
        assert donnees["secondes_sans_texte"] == 247.0

    def test_le_panneau_affiche_l_alerte(self) -> None:
        """Régression : le champ peut arriver et n'être branché nulle part."""
        from pathlib import Path

        page = (
            Path(__file__).resolve().parents[1] / "src" / "butin" / "ui" / "static" / "overlay.html"
        ).read_text(encoding="utf-8")
        assert 'id="masque"' in page, "le bloc d'alerte a disparu du panneau"
        assert "chat_masque" in page, "le panneau ne lit plus l'état du chat"
        assert "n'est plus visible depuis" in page


class TestLePanneauSuitSonContenu:
    """La seconde demande de Maxime : « on prend de plus en plus d'items »."""

    def test_la_liste_n_a_plus_de_hauteur_fixe_qui_cache_des_objets(self) -> None:
        """⛔ Régression sur le défaut exact.

        `#drops` valait `max-height: 260px; overflow: hidden` : au-delà, les
        objets n'étaient pas coupés à moitié ni signalés, ils étaient
        **absents**. Maxime avait neuf objets distincts et n'en voyait pas la
        fin.
        """
        from pathlib import Path

        page = (
            Path(__file__).resolve().parents[1] / "src" / "butin" / "ui" / "static" / "overlay.html"
        ).read_text(encoding="utf-8")
        debut = page.index("#drops {")
        regle = page[debut : debut + 120]
        assert "overflow: hidden" not in regle, "la liste cache encore des objets en silence"
        assert "overflow-y: auto" in regle, "la liste ne peut plus défiler à la borne haute"

    def test_la_hauteur_est_bornee(self) -> None:
        """Sans plafond, un long farm finirait par couvrir l'écran du jeu."""
        from butin.app import OVERLAY_HEIGHT, OVERLAY_HEIGHT_MAX

        assert OVERLAY_HEIGHT < OVERLAY_HEIGHT_MAX

    def test_les_deux_bornes_sont_APPLIQUEES_pas_seulement_declarees(self) -> None:
        """⛔ Une borne déclarée et non appliquée ne borne rien.

        C'est le défaut qui s'est répété quatre fois aujourd'hui : la
        justification écrite, le code absent. Ce test demande à `resize` ce
        qu'il a réellement transmis à la fenêtre.
        """
        from butin.app import OVERLAY_HEIGHT, OVERLAY_HEIGHT_MAX, OVERLAY_WIDTH, Overlay

        class _Fenetre:
            def __init__(self) -> None:
                self.appels: list[tuple[int, int]] = []

            def resize(self, largeur: int, hauteur: int) -> None:
                self.appels.append((largeur, hauteur))

        panneau = Overlay("http://127.0.0.1:0")
        fausse = _Fenetre()
        panneau._window = fausse

        panneau.resize(10_000)
        panneau.resize(10)
        panneau.resize(600)

        assert fausse.appels == [
            (OVERLAY_WIDTH, OVERLAY_HEIGHT_MAX),
            (OVERLAY_WIDTH, OVERLAY_HEIGHT),
            (OVERLAY_WIDTH, 600),
        ]

    def test_une_fenetre_qui_refuse_ne_leve_pas(self) -> None:
        """Même garantie que partout : un confort n'interrompt pas un farm."""
        from butin.app import Overlay

        class _Cassee:
            def resize(self, largeur: int, hauteur: int) -> None:
                raise RuntimeError("fenêtre partie")

        panneau = Overlay("http://127.0.0.1:0")
        panneau._window = _Cassee()
        panneau.resize(600)  # ne doit pas lever

    def test_un_panneau_absent_ne_fait_pas_echouer_le_redimensionnement(self) -> None:
        """Un confort ne doit jamais interrompre une session de farm."""
        import tempfile
        from pathlib import Path

        from butin.market import PriceBook, PriceCache
        from butin.store import SessionStore
        from butin.ui.server import AppState

        dossier = Path(tempfile.mkdtemp())
        magasin = SessionStore(dossier / "s.sqlite3")
        try:
            etat = AppState(magasin, PriceBook(client=None, cache=PriceCache(dossier / "p.json")))
            assert etat.redimensionner_le_panneau(600) == {"redimensionne": False}
        finally:
            magasin.close()
