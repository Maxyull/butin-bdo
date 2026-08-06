"""Tests de la marque visuelle : icône de l'exécutable et logo des fenêtres.

Le kit complet vit hors du dépôt (`D:\\DEV\\bdo\\logos`), volontairement : ce
sont des sources de plusieurs mégaoctets, régénérables, dont l'application n'a
pas besoin. Seuls les deux fichiers réellement servis entrent ici.
"""

from __future__ import annotations

from pathlib import Path

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
