"""Tests du découpage d'une ligne du journal d'acquisition.

**Toutes les lignes de ce fichier sont de vraies lignes**, relevées sur des
captures du client français le 04/08/2026. Rien n'est inventé, parce que chaque
piège traité ici est un piège qu'on n'aurait pas imaginé : la quantité 1 qui ne
s'écrit pas, les virgules de milliers, les crochets à l'intérieur d'un nom.

Le relevé complet est dans `docs/journal-acquisition.md`.
"""

from __future__ import annotations

import pytest

from butin.capture.lines import (
    DEFAULT_FORMAT,
    ChatLineFormat,
    is_stale,
    parse_frame,
    parse_line,
    split_line,
    stamp_minutes,
)
from butin.catalog import ItemCatalog, ItemMatcher

# Lignes recopiées telles qu'elles apparaissent à l'écran.
REELLES = {
    "pieces": "Système Vous avez obtenu : [Pièces] x10,000,000 (20:07)",
    "humus": "Système Vous avez obtenu : [Humus noir] x3 (20:13)",
    "anneau": "Système Vous avez obtenu : [Anneau de Tuvala]. (20:20)",
    "pierre_seule": "Système Vous avez obtenu : [Pierre noire]. (20:41)",
    "boucle": "Système Vous avez obtenu : [Boucle d'oreille de Tuvala]. (21:23)",
    "pain": "Système Vous avez obtenu : [Pain moelleux]. (21:38)",
    "pierre_x3": "Système Vous avez obtenu : [Pierre noire] x3 (21:54)",
    "pierre_x5": "Système Vous avez obtenu : [Pierre noire] x5 (21:54)",
    "costume": "Système Vous avez obtenu : [Boîte de costume de soldat de Serendia]. (22:03)",
    "imbrique": "Système Vous avez obtenu : [[Serendia] Boîte de tenue de Cleia]. (22:09)",
    "chat_brb": "Général [Xerkz] : brb (21:34)",
    "chat_xd": "Général [Maxyy] : gz on officer xD (21:38)",
    "systeme_non_butin": "Système [ Edmund ] (21:44)",
}


class TestQuantite:
    def test_une_quantite_de_1_ne_s_ecrit_pas(self) -> None:
        """Régression : le piège le plus coûteux, parce qu'il est silencieux.

        Une quantité de 1 ne s'écrit JAMAIS « x1 ». Elle s'écrit par l'absence
        de marqueur et un point collé au crochet fermant. Un analyseur qui
        cherche « x(\\d+) » et se rabat sur 1 tombe juste ici par accident, mais
        pour la mauvaise raison.
        """
        parts = split_line(REELLES["anneau"])
        assert parts is not None
        assert parts.name == "Anneau de Tuvala"
        assert parts.qty == 1
        assert not parts.quantity_uncertain

    def test_quantite_explicite(self) -> None:
        parts = split_line(REELLES["pierre_x3"])
        assert parts is not None
        assert parts.name == "Pierre noire"
        assert parts.qty == 3

    def test_les_milliers_sont_separes_par_des_virgules(self) -> None:
        """Régression : « x(\\d+) » s'arrête à 10 et compte dix pièces.

        Au lieu de dix millions. Facteur d'erreur d'un million sur la ligne la
        plus lourde du journal.
        """
        parts = split_line(REELLES["pieces"])
        assert parts is not None
        assert parts.qty == 10_000_000

    @pytest.mark.parametrize(
        ("tail", "attendu"),
        [("x3", 3), ("x 3", 3), ("×3", 3), ("x10,000,000", 10_000_000), ("x1 000", 1000)],
    )
    def test_variantes_de_marqueur(self, tail: str, attendu: int) -> None:
        parts = split_line(f"Système Vous avez obtenu : [Pain moelleux] {tail} (21:38)")
        assert parts is not None
        assert parts.qty == attendu

    def test_un_marqueur_illisible_est_signale_pas_devine(self) -> None:
        """Régression : « x » présent mais illisible n'est pas « pas de x ».

        Les deux donnent 1, mais pour des raisons opposées. Le premier est un
        doute qui doit peser moins au vote multi-images, le second est une
        certitude. Les confondre revient à oublier le doute.
        """
        parts = split_line("Système Vous avez obtenu : [Pain moelleux] x?? (21:38)")
        assert parts is not None
        assert parts.qty == 1
        assert parts.quantity_uncertain

        certain = split_line(REELLES["pain"])
        assert certain is not None
        assert certain.qty == 1
        assert not certain.quantity_uncertain


class TestNomEntreCrochets:
    def test_nom_simple(self) -> None:
        parts = split_line(REELLES["humus"])
        assert parts is not None
        assert parts.name == "Humus noir"

    def test_nom_contenant_des_crochets(self) -> None:
        """Régression : s'arrêter au premier « ] » rate l'objet pour toujours.

        Il donnerait « [Serendia » comme nom, qui ne correspond à rien et ne
        correspondra jamais, quel que soit le seuil du score flou.
        """
        parts = split_line(REELLES["imbrique"])
        assert parts is not None
        assert parts.name == "[Serendia] Boîte de tenue de Cleia"
        assert parts.qty == 1

    def test_nom_long_avec_apostrophe(self) -> None:
        parts = split_line(REELLES["boucle"])
        assert parts is not None
        assert parts.name == "Boucle d'oreille de Tuvala"

    def test_un_crochet_fermant_lu_en_l_ne_perd_pas_le_drop(self) -> None:
        """Régression : mesuré sur une vraie capture, drop perdu en silence.

        Le modèle OCR rend régulièrement le « ] » final en « l ». La recherche
        stricte échouait, la ligne était rejetée, et le drop disparaissait sans
        laisser de trace. C'était 2 des 6 gains ratés sur une capture réelle,
        sur deux fonds sur trois.
        """
        parts = split_line("Système Vous avez obtenu : [Boucle d'oreille de Tuvalal. (21:23)")
        assert parts is not None
        assert parts.name == "Boucle d'oreille de Tuvala"
        assert parts.qty == 1

    def test_un_crochet_mal_lu_avec_quantite(self) -> None:
        parts = split_line("Système Vous avez obtenu : [Pierre noirel x3 (21:54)")
        assert parts is not None
        assert parts.name == "Pierre noire"
        assert parts.qty == 3

    def test_le_repli_ne_coupe_pas_un_nom_au_premier_l(self) -> None:
        """Le repli tolérant ne doit pas devenir pire que le mal.

        Sans la condition « suivi de la fin, d'un point ou d'une quantité », le
        premier « l » venu du nom serait pris pour le crochet fermant et
        couperait le nom en plein milieu, transformant une lecture correcte en
        lecture fausse.
        """
        parts = split_line("Système Vous avez obtenu : [Pain moelleux] x2 (21:38)")
        assert parts is not None
        assert parts.name == "Pain moelleux"

    def test_l_icone_entre_le_deux_points_et_le_crochet_est_jetee(self) -> None:
        """L'OCR rend la vignette de l'objet en glyphes parasites.

        Tout ce qui précède le premier crochet est jeté sans examen, ce qui
        règle le problème sans avoir à reconnaître ces glyphes.
        """
        parts = split_line("Système Vous avez obtenu : ⬦◆w [Pain moelleux]. (21:38)")
        assert parts is not None
        assert parts.name == "Pain moelleux"


class TestHeure:
    def test_l_heure_est_retiree_et_conservee(self) -> None:
        parts = split_line(REELLES["pierre_x3"])
        assert parts is not None
        assert parts.stamp == "21:54"

    def test_l_heure_n_est_jamais_prise_pour_une_quantite(self) -> None:
        """Régression : elle contient des chiffres et un deux-points.

        C'est exactement ce qu'un analyseur de quantité laxiste avale. La
        retirer en premier supprime le problème plutôt que de s'en défendre
        partout ensuite.
        """
        parts = split_line(REELLES["anneau"])
        assert parts is not None
        assert parts.qty == 1
        assert "20" not in str(parts.qty)

    def test_ligne_sans_heure(self) -> None:
        parts = split_line("Système Vous avez obtenu : [Pain moelleux].")
        assert parts is not None
        assert parts.stamp == ""


class TestHeurePleineLargeur:
    """⭐ Régression mesurée : 7,6 % des heures étaient perdues pour une parenthèse.

    Sur 13 646 lignes d'une vraie session de Thornwood Forest, rapidocr rend
    régulièrement une parenthèse ouvrante PLEINE LARGEUR : « x2,243（16:40) ».
    L'expression régulière n'acceptait que la parenthèse normale, et ces
    lignes-là ressortaient sans heure. Or ce sont précisément les plus vieilles
    de la fenêtre, donc celles qu'on veut pouvoir refuser.
    """

    @pytest.mark.parametrize(
        "brut",
        [
            "Systeme Vous avez obtenu:[Pieces]x2,243（16:40)",
            "Systeme Vous avez obtenu:[Pieces]x2,243（16:40）",
            "Système Vous avez obtenu : [Pièces] x2,243 (16:40)",
        ],
    )
    def test_l_heure_est_lue_quelle_que_soit_la_parenthese(self, brut: str) -> None:
        parts = split_line(brut)

        assert parts is not None
        assert parts.stamp == "16:40"


class TestJournalPerime:
    """⭐ Ce qui empêche de compter le journal DÉJÀ À L'ÉCRAN au démarrage.

    Le cas réel, mesuré le 05/08/2026 : à l'ouverture d'une session à 17:19, le
    chat affichait 39 minutes de butin antérieur, daté de 16:40 à 17:14. Le
    compteur en a crédité une partie, c'est-à-dire **inventé des drops**, ce que
    le principe du projet refuse avant tout le reste.

    Le jeu horodate chaque ligne : il n'y a aucune incertitude à trancher ici,
    la réponse est écrite dans le journal.
    """

    DEPART = 17 * 60 + 19  # session ouverte à 17:19

    def test_les_minutes_sont_lues(self) -> None:
        assert stamp_minutes("17:19") == 17 * 60 + 19
        assert stamp_minutes("00:00") == 0
        assert stamp_minutes("23:59") == 23 * 60 + 59

    def test_une_heure_illisible_n_est_pas_minuit(self) -> None:
        """Régression : confondre les deux ferait passer tout un journal pour
        périmé, puisque minuit est la plus petite heure possible."""
        assert stamp_minutes("") is None
        assert stamp_minutes("xx:yy") is None
        assert stamp_minutes("25:00") is None
        assert stamp_minutes("17:99") is None

    @pytest.mark.parametrize("heure", ["16:40", "16:41", "17:07", "17:10", "17:13", "17:14"])
    def test_les_heures_reellement_perimees_sont_refusees(self, heure: str) -> None:
        """Les six heures réellement présentes dans le journal périmé de la
        session mesurée, relevées sur la transcription."""
        assert is_stale(heure, self.DEPART) is True

    @pytest.mark.parametrize("heure", ["17:19", "17:20", "17:21"])
    def test_les_heures_du_farm_sont_gardees(self, heure: str) -> None:
        """Les trois heures du vrai farm, dans la même session."""
        assert is_stale(heure, self.DEPART) is False

    def test_la_minute_de_depart_est_gardee(self) -> None:
        """⚠️ Limite assumée : l'heure n'a pas de secondes.

        Une session ouverte à 17:19:35 ne peut pas distinguer une ligne de
        17:19 déjà affichée d'une ligne de 17:19 qui vient de tomber. On garde
        les deux, donc il reste au pire une minute d'historique. Refuser la
        minute entière perdrait de vrais drops à chaque démarrage.
        """
        assert is_stale("17:19", self.DEPART) is False

    def test_une_heure_illisible_est_gardee(self) -> None:
        """Rater vaut mieux qu'inventer, mais pas au point de rater ce dont on
        ne sait rien : le journal périmé ne pose problème qu'au démarrage, une
        heure illisible peut arriver pendant toute la session."""
        assert is_stale("", self.DEPART) is False

    def test_minuit_ne_perime_pas_la_session(self) -> None:
        """⭐ Régression : une session commencée avant minuit.

        Ouverte à 23:58, une ligne de 00:05 est le lendemain, pas dix-huit
        heures plus tôt. Une comparaison naïve la refuserait, et le compteur
        s'arrêterait de compter au passage de minuit.
        """
        avant_minuit = 23 * 60 + 58

        assert is_stale("00:05", avant_minuit) is False
        assert is_stale("23:59", avant_minuit) is False
        assert is_stale("23:57", avant_minuit) is True
        assert is_stale("18:00", avant_minuit) is True


class TestFiltrage:
    @pytest.mark.parametrize("cle", ["chat_brb", "chat_xd", "systeme_non_butin"])
    def test_les_lignes_hors_butin_sont_rejetees(self, cle: str) -> None:
        """Régression : un message de chat ressemble à une ligne de butin.

        Crochets pour le pseudo, deux-points, heure entre parenthèses. Et
        « gz on officer xD » contient même un « x » suivi d'une lettre, piège
        parfait pour un analyseur de quantité laxiste. Seul l'ancrage sur la
        formule d'annonce les distingue.
        """
        assert split_line(REELLES[cle]) is None

    def test_une_ligne_systeme_sans_formule_est_rejetee(self) -> None:
        """Toutes les lignes du canal Système ne sont pas du butin."""
        assert split_line(REELLES["systeme_non_butin"]) is None

    @pytest.mark.parametrize("texte", ["", "   ", "Système", "pas de crochets ici"])
    def test_lignes_vides_ou_absurdes(self, texte: str) -> None:
        assert split_line(texte) is None


class TestToleranceALOcr:
    def test_une_formule_legerement_abimee_passe_encore(self) -> None:
        """L'annonce est lue par-dessus le décor et perd des lettres.

        Exiger une égalité stricte perdrait des drops sur une ligne pourtant
        parfaitement lisible par ailleurs.
        """
        parts = split_line("Système Vous avez obtenv : [Pain moelleux] x2 (21:38)")
        assert parts is not None
        assert parts.name == "Pain moelleux"
        assert parts.qty == 2

    def test_une_formule_trop_abimee_est_rejetee(self) -> None:
        """La tolérance ne doit pas laisser passer n'importe quoi.

        Sinon les messages des joueurs repassent le filtre et deviennent des
        drops inventés, ce qui est l'erreur la plus grave possible.
        """
        assert split_line("Général [Maxyy] : ce boss est [Pain moelleux] (21:38)") is None


class TestFormatConfigurable:
    def test_le_format_est_de_la_donnee_pas_du_code(self) -> None:
        """Un autre client doit s'ajouter sans toucher à la logique.

        Le découpage est identique dans toutes les langues, seule la formule
        d'annonce change.
        """
        allemand = ChatLineFormat(announce_prefixes=("Ihr habt erhalten",))
        parts = split_line("System Ihr habt erhalten : [Pain moelleux] x2 (21:38)", allemand)
        assert parts is not None
        assert parts.qty == 2

    def test_le_format_francais_ne_reconnait_pas_l_allemand(self) -> None:
        assert split_line("System Ihr habt erhalten : [Pain moelleux] x2 (21:38)") is None


class TestReconnaissanceComplete:
    def test_objet_reconnu(self, catalog: ItemCatalog) -> None:
        matcher = ItemMatcher(catalog)
        ligne = "Système Vous avez obtenu : [Pierre noire (arme)] x3 (21:54)"
        parsed = parse_line(ligne, matcher)

        assert parsed is not None
        assert parsed.observed.item is not None
        assert parsed.observed.item.item_id == 16001
        assert parsed.observed.qty == 3
        assert parsed.stamp == "21:54"

    def test_le_silver_ne_passe_pas_par_le_catalogue(self, catalog: ItemCatalog) -> None:
        """« Pièces » est du silver direct, pas un objet à revendre.

        Le chercher au marché central donnerait zéro, ou pire le prix d'un
        objet homonyme.
        """
        parsed = parse_line(REELLES["pieces"], ItemMatcher(catalog))

        assert parsed is not None
        assert parsed.is_silver
        assert parsed.silver == 10_000_000
        assert parsed.observed.item is None

    def test_un_objet_inconnu_est_conserve_pas_jete(self, catalog: ItemCatalog) -> None:
        """Régression : jeter la ligne décalerait tout ce qui suit.

        Elle ne deviendra jamais un drop, mais elle occupe une place à l'écran
        et l'alignement de deux captures repose sur les positions. La jeter
        ferait recompter du butin déjà compté.
        """
        parsed = parse_line(REELLES["humus"], ItemMatcher(catalog))

        assert parsed is not None
        assert parsed.observed.item is None
        assert parsed.observed.raw == REELLES["humus"]

    def test_une_capture_entiere(self, catalog: ItemCatalog) -> None:
        """Les lignes de conversation disparaissent, les gains restent.

        Retirer la conversation ne casse pas l'alignement : la sous-suite des
        lignes de gain reste une file qui défile, ce dont
        `tracking/alignment.py` a besoin.
        """
        capture = [
            REELLES["chat_brb"],
            REELLES["pain"],
            REELLES["chat_xd"],
            REELLES["pierre_x3"],
            REELLES["systeme_non_butin"],
            REELLES["imbrique"],
        ]
        lignes = parse_frame(capture, ItemMatcher(catalog))

        assert len(lignes) == 3
        assert [ligne.observed.qty for ligne in lignes] == [1, 3, 1]


class TestFormatParDefaut:
    def test_les_prefixes_sont_replies_une_seule_fois(self) -> None:
        """Le repliage est fait à la construction, pas à chaque ligne.

        Le format est consulté une vingtaine de fois par image, dix fois par
        seconde. Replier les préfixes à chaque appel serait du travail refait
        des centaines de fois par seconde pour un résultat constant.
        """
        assert DEFAULT_FORMAT.folded_prefixes == ("vous avez obtenu",)
        assert "pieces" in DEFAULT_FORMAT.folded_silver
