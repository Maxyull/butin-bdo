"""Tests du téléchargement du catalogue.

Le téléchargement est le seul endroit où Butin lit une donnée qu'il ne
contrôle pas. Chaque test ci-dessous correspond à une protection précise, et
nomme ce qui se passerait sans elle.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import requests

from butin.catalog import source
from butin.catalog.source import CatalogError


class FakeResponse:
    """Réponse HTTP minimale, suffisante pour l'usage qu'en fait source.py."""

    def __init__(
        self,
        payload: bytes = b"{}",
        *,
        url: str = source.CATALOG_URL,
        status: int = 200,
        chunk_size: int | None = None,
    ) -> None:
        self._payload = payload
        self.url = url
        self.status_code = status
        self._chunk_size = chunk_size

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"statut {self.status_code}")

    def iter_content(self, chunk_size: int = 8192):
        size = self._chunk_size or chunk_size
        for start in range(0, len(self._payload), size):
            yield self._payload[start : start + size]


def valid_payload(count: int = source.MIN_ITEMS + 10) -> bytes:
    data = {
        str(i): {
            "id": i,
            "locale_default": "us",
            "locale_name": {"us": f"Item {i}", "fr": f"Objet {i}"},
        }
        for i in range(1, count + 1)
    }
    return json.dumps(data).encode("utf-8")


@pytest.fixture
def fake_session(monkeypatch: pytest.MonkeyPatch):
    """Session HTTP dont on contrôle entièrement la réponse."""

    class Session:
        response: FakeResponse = FakeResponse()
        last_timeout: object = None

        def get(self, url: str, timeout=None, stream=False):
            Session.last_timeout = timeout
            return Session.response

        def close(self) -> None:
            pass

    return Session()


class TestListeBlancheDesHotes:
    def test_refuse_le_http_en_clair(self) -> None:
        """Sans cela, une configuration modifiée pourrait injecter un catalogue."""
        with pytest.raises(CatalogError, match="non https"):
            source.fetch_raw("http://raw.githubusercontent.com/x/items.json")

    def test_refuse_un_hote_inconnu(self) -> None:
        with pytest.raises(CatalogError, match="hôte non autorisé"):
            source.fetch_raw("https://exemple.invalide/items.json")

    def test_refuse_une_redirection_hors_liste_blanche(self, fake_session) -> None:
        """Régression : valider seulement l'URL demandée ne protège de rien.

        `requests` suit les redirections tout seul. Si l'hôte final n'était pas
        revalidé, il suffirait d'une redirection depuis un hôte autorisé pour
        servir n'importe quel contenu.
        """
        type(fake_session).response = FakeResponse(
            valid_payload(), url="https://ailleurs.invalide/items.json"
        )
        with pytest.raises(CatalogError, match="URL finale"):
            source.fetch_raw(session=fake_session)

    def test_accepte_l_hote_de_reference(self, fake_session) -> None:
        type(fake_session).response = FakeResponse(valid_payload())
        assert source.fetch_raw(session=fake_session)


class TestPlafondDeTaille:
    def test_refuse_une_reponse_trop_grosse(self, fake_session, monkeypatch) -> None:
        """Sans plafond, une réponse sans fin remplit le disque.

        Le plafond porte sur les octets réellement lus, jamais sur l'en-tête
        Content-Length, qui est déclaratif et donc mensongeable.
        """
        monkeypatch.setattr(source, "MAX_BYTES", 1024)
        type(fake_session).response = FakeResponse(b"x" * 4096, chunk_size=512)
        with pytest.raises(CatalogError, match="trop volumineuse"):
            source.fetch_raw(session=fake_session)

    def test_accepte_juste_en_dessous_du_plafond(self, fake_session, monkeypatch) -> None:
        payload = valid_payload()
        monkeypatch.setattr(source, "MAX_BYTES", len(payload))
        type(fake_session).response = FakeResponse(payload, chunk_size=512)
        assert source.fetch_raw(session=fake_session) == payload


class TestDelaiDAttente:
    def test_un_delai_est_toujours_transmis(self, fake_session) -> None:
        """Régression : sans délai de lecture, un serveur lent bloque à l'infini.

        Le délai de connexion seul ne suffit pas : un serveur qui accepte la
        connexion puis envoie un octet par minute passerait au travers.
        """
        type(fake_session).response = FakeResponse(valid_payload())
        source.fetch_raw(session=fake_session)
        connexion, lecture = type(fake_session).last_timeout
        assert connexion > 0
        assert lecture > 0


class TestAnalyse:
    def test_refuse_un_json_invalide(self) -> None:
        with pytest.raises(CatalogError, match="illisible"):
            source.parse(b"{pas du json")

    def test_refuse_un_tableau(self) -> None:
        with pytest.raises(CatalogError, match="objet"):
            source.parse(b"[]")

    def test_refuse_un_catalogue_tronque(self) -> None:
        """Un fichier coupé en cours de téléchargement ne doit pas devenir le cache.

        Il se chargerait sans erreur, mais tous les objets manquants seraient
        définitivement non reconnus, sans aucun signe visible.
        """
        with pytest.raises(CatalogError, match="anormalement court"):
            source.parse(valid_payload(count=10))

    def test_refuse_une_entree_sans_locale_name(self) -> None:
        data = {str(i): {"id": i} for i in range(1, source.MIN_ITEMS + 10)}
        with pytest.raises(CatalogError, match="locale_name"):
            source.parse(json.dumps(data).encode("utf-8"))

    def test_accepte_le_format_reel(self) -> None:
        assert len(source.parse(valid_payload())) >= source.MIN_ITEMS


class TestEcritureDuCache:
    def test_ecrit_le_contenu(self, tmp_path: Path) -> None:
        cible = tmp_path / "sous" / "dossier" / "items.json"
        source.write_cache(b"contenu", cible)
        assert cible.read_bytes() == b"contenu"

    def test_ne_laisse_aucun_fichier_temporaire(self, tmp_path: Path) -> None:
        cible = tmp_path / "items.json"
        source.write_cache(valid_payload(), cible)
        assert [p.name for p in tmp_path.iterdir()] == ["items.json"]

    def test_l_ancien_cache_survit_a_un_echec(self, tmp_path: Path, monkeypatch) -> None:
        """Régression : une écriture interrompue ne doit pas détruire le cache.

        Écrire directement dans le fichier de destination laisserait, en cas de
        coupure, un fichier à moitié écrit qui échouerait au démarrage suivant.
        L'écriture atomique garantit que le cache est soit l'ancien, soit le
        nouveau, jamais un mélange.
        """
        cible = tmp_path / "items.json"
        cible.write_bytes(b"ancien cache valide")

        def echec(*args, **kwargs):
            raise OSError("disque plein")

        monkeypatch.setattr(source.os, "replace", echec)
        with pytest.raises(OSError):
            source.write_cache(b"nouveau", cible)

        assert cible.read_bytes() == b"ancien cache valide"
        assert [p.name for p in tmp_path.iterdir()] == ["items.json"]


class TestCacheLocal:
    def test_absent_donne_none(self, tmp_path: Path) -> None:
        assert source.load_cached(tmp_path / "rien.json") is None

    def test_corrompu_donne_none_sans_lever(self, tmp_path: Path) -> None:
        """Un cache cassé est traité comme un cache absent, pas comme une panne.

        Le programme sait le reconstruire tout seul ; bloquer le démarrage
        dessus serait une panne inventée.
        """
        chemin = tmp_path / "items.json"
        chemin.write_bytes(b"corrompu")
        assert source.load_cached(chemin) is None

    def test_valide_est_relu(self, tmp_path: Path) -> None:
        chemin = tmp_path / "items.json"
        source.write_cache(valid_payload(), chemin)
        data = source.load_cached(chemin)
        assert data is not None
        assert len(data) >= source.MIN_ITEMS


class TestRafraichissement:
    def test_ne_touche_au_cache_qu_apres_validation(self, tmp_path: Path, fake_session) -> None:
        """Régression : un téléchargement invalide ne doit rien écraser.

        Valider après écriture laisserait le cache dans un état cassé jusqu'au
        prochain téléchargement réussi.
        """
        cible = tmp_path / "items.json"
        cible.write_bytes(valid_payload())
        type(fake_session).response = FakeResponse(b"[]")

        with pytest.raises(CatalogError):
            source.refresh(cible, session=fake_session)

        assert source.load_cached(cible) is not None
