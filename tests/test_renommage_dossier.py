"""Tests du renommage `BDO Tracker` → `BDO Butin`.

⛔ Le danger de ce changement tient en une phrase : **changer le nom du dossier
sans rien d'autre fait disparaître l'historique de tout le monde.** Les fichiers
restent sur le disque, intacts, et le programme regarde à côté. Du point de vue
du joueur, c'est une perte de données — exactement ce que la section 2ter du
CLAUDE.md interdit.

Deux mécanismes le rendent sûr, et il faut les deux :

1. `migrate_ancien_dossier()` renomme au lancement ;
2. `storage_root()` retombe sur l'ancien nom si le nouveau n'existe pas.

Le second existe parce que le premier peut échouer — dossier ouvert dans
l'explorateur, antivirus, disque plein. Le renommage est un confort, le repli
est la garantie.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from butin import paths


@pytest.fixture
def documents(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Un faux dossier Documents, et pas de redirection d'environnement.

    ⚠️ `BUTIN_HOME` est retiré : la fixture globale `isolated_home` le pose, et
    il court-circuite tout ce module. Sans ça, ces tests vérifieraient un
    chemin que le vrai lancement n'emprunte jamais.
    """
    monkeypatch.delenv("BUTIN_HOME", raising=False)
    docs = tmp_path / "Documents"
    docs.mkdir()
    monkeypatch.setattr(paths, "user_documents_path", lambda: docs)
    monkeypatch.setattr(paths, "pointer_path", lambda: tmp_path / "config" / "emplacement.json")
    return docs


def _peupler(dossier: Path) -> None:
    """Un dossier de données comme celui d'un vrai joueur."""
    dossier.mkdir(parents=True, exist_ok=True)
    (dossier / "sessions.sqlite3").write_bytes(b"base")
    (dossier / "reglages.json").write_text("{}", encoding="utf-8")
    (dossier / "contributeur.txt").write_text("a" * 32, encoding="utf-8")
    rapports = dossier / "rapports"
    rapports.mkdir()
    (rapports / "session-0014-x.jsonl").write_text("{}\n", encoding="utf-8")
    (rapports / "inventaire-0014.png").write_bytes(b"\x89PNG")


class TestLeRenommageEmporteTout:
    def test_il_emporte_les_journaux_ET_les_captures(self, documents: Path) -> None:
        """⭐ On renomme le DOSSIER, on ne copie pas une liste de fichiers.

        Une liste serait fausse le jour où l'on ajoute un fichier, et personne
        ne s'en apercevrait avant d'en avoir besoin. Ce test nomme ce qui doit
        arriver de l'autre côté, y compris le sous-dossier.
        """
        ancien = documents / paths.ANCIEN_FOLDER_NAME
        _peupler(ancien)

        assert paths.migrate_ancien_dossier() == ancien

        nouveau = documents / paths.FOLDER_NAME
        assert (nouveau / "sessions.sqlite3").read_bytes() == b"base"
        assert (nouveau / "reglages.json").exists()
        assert (nouveau / "contributeur.txt").exists()
        assert (nouveau / "rapports" / "session-0014-x.jsonl").exists()
        assert (nouveau / "rapports" / "inventaire-0014.png").exists()
        assert not ancien.exists()

    def test_sans_ancien_dossier_il_ne_fait_rien(self, documents: Path) -> None:
        assert paths.migrate_ancien_dossier() is None


class TestCeQuIlNeToucheJamais:
    def test_un_dossier_choisi_par_le_joueur_est_laisse_tranquille(
        self, documents: Path, tmp_path: Path
    ) -> None:
        """⛔ Ce n'est pas à nous de renommer ce qu'il a nommé.

        S'il a déplacé ses données lui-même, son choix prime sur notre envie de
        cohérence.
        """
        _peupler(documents / paths.ANCIEN_FOLDER_NAME)
        repere = tmp_path / "config" / "emplacement.json"
        repere.parent.mkdir(parents=True)
        repere.write_text('{"dossier": "D:/ailleurs"}', encoding="utf-8")

        assert paths.migrate_ancien_dossier() is None
        assert (documents / paths.ANCIEN_FOLDER_NAME).is_dir()

    def test_si_les_DEUX_existent_on_ne_fusionne_pas(self, documents: Path) -> None:
        """⛔ Fusionner deux historiques demanderait de savoir lequel fait foi.

        Personne ne le sait, ni le programme ni forcément le joueur. Ne rien
        faire laisse les deux consultables ; se tromper en écrase un.
        """
        _peupler(documents / paths.ANCIEN_FOLDER_NAME)
        _peupler(documents / paths.FOLDER_NAME)

        assert paths.migrate_ancien_dossier() is None
        assert (documents / paths.ANCIEN_FOLDER_NAME).is_dir()
        assert (documents / paths.FOLDER_NAME).is_dir()

    def test_BUTIN_HOME_court_circuite_tout(
        self, documents: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Une redirection de test ne doit rien renommer chez personne."""
        _peupler(documents / paths.ANCIEN_FOLDER_NAME)
        monkeypatch.setenv("BUTIN_HOME", str(tmp_path / "jetable"))
        assert paths.migrate_ancien_dossier() is None


class TestLeRepliEstLaVraieGarantie:
    def test_si_le_renommage_ECHOUE_les_donnees_restent_visibles(
        self, documents: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """⛔ Le test qui porte tout ce module.

        Un dossier ouvert dans l'explorateur suffit à faire échouer un
        renommage sous Windows. Sans repli, l'application regarderait un
        dossier inexistant et l'historique disparaîtrait de l'écran alors qu'il
        est intact sur le disque.
        """
        ancien = documents / paths.ANCIEN_FOLDER_NAME
        _peupler(ancien)

        def refuse(self: Path, cible: object) -> None:
            raise OSError(13, "dossier utilisé par un autre processus")

        monkeypatch.setattr(Path, "rename", refuse)

        assert paths.migrate_ancien_dossier() is None, "un échec ne doit pas passer pour un succès"
        assert paths.storage_root() == ancien, "les données ne sont plus trouvées"
        assert (paths.storage_root() / "sessions.sqlite3").exists()

    def test_apres_un_renommage_reussi_on_pointe_sur_le_NOUVEAU(self, documents: Path) -> None:
        _peupler(documents / paths.ANCIEN_FOLDER_NAME)
        paths.migrate_ancien_dossier()
        assert paths.storage_root() == documents / paths.FOLDER_NAME

    def test_une_installation_neuve_utilise_le_nouveau_nom(self, documents: Path) -> None:
        """Aucun des deux dossiers n'existe : on part du nouveau nom."""
        assert paths.storage_root() == documents / paths.FOLDER_NAME


class TestLesDeuxNomsSontDistincts:
    def test_l_ancien_nom_est_conserve_dans_le_code(self) -> None:
        """⛔ Gardé indéfiniment, et pas pendant deux versions.

        Un joueur qui n'ouvre Butin que tous les six mois doit retrouver ses
        sessions le jour où il revient, pas un historique vide.
        """
        assert paths.ANCIEN_FOLDER_NAME == "BDO Tracker"
        assert paths.FOLDER_NAME == "BDO Butin"
        assert paths.FOLDER_NAME != paths.ANCIEN_FOLDER_NAME
