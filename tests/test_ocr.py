"""Tests du prétraitement et de l'enveloppe rapidocr.

**Aucun test ne charge le vrai moteur et aucun ne lit une capture du jeu.**
Deux raisons, et les deux sont des contraintes réelles :

* l'intégration continue tourne sur Linux sans écran et **sans les captures**,
  qui sont hors dépôt parce qu'elles contiennent le chat de guilde ;
* un test qui charge un modèle ONNX de plusieurs dizaines de mégaoctets à
  chaque exécution finit par ne plus être lancé, ce qui coûte plus cher que la
  couverture qu'il apporte.

Le moteur est donc remplacé par un double. Les images sont fabriquées par le
code, comme dans `test_scroll.py`.

Les fragments de texte utilisés comme données de test sont de **vraies sorties**
du moteur sur une vraie capture, avec leur géométrie réelle : pas vertical de
21 px, pastille de canal détectée séparément du message, accents perdus par le
modèle. Les lignes de conversation des joueurs présentes sur la même capture en
sont volontairement absentes : elles contiennent des pseudonymes de tiers et ce
dépôt est public.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from butin.capture.ocr import (
    DEFAULT_SCALE,
    TextBox,
    TextLine,
    TextReader,
    boxes_from_result,
    group_boxes,
    preprocess,
    stretch_contrast,
    upscale,
)

ROW_PITCH = 21
"""Pas vertical mesuré sur la capture réelle, en 2560 x 1440."""

BOX_HEIGHT = 14
"""Hauteur médiane d'un fragment détecté, à l'échelle de l'image d'entrée."""


def quad(left: float, top: float, right: float, bottom: float) -> list[list[float]]:
    """Quadrilatère à quatre sommets, comme rapidocr les rend."""
    return [[left, top], [right, top], [right, bottom], [left, bottom]]


def journal_reel(scale: int = 1) -> list[list[Any]]:
    """Sortie du moteur sur trois lignes de gain d'une vraie capture.

    Géométrie et texte relevés tels quels, accents perdus compris. La pastille
    de canal, la formule et la fin de ligne sortent en fragments séparés, ce qui
    est le cas normal et non une anomalie.
    """
    lignes = [
        ("Systeme", "Vous avez obtenu :", "[Pierre noire]. (21:53)"),
        ("Systeme", "Vous avez obtenu :", "[Pierre noire] x3 (21:54)"),
        ("Systeme", "Vous avez obtenu :", "[Anneau de Tuvala]. (21:54)"),
    ]
    result: list[list[Any]] = []
    for index, (badge, formule, fin) in enumerate(lignes):
        top = (8 + index * ROW_PITCH) * scale
        bottom = top + BOX_HEIGHT * scale
        # La pastille est légèrement plus haute que le texte : 1,6 px d'écart
        # de centre mesuré, très en dessous du pas de 21 px.
        result.append([quad(10 * scale, top - scale, 55 * scale, bottom - scale), badge, 0.98])
        result.append([quad(66 * scale, top, 170 * scale, bottom), formule, 0.97])
        result.append([quad(176 * scale, top, 330 * scale, bottom), fin, 0.93])
    return result


class FauxMoteur:
    """Double de rapidocr. Rend un résultat scénarisé et note ce qu'il reçoit."""

    def __init__(self, result: list[list[Any]] | None = None) -> None:
        self._result = result
        self.images: list[np.ndarray[Any, np.dtype[np.uint8]]] = []

    def __call__(self, image: np.ndarray[Any, np.dtype[np.uint8]]) -> tuple[Any, Any]:
        self.images.append(image)
        return self._result, [0.01, None, 0.02]


class UsineMoteur:
    """Compte les moteurs construits, comme l'usine mss de `test_screen.py`."""

    def __init__(self, result: list[list[Any]] | None = None) -> None:
        self._result = result
        self.moteurs: list[FauxMoteur] = []

    def __call__(self) -> FauxMoteur:
        moteur = FauxMoteur(self._result)
        self.moteurs.append(moteur)
        return moteur


def image_de_journal(rows: int = 5) -> np.ndarray[Any, np.dtype[np.uint8]]:
    """Fabrique une bande imitant un journal : texte clair sur fond varié."""
    height = rows * ROW_PITCH
    frame = np.full((height, 200), 40, dtype=np.uint8)
    for index in range(rows):
        top = index * ROW_PITCH + 4
        frame[top : top + 8, 10:190] = 200
    return frame


class TestAgrandissement:
    def test_agrandit_les_deux_dimensions(self) -> None:
        agrandie = upscale(np.zeros((10, 20), dtype=np.uint8), 3)

        assert agrandie.shape == (30, 60)
        assert agrandie.dtype == np.uint8

    def test_facteur_1_ne_change_rien(self) -> None:
        frame = image_de_journal()

        assert np.array_equal(upscale(frame, 1), frame)

    def test_facteur_absurde_ne_retrecit_jamais(self) -> None:
        """Régression : un facteur 0 ou négatif venu d'un réglage mal relu.

        Réduire l'image serait la pire réaction possible : le texte du journal
        fait déjà une dizaine de pixels de haut, le réduire le rend illisible
        et l'OCR rendrait des lignes vides sans qu'aucune erreur ne le dise.
        """
        frame = image_de_journal()

        assert upscale(frame, 0).shape == frame.shape
        assert upscale(frame, -2).shape == frame.shape

    def test_les_bandes_de_texte_survivent(self) -> None:
        agrandie = upscale(image_de_journal(), 2)

        assert agrandie.max() > 150, "le texte clair doit rester clair"
        assert agrandie.min() < 100, "le fond sombre doit rester sombre"


class TestEtirementDeContraste:
    def test_etale_sur_toute_la_plage(self) -> None:
        frame = np.full((40, 40), 100, dtype=np.uint8)
        frame[10:30, 10:30] = 140

        etiree = stretch_contrast(frame)

        assert etiree.min() == 0
        assert etiree.max() == 255
        assert etiree.dtype == np.uint8

    def test_une_zone_uniforme_reste_intacte(self) -> None:
        """Régression : chat replié, écran de chargement, fondu au noir.

        La zone est alors quasi uniforme. Étirer un bruit d'un niveau de gris le
        transformerait en fausse texture plein contraste, et le détecteur
        inventerait des boîtes de texte là où il n'y a rien. Inventer une ligne
        est exactement l'erreur que ce projet refuse.
        """
        frame = np.full((40, 40), 30, dtype=np.uint8)
        frame[0, 0] = 31

        assert np.array_equal(stretch_contrast(frame), frame)

    def test_un_reflet_isole_ne_neutralise_pas_l_etirement(self) -> None:
        """Régression : pourquoi des centiles et pas le min et le max.

        Une étincelle de sort ou un reflet d'armure suffit à mettre un pixel à
        255 dans la zone. Calé sur le maximum, l'étirement ne ferait alors plus
        rien du tout, précisément sur les images où le décor gêne le plus.
        """
        frame = np.full((40, 40), 60, dtype=np.uint8)
        frame[10:30, 10:30] = 90
        frame[0, 0] = 255

        etiree = stretch_contrast(frame)

        assert int(etiree.max()) - int(etiree.min()) > 200

    def test_reste_dans_les_bornes(self) -> None:
        frame = np.zeros((30, 30), dtype=np.uint8)
        frame[5:25, 5:25] = 255

        etiree = stretch_contrast(frame)

        assert etiree.min() >= 0
        assert etiree.max() <= 255


class TestPretraitement:
    def test_enchaine_agrandissement_et_contraste(self) -> None:
        preparee = preprocess(image_de_journal(), scale=2)

        assert preparee.shape == (5 * ROW_PITCH * 2, 400)
        assert preparee.dtype == np.uint8
        assert preparee.max() == 255

    def test_sans_contraste(self) -> None:
        frame = image_de_journal()

        preparee = preprocess(frame, scale=2, contrast=False)

        assert preparee.max() < 255, "sans étirement, le texte reste à sa valeur"

    def test_refuse_une_image_couleur(self) -> None:
        """La chaîne travaille en niveaux de gris de bout en bout.

        Une image couleur passée ici viendrait d'un contournement de
        `screen.grab`, et le moteur la lirait quand même : l'erreur ne
        sortirait qu'à la mesure de défilement, très loin de sa cause.
        """
        with pytest.raises(ValueError, match="niveaux de gris"):
            preprocess(np.zeros((20, 20, 3), dtype=np.uint8))


class TestConversionDesBoites:
    def test_resultat_vide(self) -> None:
        """Régression : rapidocr rend `None`, pas une liste vide.

        C'est ce que rend une zone sans texte, chat replié ou écran de
        chargement, donc un cas normal et fréquent. Itérer dessus sans le
        prévoir ferait planter la boucle de capture au premier chargement de
        carte.
        """
        assert boxes_from_result(None) == []
        assert boxes_from_result([]) == []

    def test_boite_englobante_d_un_quadrilatere(self) -> None:
        """Le quadrilatère n'est pas garanti rectangle, même sur du texte droit."""
        result = [[[[10.0, 4.0], [90.0, 6.0], [88.0, 20.0], [12.0, 18.0]], "Systeme", 0.95]]

        (box,) = boxes_from_result(result, scale=1)

        assert (box.left, box.top, box.right, box.bottom) == (10, 4, 90, 20)
        assert box.text == "Systeme"
        assert box.confidence == pytest.approx(0.95)

    def test_coordonnees_ramenees_a_l_echelle_d_entree(self) -> None:
        """Régression : le double comptage silencieux.

        Les boîtes sortent de l'image agrandie, `tracking/scroll.py` mesure les
        défilements sur l'image d'origine. Rendre les coordonnées à l'échelle
        agrandie donnerait une hauteur de ligne deux fois trop grande à
        `expected_new_lines`, qui verrait donc moitié moins de nouvelles lignes
        qu'il n'y en a, et le tracker recompterait du butin déjà compté. Aucune
        erreur ne serait levée, seul le total serait faux.
        """
        result = [[quad(20, 40, 100, 68), "Vous avez obtenu :", 0.97]]

        (box,) = boxes_from_result(result, scale=2)

        assert (box.left, box.top, box.right, box.bottom) == (10, 20, 50, 34)
        assert box.height == BOX_HEIGHT

    def test_filtre_par_confiance(self) -> None:
        result = [
            [quad(10, 0, 50, 14), "Systeme", 0.98],
            [quad(66, 0, 170, 14), "?!", 0.20],
        ]

        gardees = boxes_from_result(result, scale=1, min_confidence=0.5)

        assert [b.text for b in gardees] == ["Systeme"]


class TestRegroupementEnRangees:
    def _boites(self, scale: int = 1) -> list[TextBox]:
        return boxes_from_result(journal_reel(scale), scale=scale)

    def test_la_pastille_et_le_message_font_une_seule_rangee(self) -> None:
        """Régression : 35 fragments pour 17 rangées sur la capture réelle.

        Le détecteur sépare la pastille de canal du message qu'elle introduit,
        parce que la pastille a son propre fond sombre. Sans regroupement,
        `lines.parse_frame` reçoit deux fois plus de lignes que le journal n'en
        contient, dont des lignes « Systeme » toutes seules.
        """
        rangees = group_boxes(self._boites())

        assert len(rangees) == 3
        assert all(len(r.boxes) == 3 for r in rangees)

    def test_ordre_de_gauche_a_droite_dans_la_rangee(self) -> None:
        """La pastille précède la formule, qui précède le nom de l'objet.

        `lines.split_line` ancre sur « Vous avez obtenu » puis prend du premier
        crochet ouvrant au dernier fermant. Un ordre inversé mettrait le nom
        avant la formule et la ligne serait rejetée comme n'étant pas un gain.
        """
        rangees = group_boxes(self._boites())

        assert rangees[1].text == "Systeme Vous avez obtenu : [Pierre noire] x3 (21:54)"

    def test_ordre_du_haut_vers_le_bas(self) -> None:
        """Régression : `tracking/alignment.py` suppose le plus ancien d'abord.

        Le chat empile les nouveaux messages en bas, donc l'ordre du haut vers
        le bas est l'ordre chronologique. Inversé, l'alignement cherche le
        recouvrement du mauvais côté et le tracker recompte des lignes déjà
        vues, sans jamais lever d'erreur.
        """
        rangees = group_boxes(self._boites())

        assert [r.top for r in rangees] == sorted(r.top for r in rangees)
        assert "(21:53)" in rangees[0].text
        assert "(21:54)" in rangees[-1].text

    def test_l_ordre_d_arrivee_des_boites_est_sans_effet(self) -> None:
        """Le détecteur ne garantit aucun ordre de sortie."""
        boites = self._boites()
        rangees = group_boxes(list(reversed(boites)))

        assert [r.text for r in rangees] == [r.text for r in group_boxes(boites)]

    def test_aucune_boite(self) -> None:
        assert group_boxes([]) == []

    def test_pas_de_derive_de_proche_en_proche(self) -> None:
        """Régression : le mode de défaillance classique du regroupement.

        Quatre fragments espacés de 10 px avec une tolérance de 12 px : comparés
        au fragment précédent, ils se rejoignent tous dans une seule rangée par
        effet de chaîne. Ancrés sur le premier de leur rangée, ils forment bien
        deux rangées. Sur un journal, la chaîne fusionnerait des lignes de butin
        successives en une seule, donc perdrait des drops.
        """
        boites = [
            TextBox(text=f"l{i}", left=0, top=i * 10, right=50, bottom=i * 10 + 4, confidence=0.9)
            for i in range(4)
        ]

        rangees = group_boxes(boites, tolerance=12.0)

        assert len(rangees) == 2

    def test_la_confiance_est_la_plus_faible_de_la_rangee(self) -> None:
        """Une rangée ne vaut que son fragment le moins bien lu.

        Une moyenne noierait un nom d'objet douteux sous une pastille et une
        formule toujours parfaitement lues, et le vote de `staging.py`
        recevrait un doute affaibli.
        """
        rangees = group_boxes(self._boites())

        assert rangees[0].confidence == pytest.approx(0.93)

    def test_geometrie_de_la_rangee(self) -> None:
        rangee = group_boxes(self._boites())[0]

        assert rangee.top == 7, "le haut est celui du fragment le plus haut"
        assert rangee.bottom == 22
        assert rangee.height == 15

    def test_le_pas_reel_de_21_px_separe_bien_les_rangees(self) -> None:
        """Régression : la tolérance doit rester loin des deux populations.

        Mesuré sur trois captures : au plus 1,6 px d'écart entre fragments d'une
        même rangée, au moins 19,7 px entre deux rangées voisines. La tolérance
        par défaut, la moitié de la hauteur médiane d'un fragment, tombe entre
        les deux avec une marge de 4x d'un côté et de 3x de l'autre. Ce test
        échouera si quelqu'un touche à ce calcul.
        """
        rangees = group_boxes(self._boites(scale=DEFAULT_SCALE))

        assert len(rangees) == 3


class TestLecteur:
    def test_le_moteur_n_est_pas_charge_a_la_construction(self) -> None:
        """Construire un lecteur ne doit pas coûter 300 ms ni 30 Mo.

        La configuration, la CLI et les tests construisent des objets sans
        forcément lire une image.
        """
        usine = UsineMoteur()

        lecteur = TextReader(engine_factory=usine)

        assert usine.moteurs == []
        assert not lecteur.loaded

    def test_le_moteur_est_charge_une_seule_fois(self) -> None:
        """Régression : le modèle rechargé à chaque image.

        Mesuré : 160 à 320 ms par chargement, contre 330 ms pour lire une image
        entière. Recharger à chaque tour doublerait le coût de la boucle pour un
        résultat identique. Même faute que l'instance mss de `screen.py`.
        """
        usine = UsineMoteur(journal_reel(DEFAULT_SCALE))
        lecteur = TextReader(engine_factory=usine)
        frame = image_de_journal()

        for _ in range(10):
            lecteur.read(frame)

        assert len(usine.moteurs) == 1
        assert len(usine.moteurs[0].images) == 10

    def test_warmup_charge_le_moteur(self) -> None:
        usine = UsineMoteur()
        lecteur = TextReader(engine_factory=usine)

        lecteur.warmup()

        assert lecteur.loaded
        assert len(usine.moteurs[0].images) == 1

    def test_l_image_envoyee_au_moteur_est_agrandie(self) -> None:
        usine = UsineMoteur()
        lecteur = TextReader(engine_factory=usine, scale=2)
        frame = image_de_journal(rows=3)

        lecteur.read(frame)

        envoyee = usine.moteurs[0].images[0]
        assert envoyee.shape == (frame.shape[0] * 2, frame.shape[1] * 2)
        assert envoyee.ndim == 2, "le moteur accepte le 2D, pas la peine d'empiler"

    def test_lecture_complete_a_l_echelle_d_entree(self) -> None:
        """Régression de bout en bout : agrandir puis rendre du natif.

        Le lecteur agrandit l'image avant de la donner au moteur, donc les
        boîtes reviennent agrandies. Les rendre telles quelles ferait mentir
        toutes les mesures de géométrie de la couche de suivi.
        """
        usine = UsineMoteur(journal_reel(DEFAULT_SCALE))
        lecteur = TextReader(engine_factory=usine, scale=DEFAULT_SCALE)

        rangees = lecteur.read(image_de_journal())

        assert len(rangees) == 3
        assert rangees[0].top == 7
        assert rangees[1].center_y - rangees[0].center_y == pytest.approx(ROW_PITCH)

    def test_read_text_rend_des_chaines(self) -> None:
        usine = UsineMoteur(journal_reel(DEFAULT_SCALE))
        lecteur = TextReader(engine_factory=usine)

        textes = lecteur.read_text(image_de_journal())

        assert textes == [
            "Systeme Vous avez obtenu : [Pierre noire]. (21:53)",
            "Systeme Vous avez obtenu : [Pierre noire] x3 (21:54)",
            "Systeme Vous avez obtenu : [Anneau de Tuvala]. (21:54)",
        ]

    def test_zone_sans_texte(self) -> None:
        usine = UsineMoteur(None)
        lecteur = TextReader(engine_factory=usine)

        assert lecteur.read(image_de_journal()) == []

    def test_facteur_d_echelle_minimal(self) -> None:
        """Un facteur nul ou négatif est ramené à 1, jamais appliqué tel quel."""
        lecteur = TextReader(engine_factory=UsineMoteur(), scale=0)

        assert lecteur.scale == 1


class TestModeleDeRangee:
    def test_hauteur_et_centre(self) -> None:
        ligne = TextLine(text="x", top=10, bottom=24, confidence=0.9, boxes=())

        assert ligne.height == 14
        assert ligne.center_y == pytest.approx(17.0)
