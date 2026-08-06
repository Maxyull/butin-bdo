"""Tests du journal de diagnostic par session.

Ce fichier est un outil de diagnostic : il ne doit JAMAIS devenir la cause du
problème qu'il sert à comprendre. La moitié des tests ci-dessous vérifient
exactement ça — qu'il se tait plutôt que d'échouer.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from butin import __version__
from butin.diagnostic import MAX_LECTURES, SessionJournal, dossier_des_rapports


def lignes(chemin: Path) -> list[dict[str, Any]]:
    return [
        json.loads(ligne)
        for ligne in chemin.read_text(encoding="utf-8").splitlines()
        if ligne.strip()
    ]


class TestFichier:
    def test_le_journal_est_ecrit_a_cote_des_sessions(self, tmp_path: Path) -> None:
        """Dans `Documents\\BDO Tracker`, visible exprès.

        C'est ce qu'on demandera au joueur de joindre à un rapport : caché dans
        un dossier d'application, il serait introuvable au moment où il sert.
        """
        journal = SessionJournal.ouvrir(7, racine=tmp_path)
        assert journal.chemin is not None
        assert journal.chemin.parent == dossier_des_rapports(tmp_path)
        assert "session-0007" in journal.chemin.name

    def test_l_entete_porte_la_version_et_la_zone(self, tmp_path: Path) -> None:
        """Sans elles, une trace ne se rattache à rien.

        Un comportement qui a changé entre deux versions, ou une zone calibrée
        de travers, sont les deux premières hypothèses à écarter en lisant un
        journal. Les chercher ailleurs ferait perdre l'aller-retour que ce
        fichier existe pour éviter.
        """
        journal = SessionJournal.ouvrir(1, racine=tmp_path, entete={"zone": "415x505 en (62, 776)"})
        assert journal.chemin is not None
        entete = lignes(journal.chemin)[0]
        assert entete["type"] == "entete"
        assert entete["version"] == __version__
        assert entete["zone"] == "415x505 en (62, 776)"

    def test_chaque_lecture_ajoute_une_ligne(self, tmp_path: Path) -> None:
        journal = SessionJournal.ouvrir(1, racine=tmp_path)
        journal.lecture({"etape": "comptee", "recouvrement": 12, "neuves": 3})
        journal.lecture({"etape": "comptee", "recouvrement": 14, "neuves": 1})
        assert journal.chemin is not None
        lues = [ligne for ligne in lignes(journal.chemin) if ligne["type"] == "lecture"]
        assert [ligne["neuves"] for ligne in lues] == [3, 1]

    def test_un_tour_sans_reconnaissance_n_ecrit_rien(self, tmp_path: Path) -> None:
        """Il y a dix tours par seconde et une lecture : écrire les neuf autres
        noierait les seules lignes qui apprennent quelque chose."""
        journal = SessionJournal.ouvrir(1, racine=tmp_path)
        journal.lecture(None)
        assert journal.chemin is not None
        assert [ligne["type"] for ligne in lignes(journal.chemin)] == ["entete"]

    def test_le_fichier_est_ecrit_au_fil_de_l_eau(self, tmp_path: Path) -> None:
        """⛔ Régression : un journal écrit d'un bloc à la fin perdrait tout.

        Et il le perdrait précisément dans le cas qui nous intéresse le plus,
        celui où la session se termine par un plantage. Chaque ligne doit être
        sur le disque avant la suivante.
        """
        journal = SessionJournal.ouvrir(1, racine=tmp_path)
        journal.lecture({"etape": "comptee"})
        assert journal.chemin is not None
        # Rien n'est fermé, et pourtant tout est là.
        assert len(lignes(journal.chemin)) == 2


class TestBilan:
    def test_le_bilan_clot_le_fichier(self, tmp_path: Path) -> None:
        journal = SessionJournal.ouvrir(1, racine=tmp_path)
        chemin = journal.chemin
        assert chemin is not None
        journal.lecture({"etape": "comptee"})
        journal.fermer({"drops_enregistres": 47})
        bilan = lignes(chemin)[-1]
        assert bilan["type"] == "bilan"
        assert bilan["drops_enregistres"] == 47
        assert bilan["lectures_ecrites"] == 1

    def test_fermer_deux_fois_n_ecrit_qu_un_bilan(self, tmp_path: Path) -> None:
        """Arrêter une session déjà arrêtée ne doit pas produire une seconde
        fin de fichier qui contredirait la première."""
        journal = SessionJournal.ouvrir(1, racine=tmp_path)
        chemin = journal.chemin
        assert chemin is not None
        journal.fermer()
        journal.fermer()
        assert sum(1 for ligne in lignes(chemin) if ligne["type"] == "bilan") == 1

    def test_les_images_ecartees_sont_comptees(self, tmp_path: Path) -> None:
        """Une image écartée sans trace est indiscernable d'une image sans butin."""
        journal = SessionJournal.ouvrir(1, racine=tmp_path)
        journal.lecture({"etape": "ecartee", "motif": "saut invraisemblable"})
        journal.lecture({"etape": "comptee"})
        chemin = journal.chemin
        assert chemin is not None
        journal.fermer()
        assert lignes(chemin)[-1]["images_ecartees"] == 1


class TestBornes:
    def test_au_dela_du_plafond_on_cesse_d_ecrire(self, tmp_path: Path, monkeypatch: Any) -> None:
        monkeypatch.setattr("butin.diagnostic.MAX_LECTURES", 3)
        journal = SessionJournal.ouvrir(1, racine=tmp_path)
        for _ in range(10):
            journal.lecture({"etape": "comptee"})
        chemin = journal.chemin
        assert chemin is not None
        assert sum(1 for ligne in lignes(chemin) if ligne["type"] == "lecture") == 3

    def test_la_troncature_est_ANNONCEE_dans_le_bilan(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        """⛔ Une troncature silencieuse ferait lire « voilà tout ce qui s'est
        passé » à un fichier incomplet.

        C'est la règle du dépôt sur les plafonds : ce qu'on coupe se dit. Sinon
        on cherche une cause dans les lignes manquantes en croyant les avoir.
        """
        monkeypatch.setattr("butin.diagnostic.MAX_LECTURES", 2)
        journal = SessionJournal.ouvrir(1, racine=tmp_path)
        for _ in range(5):
            journal.lecture({"etape": "comptee"})
        chemin = journal.chemin
        assert chemin is not None
        journal.fermer()
        bilan = lignes(chemin)[-1]
        assert bilan["tronque"] is True
        assert bilan["plafond"] == 2

    def test_sans_troncature_le_bilan_le_dit_aussi(self, tmp_path: Path) -> None:
        journal = SessionJournal.ouvrir(1, racine=tmp_path)
        journal.lecture({"etape": "comptee"})
        chemin = journal.chemin
        assert chemin is not None
        journal.fermer()
        assert lignes(chemin)[-1]["tronque"] is False

    def test_le_plafond_couvre_plusieurs_heures_de_farm(self) -> None:
        """Une lecture par seconde : le plafond ne doit pas tomber sur une
        session normale, sinon la troncature devient la règle."""
        assert MAX_LECTURES / 3600 >= 5


class TestIlNeCassEJamaisLaCapture:
    def test_un_dossier_impossible_rend_un_journal_muet(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        """⛔ Le test qui justifie tout le reste.

        Perdre le journal est ennuyeux. Perdre la session de farm parce que le
        journal n'a pas pu s'ouvrir serait impardonnable : c'est l'outil de
        diagnostic qui deviendrait la panne.
        """

        def refuse(*a: Any, **k: Any) -> None:
            raise OSError("disque plein")

        monkeypatch.setattr(Path, "mkdir", refuse)
        journal = SessionJournal.ouvrir(1, racine=tmp_path)
        assert journal.chemin is None
        # Et il continue d'accepter tout ce qu'on lui donne, sans rien lever.
        journal.lecture({"etape": "comptee"})
        journal.fermer({"drops_enregistres": 3})

    def test_une_panne_d_ecriture_en_cours_de_route_ne_leve_pas(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        journal = SessionJournal.ouvrir(1, racine=tmp_path)

        def refuse(*a: Any, **k: Any) -> None:
            raise OSError("disque plein")

        monkeypatch.setattr(Path, "open", refuse)
        journal.lecture({"etape": "comptee"})
        journal.lecture({"etape": "comptee"})
        assert journal._pannes == 2

    def test_un_journal_muet_se_ferme_sans_bruit(self, tmp_path: Path) -> None:
        journal = SessionJournal(session_id=0)
        journal.lecture({"etape": "comptee"})
        journal.fermer()
        assert journal.chemin is None
