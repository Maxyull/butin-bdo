"""Tests de la détection de la grille d'inventaire.

⛔ Le fil rouge : **le détecteur doit savoir dire NON.** Un banc dont tous les
cas sont positifs répond « trouvé » à tout, exactement comme un détecteur qui
accepte n'importe quoi, et les deux sont indistinguables depuis le code de
sortie. C'est arrivé trois fois sur le verrou de session le 07/08/2026, et le
seul signal a été une série d'acceptations remarquée à l'œil.

La moitié des cas ci-dessous sont donc des refus attendus, et chacun porte le
motif précis qui pourrait tromper la méthode : un dégradé lisse, un aplat, des
rayures qui ne se répètent que dans un sens.

⚠️ Les images sont **synthétiques**, et c'est un choix, pas une facilité. La
seule capture d'inventaire réelle disponible contient le solde en silver et le
nom du personnage de Maxime, et ce dépôt est public. Ce que la synthèse permet
en échange est une vérité terrain **exacte** : on connaît le pas au pixel, ce
qu'aucune capture ne donne.

⭐ La mesure sur les vraies captures existe, elle est dans l'en-tête de
`capture/grid.py` : force 4,00 sur la seule capture avec inventaire, 0,70 au
plus sur les treize sans.
"""

from __future__ import annotations

import numpy as np
import pytest

from butin.capture.grid import MIN_STRENGTH, find_lattice


def grille(
    pas: int = 48,
    rangees: int = 8,
    colonnes: int = 8,
    origine: tuple[int, int] = (300, 200),
    taille: tuple[int, int] = (720, 1280),
    fond: int = 20,
) -> np.ndarray:
    """Une grille de cases sur un fond sombre, comme l'inventaire du jeu.

    Les cases sont des carrés un peu plus clairs que le fond, avec un liseré :
    c'est le dessin réel d'un emplacement vide, et c'est ce qui se répète.
    """
    image = np.full(taille, fond, dtype=np.uint8)
    gauche, haut = origine
    marge = max(2, pas // 12)
    for rangee in range(rangees):
        for colonne in range(colonnes):
            x = gauche + colonne * pas
            y = haut + rangee * pas
            image[y + marge : y + pas - marge, x + marge : x + pas - marge] = fond + 18
            image[y + marge : y + marge + 2, x + marge : x + pas - marge] = fond + 55
            image[y + pas - marge - 2 : y + pas - marge, x + marge : x + pas - marge] = fond + 55
            image[y + marge : y + pas - marge, x + marge : x + marge + 2] = fond + 55
            image[y + marge : y + pas - marge, x + pas - marge - 2 : x + pas - marge] = fond + 55
    return image


def decor(taille: tuple[int, int] = (720, 1280), graine: int = 7) -> np.ndarray:
    """Un fond de jeu plausible : un dégradé, du bruit, quelques formes.

    Le dégradé est là exprès : c'est LE motif qui piège une autocorrélation
    naïve, parce que plus le décalage est petit, plus deux copies se
    ressemblent.
    """
    hauteur, largeur = taille
    hasard = np.random.default_rng(graine)
    yy, xx = np.mgrid[0:hauteur, 0:largeur]
    image = 40 + 120 * (yy / hauteur) + 40 * (xx / largeur)
    image += hasard.normal(0, 6, size=taille)
    image[100:300, 200:600] += 30
    return np.clip(image, 0, 255).astype(np.uint8)


class TestIlTrouveUneGrille:
    def test_une_grille_est_trouvee(self) -> None:
        trouve = find_lattice(grille())

        assert trouve is not None
        assert trouve.strength >= MIN_STRENGTH

    @pytest.mark.parametrize("pas", [32, 40, 48, 60, 72])
    def test_le_pas_est_rendu_juste(self, pas: int) -> None:
        """Le pas décide de tout ce qui vient après : une case lue de travers
        mélangerait deux objets. La tolérance est le pixel de l'image réduite,
        soit deux pixels d'écran."""
        trouve = find_lattice(grille(pas=pas, rangees=7, colonnes=7))

        assert trouve is not None
        assert abs(trouve.pitch_px - pas) <= 2, f"pas rendu {trouve.pitch_px}, attendu {pas}"

    def test_la_bande_certaine_tombe_dans_la_grille(self) -> None:
        """⚠️ Elle dit « ici, à coup sûr », pas « la grille s'arrête là » : la
        carte est lissée sur quatre pas et culmine au milieu du motif. Ce qui
        est exigé, c'est qu'elle ne déborde pas."""
        pas, rangees, colonnes = 48, 8, 8
        trouve = find_lattice(grille(pas=pas, rangees=rangees, colonnes=colonnes))

        assert trouve is not None
        assert trouve.band.left >= 300
        assert trouve.band.top >= 200
        assert trouve.band.left + trouve.band.width <= 300 + colonnes * pas
        assert trouve.band.top + trouve.band.height <= 200 + rangees * pas

    def test_la_grille_se_trouve_ou_qu_elle_soit(self) -> None:
        """⚠️ L'inventaire SE DÉPLACE : le joueur pose sa fenêtre où il veut.
        Une détection qui ne marcherait qu'au milieu de l'écran serait fausse
        dès la session suivante."""
        coins = [(60, 40), (760, 40), (60, 300), (700, 280)]
        forces = []
        for origine in coins:
            trouve = find_lattice(grille(origine=origine, rangees=6, colonnes=6))
            assert trouve is not None, f"grille manquée en {origine}"
            forces.append(trouve.strength)

        assert min(forces) >= MIN_STRENGTH

    def test_une_grille_posee_sur_un_decor_reste_trouvee(self) -> None:
        """Le cas réel : l'inventaire est une fenêtre opaque posée sur le jeu."""
        image = decor()
        motif = grille(rangees=7, colonnes=7)
        zone = motif[200 : 200 + 7 * 48, 300 : 300 + 7 * 48]
        image[200 : 200 + 7 * 48, 300 : 300 + 7 * 48] = zone

        trouve = find_lattice(image)

        assert trouve is not None
        assert abs(trouve.pitch_px - 48) <= 2


class TestIlSaitDireNon:
    """⛔ La moitié qui compte. Un détecteur qui ne refuse jamais ne détecte rien.

    Chaque cas porte un motif qui a une raison précise de tromper : ce ne sont
    pas des images au hasard.
    """

    def test_un_decor_de_jeu_est_refuse(self) -> None:
        """⚠️ Le dégradé est le piège documenté : sur une pente lisse, plus le
        décalage est petit, plus deux copies se ressemblent, donc une
        autocorrélation naïve désigne toujours le plus petit pas. Mesuré sur
        les 12 captures réelles : le critère naïf rendait jusqu'à 0,88 sur des
        écrans sans le moindre inventaire."""
        assert find_lattice(decor()) is None

    def test_un_aplat_uniforme_est_refuse(self) -> None:
        """⚠️ « Ressembler à soi-même » ne suffit pas : un ciel uniforme
        ressemble parfaitement à lui-même décalé de n'importe quoi."""
        assert find_lattice(np.full((720, 1280), 30, dtype=np.uint8)) is None

    def test_du_bruit_est_refuse(self) -> None:
        hasard = np.random.default_rng(3)
        bruit = hasard.integers(0, 255, size=(720, 1280), dtype=np.uint8)

        assert find_lattice(bruit) is None

    def test_des_rayures_dans_UN_SEUL_sens_sont_refusees(self) -> None:
        """⭐ Le cas qui justifie d'additionner les deux directions.

        Une barre de vie, une liste, une bordure d'interface se répètent
        verticalement sans se répéter horizontalement. Si l'on cherchait la
        périodicité d'un seul côté, chacune passerait pour une grille.
        """
        image = np.full((720, 1280), 20, dtype=np.uint8)
        for y in range(200, 600, 48):
            image[y : y + 24, 300:800] = 90

        assert find_lattice(image) is None

    def test_une_image_trop_petite_est_refusee(self) -> None:
        """Sans assez de hauteur pour le plus grand pas cherché, la question
        n'a pas de sens : on refuse plutôt que de rendre un chiffre."""
        assert find_lattice(np.full((60, 60), 30, dtype=np.uint8)) is None


class TestLaLimiteConnue:
    """⛔ Le détecteur RATE un inventaire rempli, et ce test l'écrit noir sur blanc.

    Mesuré le 08/08/2026 sur deux captures réelles : **2,92** à 13 emplacements
    occupés sur 76, **0,24** à 51 sur 192. Le second est sous le pire des faux
    positifs (0,38), donc aucun seuil ne sépare les deux.

    La méthode mesure la ressemblance d'une case à sa voisine. Un inventaire
    presque vide en aligne des dizaines de rigoureusement identiques ; un
    inventaire rempli n'en a aucune. Et c'est le cas rempli qui compte, puisque
    l'inventaire se lit **après** une session de farm.

    ⚠️ Le cas réel ne peut pas entrer ici : la capture porte le solde en silver
    et le nom du personnage, et ce dépôt est public. La grille synthétique
    ci-dessous reproduit le **mécanisme**, pas l'image.
    """

    def test_une_grille_dont_chaque_case_differe_n_est_PAS_trouvee(self) -> None:
        """Le mécanisme de l'échec, reproduit : mêmes cases, contenus tous
        différents. La géométrie est intacte, la ressemblance a disparu."""
        pas, rangees, colonnes = 48, 8, 8
        image = grille(pas=pas, rangees=rangees, colonnes=colonnes)
        hasard = np.random.default_rng(11)
        for rangee in range(rangees):
            for colonne in range(colonnes):
                x = 300 + colonne * pas + 8
                y = 200 + rangee * pas + 8
                icone = hasard.integers(40, 230, size=(pas - 16, pas - 16), dtype=np.uint8)
                image[y : y + pas - 16, x : x + pas - 16] = icone

        assert find_lattice(image) is None, (
            "le détecteur voit maintenant une grille pleine : la limite documentée "
            "en tête de grid.py a changé, il faut y remesurer les deux populations"
        )

    def test_la_grille_vide_reste_trouvee(self) -> None:
        """L'autre moitié du même constat, sans quoi le test ci-dessus passerait
        aussi sur un détecteur simplement cassé."""
        assert find_lattice(grille()) is not None


class TestLeBancPeutEchouer:
    """⛔ Le canari. Sans lui, on ne saurait pas si le banc mesure quoi que ce soit.

    Si ce test passait alors que le détecteur est cassé au point de tout
    refuser, tous les tests de refus ci-dessus passeraient aussi — et le
    fichier entier serait vert sur un détecteur mort.
    """

    def test_la_grille_de_reference_est_bien_detectable(self) -> None:
        trouve = find_lattice(grille())

        assert trouve is not None, (
            "le détecteur ne voit plus sa propre grille de référence : "
            "tous les tests de refus de ce fichier sont donc sans valeur"
        )

    def test_une_image_en_couleur_est_refusee_bruyamment(self) -> None:
        """Une image RVB passée par erreur donnerait des chiffres qui ne
        veulent rien dire. Elle lève au lieu de répondre."""
        with pytest.raises(ValueError, match="niveaux de gris"):
            find_lattice(np.zeros((100, 100, 3), dtype=np.uint8))
