"""Tests de la source de noms bdocodex.

Le module n'en avait aucun, alors qu'il fait **autorité sur les noms** : mesuré,
l'ancienne source attribuait des objets faux en silence, pas seulement des
oublis. Ce qui se passe ici décide de ce qu'un drop devient.

Les exports sont fabriqués à la forme réelle de bdocodex, relevée sur le fichier
en cache : une enveloppe `aaData`, et par ligne l'identifiant, une vignette, puis
le nom habillé de son balisage de rendu avec sa classe de rareté.
"""

from __future__ import annotations

import json

import pytest

from butin.catalog import bdocodex
from butin.catalog.source import CatalogError


def _ligne(item_id: int, nom: str, grade: int) -> list[object]:
    """Une ligne d'export, au format réel."""
    lien = (
        f'<a href="/fr/item/{item_id}/" class="qtooltip item_grade_{grade}" '
        f'data-id="item--{item_id}"><b><span></span>{nom}</b></a>'
    )
    return [item_id, "<div>vignette</div>", lien, 1, "[255]", grade, "[0,0]"]


def _export(lignes: list[list[object]], *, complet: bool = True) -> bytes:
    """Un export, rembourré jusqu'au minimum attendu par le garde-fou.

    Le rembourrage n'est pas un artifice : `extract` refuse un export
    anormalement court, parce qu'une source qui rend soudain trois objets a
    changé de format. Un test qui n'en tiendrait pas compte mesurerait le
    garde-fou au lieu de la lecture. `complet=False` sert justement à mesurer le
    garde-fou.
    """
    corps = list(lignes)
    if complet:
        depart = 900_000
        corps += [
            _ligne(depart + index, f"Remplissage {index}", 0) for index in range(bdocodex.MIN_ITEMS)
        ]
    return json.dumps({"aaData": corps}, ensure_ascii=False).encode("utf-8")


class TestLecture:
    def test_les_noms_sont_deshabilles_de_leur_balisage(self) -> None:
        charge = _export([_ligne(16001, "Pierre noire (arme)", 4)])

        assert bdocodex.extract(charge)[16001] == "Pierre noire (arme)"

    def test_les_entites_html_sont_rendues(self) -> None:
        """« Bo&icirc;te » doit redevenir « Boîte », sinon le nom ne se
        reconnaît jamais."""
        charge = _export([_ligne(1, "Bo&icirc;te de Cleia", 2)])

        assert bdocodex.extract(charge)[1] == "Boîte de Cleia"

    def test_la_rarete_est_lue_dans_la_classe_de_rendu(self) -> None:
        """C'est le code couleur du jeu, et il était disponible sans être lu.

        Vérifié sur 8 000 lignes de l'export réel : la classe et la sixième
        colonne portent la même valeur, sans un seul désaccord. La classe est
        retenue parce qu'elle est nommée, là où un indice de colonne se décale
        en silence le jour où l'export gagne un champ.
        """
        charge = _export([_ligne(16001, "Pierre noire", 4), _ligne(4998, "Éclat", 2)])

        grades = bdocodex.extract_grades(charge)

        assert (grades[16001], grades[4998]) == (4, 2)

    def test_une_ligne_sans_rarete_est_ignoree_et_non_comptee_zero(self) -> None:
        """Zéro est une vraie rareté, celle des objets communs.

        La confondre avec « inconnu » afficherait en blanc des objets dont on ne
        sait rien, ce qui est une affirmation et non une absence.
        """
        charge = _export([[7, "<div/>", "<b>Sans classe</b>", 1, "[]", 0, "[]"]], complet=False)

        assert bdocodex.extract_grades(charge) == {}

    def test_un_export_sans_enveloppe_est_refuse(self) -> None:
        with pytest.raises(CatalogError, match="aaData"):
            bdocodex.extract(json.dumps({"autre": []}).encode("utf-8"))

    def test_un_export_illisible_est_refuse(self) -> None:
        with pytest.raises(CatalogError, match="illisible"):
            bdocodex.extract(b"\xff\xfe pas du json")

    def test_un_export_anormalement_court_est_refuse(self) -> None:
        """Une source qui rend soudain trois objets a changé de format.

        L'accepter remplacerait 68 000 noms par trois, et tous les drops
        deviendraient inconnus sans qu'aucune erreur ne le dise.
        """
        with pytest.raises(CatalogError, match="anormalement court"):
            bdocodex.extract(_export([_ligne(1, "Un", 0)], complet=False))


class TestCacheCompact:
    def test_les_langues_et_les_raretes_sont_fusionnees(self) -> None:
        compact = bdocodex.build_compact(
            {"fr": {16001: "Pierre noire"}, "us": {16001: "Black Stone"}}, {16001: 4}
        )

        assert compact["16001"][bdocodex.COMPACT_NAMES] == {
            "fr": "Pierre noire",
            "us": "Black Stone",
        }
        assert compact["16001"][bdocodex.COMPACT_GRADE] == 4

    def test_une_rarete_sans_nom_est_ignoree(self) -> None:
        """Un objet dont on connaît la couleur mais pas le nom n'existe pas.

        L'ajouter créerait une entrée sans nom, qui ne se reconnaîtrait jamais
        et alourdirait l'index du score flou pour rien.
        """
        compact = bdocodex.build_compact({"fr": {1: "Un"}}, {1: 2, 999: 4})

        assert "999" not in compact

    def test_la_charge_du_catalogue_porte_la_rarete(self) -> None:
        compact = bdocodex.build_compact({"fr": {1: "Un"}}, {1: 3})

        charge = bdocodex.to_catalog_payload(compact)

        assert charge["1"]["grade"] == 3
        assert charge["1"]["locale_name"] == {"fr": "Un"}

    def test_un_objet_sans_rarete_connue_vaut_zero(self) -> None:
        charge = bdocodex.to_catalog_payload(bdocodex.build_compact({"fr": {1: "Un"}}))

        assert charge["1"]["grade"] == 0


class TestFormatPerime:
    def test_un_cache_de_l_ancienne_version_est_rejete(self) -> None:
        """Régression : les noms étaient à la racine, ils sont sous une clé.

        Charger un ancien cache à moitié afficherait des objets **sans nom**, ce
        qui ressemble à un défaut de catalogue alors que c'est un format périmé.
        Le rejeter le fait reconstruire depuis les exports bruts déjà sur le
        disque, sans retélécharger 70 Mo.
        """
        ancien = {str(index): {"fr": f"Objet {index}"} for index in range(bdocodex.MIN_ITEMS + 1)}

        assert bdocodex._compact_valide(ancien) is False

    def test_un_cache_au_format_courant_est_accepte(self) -> None:
        entree = {bdocodex.COMPACT_NAMES: {"fr": "Objet"}, bdocodex.COMPACT_GRADE: 0}
        courant = {str(index): dict(entree) for index in range(bdocodex.MIN_ITEMS + 1)}

        assert bdocodex._compact_valide(courant) is True

    def test_un_cache_trop_court_est_rejete(self) -> None:
        assert bdocodex._compact_valide({"1": {bdocodex.COMPACT_NAMES: {"fr": "Un"}}}) is False
