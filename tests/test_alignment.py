"""Tests de l'alignement de deux captures.

L'invariant testé partout : les lignes communes forment un suffixe de l'ancienne
capture et un préfixe de la nouvelle, donc les lignes nouvelles sont
`current[recouvrement:]`.
"""

from __future__ import annotations

from butin.catalog import ItemCatalog
from butin.tracking import align, is_glitch_frame, is_implausible_jump
from butin.tracking.alignment import (
    GLITCH_MAX_SKIPS,
    PLAUSIBLE_MAX_NEW,
    AlignmentResult,
    plausible_max_new,
)
from butin.tracking.models import ObservedLine


def ligne(catalog: ItemCatalog, item_id: int, qty: int = 1) -> ObservedLine:
    item = catalog.get(item_id)
    return ObservedLine(raw=item.name() if item else "?", item=item, qty=qty)


# Quatre objets distincts, pour composer des fenêtres lisibles.
A, B, C, D = 16001, 16002, 4998, 721003


class TestCasNominal:
    def test_defilement_d_une_ligne(self, catalog: ItemCatalog) -> None:
        previous = [ligne(catalog, A), ligne(catalog, B), ligne(catalog, C)]
        current = [ligne(catalog, B), ligne(catalog, C), ligne(catalog, D)]

        result = align(previous, current)

        assert result.overlap == 2
        assert [line.item_id for line in result.new_lines] == [D]
        assert not result.zero_overlap

    def test_aucun_defilement(self, catalog: ItemCatalog) -> None:
        window = [ligne(catalog, A), ligne(catalog, B), ligne(catalog, C)]
        result = align(window, list(window))
        assert result.overlap == 3
        assert result.new_lines == []

    def test_defilement_de_plusieurs_lignes(self, catalog: ItemCatalog) -> None:
        previous = [ligne(catalog, A), ligne(catalog, B), ligne(catalog, C)]
        current = [ligne(catalog, C), ligne(catalog, D), ligne(catalog, A)]
        result = align(previous, current)
        assert result.overlap == 1
        assert len(result.new_lines) == 2

    def test_premiere_capture_tout_est_nouveau(self, catalog: ItemCatalog) -> None:
        current = [ligne(catalog, A), ligne(catalog, B)]
        result = align([], current)
        assert result.overlap == 0
        assert len(result.new_lines) == 2
        assert not result.zero_overlap, "aucune image précédente n'est pas un cas suspect"

    def test_deux_captures_vides(self, catalog: ItemCatalog) -> None:
        result = align([], [])
        assert result.overlap == 0
        assert result.new_lines == []
        assert not result.zero_overlap


class TestPlusGrandRecouvrement:
    def test_le_plus_grand_recouvrement_est_retenu(self, catalog: ItemCatalog) -> None:
        """Choisir le plus grand recouvrement déclare le moins de nouveautés.

        C'est ce qui protège du recomptage : à choisir entre deux lectures
        possibles, on prend celle qui compte le moins de drops.
        """
        previous = [ligne(catalog, A), ligne(catalog, A), ligne(catalog, A)]
        current = [ligne(catalog, A), ligne(catalog, A), ligne(catalog, A)]
        result = align(previous, current)
        assert result.overlap == 3
        assert result.new_lines == []


class TestMurDeLignesIdentiques:
    """Le cas que le texte seul ne peut pas trancher.

    Dix « Pierre noire (arme) x1 » d'affilée est la situation normale en farm,
    pas un cas limite. Plusieurs recouvrements sont alors valides, et le texte
    n'a aucun moyen de choisir. Seuls les pixels le peuvent.
    """

    def test_sans_indice_pixel_le_texte_surestime_le_recouvrement(
        self, catalog: ItemCatalog
    ) -> None:
        """Régression : documente le point aveugle de l'alignement textuel.

        Cinq lignes identiques dont une a réellement défilé. Le texte retient
        le recouvrement maximal et conclut à zéro nouveauté, donc rate le drop.
        Ce test fige le comportement pour que le suivant montre le rattrapage.
        """
        previous = [ligne(catalog, A) for _ in range(5)]
        current = [ligne(catalog, A) for _ in range(5)]

        result = align(previous, current)

        assert result.overlap == 5
        assert result.new_lines == []

    def test_l_indice_pixel_tranche(self, catalog: ItemCatalog) -> None:
        """Les pixels disent qu'une ligne a défilé, l'alignement s'y range."""
        previous = [ligne(catalog, A) for _ in range(5)]
        current = [ligne(catalog, A) for _ in range(5)]

        result = align(previous, current, expected_new=1)

        assert result.overlap == 4
        assert len(result.new_lines) == 1
        assert result.diagnostics["disagreement"] is True

    def test_le_desaccord_est_trace_pas_masque(self, catalog: ItemCatalog) -> None:
        """Un désaccord texte/pixels doit rester visible dans le diagnostic.

        Un tracker qui se trompe sans laisser de trace n'est pas
        diagnosticable : l'utilisateur voit un chiffre, jamais le raisonnement.
        """
        previous = [ligne(catalog, A) for _ in range(4)]
        current = [ligne(catalog, A) for _ in range(4)]

        result = align(previous, current, expected_new=2)

        assert result.diagnostics["largest_valid"] == 4
        assert result.diagnostics["target_overlap"] == 2
        assert result.diagnostics["disagreement"] is True

    def test_l_indice_pixel_ne_cree_pas_un_recouvrement_invalide(
        self, catalog: ItemCatalog
    ) -> None:
        """Les pixels orientent le choix, ils ne l'imposent pas.

        Seuls les recouvrements textuellement valides sont candidats. Une
        prédiction fausse ne peut donc pas fabriquer un alignement absurde.
        """
        previous = [ligne(catalog, A), ligne(catalog, B), ligne(catalog, C)]
        current = [ligne(catalog, B), ligne(catalog, C), ligne(catalog, D)]

        result = align(previous, current, expected_new=0)

        assert result.overlap in result.diagnostics["valid_overlaps"]
        assert [line.item_id for line in result.new_lines] == [D]


class TestUnePredictionFausseNeVidePasLeRecouvrement:
    """⛔ Régression : la moitié d'une vraie session comptée en trop.

    Session 0018 du 08/08/2026, aux Ruines de Sycraia, dix-huit secondes après
    le démarrage. L'écran montrait deux lignes déjà vues à l'amorce plus une
    neuve, donc un recouvrement de 2. La fenêtre de chat se remplissait encore,
    donc la mesure de défilement n'avait aucun sens : elle a prédit **3**
    nouvelles lignes.

    `k = 0` est toujours un recouvrement « valide » — il n'a aucune paire à
    contredire — et il était candidat à égalité avec les autres. La cible étant
    zéro, il a gagné. Les deux emplacements posés par l'amorce sont sortis de la
    liste, trois emplacements neufs et non validés les ont remplacés, et six
    secondes plus tard un « Élixir d'expérience splendide » que le joueur
    possédait **avant** la session a été crédité **6 261 unités** : la moitié du
    total de la session.

    ⭐ L'amorce avait parfaitement fait son travail. C'est l'alignement qui l'a
    défaite, et c'est donc là que le correctif va.

    ⚠️ Le banc d'essai ne peut pas valider ce correctif : sa rafale ne contient
    pas le cas (aucune image sans recouvrement sur les 300). Il montre
    seulement l'absence de régression — 47/47 drops et 140/140 unités, inchangés.
    """

    def test_le_cas_reel_de_la_session_0018(self, catalog: ItemCatalog) -> None:
        """Deux lignes déjà vues, une neuve, et les pixels qui en annoncent trois."""
        previous = [ligne(catalog, A), ligne(catalog, B)]
        current = [ligne(catalog, A), ligne(catalog, B), ligne(catalog, C)]

        result = align(previous, current, expected_new=3)

        assert result.overlap == 2, "les deux lignes déjà vues seraient recomptées"
        assert [line.item_id for line in result.new_lines] == [C]
        assert result.zero_overlap is False

    def test_sans_le_correctif_le_choix_serait_zero(self, catalog: ItemCatalog) -> None:
        """⛔ Le banc doit pouvoir montrer ce qu'il garde, sinon il ne garde rien.

        Ce test fige les deux faits qui rendaient l'erreur possible : le
        recouvrement vide EST valide, et la cible visée par les pixels EST zéro.
        Si l'un des deux disparaissait un jour, le test ci-dessus passerait pour
        une raison qui n'a rien à voir avec le correctif.
        """
        previous = [ligne(catalog, A), ligne(catalog, B)]
        current = [ligne(catalog, A), ligne(catalog, B), ligne(catalog, C)]

        result = align(previous, current, expected_new=3)

        assert 0 in result.diagnostics["valid_overlaps"]
        assert result.diagnostics["target_overlap"] == 0
        assert result.diagnostics["vide_ecarte"] is True

    def test_le_vide_reste_atteignable_quand_le_texte_n_offre_RIEN(
        self, catalog: ItemCatalog
    ) -> None:
        """⛔ Le correctif ne doit pas rendre le recouvrement nul impossible.

        Un vrai renouvellement complet de l'écran existe — le joueur change de
        zone, le chat est vidé — et `is_glitch_frame` a besoin de le voir pour
        écarter l'image. Écarter le vide *par principe* le rendrait aveugle.
        """
        previous = [ligne(catalog, A), ligne(catalog, B)]
        current = [ligne(catalog, C), ligne(catalog, D)]

        result = align(previous, current, expected_new=2)

        assert result.overlap == 0
        assert result.zero_overlap is True

    def test_les_pixels_arbitrent_toujours_entre_deux_recouvrements_REELS(
        self, catalog: ItemCatalog
    ) -> None:
        """Le mur de lignes identiques ne doit pas être cassé par le correctif.

        C'est tout l'intérêt de la prédiction, et elle porte sur des
        recouvrements que le texte soutient tous : le correctif ne touche que le
        cas où elle désigne le vide.
        """
        previous = [ligne(catalog, A) for _ in range(5)]
        current = [ligne(catalog, A) for _ in range(5)]

        result = align(previous, current, expected_new=2)

        assert result.overlap == 3
        assert len(result.new_lines) == 2


class TestBruitDeLecture:
    def test_un_chiffre_mal_lu_ne_casse_pas_l_alignement(self, catalog: ItemCatalog) -> None:
        """Régression : sinon le drop mal lu est recompté.

        Si la ligne portée à 68 puis relue 88 était vue comme une autre ligne,
        l'alignement conclurait qu'une ligne a disparu et qu'une nouvelle est
        apparue, donc compterait le drop deux fois.
        """
        previous = [ligne(catalog, A), ligne(catalog, B, qty=68)]
        current = [ligne(catalog, A), ligne(catalog, B, qty=88)]

        result = align(previous, current)

        assert result.overlap == 2
        assert result.new_lines == []

    def test_une_ligne_illisible_ne_fait_pas_perdre_tout_le_recouvrement(
        self, catalog: ItemCatalog
    ) -> None:
        """Régression : une ligne ratée annulait un recouvrement de vingt.

        `_overlap_score` exigeait que **toutes** les paires franchissent le
        seuil. Il suffisait donc qu'une seule ligne de la fenêtre soit mal lue
        pour qu'aucun recouvrement ne soit jugé valide : l'appelant concluait
        que rien ne se recouvrait, et `is_glitch_frame` jetait l'image entière.

        Mesuré par le banc d'essai le 05/08/2026 sur 300 images de vrai farm :
        **8 lectures sur 15 partaient ainsi à la poubelle**, alors qu'elles
        portaient chacune une vingtaine de lignes parfaitement lisibles. C'est
        ce qui faisait perdre les trois quarts du butin.

        Ici une ligne sur vingt est illisible, la proportion réellement
        observée.
        """
        fenetre = [ligne(catalog, A, qty=index + 1) for index in range(20)]
        previous = list(fenetre)
        current = [*fenetre[1:], ligne(catalog, D)]
        # L'OCR n'a pas reconnu l'objet sur cette lecture-là : la ligne existe
        # toujours à l'écran, mais elle ne ressemble plus à rien.
        current[5] = ObservedLine(raw="Systeme Vous avez obtenu : [??] x9 (01:45)")

        result = align(previous, current)

        assert result.overlap == 19
        assert [line.item_id for line in result.new_lines] == [D]
        assert not is_glitch_frame(result, previous_length=20, consecutive_skips=0)
        assert result.diagnostics["mismatched_pairs"] == 1

    def test_un_recouvrement_a_moitie_faux_reste_refuse(self, catalog: ItemCatalog) -> None:
        """L'autre bord du seuil : la tolérance ne doit rien ouvrir de plus.

        C'est le test qui compte le plus des deux. Accepter un recouvrement
        trop petit ferait déclarer nouvelles des lignes déjà comptées, donc
        **recompter des drops**, ce qui est l'erreur que ce projet refuse.

        Le seuil est posé au milieu de deux populations mesurées sur les 300
        images : le vrai recouvrement accorde 74 % à 100 % de ses paires, le
        meilleur des faux n'en accorde jamais plus de 50 %. Ici la moitié des
        paires s'accordent, exactement le pire cas mesuré côté faux.
        """
        previous = [ligne(catalog, A), ligne(catalog, B), ligne(catalog, C), ligne(catalog, D)]
        current = [ligne(catalog, A), ligne(catalog, D), ligne(catalog, B), ligne(catalog, C)]

        result = align(previous, current)

        assert 4 not in result.diagnostics["valid_overlaps"]


class TestImageAberrante:
    def test_perte_totale_de_recouvrement_signalee(self, catalog: ItemCatalog) -> None:
        previous = [ligne(catalog, A), ligne(catalog, B), ligne(catalog, C)]
        current = [ligne(catalog, D), ligne(catalog, D), ligne(catalog, D)]

        result = align(previous, current)

        assert result.overlap == 0
        assert result.zero_overlap
        assert "reason" in result.diagnostics

    def test_image_aberrante_ignoree(self, catalog: ItemCatalog) -> None:
        previous = [ligne(catalog, A), ligne(catalog, B), ligne(catalog, C)]
        current = [ligne(catalog, D), ligne(catalog, D), ligne(catalog, D)]
        result = align(previous, current)

        assert is_glitch_frame(result, previous_length=3, consecutive_skips=0)

    def test_on_finit_par_ceder(self, catalog: ItemCatalog) -> None:
        """Régression : sans borne, le tracker se figerait pour de bon.

        Un vrai changement d'écran (changement de spot, redémarrage du jeu)
        produit une perte totale de recouvrement légitime. S'entêter à
        l'ignorer bloquerait le suivi jusqu'à la fin de la session.
        """
        previous = [ligne(catalog, A), ligne(catalog, B), ligne(catalog, C)]
        current = [ligne(catalog, D), ligne(catalog, D), ligne(catalog, D)]
        result = align(previous, current)

        assert not is_glitch_frame(result, 3, consecutive_skips=GLITCH_MAX_SKIPS)

    def test_pas_de_garde_fou_sans_base_credible(self, catalog: ItemCatalog) -> None:
        """Perdre le recouvrement d'une fenêtre d'une seule ligne est normal."""
        previous = [ligne(catalog, A)]
        current = [ligne(catalog, D)]
        result = align(previous, current)

        assert not is_glitch_frame(result, previous_length=1, consecutive_skips=0)


def saut_de(catalog: ItemCatalog, nouvelles: int) -> AlignmentResult:
    """Alignement déclarant `nouvelles` lignes nouvelles et rien de commun."""
    previous = [ligne(catalog, A)]
    current = [ligne(catalog, D) for _ in range(nouvelles)]
    return align(previous, current)


class TestSautInvraisemblable:
    def _resultat_avec(self, catalog: ItemCatalog, nouvelles: int) -> AlignmentResult:
        return saut_de(catalog, nouvelles)

    def test_saut_normal_accepte(self, catalog: ItemCatalog) -> None:
        result = self._resultat_avec(catalog, 3)
        assert not is_implausible_jump(result, consecutive_skips=0)

    def test_saut_enorme_rejete(self, catalog: ItemCatalog) -> None:
        """Le journal ne défile pas de vingt lignes en un dixième de seconde."""
        result = self._resultat_avec(catalog, PLAUSIBLE_MAX_NEW + 10)
        assert is_implausible_jump(result, consecutive_skips=0)

    def test_les_pixels_autorisent_le_saut(self, catalog: ItemCatalog) -> None:
        """Deux signaux indépendants qui concordent priment sur notre plafond.

        Le plafond est une supposition sur ce qui est plausible. Une mesure de
        défilement qui confirme le saut vaut mieux qu'une supposition.
        """
        nouvelles = PLAUSIBLE_MAX_NEW + 10
        result = self._resultat_avec(catalog, nouvelles)
        assert not is_implausible_jump(result, 0, expected_new=nouvelles)

    def test_on_finit_par_ceder(self, catalog: ItemCatalog) -> None:
        result = self._resultat_avec(catalog, PLAUSIBLE_MAX_NEW + 10)
        assert not is_implausible_jump(result, consecutive_skips=GLITCH_MAX_SKIPS)


class TestPlafondSelonLeTempsEcoule:
    def test_le_plafond_suit_l_intervalle(self) -> None:
        """Deux secondes autorisent vingt fois ce qu'autorise un dixième."""
        assert plausible_max_new(2.0) == 40
        assert plausible_max_new(5.0) == 100

    def test_le_plancher_protege_les_intervalles_courts(self) -> None:
        """Le plafond ne doit jamais devenir plus sévère qu'avant.

        Sur un intervalle très court, le calcul au débit donnerait un plafond
        inférieur à l'ancienne constante, donc rejetterait des lectures que le
        code acceptait. Un correctif ne doit pas resserrer ce qu'il vient
        desserrer.
        """
        assert plausible_max_new(0.1) == PLAUSIBLE_MAX_NEW
        assert plausible_max_new(0.0) == PLAUSIBLE_MAX_NEW

    def test_quatorze_lignes_en_deux_secondes_sont_normales(self, catalog: ItemCatalog) -> None:
        """Régression : le plafond supposait une cadence que la boucle n'a pas.

        `PLAUSIBLE_MAX_NEW` valait 10 avec pour justification écrite que « le
        journal ne défile pas de dix lignes en un dixième de seconde ». C'était
        vrai de la cadence de **capture**, pas de celle de **lecture** : la
        reconnaissance ne tourne qu'une fois par seconde au mieux.

        Mesuré par le banc le 05/08/2026 : une lecture portant **14 lignes
        réellement nouvelles** après deux secondes était rejetée comme un saut
        invraisemblable, donc quatorze lignes de journal perdues d'un coup.
        """
        result = saut_de(catalog, 14)

        assert not is_implausible_jump(result, 0, max_new=plausible_max_new(2.0))
        assert is_implausible_jump(result, 0, max_new=plausible_max_new(0.1))
