"""Tests de la couche de noms vérifiés à la main."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from butin.catalog import overrides
from butin.catalog.catalog import ItemCatalog
from butin.catalog.overrides import OverrideError, VerifiedName


def _write(path: Path, payload: dict[str, object]) -> Path:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


class TestAnalyse:
    def test_entree_complete(self) -> None:
        result = overrides.parse(
            {
                "version": 1,
                "items": {
                    "4998": {
                        "nom": "Éclat de cristal noir tranchant",
                        "sources": ["bdocodex", "garmoth"],
                        "verifie_le": "2026-08-04",
                    }
                },
            }
        )
        entry = result[4998]
        assert entry.name == "Éclat de cristal noir tranchant"
        assert entry.sources == ("bdocodex", "garmoth")
        assert entry.checked_on == date(2026, 8, 4)
        assert entry.is_verified

    def test_version_inconnue_refusee(self) -> None:
        with pytest.raises(OverrideError, match="version de schéma"):
            overrides.parse({"version": 99, "items": {}})

    @pytest.mark.parametrize(
        ("entree", "motif"),
        [
            ({"sources": ["bdocodex", "garmoth"]}, "nom"),
            ({"nom": "  ", "sources": ["bdocodex", "garmoth"]}, "nom"),
            ({"nom": "Pierre noire"}, "sources"),
            ({"nom": "Pierre noire", "sources": []}, "sources"),
            ({"nom": "Pierre noire", "sources": [1, 2]}, "sources"),
        ],
    )
    def test_entree_mal_formee_refusee(self, entree: dict, motif: str) -> None:
        """Échec net plutôt qu'entrée silencieusement ignorée.

        Ce fichier est écrit à la main, objet par objet. Une entrée ignorée en
        silence ferait croire à un recoupement fait alors qu'il ne l'est pas.
        """
        with pytest.raises(OverrideError, match=motif):
            overrides.parse({"version": 1, "items": {"16001": entree}})

    def test_identifiant_non_numerique_refuse(self) -> None:
        with pytest.raises(OverrideError, match="non numérique"):
            overrides.parse(
                {"version": 1, "items": {"pierre": {"nom": "x", "sources": ["bdocodex"]}}}
            )

    def test_date_illisible_refusee(self) -> None:
        with pytest.raises(OverrideError, match="illisible"):
            overrides.parse(
                {
                    "version": 1,
                    "items": {
                        "16001": {
                            "nom": "Pierre noire (arme)",
                            "sources": ["bdocodex", "garmoth"],
                            "verifie_le": "04/08/2026",
                        }
                    },
                }
            )

    def test_sources_dupliquees_dedupliquees(self) -> None:
        """Citer deux fois le même site ne vaut pas un recoupement.

        Sans déduplication, ["bdocodex", "bdocodex"] passerait le seuil de deux
        sources tout en ne reposant que sur une seule.
        """
        result = overrides.parse(
            {
                "version": 1,
                "items": {
                    "16001": {"nom": "Pierre noire (arme)", "sources": ["bdocodex", "bdocodex"]}
                },
            }
        )
        assert result[16001].sources == ("bdocodex",)
        assert not result[16001].is_verified


class TestRegleDeVerification:
    def test_deux_sources_dont_une_reference(self) -> None:
        assert VerifiedName(1, "x", ("bdocodex", "bdolytics")).is_verified

    def test_une_seule_source_insuffisante(self) -> None:
        assert not VerifiedName(1, "x", ("bdocodex",)).is_verified

    def test_deux_sources_sans_reference_insuffisantes(self) -> None:
        """bdocodex ou garmoth doit figurer, pas seulement deux sites au hasard."""
        assert not VerifiedName(1, "x", ("bdolytics", "grumpygreen")).is_verified

    def test_audit_remonte_les_entrees_incompletes(self) -> None:
        entries = {
            1: VerifiedName(1, "ok", ("bdocodex", "garmoth")),
            2: VerifiedName(2, "incomplet", ("bdocodex",)),
        }
        assert [e.item_id for e in overrides.audit_sources(entries)] == [2]


class TestFichierLivre:
    def test_le_fichier_du_depot_est_valide(self) -> None:
        """Le fichier livré doit toujours se charger.

        Il est édité à la main sur la durée : ce test est le filet qui attrape
        une virgule oubliée avant qu'elle ne casse le démarrage du logiciel.
        """
        assert overrides.load(overrides.default_path()) is not None

    def test_aucune_entree_a_moitie_verifiee(self) -> None:
        """Régression : un recoupement commencé ne doit pas passer pour acquis.

        Tant qu'une entrée ne cite pas deux sources distinctes dont une
        référence, elle n'est pas vérifiée et ce test échoue en le disant.
        """
        incompletes = overrides.audit_sources(overrides.load(overrides.default_path()))
        assert not incompletes, (
            "entrées citant moins de deux sources ou aucune référence : "
            + ", ".join(f"{e.item_id} ({', '.join(e.sources)})" for e in incompletes)
        )


class TestFichierAbsentOuIllisible:
    def test_fichier_absent_donne_un_dictionnaire_vide(self, tmp_path: Path) -> None:
        assert overrides.load(tmp_path / "inexistant.json") == {}

    def test_fichier_illisible_leve_une_erreur(self, tmp_path: Path) -> None:
        """Un fichier présent mais cassé n'est pas la même chose qu'un absent.

        Il a été écrit intentionnellement ; l'ignorer perdrait en silence tout
        le travail de recoupement déjà fait.
        """
        path = tmp_path / "noms.json"
        path.write_text("{ceci n'est pas du json", encoding="utf-8")
        with pytest.raises(OverrideError):
            overrides.load(path)


class TestApplicationAuCatalogue:
    def test_le_nom_verifie_gagne_sur_la_source_amont(
        self, raw_catalog: dict[str, dict[str, object]]
    ) -> None:
        corrige = {
            4998: VerifiedName(4998, "Éclat de cristal noir aiguisé", ("bdocodex", "garmoth"))
        }
        catalog = ItemCatalog.from_raw(raw_catalog, overrides=corrige)
        item = catalog.get(4998)
        assert item is not None
        assert item.name() == "Éclat de cristal noir aiguisé"

    def test_le_nom_verifie_devient_reconnaissable(
        self, raw_catalog: dict[str, dict[str, object]]
    ) -> None:
        """Corriger le nom doit corriger la reconnaissance, pas juste l'affichage.

        Si l'index était construit avant l'application des noms vérifiés, la
        correction serait visible dans l'interface mais l'OCR continuerait de
        chercher l'ancien nom. Ce test fige l'ordre.
        """
        from butin.catalog import ItemMatcher

        corrige = {
            4998: VerifiedName(4998, "Éclat de cristal noir aiguisé", ("bdocodex", "garmoth"))
        }
        catalog = ItemCatalog.from_raw(raw_catalog, overrides=corrige)
        match = ItemMatcher(catalog).resolve("Eclat de cristal noir aiguise")
        assert match is not None
        assert match.item.item_id == 4998

    def test_le_drop_le_plus_frequent_du_jeu_est_reconnu(
        self, raw_catalog: dict[str, dict[str, object]]
    ) -> None:
        """Régression : « Pierre noire » ne doit plus être reconnu par accident.

        Le jeu a fusionné « Pierre noire (arme) » et « Pierre noire (armure) »
        en un seul objet, qui garde l'identifiant 16001 et perd son suffixe.
        veliainn n'a pas suivi et nomme toujours 16001 « Pierre noire (arme) ».

        Sans correction, la reconnaissance **fonctionne quand même**, mais pour
        une raison qui n'a rien à voir avec la bonne : le score flou place
        « pierre noire arme » à 95 et « pierre noire armure » à 90, simplement
        parce que le premier est plus court. Vérifié sur le catalogue réel de
        8344 objets. La marge d'ambiguïté est de 4 points et l'écart de 5 : il
        s'en faut d'un seul point que le drop le plus fréquent du jeu ne soit
        plus compté du tout.

        Et si le jeu avait fusionné dans l'autre sens, ce même mécanisme aurait
        rendu l'objet « (armure) », faux, en silence, avec la même assurance.

        Un résultat juste par accident est plus dangereux qu'un échec franc :
        rien ne le signale. La correction rend la reconnaissance **exacte**, ce
        qui supprime la chance de l'équation.

        Ce test utilise le VRAI fichier livré : il échouera si quelqu'un retire
        ou casse cette entrée.
        """
        from butin.catalog import ItemMatcher

        sans = ItemMatcher(ItemCatalog.from_raw(raw_catalog)).resolve("Pierre noire")
        assert sans is not None
        assert sans.method.value == "flou", "avant correction, la reconnaissance est fragile"
        assert sans.score < 100

        corrige = ItemCatalog.from_raw(
            raw_catalog, overrides=overrides.load(overrides.default_path())
        )
        match = ItemMatcher(corrige).resolve("Pierre noire")
        assert match is not None
        assert match.item.item_id == 16001
        assert match.method.value == "exact", "après correction, plus aucune part de chance"
        assert match.score == 100.0

    def test_un_identifiant_absent_du_catalogue_est_sans_effet(
        self, raw_catalog: dict[str, dict[str, object]]
    ) -> None:
        corrige = {999999999: VerifiedName(999999999, "Inexistant", ("bdocodex", "garmoth"))}
        catalog = ItemCatalog.from_raw(raw_catalog, overrides=corrige)
        assert catalog.get(999999999) is None
