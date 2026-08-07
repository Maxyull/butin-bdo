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

    def test_le_libelle_n_invite_pas_a_rejoindre(self) -> None:
        """« Discord » suffit, et c'est ce que Maxime a demandé.

        Le logo dit déjà où ça mène ; ajouter « Rejoindre le Discord » répète
        l'icône en mots et donne au bouton un ton d'encart publicitaire.
        """
        texte = INDEX.read_text(encoding="utf-8")
        assert "Rejoindre" not in texte
        assert "rejoindre le Discord" not in texte


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
