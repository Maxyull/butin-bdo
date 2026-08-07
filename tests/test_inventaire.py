"""Tests de la capture d'inventaire.

⭐ Pourquoi cette image existe : l'inventaire est la **seule** vérité de ce
logiciel qui ne passe par aucune reconnaissance d'écran. Le compteur et le banc
d'essai lisent les mêmes pixels avec le même moteur, donc ils peuvent se
tromper ensemble. Seul un inventaire compté à la main peut les contredire tous
les deux.

⛔ Le fil rouge des tests ci-dessous : ce module **ne touche jamais au jeu** et
**n'envoie jamais rien**. Les deux se vérifient, ils ne se promettent pas.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from butin import bundle
from butin.capture import inventaire
from butin.capture.inventaire import capturer, captures_existantes, chemin_pour


@pytest.fixture
def racine(tmp_path: Path) -> Path:
    (tmp_path / "rapports").mkdir(parents=True)
    return tmp_path


class TestIlNeToucheJamaisAuJeu:
    def test_aucune_injection_d_entree_dans_le_module(self) -> None:
        """⛔ Le test qui protège le compte de quelqu'un.

        Automatiser la barre de recherche du jeu rendrait la lecture de
        l'inventaire triviale, et c'est précisément pour ça qu'il faut
        l'interdire par écrit : injecter des entrées dans un client de Black
        Desert est sanctionné par un bannissement.

        Ce test lit la source. Une intention documentée qu'aucun test ne garde
        finit toujours par se faire contredire par une bonne idée pressée.
        """
        source = Path(inventaire.__file__).read_text(encoding="utf-8")
        interdits = (
            "SendInput",
            "keybd_event",
            "pyautogui",
            "pydirectinput",
            "keyboard.",
            "PostMessage",
            "SendMessage",
        )
        for mot in interdits:
            assert mot not in source, f"« {mot} » enverrait des entrées dans le jeu"

    def test_aucun_envoi_reseau_dans_le_module(self) -> None:
        """L'image reste sur le disque. Elle part avec l'archive, si le joueur
        la dépose, et pas autrement : une capture d'écran entier montre bien
        plus qu'un inventaire."""
        source = Path(inventaire.__file__).read_text(encoding="utf-8")
        for mot in ("requests", "urlopen", "http", "socket"):
            assert mot not in source, f"« {mot} » ferait sortir l'image de la machine"


class TestOuElleVit:
    def test_elle_vit_avec_les_journaux(self, racine: Path) -> None:
        """Le joueur n'a qu'un seul dossier à connaître."""
        assert chemin_pour(12, racine).parent == racine / "rapports"

    def test_une_seule_capture_par_session(self, racine: Path) -> None:
        """⛔ Recapturer REMPLACE, ça n'empile pas.

        Ranger son inventaire puis recapturer doit corriger l'image, pas en
        ajouter une seconde : l'archive emporterait alors deux écrans dont
        personne ne saurait lequel fait foi.
        """
        assert chemin_pour(12, racine) == chemin_pour(12, racine)
        assert chemin_pour(12, racine) != chemin_pour(13, racine)

    def test_le_nom_porte_le_numero_de_session(self, racine: Path) -> None:
        assert chemin_pour(9, racine).name == "inventaire-0009.png"


class TestElleNeLeveJamais:
    def test_sans_ecran_elle_rend_un_message_au_lieu_de_planter(
        self, racine: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Même garantie que `send_report` et `preparer`.

        L'intégration continue n'a pas d'écran, et une machine de joueur peut
        avoir un pilote graphique fâché. Aucun de ces cas ne justifie
        d'interrompre quelqu'un qui vient de finir sa session.
        """
        from butin.capture import screen

        def casse(*args: object, **kwargs: object) -> object:
            raise RuntimeError("pas d'écran")

        monkeypatch.setattr(screen, "ScreenCapture", casse)
        resultat = capturer(1, racine=racine)
        assert resultat.reussie is False
        assert "impossible" in resultat.message.lower()
        assert resultat.chemin is None


class TestElleAtteintVraimentQuelquUn:
    def test_l_archive_joint_la_capture(self, racine: Path) -> None:
        """⛔ Régression : une image écrite et jamais jointe ne sert à personne.

        C'est le sort de tout diagnostic qu'on range sans le transmettre. Le
        test lit le CONTENU réel de l'archive.
        """
        (racine / "rapports" / "inventaire-0007.png").write_bytes(b"\x89PNG\r\n\x1a\n fausse")
        (racine / "rapports" / "session-0007-x.jsonl").write_text("{}\n", encoding="utf-8")

        archive = bundle.preparer(racine=racine)
        with zipfile.ZipFile(archive.chemin) as zf:
            noms = zf.namelist()
        assert any("inventaire-0007.png" in n for n in noms), f"capture non jointe : {noms}"

    def test_seule_la_plus_recente_part(self, racine: Path) -> None:
        """⛔ Une seule, et la raison est mesurée.

        Une capture 2560x1440 pèse 5,1 Mo et un PNG ne se compresse plus :
        l'archive fait 5,3 Mo avec une, elle en ferait 10,6 avec deux. Discord
        refuse au-delà de 10 Mo sans abonnement, et une archive trop lourde
        pour être déposée n'atteint personne.
        """
        for i in range(6):
            (racine / "rapports" / f"inventaire-{i:04d}.png").write_bytes(b"x")
        assert len(captures_existantes(racine)) == 6

        archive = bundle.preparer(racine=racine)
        with zipfile.ZipFile(archive.chemin) as zf:
            jointes = [n for n in zf.namelist() if n.startswith("inventaires/")]
        assert len(jointes) == 1 == bundle.INVENTAIRES_JOINTS

    def test_une_archive_trop_lourde_le_DIT(self, racine: Path, monkeypatch) -> None:
        """Sinon le joueur le découvre au moment où Discord refuse le fichier,
        après avoir fait tout le travail."""
        monkeypatch.setattr(bundle, "OCTETS_AVANT_AVERTISSEMENT", 10)
        (racine / "rapports" / "session-x.jsonl").write_text("x" * 500, encoding="utf-8")
        archive = bundle.preparer(racine=racine)
        assert any("10 Mo" in a for a in archive.avertissements)

    def test_sans_capture_l_archive_ne_dit_rien_de_special(self, racine: Path) -> None:
        """Ne pas avoir capturé n'est pas une anomalie à signaler.

        Le joueur qui n'a pas encore utilisé le bouton n'a rien fait de mal, et
        un avertissement de plus noierait ceux qui comptent.
        """
        archive = bundle.preparer(racine=racine)
        assert not any("inventaire" in a for a in archive.avertissements)


class TestLaConsigneEstAvantLeBouton:
    def test_la_page_dit_d_ouvrir_l_inventaire_AVANT(self) -> None:
        """⛔ Elle prend l'écran tel qu'il est, elle ne devine pas.

        Si l'inventaire est fermé, l'image ne contiendra rien d'utile et
        personne ne s'en rendra compte avant d'ouvrir le fichier, peut-être
        trois jours plus tard, quand l'inventaire aura bougé.
        """
        page = (
            Path(__file__).resolve().parents[1] / "src" / "butin" / "ui" / "static" / "index.html"
        ).read_text(encoding="utf-8")
        assert 'id="bouton-inventaire"' in page
        assert "Ouvre ton inventaire dans le jeu avant de cliquer" in page

    def test_la_page_n_utilise_pas_de_style_en_ligne_pour_cette_note(self) -> None:
        """Ce fichier en comptait vingt-huit, avec sept valeurs pour la même
        intention. On ne recommence pas."""
        page = (
            Path(__file__).resolve().parents[1] / "src" / "butin" / "ui" / "static" / "index.html"
        ).read_text(encoding="utf-8")
        debut = page.index('id="bouton-inventaire"')
        assert "style=" not in page[debut : debut + 700]
