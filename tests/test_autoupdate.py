"""Tests de la mise à jour en un clic.

Aucun test ne touche le réseau ni ne lance de processus : `requests` et
`subprocess.Popen` sont remplacés. Ce qui compte ici n'est pas que le
téléchargement parte, c'est qu'aucun binaire non vérifié n'atteigne le disque,
et que Butin ne se ferme jamais lui-même.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest
import requests

from butin import autoupdate

INSTALLEUR = b"MZ ceci est un faux installeur"
EMPREINTE = hashlib.sha256(INSTALLEUR).hexdigest()


class FausseReponse:
    def __init__(self, *, content: bytes = b"", text: str = "", url: str = "", status: int = 200):
        self.content = content
        self.text = text
        self.url = url or autoupdate.installer_url("0.5.0")
        self.status_code = status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"statut {self.status_code}")


class FausseSession:
    """Rend l'installeur pour l'URL principale, l'empreinte pour `.sha256`."""

    def __init__(self, *, contenu: bytes = INSTALLEUR, empreinte: str | None = None) -> None:
        self.contenu = contenu
        self.empreinte = EMPREINTE if empreinte is None else empreinte
        self.urls: list[str] = []

    def get(self, url: str, **kwargs: Any) -> FausseReponse:
        self.urls.append(url)
        if url.endswith(".sha256"):
            nom = url.rsplit("/", 1)[-1].removesuffix(".sha256")
            return FausseReponse(text=f"{self.empreinte}  {nom}", url=url)
        return FausseReponse(content=self.contenu, url=url)


class TestAdresse:
    def test_l_url_suit_le_nom_produit_par_l_installeur(self) -> None:
        """Régression : ce nom est fixé par `OutputBaseFilename` de butin.iss.

        L'URL est construite sans interroger l'API GitHub, qui a ses propres
        limites de débit et que `update.py` sollicite déjà toutes les cinq
        minutes. Le prix de ce choix est ce couplage-là : si le nom du fichier
        change dans `butin.iss`, il change ici aussi, sinon la mise à jour
        télécharge un 404.
        """
        url = autoupdate.installer_url("0.5.0")
        assert url.endswith("/releases/download/v0.5.0/butin-0.5.0-installation.exe")

    def test_le_v_de_l_etiquette_n_entre_pas_dans_le_nom_de_fichier(self) -> None:
        assert autoupdate.installer_url("v0.5.0") == autoupdate.installer_url("0.5.0")


class TestTelechargement:
    def test_une_empreinte_juste_ecrit_le_fichier(self, tmp_path: Path) -> None:
        cible = tmp_path / "installeur.exe"
        assert autoupdate.download_installer("0.5.0", cible, session=FausseSession())
        assert cible.read_bytes() == INSTALLEUR

    def test_une_empreinte_fausse_n_ecrit_RIEN(self, tmp_path: Path) -> None:
        """⛔ Le test qui justifie tout le mécanisme d'empreinte.

        TLS garantit que le fichier vient de GitHub, pas que c'est le BON
        fichier : une construction interrompue ou une release mal publiée
        donnerait un binaire corrompu qu'on s'apprêterait à exécuter avec les
        droits de l'utilisateur. Rien ne doit atteindre le disque.
        """
        cible = tmp_path / "installeur.exe"
        session = FausseSession(empreinte="0" * 64)
        assert not autoupdate.download_installer("0.5.0", cible, session=session)
        assert not cible.exists()

    def test_une_empreinte_absente_n_ecrit_rien(self, tmp_path: Path) -> None:
        """Une release publiée sans son `.sha256` ne doit pas s'installer.

        C'est le cas des versions v0.1.0 à v0.4.0, publiées avant que
        `construire.ps1` génère l'empreinte : elles refusent la mise à jour
        automatique plutôt que de l'accepter sans vérification.
        """
        cible = tmp_path / "installeur.exe"
        assert not autoupdate.download_installer(
            "0.5.0", cible, session=FausseSession(empreinte="")
        )
        assert not cible.exists()

    def test_une_panne_reseau_ne_leve_jamais(self, tmp_path: Path) -> None:
        class SessionCassee:
            def get(self, url: str, **kwargs: Any) -> FausseReponse:
                raise requests.ConnectionError("pas de réseau")

        cible = tmp_path / "installeur.exe"
        assert not autoupdate.download_installer("0.5.0", cible, session=SessionCassee())
        assert not cible.exists()

    def test_un_fichier_trop_gros_est_refuse(self, tmp_path: Path, monkeypatch: Any) -> None:
        monkeypatch.setattr(autoupdate, "MAX_BYTES", 4)
        cible = tmp_path / "installeur.exe"
        assert not autoupdate.download_installer("0.5.0", cible, session=FausseSession())
        assert not cible.exists()

    def test_l_empreinte_est_bien_demandee_a_cote_de_l_installeur(self, tmp_path: Path) -> None:
        session = FausseSession()
        autoupdate.download_installer("0.5.0", tmp_path / "i.exe", session=session)
        assert session.urls[1] == session.urls[0] + ".sha256"


class TestListeBlanche:
    @pytest.mark.parametrize(
        "hote",
        ["github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com"],
    )
    def test_les_hotes_de_github_sont_autorises(self, hote: str) -> None:
        """GitHub redirige les fichiers de release vers un autre domaine.

        Ne lister que `github.com` ferait échouer chaque téléchargement à la
        redirection, sans que le message dise pourquoi.
        """
        assert hote in autoupdate.ALLOWED_HOSTS

    def test_une_redirection_ailleurs_est_refusee(self, tmp_path: Path) -> None:
        class SessionQuiDetourne(FausseSession):
            def get(self, url: str, **kwargs: Any) -> FausseReponse:
                return FausseReponse(content=INSTALLEUR, url="https://ailleurs.invalide/x")

        cible = tmp_path / "i.exe"
        assert not autoupdate.download_installer("0.5.0", cible, session=SessionQuiDetourne())
        assert not cible.exists()


#: Le fichier de l'installeur, lu par les tests ci-dessous. C'est le SEUL
#: endroit où vit la moitié « rouvrir » de la mise à jour : aucun test Python ne
#: l'exécute, donc rien d'autre ne le vérifie.
ISS = Path(__file__).resolve().parents[1] / "installeur" / "butin.iss"

#: Le commutateur qui demande la réouverture. Il doit être écrit à l'identique
#: dans `autoupdate.py` et dans `butin.iss` ; c'est tout l'objet de
#: `test_le_commutateur_est_le_MEME_des_deux_cotes`.
RELANCER = "/RELANCER"


def _directives(chemin: Path) -> str:
    """Le contenu de `butin.iss` SANS ses commentaires.

    Un commentaire d'Inno Setup commence par `;`. Ce fichier en contient
    beaucoup, dont ceux qui racontent les anciennes valeurs : chercher une
    directive dans le texte brut trouve alors ce qui est expliqué au lieu de ce
    qui est appliqué.
    """
    lignes = chemin.read_text(encoding="utf-8").splitlines()
    return "\n".join(ligne for ligne in lignes if not ligne.strip().startswith(";"))


class TestLancement:
    def test_l_installeur_recoit_les_options_de_relance(self, monkeypatch: Any) -> None:
        vus: list[list[str]] = []
        monkeypatch.setattr(
            autoupdate.subprocess, "Popen", lambda args, **kw: vus.append(args) or None
        )
        autoupdate.launch_installer(Path("installeur.exe"))
        assert RELANCER in vus[0]
        assert "/VERYSILENT" in vus[0]
        assert "/NORESTART" in vus[0]

    def test_RESTARTAPPLICATIONS_n_est_PLUS_passe(self, monkeypatch: Any) -> None:
        """⛔ Régression : deux mécanismes de réouverture en lanceraient deux.

        Le Gestionnaire de redémarrage de Windows et la section [Run] de
        l'installeur rouvriraient chacun leur exemplaire. Deux Butin en
        parallèle, ce sont deux fils de capture sur la même session : le
        compteur doublerait, et c'est exactement l'invention de drops que la
        section 1 du CLAUDE.md refuse en premier.
        """
        vus: list[list[str]] = []
        monkeypatch.setattr(
            autoupdate.subprocess, "Popen", lambda args, **kw: vus.append(args) or None
        )
        autoupdate.launch_installer(Path("installeur.exe"))
        assert "/RESTARTAPPLICATIONS" not in vus[0]


class TestLInstalleurRouvreVraimentButin:
    """⛔ Ce que l'ancien test ne regardait PAS, et qui a coûté une version.

    Il vérifiait que `/RESTARTAPPLICATIONS` était bien passé à l'installeur, et
    il était vert. Butin ne revenait quand même pas après une mise à jour :
    passer un commutateur n'est pas la même chose que rouvrir l'application, et
    la moitié qui manquait était dans `butin.iss`, qu'aucun test ne lisait.

    Constaté par Maxime en jouant, le 07/08/2026.
    """

    def test_une_ligne_de_relancement_existe_et_n_est_PAS_skipifsilent(self) -> None:
        """⛔ Le défaut exact, figé.

        La seule ligne qui relançait l'application portait `skipifsilent`, et
        la mise à jour en un clic passe précisément en `/VERYSILENT` : elle
        était donc systématiquement sautée sur le seul chemin où elle
        comptait.
        """
        lignes = [
            ligne.strip()
            for ligne in ISS.read_text(encoding="utf-8").splitlines()
            if ligne.strip().startswith("Filename:") and "MyAppExeName" in ligne
        ]
        relance = [ligne for ligne in lignes if "Check: RelancementDemande" in ligne]
        assert relance, "aucune ligne [Run] ne relance Butin après une mise à jour silencieuse"
        assert "skipifsilent" not in relance[0], (
            "la ligne de relancement est sautée en mode silencieux, "
            "c'est-à-dire sur le seul chemin où elle sert"
        )

    def test_le_commutateur_est_le_MEME_des_deux_cotes(self) -> None:
        """⭐ Le test qui relie les deux fichiers.

        `autoupdate.py` passe un commutateur, `butin.iss` en teste un. Rien
        n'oblige les deux à s'accorder, et les renommer d'un seul côté casserait
        la réouverture **en silence** : l'installation continuerait de réussir,
        et seul un joueur s'en apercevrait.
        """
        source = Path(autoupdate.__file__).read_text(encoding="utf-8")
        assert f'"{RELANCER}"' in source, f"{RELANCER} n'est plus passé par autoupdate.py"
        assert f"ParametrePresent('{RELANCER}')" in _directives(ISS), (
            f"butin.iss ne teste plus {RELANCER} : le commutateur a été renommé d'un seul côté"
        )

    def test_le_gestionnaire_de_redemarrage_ne_rouvre_PAS_en_plus(self) -> None:
        """Sinon deux exemplaires de Butin s'ouvriraient. Voir le test jumeau.

        ⚠️ Les commentaires sont retirés avant de chercher. Une première
        version cherchait dans le fichier entier et échouait sur le commentaire
        qui raconte l'ancienne valeur : un test qui lit une configuration doit
        ignorer ce qui l'explique, sinon documenter un changement casse le test
        qui le garde.
        """
        directives = _directives(ISS)
        assert "RestartApplications=no" in directives
        assert "RestartApplications=yes" not in directives

    def test_la_fermeture_reste_confiee_au_gestionnaire_de_redemarrage(self) -> None:
        """Elle, on la garde : sans elle l'installeur ne peut pas écrire.

        Windows refuse qu'on écrase un `.exe` en cours d'exécution. Retirer
        cette ligne ferait échouer la mise à jour elle-même, pas seulement la
        réouverture.
        """
        assert "CloseApplications=force" in ISS.read_text(encoding="utf-8")

    def test_butin_ne_se_ferme_JAMAIS_lui_meme(self) -> None:
        """⛔ Régression sur le bogue que Rubin a payé en jouant.

        Rubin fermait l'application après avoir lancé l'installeur, et plus
        rien ne se relançait : fermer avant que le Gestionnaire de redémarrage
        de Windows ait enregistré le processus lui retire l'objet qu'il devait
        rouvrir. L'installeur possède tout le cycle, du début à la fin.

        Ce test lit le module : aucun appel de sortie ne doit y figurer.
        """
        source = Path(autoupdate.__file__).read_text(encoding="utf-8")
        for interdit in ("sys.exit", "os._exit", "SystemExit", ".destroy()", ".quit()"):
            assert interdit not in source, f"« {interdit} » referme Butin et casse la relance"


class TestEnchainement:
    def test_un_succes_annonce_la_reouverture(self, tmp_path: Path, monkeypatch: Any) -> None:
        monkeypatch.setattr(autoupdate.subprocess, "Popen", lambda args, **kw: None)
        lance, message = autoupdate.install_update(
            "0.5.0", session=FausseSession(), dossier=tmp_path
        )
        assert lance
        assert "rouvrir" in message

    def test_un_telechargement_rate_propose_le_chemin_manuel(self, tmp_path: Path) -> None:
        lance, message = autoupdate.install_update(
            "0.5.0", session=FausseSession(empreinte="0" * 64), dossier=tmp_path
        )
        assert not lance
        assert "versions" in message

    def test_l_installeur_ne_va_pas_dans_les_donnees_du_joueur(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        """`Documents\\BDO Tracker` appartient au joueur, pas au programme.

        Y déposer un exécutable de 80 Mo à chaque mise à jour salirait le
        dossier qu'il ouvre pour retrouver ses sessions.
        """
        monkeypatch.setattr(autoupdate.subprocess, "Popen", lambda args, **kw: None)
        autoupdate.install_update("0.5.0", session=FausseSession(), dossier=tmp_path)
        assert (tmp_path / "butin-0.5.0-installation.exe").exists()
