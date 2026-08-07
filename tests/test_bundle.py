"""Tests de l'archive de diagnostic.

⛔ Le fil rouge : **ce qui N'ENTRE PAS dedans**. Une archive de diagnostic est
faite pour être déposée dans un salon public, donc chaque fichier qu'elle
emporte est un fichier que des inconnus liront. Les tests qui comptent ici sont
ceux qui échouent quand on y ajoute quelque chose de trop.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from butin import bundle, paths
from butin.bundle import Archive, contexte, decrire_le_contenu, journaux_recents, preparer


@pytest.fixture
def racine(tmp_path: Path) -> Path:
    """Un dossier de données peuplé comme celui d'un vrai joueur."""
    rapports = tmp_path / "rapports"
    rapports.mkdir(parents=True)
    for nom in ("session-0001-20260805-231000", "session-0002-20260807-032857"):
        (rapports / f"{nom}.jsonl").write_text('{"lecture": 1}\n', encoding="utf-8")
    # ⭐ Le fichier qu'on ne doit JAMAIS joindre, présent comme en vrai.
    (tmp_path / bundle.FICHIER_INTERDIT).write_text("a" * 32, encoding="utf-8")
    return tmp_path


def _noms(archive: Archive) -> set[str]:
    with zipfile.ZipFile(archive.chemin) as zf:
        return set(zf.namelist())


class TestCeQuiNEntreJamais:
    def test_rien_de_sensible_n_entre_dans_l_archive(self, racine: Path) -> None:
        """⛔ Le test qui porte tout le module.

        `contributeur.txt` **est** la clé du rattachement Discord : le relais
        signe un état qui le contient, donc le connaître suffit à rattacher
        SON compte au numéro de quelqu'un d'autre et à s'attribuer ses
        rapports. Dans une archive déposée dans un salon public, il serait
        lisible par tout le monde.

        Le test lit le CONTENU réel de l'archive, pas la liste de ce qu'on a
        voulu y mettre : c'est la différence entre vérifier une intention et
        vérifier un résultat.

        ⭐ **Il a été piégé avant d'être cru** (07/08/2026) : en ajoutant pour
        de vrai le fichier interdit à l'archive, il échoue en nommant
        l'intrus. Un test de non-présence qui n'a jamais su dire non ne prouve
        rien, il constate juste qu'on n'a pas encore fait la bêtise.

        ⚠️ Le premier piège était injuste et donnait un faux vert : il posait
        le fichier à `paths.storage_root()`, qui vaut `BUTIN_HOME/data` et non
        `BUTIN_HOME`. Le code ne regardait donc jamais là. Un piège doit viser
        le chemin que le code emprunte vraiment, sinon c'est le piège qu'on
        teste et pas le garde-fou.
        """
        archive = preparer(racine=racine)
        noms = _noms(archive)
        assert not any(bundle.FICHIER_INTERDIT in nom for nom in noms), (
            f"l'identifiant du contributeur est dans l'archive : {noms}"
        )

        with zipfile.ZipFile(archive.chemin) as zf:
            entier = b"".join(zf.read(nom) for nom in zf.namelist())
        assert b"a" * 32 not in entier, "l'identifiant se retrouve dans le contenu d'un fichier"

    def test_le_contexte_ne_porte_ni_nom_d_utilisateur_ni_chemin(self) -> None:
        """Un chemin absolu sous Windows contient le nom de compte Windows.

        « C:\\Users\\maxim\\... » suffit à donner le vrai prénom de la personne
        à un salon entier, pour une information qui n'aide en rien à
        comprendre un défaut de comptage.
        """
        texte = " ".join(str(v) for v in contexte().values())
        assert "Users" not in texte
        assert ":\\" not in texte and ":/" not in texte


class TestContenu:
    def test_les_journaux_sont_joints(self, racine: Path) -> None:
        archive = preparer(racine=racine)
        joints = [nom for nom in _noms(archive) if nom.startswith("journaux/")]
        assert len(joints) == 2

    def test_le_plus_recent_d_abord(self, racine: Path) -> None:
        """L'ordre compte : c'est la dernière session qui pose problème."""
        fichiers = journaux_recents(racine)
        assert fichiers[0].stat().st_mtime >= fichiers[-1].stat().st_mtime

    def test_seuls_les_trois_derniers_journaux_partent(self, racine: Path) -> None:
        """Sinon une machine qui farme tous les jours ferait une archive énorme."""
        for i in range(10):
            (racine / "rapports" / f"session-01{i}-20260807-04{i}000.jsonl").write_text(
                "{}\n", encoding="utf-8"
            )
        assert len(journaux_recents(racine)) == bundle.JOURNAUX_JOINTS

    def test_le_contexte_est_toujours_present(self, racine: Path) -> None:
        assert "contexte.txt" in _noms(preparer(racine=racine))

    def test_l_apercu_est_joint_quand_il_existe(self, racine: Path) -> None:
        archive = preparer(racine=racine, apercu=b"\x89PNG\r\n\x1a\n fausse image")
        assert "zone-calibree.png" in _noms(archive)


class TestRienNEstSilencieux:
    def test_un_journal_TRONQUE_est_annonce(self, racine: Path, monkeypatch) -> None:
        """⛔ Une troncature muette ferait chercher une cause dans un fichier amputé.

        Même règle que le journal de diagnostic lui-même : il est borné, et il
        le DIT dans son bilan. Une archive qui coupe en silence enverrait
        quelqu'un chercher pendant une heure une ligne qu'on a jetée.
        """
        monkeypatch.setattr(bundle, "MAX_OCTETS_JOURNAL", 4)
        archive = preparer(racine=racine)
        assert any("TRONQUÉ" in a for a in archive.avertissements)

    def test_l_absence_de_journal_est_annoncee(self, tmp_path: Path) -> None:
        """Et elle dit quoi faire, plutôt que de constater.

        Une archive sans journal est presque inutile pour un sur-comptage :
        autant dire tout de suite qu'il faut farmer d'abord.
        """
        archive = preparer(racine=tmp_path)
        assert any("aucun journal" in a for a in archive.avertissements)

    def test_l_absence_d_apercu_est_annoncee(self, racine: Path) -> None:
        archive = preparer(racine=racine, apercu=None)
        assert any("capture de la zone" in a for a in archive.avertissements)

    def test_la_description_montre_le_contenu_ET_les_manques(self, racine: Path) -> None:
        """C'est ce que le joueur lit avant de déposer le fichier.

        Une archive qu'on dépose sans savoir ce qu'il y a dedans est un
        formulaire signé en blanc.
        """
        texte = decrire_le_contenu(preparer(racine=racine))
        assert "contexte.txt" in texte
        assert "⚠️" in texte


class TestElleNeLevePasJamais:
    def test_un_dossier_impossible_a_ecrire_ne_leve_pas(self, tmp_path: Path, monkeypatch) -> None:
        """Même garantie que `send_report`.

        Préparer un rapport de bogue ne doit pas planter l'application au
        moment précis où quelqu'un signale un bogue.
        """

        def refuse(*args, **kwargs):
            raise OSError(13, "accès refusé")

        monkeypatch.setattr(Path, "mkdir", refuse)
        archive = preparer(racine=tmp_path / "inexistant")
        assert archive.octets == 0
        assert archive.avertissements

    def test_un_journal_illisible_n_empeche_pas_le_reste(self, racine: Path, monkeypatch) -> None:
        """Un fichier verrouillé par un antivirus ne doit pas tout perdre."""
        vrai = Path.read_bytes

        def parfois(self: Path) -> bytes:
            if self.suffix == ".jsonl":
                raise OSError(13, "verrouillé")
            return vrai(self)

        monkeypatch.setattr(Path, "read_bytes", parfois)
        archive = preparer(racine=racine)
        assert "contexte.txt" in _noms(archive)
        assert any("illisible" in a for a in archive.avertissements)


class TestElleVitAvecLesAutresRapports:
    def test_l_archive_est_ecrite_a_cote_des_journaux(self, racine: Path) -> None:
        """Le joueur n'a qu'un seul dossier à connaître.

        Éparpiller les fichiers de diagnostic dans deux endroits garantit qu'on
        lui demandera celui qu'il n'a pas sous les yeux.
        """
        archive = preparer(racine=racine)
        assert archive.chemin.parent == racine / "rapports"

    def test_deux_archives_ne_s_ecrasent_pas(self, racine: Path) -> None:
        """Elles portent l'heure : deux essais à dix minutes d'écart se gardent."""
        a = preparer(racine=racine, maintenant=1_754_000_000)
        b = preparer(racine=racine, maintenant=1_754_000_600)
        assert a.chemin != b.chemin

    def test_le_dossier_est_bien_celui_des_rapports(self, racine: Path) -> None:
        assert bundle.dossier_des_archives(racine).name == "rapports"


class TestReglagesEtCalibrage:
    def test_ils_sont_joints_quand_ils_existent(self, racine: Path, monkeypatch) -> None:
        """Le calibrage est la première cause d'un compteur qui ne compte rien."""
        reglages = racine / "reglages.json"
        reglages.write_text('{"langue": "fr"}', encoding="utf-8")
        calibrage = racine / "calibrage.json"
        calibrage.write_text('{"region": {}}', encoding="utf-8")
        monkeypatch.setattr(paths, "settings_path", lambda: reglages)
        monkeypatch.setattr(paths, "calibration_path", lambda: calibrage)

        noms = _noms(preparer(racine=racine))
        assert "reglages.json" in noms
        assert "calibrage.json" in noms
