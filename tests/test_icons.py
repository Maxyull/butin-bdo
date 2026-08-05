"""Tests des images d'objets.

Ce que ces tests protègent : **le fait qu'une image ne casse jamais rien**.
Une icône absente est un défaut cosmétique, un drop non compté est une erreur.
Tout ce module doit donc rendre « pas d'image » là où il serait tentant de
lever, et aucun test ici ne touche au réseau.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import requests

from butin.catalog.icons import MAX_BYTES, IconStore

# Une vraie image, telle que bdocodex la sert : en-tête WEBP minimal. Les
# octets ne sont pas décodés par le programme, qui ne fait que les ranger, mais
# écrire de vrais octets d'image plutôt que « abc » garde le test honnête.
WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x00" * 24

# Chemin réel relevé le 05/08/2026 dans l'export bdocodex, pour l'objet 890081.
CHEMIN_REEL = "/items/new_icon/03_etc/07_productmaterial/00008055.webp"


class _Reponse:
    def __init__(self, contenu: bytes, *, url: str, status: int = 200) -> None:
        self._contenu = contenu
        self.url = url
        self._status = status

    def iter_content(self, chunk_size: int = 0):
        yield self._contenu

    def raise_for_status(self) -> None:
        if self._status >= 400:
            raise requests.HTTPError(f"statut {self._status}")

    def __enter__(self):
        return self

    def __exit__(self, *exc: object) -> None:
        return None


class SessionFactice:
    """Une session HTTP qui rend ce que le test décide, sans réseau."""

    def __init__(self, contenu: bytes = WEBP, *, url: str | None = None, status: int = 200) -> None:
        self.contenu = contenu
        self.url = url
        self.status = status
        self.appels: list[str] = []

    def get(self, url: str, **_: object) -> _Reponse:
        self.appels.append(url)
        return _Reponse(self.contenu, url=self.url or url, status=self.status)

    def close(self) -> None:
        return None


class SessionQuiCasse:
    def __init__(self) -> None:
        self.appels: list[str] = []

    def get(self, url: str, **_: object):
        self.appels.append(url)
        raise requests.ConnectionError("pas de réseau")

    def close(self) -> None:
        return None


@pytest.fixture
def magasin(tmp_path: Path) -> IconStore:
    return IconStore(tmp_path / "icones", session=SessionFactice())


class TestTelechargement:
    def test_l_image_est_rangee_sous_son_identifiant(self, tmp_path: Path) -> None:
        """Le nom du fichier vient de l'identifiant, jamais du chemin distant.

        Sinon un chemin fourni par la source déciderait d'où l'on écrit.
        """
        session = SessionFactice()
        magasin = IconStore(tmp_path / "icones", session=session)

        chemin = magasin.get(890081, CHEMIN_REEL)

        assert chemin is not None
        assert chemin.name == "890081.webp"
        assert chemin.read_bytes() == WEBP
        assert session.appels == ["https://bdocodex.com" + CHEMIN_REEL]

    def test_la_seconde_demande_ne_retelecharge_pas(self, tmp_path: Path) -> None:
        """Une ligne du récap redemande son image à chaque rafraîchissement,
        donc chaque seconde. Retélécharger serait absurde."""
        session = SessionFactice()
        magasin = IconStore(tmp_path / "icones", session=session)

        magasin.get(890081, CHEMIN_REEL)
        magasin.get(890081, CHEMIN_REEL)

        assert len(session.appels) == 1

    def test_sans_chemin_distant_on_n_essaie_meme_pas(self, magasin: IconStore) -> None:
        """La source ne connaît pas d'image pour cet objet : tenter le
        téléchargement échouerait à chaque drop de cet objet, pour rien."""
        assert magasin.get(999999, "") is None

    def test_local_ne_touche_jamais_au_reseau(self, tmp_path: Path) -> None:
        session = SessionFactice()
        magasin = IconStore(tmp_path / "icones", session=session)

        assert magasin.local(890081) is None
        assert session.appels == []


class TestNeCassePas:
    """⛔ Aucun appel de ce module ne doit lever. Une image manquante est
    cosmétique ; interrompre l'affichage d'un drop ne l'est pas."""

    def test_un_reseau_absent_rend_none(self, tmp_path: Path) -> None:
        magasin = IconStore(tmp_path / "icones", session=SessionQuiCasse())

        assert magasin.get(890081, CHEMIN_REEL) is None

    def test_un_404_rend_none(self, tmp_path: Path) -> None:
        magasin = IconStore(tmp_path / "icones", session=SessionFactice(status=404))

        assert magasin.get(890081, CHEMIN_REEL) is None

    def test_une_reponse_vide_rend_none(self, tmp_path: Path) -> None:
        """Régression : zéro octet écrit ferait un fichier que `local()`
        prendrait pour une image valide, et qui ne se retéléchargerait jamais."""
        magasin = IconStore(tmp_path / "icones", session=SessionFactice(b""))

        assert magasin.get(890081, CHEMIN_REEL) is None
        assert magasin.local(890081) is None

    def test_un_preload_qui_echoue_ne_leve_pas(self, tmp_path: Path) -> None:
        magasin = IconStore(tmp_path / "icones", session=SessionQuiCasse())

        assert magasin.preload({890081: CHEMIN_REEL, 16001: CHEMIN_REEL}) == 0


class TestDurcissement:
    """Les mêmes protections que le téléchargement du catalogue."""

    def test_un_hote_etranger_est_refuse(self, tmp_path: Path) -> None:
        session = SessionFactice()
        magasin = IconStore(tmp_path / "icones", session=session)

        assert magasin.get(890081, "https://ailleurs.example/image.webp") is None
        assert session.appels == [], "aucune requête ne doit partir vers un hôte non autorisé"

    def test_une_redirection_vers_un_hote_etranger_est_refusee(self, tmp_path: Path) -> None:
        """⭐ Régression : vérifier l'URL demandée ne suffit pas.

        L'hôte de départ est le bon, mais la réponse vient d'ailleurs. Sans
        revalidation après redirection, on écrirait sur le disque des octets
        venus de n'importe où.
        """
        session = SessionFactice(url="https://ailleurs.example/image.webp")
        magasin = IconStore(tmp_path / "icones", session=session)

        assert magasin.get(890081, CHEMIN_REEL) is None
        assert magasin.local(890081) is None

    def test_une_image_trop_grosse_est_refusee(self, tmp_path: Path) -> None:
        """Les vraies pèsent 2 à 8 Ko. Le plafond ferme la porte à un fichier
        qui remplirait le disque."""
        session = SessionFactice(b"\x00" * (MAX_BYTES + 1))
        magasin = IconStore(tmp_path / "icones", session=session)

        assert magasin.get(890081, CHEMIN_REEL) is None
        assert magasin.local(890081) is None

    def test_une_extension_inattendue_est_refusee(self, tmp_path: Path) -> None:
        """Régression : l'extension du fichier écrit vient du chemin distant.

        La restreindre évite d'écrire un exécutable sur le disque de quelqu'un
        parce que la source aurait changé de contenu.
        """
        session = SessionFactice()
        magasin = IconStore(tmp_path / "icones", session=session)

        assert magasin.get(890081, "/items/new_icon/piege.exe") is None
        assert session.appels == []


class TestPrechargement:
    def test_il_rend_le_nombre_d_images_disponibles(self, tmp_path: Path) -> None:
        magasin = IconStore(tmp_path / "icones", session=SessionFactice())

        obtenues = magasin.preload({890081: CHEMIN_REEL, 16001: CHEMIN_REEL, 4998: ""})

        assert obtenues == 2
        assert magasin.local(890081) is not None
        assert magasin.local(4998) is None
