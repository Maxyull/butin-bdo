"""Tests des emplacements sur disque.

Ce que ces tests protègent : **les sessions de farm de quelqu'un**. Une erreur
ici ne casse rien de visible, elle fait simplement regarder ailleurs — et du
point de vue de la personne, un historique qu'on ne retrouve plus est un
historique perdu.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from butin import paths


@pytest.fixture
def sans_redirection(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Retire `BUTIN_HOME` et range le repère dans un dossier jetable.

    Nécessaire pour mesurer le comportement réel : la redirection gagne sur
    tout, donc tant qu'elle est là on ne teste qu'elle.
    """
    monkeypatch.delenv("BUTIN_HOME", raising=False)
    reglages = tmp_path / "config"
    reglages.mkdir()
    monkeypatch.setattr(paths, "_settings_dir", lambda: reglages)

    # ⛔ Documents est isolé lui aussi, et ça manquait. Sans ça ces tests
    # lisaient le VRAI dossier Documents de la machine : leur résultat
    # dépendait donc de ce qu'on y trouvait, et trois d'entre eux ont basculé
    # au rouge le 08/08/2026 sur une machine qui possédait encore l'ancien
    # dossier « BDO Tracker » — alors que le code faisait exactement ce qu'on
    # lui demandait. Un test qui dépend de l'état du poste ne mesure pas le
    # code.
    documents = tmp_path / "Documents"
    documents.mkdir()
    monkeypatch.setattr(paths, "user_documents_path", lambda: documents)
    return tmp_path


class TestEmplacementParDefaut:
    def test_les_sessions_vont_dans_documents(self, sans_redirection: Path) -> None:
        """Dans Documents et non dans les données d'application.

        Ce sont **ses** données : il voudra les sauvegarder, les copier sur une
        autre machine, ou simplement les retrouver. Les enterrer dans
        `%LOCALAPPDATA%` reviendrait à les cacher.
        """
        defaut = paths.default_storage_root()

        assert defaut.name == paths.FOLDER_NAME
        assert paths.storage_root() == defaut

    def test_la_redirection_d_environnement_gagne_sur_tout(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Sinon un test qui écrirait un repère déplacerait les vraies données.

        C'est aussi ce qui rend l'application portable sans toucher au repère.
        """
        monkeypatch.setenv("BUTIN_HOME", str(tmp_path))
        paths.set_storage_root(tmp_path / "ailleurs")

        assert paths.storage_root() == tmp_path / "data"

    def test_les_reglages_suivent_les_donnees_et_non_le_cache(self) -> None:
        """Le profil de taxe décrit le COMPTE de jeu, ça ne se retélécharge pas.

        Dans le cache, il disparaîtrait au premier nettoyage et le silver par
        heure retomberait au taux sans bonus sans que rien ne le dise. Rangé
        avec le calibrage, il suit le dossier de sessions.
        """
        assert paths.settings_path().parent == paths.data_dir()
        assert paths.settings_path().parent == paths.calibration_path().parent


class TestChoixDeL_utilisateur:
    def test_le_dossier_choisi_est_retenu(self, sans_redirection: Path) -> None:
        choisi = sans_redirection / "mes sessions"

        paths.set_storage_root(choisi)

        assert paths.storage_root() == choisi
        assert choisi.is_dir()

    def test_un_repere_illisible_ne_bloque_pas_le_lancement(self, sans_redirection: Path) -> None:
        """Refuser de démarrer retirerait aussi le moyen de corriger.

        L'utilisateur retombe sur le dossier par défaut, et reverra ses données
        au prochain choix.
        """
        paths.pointer_path().write_text("pas du json", encoding="utf-8")

        assert paths.storage_root() == paths.default_storage_root()

    def test_un_repere_vide_retombe_sur_le_defaut(self, sans_redirection: Path) -> None:
        paths.pointer_path().write_text(json.dumps({"dossier": "   "}), encoding="utf-8")

        assert paths.storage_root() == paths.default_storage_root()


class TestRepriseD_uneAncienneInstallation:
    def test_les_donnees_d_avant_sont_reprises(
        self, sans_redirection: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """⭐ Régression à ne jamais introduire : l'historique qui disparaît.

        Les versions précédentes écrivaient dans les données d'application.
        Sans ce déménagement, une mise à jour ferait **disparaître l'historique**
        de l'utilisateur : les fichiers seraient toujours là, mais le programme
        regarderait ailleurs, ce qui revient au même pour lui.
        """
        ancien = sans_redirection / "ancien"
        ancien.mkdir()
        (ancien / "sessions.sqlite3").write_text("base", encoding="utf-8")
        (ancien / "calibrage.json").write_text("{}", encoding="utf-8")
        nouveau = sans_redirection / "nouveau"
        monkeypatch.setattr(paths, "user_data_path", lambda *a, **k: ancien)
        monkeypatch.setattr(paths, "storage_root", lambda: nouveau)

        origine = paths.migrate_legacy()

        assert origine == ancien
        assert (nouveau / "sessions.sqlite3").read_text(encoding="utf-8") == "base"
        assert not (ancien / "sessions.sqlite3").exists()

    def test_une_destination_deja_remplie_n_est_pas_ecrasee(
        self, sans_redirection: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Écraser des données récentes par des anciennes serait pire que le
        problème résolu."""
        ancien = sans_redirection / "ancien"
        ancien.mkdir()
        (ancien / "sessions.sqlite3").write_text("vieille", encoding="utf-8")
        nouveau = sans_redirection / "nouveau"
        nouveau.mkdir()
        (nouveau / "sessions.sqlite3").write_text("récente", encoding="utf-8")
        monkeypatch.setattr(paths, "user_data_path", lambda *a, **k: ancien)
        monkeypatch.setattr(paths, "storage_root", lambda: nouveau)

        assert paths.migrate_legacy() is None
        assert (nouveau / "sessions.sqlite3").read_text(encoding="utf-8") == "récente"

    def test_rien_a_reprendre_ne_fait_rien(
        self, sans_redirection: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(paths, "user_data_path", lambda *a, **k: sans_redirection / "absent")

        assert paths.migrate_legacy() is None

    def test_une_redirection_active_interdit_le_demenagement(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Un test qui déménagerait les vraies données de la personne serait un
        test qui casse ce qu'il vérifie."""
        monkeypatch.setenv("BUTIN_HOME", str(tmp_path))

        assert paths.migrate_legacy() is None


class TestDonneesLivreesAvecLeProjet:
    """`data/butin-connu.json`, les noms vérifiés, les valeurs au marchand.

    ⭐ Régression visée : `Path(__file__).resolve().parents[N]` se casse
    silencieusement dans une application figée par PyInstaller, qui aplatit
    tout sous `sys._MEIPASS`. Sans cette distinction, une installation figée
    afficherait tous les objets sans zone de farm ni valeur au marchand, sans
    la moindre erreur pour le dire.
    """

    def test_en_developpement_le_dossier_data_est_a_la_racine_du_depot(self) -> None:
        dossier = paths.bundled_data_dir()

        assert dossier.name == "data"
        assert (dossier / "butin-connu.json").exists(), (
            "le calcul ne pointe plus vers le vrai dossier data/ du dépôt"
        )

    def test_une_application_figee_cherche_sous_sys_meipass(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """`sys._MEIPASS` est l'attribut que PyInstaller pose sur `sys` au
        démarrage d'une application figée. Absent en développement."""
        monkeypatch.setattr(paths.sys, "_MEIPASS", str(tmp_path), raising=False)

        assert paths.bundled_data_dir() == tmp_path / "data"
