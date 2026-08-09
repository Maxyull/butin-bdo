"""Tests de la marque visuelle : icône de l'exécutable et logo des fenêtres.

Le kit complet vit hors du dépôt (`D:\\DEV\\bdo\\logos`), volontairement : ce
sont des sources de plusieurs mégaoctets, régénérables, dont l'application n'a
pas besoin. Seuls les deux fichiers réellement servis entrent ici.
"""

from __future__ import annotations

from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
ICONE = RACINE / "installeur" / "butin.ico"
MARQUE = RACINE / "src" / "butin" / "ui" / "static" / "butin.png"
INDEX = RACINE / "src" / "butin" / "ui" / "static" / "index.html"
PANNEAU = RACINE / "src" / "butin" / "ui" / "static" / "overlay.html"


class TestFichiers:
    def test_l_icone_de_l_executable_existe(self) -> None:
        assert ICONE.is_file()

    def test_la_marque_servie_aux_pages_existe(self) -> None:
        assert MARQUE.is_file()

    def test_la_marque_est_SUIVIE_PAR_GIT(self) -> None:
        """⛔ Régression : `.gitignore` avait un `*.png` global qui l'avalait.

        Le mode de défaillance est le pire qui soit : le fichier existait sur
        ma machine, donc la page l'affichait, le test précédent passait, et le
        navigateur la chargeait en 200. Elle n'était nulle part dans le dépôt.
        Seule l'intégration continue l'a vue, en 404, sur une copie propre.

        `is_file()` ne suffit donc pas ici : il faut demander à git ce qu'il
        emporterait vraiment. Ignoré si git n'est pas là — le test ne doit pas
        échouer sur une machine qui n'a pas l'outil, seulement sur un dépôt où
        le fichier manque.
        """
        import shutil
        import subprocess

        git = shutil.which("git")
        if git is None:
            pytest.skip("git indisponible")
        # Chemin complet : l'analyseur de sécurité refuse un exécutable résolu
        # par le PATH, et il a raison — le PATH décide alors de ce qui tourne.
        resultat = subprocess.run(  # noqa: S603
            [git, "check-ignore", "-q", str(MARQUE)],
            cwd=RACINE,
            capture_output=True,
            check=False,
        )
        # `check-ignore` rend 0 quand le chemin EST ignoré : c'est l'échec.
        assert resultat.returncode != 0, (
            "butin.png est ignoré par git : il marchera en local et nulle part ailleurs"
        )

    def test_l_icone_porte_ses_petites_resolutions(self) -> None:
        """Régression : une icône en 256 seulement devient floue en 16 px.

        16 px est la taille de la barre des tâches et de l'onglet, donc
        exactement là où l'utilisateur la voit le plus souvent. Windows
        redimensionne à la volée quand la résolution manque, et le résultat est
        une bouillie sur un trait fin comme celui de cette marque.
        """
        from PIL import Image

        with Image.open(ICONE) as im:
            tailles = {t[0] for t in im.info.get("sizes", set())}
        for attendue in (16, 32, 48, 256):
            assert attendue in tailles, f"résolution {attendue} px absente de butin.ico"

    def test_les_petites_tailles_restent_LISIBLES(self) -> None:
        """⛔ Régression : porter la bonne résolution ne suffit pas à se voir.

        La marque est un trait fin doré sur fond sombre. Générer le `.ico` en
        donnant à Pillow une seule image de 256 px et une liste de tailles
        réduit naïvement : le trait est moyenné avec le fond, et l'icône
        s'éteint en rapetissant. Mesuré sur la version publiée en 0.5.0, la
        luminance du pixel le plus clair tombait de **196 à 256 px** à
        **104 à 16 px** — à l'écran, une tache sombre dans la barre des tâches
        et dans l'explorateur, c'est-à-dire là où on la regarde le plus.

        Signalé par Maxime sur ses propres captures, pas trouvé en relisant.

        Le correctif épaissit le trait avant de réduire, et remonte le
        contraste sur les petites tailles seulement. Le seuil est posé entre
        les deux populations mesurées : 104 avant, 229 à 242 après.
        """
        import numpy as np
        from PIL import Image

        with Image.open(ICONE) as im:
            for taille in (16, 24, 32):
                im.size = (taille, taille)
                im.load()
                tableau = np.asarray(im.convert("RGBA")).astype(float)
                luminance = tableau[..., :3].mean(axis=2) * (tableau[..., 3] / 255)
                assert luminance.max() >= 180, (
                    f"à {taille} px le trait plafonne à {luminance.max():.0f} sur 255 : "
                    "l'icône s'éteint en rapetissant"
                )


class TestPages:
    def test_les_deux_fenetres_declarent_la_favicon(self) -> None:
        """Le panneau posé sur le jeu a sa propre fenêtre, donc sa propre icône.

        L'oublier laisse l'icône par défaut du moteur web sur l'une des deux, ce
        qui se voit dans la barre des tâches pendant tout le farm.
        """
        for page in (INDEX, PANNEAU):
            texte = page.read_text(encoding="utf-8")
            assert 'rel="icon"' in texte, f"{page.name} n'a pas de favicon"
            assert "/butin.png" in texte, f"{page.name} ne pointe pas sur la marque"

    def test_la_marque_de_l_en_tete_est_decorative(self) -> None:
        """Régression : un `alt` rempli ferait lire « Butin » deux fois.

        Le mot est déjà écrit juste à côté dans le titre. Une image qui répète
        le texte voisin doit avoir un `alt` VIDE pour que les lecteurs d'écran
        la sautent, et non un `alt` descriptif.
        """
        texte = INDEX.read_text(encoding="utf-8")
        assert '<img class="marque" src="/butin.png" alt="">' in texte


class TestBoutonDiscord:
    def test_le_logo_est_la_VRAIE_marque_discord(self) -> None:
        """⛔ Régression : l'ancien « logo » était un smiley dessiné à la main.

        Le tracé posé jusqu'au 06/08/2026 était un cercle, deux points et une
        courbe — autrement dit une frimousse. Ça ne ressemblait à rien de
        reconnaissable, ce qui vide de son sens l'idée même d'utiliser une
        marque : un joueur doit identifier le lien sans lire le mot à côté.

        Le tracé officiel commence par `M20.317 4.3698`.
        """
        texte = INDEX.read_text(encoding="utf-8")
        assert "M20.317 4.3698" in texte, "le logo Discord n'est pas la marque officielle"
        assert "M12 2a10 10 0 100 20" not in texte, "le smiley dessiné est revenu"

    def test_le_bouton_est_plein_et_non_un_contour_discret(self) -> None:
        """Il doit se voir : c'est le seul chemin vers la communauté.

        En contour à 10 % d'opacité, il se confondait avec les sliders posés
        juste à côté. Rempli du bleu de la marque, il est le seul aplat coloré
        de la page, donc repérable sans être criard.
        """
        texte = INDEX.read_text(encoding="utf-8")
        assert "background: #5865f2" in texte

    def test_le_lien_du_salon_est_une_ICONE_seule(self) -> None:
        """Trois décisions successives de Maxime, et la dernière tranche.

        06/08/2026 : « Discord » suffit comme libellé, une invitation en toutes
        lettres sonne comme un encart publicitaire. 09/08/2026 : « met juste
        l'icône de Discord et un lien vers le Discord ». Le mot disparaît donc
        à son tour — c'est la même idée poussée d'un cran, le logo dit déjà où
        ça mène.
        """
        libelle = _contenu_du_lien(INDEX.read_text(encoding="utf-8"), "lien-discord")
        mot = libelle.rpartition("</svg>")[2].strip()

        assert mot == "", f"le lien du salon porte encore du texte : {mot!r}"

    def test_une_icone_seule_garde_un_NOM_pour_qui_ne_la_reconnait_pas(self) -> None:
        """⛔ Un lien sans texte n'a plus de nom.

        Sans `aria-label`, un lecteur d'écran lit l'adresse ou rien ; sans
        `title`, personne ne peut vérifier au survol où mène un pictogramme.
        Une icône « évidente » ne l'est que pour qui la connaît déjà, et c'est
        exactement la personne qui n'avait pas besoin du lien.
        """
        texte = INDEX.read_text(encoding="utf-8")

        for classe in ("lien-discord", "lien-depot"):
            ouvrant = texte.partition(f'class="{classe} icone-seule"')[2].partition(">")[0]
            assert "aria-label=" in ouvrant, f"{classe} n'a pas de nom accessible"
            assert "title=" in ouvrant, f"{classe} n'a pas d'infobulle"

    def test_le_garde_fou_voit_le_cas_qu_il_garde(self) -> None:
        """⛔ Un garde-fou qui ne peut pas échouer ne garde rien.

        Le test du libellé regardait le FICHIER entier, commentaires compris,
        et il a échoué sur le commentaire qui expliquait justement pourquoi le
        libellé ne changeait pas — un garde-fou qui interdit d'écrire sa propre
        raison. Resserré sur le contenu du lien, il fallait vérifier qu'il mord
        encore.
        """
        invitant = '<a class="lien-discord" href="#"><svg></svg>\n  Rejoindre le Discord\n</a>'

        assert _contenu_du_lien(invitant, "lien-discord").rpartition("</svg>")[2].strip() != ""


class TestLienVersLeDepot:
    """⭐ Demandé par Maxime le 09/08/2026, à côté de l'icône Discord.

    Butin est sous licence MIT et son code est public. Le lien n'est pas de la
    coquetterie : c'est ce qui permet à un joueur de vérifier ce qu'un logiciel
    qui lit son écran fait de ce qu'il y lit.
    """

    def test_il_mene_au_depot_de_butin(self) -> None:
        texte = INDEX.read_text(encoding="utf-8")

        assert "https://github.com/Maxyull/butin-bdo" in texte

    def test_il_s_ouvre_dans_le_navigateur_du_systeme_sans_donner_la_main(self) -> None:
        """⛔ `rel="noopener"`, comme les autres liens sortants : sans lui, la
        page ouverte garde une poignée sur celle-ci."""
        ouvrant = INDEX.read_text(encoding="utf-8").partition('class="lien-depot')[2]
        ouvrant = ouvrant.partition(">")[0]

        assert 'target="_blank"' in ouvrant
        assert 'rel="noopener"' in ouvrant

    def test_il_ne_porte_PAS_un_aplat_de_couleur(self) -> None:
        """La page n'a qu'un seul aplat coloré, celui de Discord, et c'est ce
        qui le rend reconnaissable. Deux aplats côte à côte se disputeraient
        l'attention sans que rien ne dise lequel compte."""
        texte = INDEX.read_text(encoding="utf-8")
        regle = texte.partition("  .lien-depot {")[2].partition("}")[0]

        assert "var(--fond-champ)" in regle, "le lien du dépôt doit rester en contour neutre"


def _contenu_du_lien(source: str, classe: str) -> str:
    """Ce qu'il y a entre les balises du lien portant cette classe.

    Découpage littéral, pas d'expression régulière sur du HTML : CodeQL refuse
    la seconde (`py/bad-tag-filter`).
    """
    return source.partition(f'class="{classe}')[2].partition(">")[2].partition("</a>")[0]


class TestServeur:
    def test_le_type_png_est_declare(self) -> None:
        """Régression : sans type déclaré, le PNG se télécharge au lieu de s'afficher.

        Le serveur envoie `X-Content-Type-Options: nosniff`, ce qui est le bon
        réglage : le navigateur ne devine pas. Conséquence directe, un format
        absent de la table part en `application/octet-stream` et n'est jamais
        rendu. Le défaut est visuel et silencieux, aucun test d'API ne le voit.
        """
        source = (RACINE / "src" / "butin" / "ui" / "server.py").read_text(encoding="utf-8")
        assert '".png": "image/png"' in source

    def test_la_marque_a_sa_route(self) -> None:
        source = (RACINE / "src" / "butin" / "ui" / "server.py").read_text(encoding="utf-8")
        assert '"/butin.png"' in source


FUNDING = RACINE / ".github" / "FUNDING.yml"
BANNIERE_DON = RACINE / "ressources" / "bouton-don-butin.png"
LIEN_DON = "https://paypal.me/maxyull"


class TestSoutien:
    """Le canal de don, et les deux endroits qui doivent rester d'accord.

    ⚠️ Rien dans la chaîne de construction ne relie ces trois fichiers. Un
    changement de canal de don qui n'en corrige que deux passerait la CI en
    laissant le troisième pointer vers l'ancien, et personne ne le verrait :
    ni ruff, ni mypy, ni la suite d'intégration ne lisent `.github/`, un README
    ni un PNG. C'est le même angle mort que celui qui a motivé
    `test_workflows.py`.
    """

    def test_le_bouton_sponsor_pointe_vers_le_bon_canal(self) -> None:
        assert FUNDING.is_file(), "sans ce fichier, GitHub n'affiche aucun bouton Sponsor"
        contenu = FUNDING.read_text(encoding="utf-8")
        assert LIEN_DON in contenu, f"FUNDING.yml ne cite pas {LIEN_DON}"

    def test_la_banniere_de_don_existe_et_est_servie_par_le_readme(self) -> None:
        """Une image manquante ne casse rien : GitHub affiche un carré vide à sa
        place, ce qui donne un README abîmé sans la moindre alerte."""
        assert BANNIERE_DON.is_file(), "bannière de don absente du dépôt"

        readme = (RACINE / "README.md").read_text(encoding="utf-8")
        chemin_relatif = "ressources/bouton-don-butin.png"
        assert chemin_relatif in readme, "le README n'affiche pas la bannière"
        assert LIEN_DON in readme, f"le README ne renvoie pas vers {LIEN_DON}"

    def test_la_banniere_a_les_dimensions_du_gabarit(self) -> None:
        """560 x 120 est le gabarit produit par le générateur du kit. Une image
        d'une autre taille signale qu'elle vient d'ailleurs, ou a été retouchée
        à la main, ce qui la ferait diverger des bannières des autres dépôts."""
        Image = pytest.importorskip("PIL.Image")

        with Image.open(BANNIERE_DON) as image:
            assert image.size == (560, 120), f"gabarit inattendu : {image.size}"


class TestEnteteDeMiseAJour:
    """L'en-tête ne montre RIEN quand il n'y a rien à montrer.

    Demandé par Maxime le 07/08/2026, sur une capture où trois éléments
    cohabitaient — un bouton, un lien et une phrase — pour annoncer qu'aucune
    mise à jour n'était disponible. Trois fois trop pour une information nulle.
    """

    def test_le_message_est_efface_quand_il_n_y_a_pas_de_mise_a_jour(self) -> None:
        """⛔ Régression : une phrase qui survit à ce qu'elle décrit ment.

        « Aucune mise à jour disponible » restait affichée indéfiniment : la
        fonction cachait bien les boutons, mais ne vidait jamais le message.
        Vérifié dans un navigateur, pas déduit.
        """
        texte = INDEX.read_text(encoding="utf-8")
        assert 'etat.textContent = "";' in texte

    def test_le_message_a_une_DUREE_DE_VIE(self) -> None:
        """⛔ Le même arbitrage, vu par son autre bout.

        Effacer à chaque rafraîchissement corrigeait le message éternel, mais
        faisait disparaître le message d'ÉCHEC en 400 ms, avant qu'on ait pu le
        lire. Les deux défauts ont été vus dans un navigateur à dix minutes
        d'intervalle. Le rafraîchissement n'efface donc que ce qui a dépassé
        son temps.
        """
        texte = INDEX.read_text(encoding="utf-8")
        assert "majMessageJusqua" in texte
        assert "MAJ_MESSAGE_MS" in texte
        assert "if (Date.now() > majMessageJusqua)" in texte

    def test_la_marque_de_l_entete_est_assez_grande(self) -> None:
        """22 px calés sur la hauteur des majuscules se lisaient mal.

        Le trait de la marque est fin : c'est le même défaut qui la rendait
        illisible en petit dans la barre des tâches. Elle dépasse donc
        volontairement la ligne de base du texte.
        """
        texte = INDEX.read_text(encoding="utf-8")
        assert ".marque { width: 30px; height: 30px;" in texte
