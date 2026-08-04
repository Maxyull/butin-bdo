"""Tests des prix du marché et de la chaîne de repli.

Aucun test ne touche au réseau. L'API est indisponible par moments **par
nature**, donc un test qui l'appellerait vraiment échouerait au hasard et on
finirait par ignorer la suite entière.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import requests

from butin.market import (
    MarketClient,
    MarketError,
    Price,
    PriceBook,
    PriceCache,
    PriceSource,
    Region,
)
from butin.market.book import load_vendor_values

# Réponse réelle du relais, relevée le 04/08/2026 sur EU pour la pierre noire.
REPONSE_REELLE = json.dumps(
    {
        "name": "Pierre noire",
        "id": 16001,
        "sid": 0,
        "minEnhance": 0,
        "maxEnhance": 0,
        "basePrice": 135000,
        "currentStock": 30151,
        "totalTrades": 3589526446,
        "priceMin": 120000,
        "priceMax": 300000,
        "lastSoldPrice": 141000,
        "lastSoldTime": 1785880339,
    }
).encode("utf-8")


class ReponseFactice:
    def __init__(self, contenu: bytes, *, statut: int = 200, url: str = "") -> None:
        self.content = contenu
        self.status_code = statut
        self.url = url or "https://api.arsha.io/v2/eu/item"

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"statut {self.status_code}")


class SessionFactice:
    def __init__(self, reponse: ReponseFactice | Exception) -> None:
        self.reponse = reponse
        self.appels = 0
        self.derniers_params: dict[str, str] = {}

    def get(self, url: str, **kwargs: object) -> ReponseFactice:
        self.appels += 1
        self.derniers_params = dict(kwargs.get("params") or {})  # type: ignore[arg-type]
        if isinstance(self.reponse, Exception):
            raise self.reponse
        return self.reponse


class TestClient:
    def test_lit_le_prix_affiche(self) -> None:
        """`basePrice` et non `lastSoldPrice`, et c'est un choix.

        Le dernier prix échangé peut être très au-dessus sur un objet rare peu
        liquide. Le prix affiché est celui auquel on peut vendre maintenant,
        donc le seul honnête pour estimer un revenu horaire.
        """
        client = MarketClient(Region.EU, session=SessionFactice(ReponseFactice(REPONSE_REELLE)))
        prix = client.fetch(16001)

        assert prix.value == 135000
        assert prix.source is PriceSource.MARKET
        assert prix.item_id == 16001

    def test_transmet_la_region_et_le_niveau(self) -> None:
        """Le prix d'un même objet varie du simple au double selon la région."""
        session = SessionFactice(ReponseFactice(REPONSE_REELLE))
        MarketClient(Region.NA, session=session).fetch(16001, sid=2)

        assert session.derniers_params["sid"] == "2"

    def test_refuse_un_hote_inconnu(self) -> None:
        client = MarketClient(Region.EU, base_url="https://exemple.invalide/item")
        with pytest.raises(MarketError, match="hôte non autorisé"):
            client.fetch(16001)

    def test_erreur_reseau_convertie(self) -> None:
        session = SessionFactice(requests.ConnectionError("réseau coupé"))
        client = MarketClient(Region.EU, session=session)
        with pytest.raises(MarketError, match="indisponible"):
            client.fetch(16001)

    def test_le_500_du_pare_feu_est_une_erreur_normale(self) -> None:
        """Régression : ce cas arrive tout le temps, pas exceptionnellement.

        Le relais interroge une API protégée par un pare-feu applicatif qui le
        bloque par intermittence. Traiter ce 500 comme une anomalie ferait
        remonter une panne à l'utilisateur là où il faut juste descendre d'un
        cran dans la chaîne de repli.
        """
        session = SessionFactice(ReponseFactice(b'{"status":500}', statut=500))
        with pytest.raises(MarketError):
            MarketClient(Region.EU, session=session).fetch(16001)

    def test_prix_manquant_refuse(self) -> None:
        session = SessionFactice(ReponseFactice(b'{"id":16001,"name":"x"}'))
        with pytest.raises(MarketError, match="prix manquant"):
            MarketClient(Region.EU, session=session).fetch(16001)


class TestCache:
    def test_aller_retour(self, tmp_path: Path) -> None:
        cache = PriceCache(tmp_path / "prix.json")
        cache.put(Price(item_id=16001, value=135000, source=PriceSource.MARKET, fetched_at=100.0))
        cache.save()

        relu = PriceCache(tmp_path / "prix.json").get(16001)
        assert relu is not None
        assert relu.value == 135000

    def test_survit_a_un_redemarrage(self, tmp_path: Path) -> None:
        """Sur disque et non en mémoire, et c'est nécessaire.

        L'API est indisponible par moments. Une session lancée pendant une de
        ces fenêtres n'aurait aucun prix du tout si le cache disparaissait à
        chaque fermeture du logiciel.
        """
        chemin = tmp_path / "prix.json"
        premier = PriceCache(chemin)
        premier.put(Price(item_id=44195, value=999, source=PriceSource.MARKET, fetched_at=1.0))
        premier.save()

        assert PriceCache(chemin).get(44195) is not None

    def test_cache_corrompu_traite_comme_vide(self, tmp_path: Path) -> None:
        chemin = tmp_path / "prix.json"
        chemin.write_text("{pas du json", encoding="utf-8")
        assert PriceCache(chemin).get(16001) is None

    def test_les_niveaux_ne_se_melangent_pas(self, tmp_path: Path) -> None:
        """Régression : un accessoire et son PRI partagent leur identifiant.

        Les ranger sous la même clé ferait valoriser un TET au prix du niveau
        de base, ce qui fausse le total de plusieurs milliards.
        """
        cache = PriceCache(tmp_path / "prix.json")
        cache.put(Price(item_id=11653, value=100, source=PriceSource.MARKET, fetched_at=1.0, sid=0))
        cache.put(
            Price(
                item_id=11653, value=920_000_000, source=PriceSource.MARKET, fetched_at=1.0, sid=1
            )
        )

        assert cache.get(11653, 0).value == 100
        assert cache.get(11653, 1).value == 920_000_000


class TestChaineDeRepli:
    def _livre(self, tmp_path: Path, **kwargs: object) -> PriceBook:
        return PriceBook(cache=PriceCache(tmp_path / "prix.json"), **kwargs)  # type: ignore[arg-type]

    def test_le_cache_frais_evite_le_reseau(self, tmp_path: Path) -> None:
        """Le relais met lui-même en cache trente minutes.

        Redemander plus souvent ne rendrait pas une valeur plus récente,
        seulement plus de charge pour un service gratuit.
        """
        session = SessionFactice(ReponseFactice(REPONSE_REELLE))
        livre = self._livre(
            tmp_path, client=MarketClient(Region.EU, session=session), vendor_values={}
        )
        livre.cache.put(Price(item_id=16001, value=1, source=PriceSource.MARKET, fetched_at=1000.0))

        prix = livre.price(16001, now=1100.0)

        assert prix.value == 1
        assert session.appels == 0

    def test_le_reseau_prend_le_relais_quand_le_cache_est_perime(self, tmp_path: Path) -> None:
        session = SessionFactice(ReponseFactice(REPONSE_REELLE))
        livre = self._livre(
            tmp_path, client=MarketClient(Region.EU, session=session), vendor_values={}
        )
        livre.cache.put(Price(item_id=16001, value=1, source=PriceSource.MARKET, fetched_at=0.0))

        prix = livre.price(16001, now=10_000.0)

        assert prix.value == 135000
        assert session.appels == 1

    def test_un_cache_perime_vaut_mieux_que_zero(self, tmp_path: Path) -> None:
        """Et il doit se DIRE périmé.

        Un total calculé sur des prix vieux de six heures reste utile. Le
        présenter comme un cours du jour serait faux.
        """
        session = SessionFactice(requests.ConnectionError("bloqué"))
        livre = self._livre(
            tmp_path, client=MarketClient(Region.EU, session=session), vendor_values={}
        )
        livre.cache.put(
            Price(item_id=16001, value=135000, source=PriceSource.MARKET, fetched_at=0.0)
        )

        prix = livre.price(16001, now=10_000.0)

        assert prix.value == 135000
        assert prix.source is PriceSource.MARKET_STALE
        assert livre.network_failures == 1

    def test_la_valeur_au_marchand_n_est_pas_un_repli_degrade(self, tmp_path: Path) -> None:
        """Pour le trash loot, c'est la SEULE valeur qui existe.

        Il ne s'échange pas à l'hôtel des ventes, il se vend au PNJ à prix fixe.
        Chercher un prix de marché pour lui n'a aucun sens.
        """
        livre = self._livre(tmp_path, client=None, vendor_values={43984: {"base": 500}})

        prix = livre.price(43984)

        assert prix.value == 500
        assert prix.source is PriceSource.VENDOR

    def test_inconnu_vaut_zero_et_le_dit(self, tmp_path: Path) -> None:
        livre = self._livre(tmp_path, client=None, vendor_values={})
        prix = livre.price(999999)

        assert prix.value == 0
        assert prix.source is PriceSource.UNKNOWN
        assert not prix.is_known

    def test_un_echec_reseau_n_interrompt_jamais_une_session(self, tmp_path: Path) -> None:
        """Le test qui compte : `price` ne lève jamais.

        Une session de farm ne doit pas s'arrêter parce qu'un prix manque.
        """
        session = SessionFactice(requests.ConnectionError("bloqué"))
        livre = self._livre(
            tmp_path, client=MarketClient(Region.EU, session=session), vendor_values={}
        )

        for item_id in (16001, 44195, 999999):
            assert livre.price(item_id).value == 0

    def test_un_niveau_non_renseigne_retombe_sur_la_base(self, tmp_path: Path) -> None:
        """Sous-estimer est le bon sens de l'erreur."""
        livre = self._livre(tmp_path, client=None, vendor_values={11653: {"base": 100}})
        assert livre.price(11653, sid=3).value == 100

    def test_total_d_un_ensemble(self, tmp_path: Path) -> None:
        livre = self._livre(
            tmp_path, client=None, vendor_values={43984: {"base": 500}, 44069: {"base": 6200}}
        )
        assert livre.total({43984: 10, 44069: 2}) == 5000 + 12400


class TestValeursLivrees:
    def test_le_fichier_du_depot_se_charge(self) -> None:
        """Il est généré par un script : ce test attrape une régression du script."""
        valeurs = load_vendor_values()
        assert len(valeurs) > 300, "la liste de butin livrée doit être peuplée"

    def test_un_objet_connu_a_bien_sa_valeur(self) -> None:
        valeurs = load_vendor_values()
        assert valeurs[43984]["base"] == 500

    def test_fichier_absent_sans_erreur(self, tmp_path: Path) -> None:
        assert load_vendor_values(tmp_path / "rien.json") == {}
