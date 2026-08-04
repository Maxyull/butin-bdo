"""Tests de la reconnaissance d'objets.

Le fil conducteur : le matcher doit préférer ne rien rendre plutôt que rendre
un objet faux. Un drop raté fait un chiffre légèrement bas, un drop inventé
fait un chiffre faux, et l'utilisateur ne peut détecter ni l'un ni l'autre
depuis l'interface.
"""

from __future__ import annotations

from butin.catalog import ItemCatalog, ItemMatcher, MatchMethod, Scope


class TestCorrespondanceExacte:
    def test_nom_exact(self, matcher: ItemMatcher) -> None:
        match = matcher.resolve("Pierre noire (arme)")
        assert match is not None
        assert match.item.item_id == 16001
        assert match.method is MatchMethod.EXACT
        assert match.is_certain

    def test_insensible_a_la_casse(self, matcher: ItemMatcher) -> None:
        assert matcher.resolve("PIERRE NOIRE (ARME)").item.item_id == 16001

    def test_insensible_aux_accents(self, matcher: ItemMatcher) -> None:
        """L'OCR perd régulièrement les accents sur les majuscules du jeu."""
        match = matcher.resolve("Eclat de cristal noir tranchant")
        assert match is not None
        assert match.item.item_id == 4998
        assert match.method is MatchMethod.EXACT

    def test_insensible_a_la_ligature(self, matcher: ItemMatcher) -> None:
        """Régression : « Nœud d'arbre ensanglanté » lu sans ligature.

        Chemin exact, pas flou : après dépliage, les deux formes sont
        strictement identiques, donc la reconnaissance doit être certaine.
        """
        match = matcher.resolve("Noeud d'arbre ensanglante")
        assert match is not None
        assert match.item.item_id == 5005
        assert match.method is MatchMethod.EXACT

    def test_insensible_a_la_variante_d_apostrophe(self, matcher: ItemMatcher) -> None:
        for variante in ["Potion d'énergie (petite)", "Potion d’énergie (petite)"]:
            match = matcher.resolve(variante)
            assert match is not None, variante
            assert match.item.item_id == 586


class TestCorrespondanceFloue:
    def test_rattrape_une_lettre_abimee(self, matcher: ItemMatcher) -> None:
        match = matcher.resolve("Fragrnent de mémoire")
        assert match is not None
        assert match.item.item_id == 44195
        assert match.method is MatchMethod.FUZZY
        assert match.score < 100

    def test_rattrape_un_caractere_manquant(self, matcher: ItemMatcher) -> None:
        match = matcher.resolve("Pierre de Caphra")
        assert match is not None
        assert match.item.item_id == 721003

    def test_rejette_du_texte_sans_rapport(self, matcher: ItemMatcher) -> None:
        assert matcher.resolve("Vous avez rejoint le canal 3") is None

    def test_rejette_le_bruit_court(self, matcher: ItemMatcher) -> None:
        assert matcher.resolve("ll") is None
        assert matcher.resolve("x") is None


class TestAmbiguite:
    """Le cas le plus coûteux du projet.

    « Éclat de cristal noir tranchant » et « Éclat de cristal noir dur » sont
    deux vrais objets, tous deux du loot de farm courant, qui ne diffèrent que
    par leur dernier mot et dont les prix diffèrent nettement. Une lecture
    abîmée de l'un ne doit jamais être attribuée à l'autre.
    """

    def test_les_deux_noms_complets_se_resolvent_correctement(self, matcher: ItemMatcher) -> None:
        assert matcher.resolve("Éclat de cristal noir tranchant").item.item_id == 4998
        assert matcher.resolve("Éclat de cristal noir dur").item.item_id == 4997

    def test_un_dernier_mot_illisible_est_rejete(self, matcher: ItemMatcher) -> None:
        """Régression : le mot discriminant perdu doit annuler la ligne.

        Sans marge d'ambiguïté, le score flou tranche entre deux candidats
        quasi ex aequo et attribue silencieusement le drop au mauvais objet.
        Rendre None ici est le comportement voulu.
        """
        assert matcher.resolve("Éclat de cristal noir") is None

    def test_un_nom_partage_par_cinq_objets_departage_de_facon_stable(
        self, catalog: ItemCatalog, matcher: ItemMatcher
    ) -> None:
        """Cinq objets réels partagent le nom « Jeune dragon écarlate ».

        Le départage doit être déterministe : deux exécutions du programme sur
        la même capture doivent créditer le même identifiant, sinon le prix
        retenu change d'une session à l'autre sans raison visible.
        """
        premier = matcher.resolve("Jeune dragon écarlate")
        second = matcher.resolve("Jeune dragon écarlate")
        assert premier is not None and second is not None
        assert premier.item.item_id == second.item.item_id == 18480
        assert len(catalog.ids_for_name("Jeune dragon écarlate")) == 5

    def test_marge_desactivee_accepte_le_cas_ambigu(self, catalog: ItemCatalog) -> None:
        """Vérifie que c'est bien la marge qui produit le rejet ci-dessus.

        Sans ce contrôle, le test précédent pourrait passer pour une tout autre
        raison (score sous le seuil) et donner une fausse assurance sur un
        garde-fou qui ne servirait à rien.
        """
        permissif = ItemMatcher(catalog, ambiguity_margin=0.0, threshold=60.0)
        assert permissif.resolve("Éclat de cristal noir") is not None


class TestPerimetre:
    def test_le_perimetre_restreint_les_candidats(self, catalog: ItemCatalog) -> None:
        scope = Scope(catalog, [16001, 16002, 5956])
        matcher = ItemMatcher(catalog)
        match = matcher.resolve("Trace de sauvagerie", scope=scope)
        assert match is not None
        assert match.item.item_id == 5956

    def test_le_flou_ne_propose_pas_un_objet_hors_perimetre(self, catalog: ItemCatalog) -> None:
        """C'est tout l'intérêt du périmètre.

        Une lecture abîmée ne doit pas pouvoir être attribuée à un objet qui ne
        tombe pas sur le spot en cours, même si son nom ressemble à la ligne.
        """
        scope = Scope(catalog, [16001, 16002])
        matcher = ItemMatcher(catalog)
        assert matcher.resolve("Pierre de Caphra", scope=scope) is None

    def test_une_lecture_exacte_hors_perimetre_reste_acceptee(self, catalog: ItemCatalog) -> None:
        """Choix de conception, pas un oubli.

        Les tables de drops par spot sont saisies à la main, donc incomplètes.
        Une correspondance exacte signifie que le texte lu se replie caractère
        pour caractère sur un vrai nom : refuser cette certitude parce que
        notre table est en retard perdrait un vrai drop sans rien gagner.
        """
        scope = Scope(catalog, [16001, 16002])
        matcher = ItemMatcher(catalog)
        match = matcher.resolve("Pierre de Caphras", scope=scope)
        assert match is not None
        assert match.item.item_id == 721003

    def test_le_mode_strict_refuse_meme_une_lecture_exacte(self, catalog: ItemCatalog) -> None:
        scope = Scope(catalog, [16001, 16002], strict=True)
        matcher = ItemMatcher(catalog)
        assert matcher.resolve("Pierre de Caphras", scope=scope) is None
        assert matcher.resolve("Pierre noire (arme)", scope=scope) is not None

    def test_perimetre_vide_ignore(self, catalog: ItemCatalog) -> None:
        """Un périmètre vide ne doit pas bloquer toute reconnaissance.

        Il retombe sur le catalogue complet : mieux vaut un seuil plus
        exigeant qu'un tracker qui ne compte plus rien parce que la liste de
        drops du spot n'a pas encore été renseignée.
        """
        scope = Scope(catalog, [])
        matcher = ItemMatcher(catalog)
        assert matcher.resolve("Pierre de Caphras", scope=scope) is not None

    def test_identifiant_inconnu_ignore_sans_planter(self, catalog: ItemCatalog) -> None:
        scope = Scope(catalog, [16001, 999999999])
        assert len(scope) == 1


class TestSeuil:
    def test_seuil_haut_rejette_une_ressemblance_faible(self, catalog: ItemCatalog) -> None:
        strict = ItemMatcher(catalog, threshold=99.0)
        assert strict.resolve("Fragrnent de mémoire") is None

    def test_le_perimetre_utilise_un_seuil_plus_permissif(self, catalog: ItemCatalog) -> None:
        """Le seuil restreint est plus bas, et c'est volontaire.

        Sur quelques dizaines de candidats au lieu de plusieurs milliers, le
        risque de collision s'effondre, donc on peut accepter des lectures plus
        abîmées sans perdre en sûreté.
        """
        matcher = ItemMatcher(catalog)
        assert matcher.scoped_threshold < matcher.threshold
