"""Tests de la détection du spot de farm par le trash loot."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from butin.catalog import zones as zones_module
from butin.catalog.zones import (
    detect_spot,
    known_zones,
    load_zone_translations,
    load_zones,
    zones_for,
)

# Indicateurs réels, relevés dans data/butin-connu.json.
CHAINES_BRISEES = 43984  # mine de fer abandonnée
FRAGMENT_OS = 44069  # sanctuaire d'Hexe
CROC_RHUTUM = 44085  # avant-poste rhutum


@pytest.fixture
def table() -> dict[int, tuple[str, ...]]:
    return {
        CHAINES_BRISEES: ("Abandoned Iron Mine",),
        FRAGMENT_OS: ("Hexe Sanctuary",),
        CROC_RHUTUM: ("Rhutum Outstation",),
        999: ("Hexe Sanctuary", "Rhutum Outstation"),
    }


class TestDetection:
    def test_un_indicateur_suffit(self, table) -> None:
        """Le trash loot est propre à son spot.

        Voir tomber des « Chaînes brisées » veut dire qu'on est à la mine de fer
        abandonnée, et nulle part ailleurs.
        """
        assert detect_spot([CHAINES_BRISEES], table) == "Abandoned Iron Mine"

    def test_la_majorite_l_emporte(self, table) -> None:
        assert detect_spot([FRAGMENT_OS, FRAGMENT_OS, CROC_RHUTUM], table) == "Hexe Sanctuary"

    def test_les_objets_sans_zone_sont_ignores(self, table) -> None:
        assert detect_spot([16001, 44195, CHAINES_BRISEES], table) == "Abandoned Iron Mine"

    def test_aucun_indicateur_donne_none(self, table) -> None:
        assert detect_spot([16001, 44195], table) is None

    def test_une_egalite_ne_se_tranche_PAS_au_hasard(self, table) -> None:
        """Régression : une étiquette fausse est pire qu'une absente.

        Elle sera comparée à d'autres sessions ensuite, donc elle contamine des
        chiffres au-delà de la session concernée. Ne rien dire laisse
        l'utilisateur corriger ; se tromper ne lui laisse aucune chance de le
        remarquer.
        """
        assert detect_spot([FRAGMENT_OS, CROC_RHUTUM], table) is None

    def test_un_objet_de_plusieurs_zones_compte_pour_chacune(self, table) -> None:
        scores = zones_for([999], table)
        assert scores == {"Hexe Sanctuary": 1, "Rhutum Outstation": 1}

    def test_liste_vide(self, table) -> None:
        assert detect_spot([], table) is None


class TestFichierLivre:
    def test_le_fichier_du_depot_porte_bien_des_zones(self) -> None:
        table = load_zones()
        assert len(table) >= 100, "la liste livrée doit contenir les indicateurs de zone"

    def test_un_indicateur_connu_pointe_sur_sa_zone(self) -> None:
        assert load_zones()[CHAINES_BRISEES] == ("Abandoned Iron Mine",)

    def test_les_zones_connues_alimentent_un_choix(self) -> None:
        toutes = known_zones()
        assert len(toutes) >= 90
        assert toutes == tuple(sorted(toutes)), "triées, pour un menu stable"

    def test_fichier_absent_sans_erreur(self, tmp_path: Path, monkeypatch) -> None:
        """La détection de spot est un confort, pas une condition de
        fonctionnement : son absence ne doit rien empêcher."""
        monkeypatch.setattr(zones_module, "default_path", lambda: tmp_path / "rien.json")
        assert load_zones() == {}

    def test_fichier_corrompu_sans_erreur(self, tmp_path: Path) -> None:
        chemin = tmp_path / "casse.json"
        chemin.write_text("{pas du json", encoding="utf-8")
        assert load_zones(chemin) == {}

    def test_entrees_mal_formees_ignorees(self, tmp_path: Path) -> None:
        chemin = tmp_path / "partiel.json"
        chemin.write_text(
            json.dumps(
                {
                    "items": {
                        "1": {"zone_en": "Bonne Zone"},
                        "pas-un-nombre": {"zone_en": "X"},
                        "2": {"zone_en": ""},
                        "3": "pas un objet",
                    }
                }
            ),
            encoding="utf-8",
        )
        assert load_zones(chemin) == {1: ("Bonne Zone",)}


class TestTraductionDesZones:
    """zone_fr, ajoutée le 06/08/2026 : `detect_spot` rend un nom anglais,
    mais nommer une session en anglais serait la seule chose de tout le
    produit à ne pas être pensée pour le client français."""

    def test_une_zone_connue_se_traduit(self, tmp_path: Path) -> None:
        chemin = tmp_path / "zones.json"
        chemin.write_text(
            json.dumps(
                {"items": {"1": {"zone_en": "Sausan Garrison", "zone_fr": "Garnison des sausans"}}}
            ),
            encoding="utf-8",
        )
        assert load_zone_translations(chemin) == {"Sausan Garrison": "Garnison des sausans"}

    def test_une_zone_sans_traduction_connue_est_absente(self, tmp_path: Path) -> None:
        """Absente et non mappée sur elle-même : à l'appelant de choisir le
        repli, comme `load_zones` le documente déjà pour un fichier absent."""
        chemin = tmp_path / "zones.json"
        chemin.write_text(
            json.dumps({"items": {"1": {"zone_en": "Zone Inconnue", "zone_fr": ""}}}),
            encoding="utf-8",
        )
        assert load_zone_translations(chemin) == {}

    def test_fichier_absent_sans_erreur(self, tmp_path: Path) -> None:
        assert load_zone_translations(tmp_path / "rien.json") == {}

    def test_fichier_corrompu_sans_erreur(self, tmp_path: Path) -> None:
        chemin = tmp_path / "casse.json"
        chemin.write_text("{pas du json", encoding="utf-8")
        assert load_zone_translations(chemin) == {}

    def test_le_fichier_du_depot_traduit_un_indicateur_connu(self) -> None:
        """Même objet que `test_un_indicateur_connu_pointe_sur_sa_zone` :
        `load_zones` rend l'anglais (clé de regroupement), cette fonction
        rend la traduction de ce même anglais."""
        traductions = load_zone_translations()
        assert traductions["Abandoned Iron Mine"] == "Mine de fer abandonnée"


class TestPourquoiPasUnPerimetre:
    def test_les_zones_sont_trop_maigres_pour_restreindre(self) -> None:
        """Régression : documente pourquoi ces données ne font PAS un `Scope`.

        Environ un seul objet par zone. Un périmètre à un candidat ne restreint
        rien, il force : une lecture abîmée de n'importe quel autre objet se
        collerait sur l'unique candidat dès qu'elle atteint le seuil, ce qui
        recréerait l'attribution fausse qu'on a supprimée en branchant bdocodex.

        Ce test échouera si les données deviennent assez riches pour qu'un
        périmètre ait du sens. Ce sera le moment d'y revenir, pas avant.
        """
        table = load_zones()
        par_zone: dict[str, int] = {}
        for liste in table.values():
            for zone in liste:
                par_zone[zone] = par_zone.get(zone, 0) + 1

        moyenne = sum(par_zone.values()) / len(par_zone)
        assert moyenne < 2, (
            f"{moyenne:.1f} objets par zone en moyenne : si ça monte nettement, "
            "un vrai périmètre de reconnaissance redevient envisageable"
        )
