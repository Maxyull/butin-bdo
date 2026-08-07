"""Tests de la clé compacte : la reconnaissance malgré les espaces mangés.

⭐ Toutes les chaînes de ce fichier sont de VRAIES lectures, relevées dans le
journal de diagnostic d'une session de farm de Maxime le 07/08/2026
(`session-0009-20260807-032857.jsonl`). Aucune n'est inventée : c'est la règle
du dépôt, et elle compte doublement ici, puisque le défaut corrigé est
précisément une façon dont l'OCR abîme le texte — l'imaginer reviendrait à
corriger un problème qu'on aurait décidé soi-même.
"""

from __future__ import annotations

import pytest

from butin.catalog import ItemCatalog, ItemMatcher, MatchMethod
from butin.catalog.catalog import compact_key
from butin.catalog.models import Item

#: Relevées telles quelles dans le journal, avec le nom que le jeu affiche.
LECTURES_REELLES = [
    ("[Even.]Sceau deI'Agent", "[Évén.] Sceau de l'Agent"),
    ("[Even.] Sceau de I'Agent", "[Évén.] Sceau de l'Agent"),
    ("[Even.] Sceau del'Agent", "[Évén.] Sceau de l'Agent"),
    ("PierredeCaphras", "Pierre de Caphras"),
    ("Cristal demagienoire scelle", "Cristal de magie noire scellé"),
    ("Poussiere d'espritancien", "Poussière d'esprit ancien"),
]


def _catalogue(*noms: str) -> ItemCatalog:
    """Un catalogue minimal à partir de noms réels.

    ⚠️ Les doublons sont retirés : trois lectures abîmées visent le MÊME objet,
    et leur donner trois identifiants différents en ferait trois objets
    homonymes, donc une clé ambiguë que le code refuse à juste titre. Le banc
    d'essai fabriquait alors le défaut qu'il croyait mesurer.
    """
    uniques = list(dict.fromkeys(noms))
    return ItemCatalog([Item(item_id=1000 + i, names={"fr": nom}) for i, nom in enumerate(uniques)])


class TestCleCompacte:
    def test_elle_retire_les_espaces(self) -> None:
        assert compact_key("Pierre de Caphras") == compact_key("PierredeCaphras")

    def test_elle_unifie_les_glyphes_verticaux(self) -> None:
        """`l`, `I`, `1` et `|` se confondent dans la police du journal.

        Un nom qui contient « l' » les cumule avec l'espace mangé, ce qui
        explique que « Sceau de l'Agent » soit précisément celui qui disparaît.
        """
        for variante in ("Sceau de I'Agent", "Sceau de 1'Agent"):
            assert compact_key(variante) == compact_key("Sceau de l'Agent")

    def test_la_barre_verticale_est_deja_retiree_par_fold(self) -> None:
        """Elle n'est PAS dans la liste des glyphes, et ce n'est pas un oubli.

        `fold` la supprime comme ponctuation avant que la clé compacte ne voie
        quoi que ce soit. L'ajouter serait du code mort, et laisser croire
        qu'elle est traitée serait pire que de ne pas la traiter.
        """
        from butin.catalog.normalize import fold

        assert "|" not in fold("Sceau de |'Agent")

    def test_elle_ne_confond_pas_deux_noms_differents(self) -> None:
        assert compact_key("Pierre noire") != compact_key("Pierre de Caphras")


class TestLecturesReelles:
    @pytest.mark.parametrize(("lu", "attendu"), LECTURES_REELLES)
    def test_chaque_lecture_abimee_retrouve_son_objet(self, lu: str, attendu: str) -> None:
        """Régression : ces six chaînes viennent d'une vraie session.

        Deux d'entre elles n'étaient reconnues PAR RIEN avant ce correctif
        (« [Even.]Sceau deI'Agent » et « PierredeCaphras ») : le drop était
        perdu en silence. Les autres passaient par un score flou, donc par une
        décision qui pouvait désigner le mauvais objet.
        """
        matcher = ItemMatcher(_catalogue(*(nom for _, nom in LECTURES_REELLES)))
        resultat = matcher.resolve(lu)
        assert resultat is not None, f"« {lu} » n'est reconnu par rien"
        assert resultat.item.name() == attendu

    @pytest.mark.parametrize(("lu", "_attendu"), LECTURES_REELLES)
    def test_elles_sont_reconnues_EXACTEMENT_et_non_au_score(self, lu: str, _attendu: str) -> None:
        """⭐ Ce qui change vraiment : une certitude au lieu d'une devinette.

        Avant, « Sceau de I'Agent » sortait en flou à **95,0**. Un score de 95
        peut désigner le mauvais objet ; une clé exacte ne le peut pas. C'est
        le principe qui tranche tout dans ce projet : rater un drop donne un
        chiffre bas, en inventer un donne un chiffre faux.

        Exception assumée : « Pierrenoire » reste flou, parce que le nom du
        jeu comporte un suffixe que la clé compacte ne reconstitue pas. Il
        n'est donc pas dans cette liste.
        """
        matcher = ItemMatcher(_catalogue(*(nom for _, nom in LECTURES_REELLES)))
        resultat = matcher.resolve(lu)
        assert resultat is not None
        assert resultat.method is MatchMethod.EXACT
        assert resultat.score == 100.0


class TestElleNeDecideJamaisAuHasard:
    def test_une_cle_partagee_par_DEUX_objets_est_refusee(self) -> None:
        """⛔ Le garde-fou qui rend ce raccourci acceptable.

        Deux objets différents dont les noms deviennent identiques une fois
        compactés ne peuvent pas être départagés : les distinguer demanderait
        justement l'information qu'on vient de jeter. On refuse, et le score
        flou reprend la main avec sa propre marge d'ambiguïté.

        Trancher au hasard reviendrait à attribuer un drop au mauvais objet,
        donc à inventer une valeur — l'erreur que ce projet refuse en premier.
        """
        catalogue = _catalogue("Anneau de Tuvala", "Anneaude Tuvala")
        assert catalogue.by_compact_name("AnneaudeTuvala") is None

    def test_deux_ecritures_du_MEME_objet_restent_resolues(self) -> None:
        """La plupart des collisions mesurées sont de ce genre.

        Sur le catalogue réel, les six clés que le retrait des espaces fusionne
        sont le même objet écrit « 7 jours » et « 7jours ». Refuser celles-là
        serait perdre un objet parfaitement identifiable.
        """
        catalogue = ItemCatalog(
            [
                Item(item_id=42, names={"fr": "Tenue de Valks 7 jours"}),
                Item(item_id=42, names={"fr": "Tenue de Valks 7jours"}),
            ]
        )
        resolu = catalogue.by_compact_name("Tenue de Valks 7 jours")
        assert resolu is not None
        assert resolu.item_id == 42

    def test_le_cout_sur_le_vrai_catalogue_reste_negligeable(self) -> None:
        """Mesure, pas promesse : le seuil vient d'un comptage réel.

        57 547 noms, 13 clés fusionnées, soit 0,02 %. Le plafond est posé
        largement au-dessus pour ne pas casser à chaque mise à jour du jeu,
        mais assez bas pour signaler une dérive : si ce chiffre explose, c'est
        que la clé est devenue trop permissive et il faudra la resserrer.

        ⚠️ Ignoré quand le catalogue réel n'est pas en cache : l'intégration
        continue n'a pas le droit d'aller le chercher sur le réseau, et un test
        qui échouerait faute de données ne dirait rien sur le code.
        """
        from butin.catalog.source import CatalogError

        try:
            catalogue = ItemCatalog.load(allow_download=False)
        except CatalogError:
            pytest.skip("catalogue réel absent du cache")
        fusions = sum(
            len(set(ids)) - 1 for ids in catalogue._by_compact.values() if len(set(ids)) > 1
        )
        assert fusions <= 60, f"{fusions} objets deviennent ambigus : la clé est trop large"


class TestOrdreDesEtapes:
    def test_une_correspondance_stricte_gagne_toujours(self) -> None:
        """La clé compacte est un RATTRAPAGE, pas le chemin normal.

        Tant qu'un nom se lit correctement, c'est lui qui décide. Inverser
        l'ordre ferait passer tout le catalogue par une clé plus permissive
        sans aucun gain, et rendrait les collisions bien plus probables.
        """
        catalogue = _catalogue("Pierre noire", "Pierrenoire (arme)")
        matcher = ItemMatcher(catalogue)
        resultat = matcher.resolve("Pierre noire")
        assert resultat is not None
        assert resultat.item.name() == "Pierre noire"
        assert resultat.method is MatchMethod.EXACT
