"""Tests de la ligne de commande de diagnostic.

Elle n'était couverte par **aucun test** jusqu'au 07/08/2026 : 127 instructions
à 0 %, le plus gros trou du dépôt d'après la mesure de couverture. Ce n'est pas
le chemin qu'un joueur emprunte — l'application de bureau l'est — mais c'est
celui qu'on emprunte pour comprendre ce qui ne va pas chez lui, donc le pire
endroit où découvrir une panne.

Rien ici n'ouvre de fenêtre, ne capture d'écran ni ne va sur le réseau : les
quatre commandes sont interceptées et on vérifie ce que la couche
d'aiguillage leur transmet.
"""

from __future__ import annotations

from typing import Any

import pytest

from butin import __main__ as cli
from butin import __version__
from butin.catalog.source import CatalogError


class TestAnalyseDesArguments:
    def test_sans_argument_c_est_l_application_qui_s_ouvre(self, monkeypatch: Any) -> None:
        """Régression : `butin` tout court doit lancer le logiciel.

        La ligne de commande est un outil de diagnostic, mais la commande nue
        reste ce qu'un raccourci du bureau appelle. La faire tomber sur l'aide
        ouvrirait une console noire au lieu de l'application.
        """
        vus: dict[str, Any] = {}
        monkeypatch.setattr("butin.app.run", lambda **kw: vus.update(kw) or 0)
        assert cli.main([]) == 0
        assert vus == {"port": 0}

    def test_la_version_est_celle_du_paquet(self, capsys: Any) -> None:
        """`--version` sort en SystemExit : c'est le comportement d'argparse."""
        with pytest.raises(SystemExit) as sortie:
            cli.main(["--version"])
        assert sortie.value.code == 0
        assert __version__ in capsys.readouterr().out

    def test_une_commande_inconnue_est_refusee(self) -> None:
        with pytest.raises(SystemExit) as sortie:
            cli.main(["nimporte-quoi"])
        assert sortie.value.code == 2

    def test_le_port_de_l_interface_est_transmis(self, monkeypatch: Any) -> None:
        vus: dict[str, Any] = {}
        monkeypatch.setattr("butin.ui.serve", lambda **kw: vus.update(kw))
        assert cli.main(["interface", "--port", "8799"]) == 0
        assert vus == {"port": 8799}

    def test_verbeux_abaisse_le_niveau_de_journalisation(self, monkeypatch: Any) -> None:
        """Sans ça, `--verbeux` ne changerait rien et personne ne le verrait.

        C'est l'option qu'on demande à un joueur d'ajouter quand rien ne
        marche : si elle ne fait rien, on lui fait perdre un aller-retour.
        """
        import logging

        niveaux: list[int] = []
        monkeypatch.setattr(logging, "basicConfig", lambda **kw: niveaux.append(kw.get("level", 0)))
        monkeypatch.setattr("butin.app.run", lambda **kw: 0)
        cli.main(["--verbeux"])
        cli.main([])
        assert niveaux == [logging.DEBUG, logging.WARNING]


class TestAiguillage:
    @pytest.mark.parametrize(
        ("argv", "cible", "attendu"),
        [
            (["catalogue"], "_commande_catalogue", (False,)),
            (["catalogue", "--rafraichir"], "_commande_catalogue", (True,)),
            # 5 s par defaut : le temps de basculer sur le jeu avant la capture.
            (["calibrer"], "_commande_calibrer", (5.0, 1, False)),
            (["calibrer", "--ecran", "2"], "_commande_calibrer", (5.0, 2, False)),
            (["reconnaitre", "Pierre noire"], "_commande_reconnaitre", ("Pierre noire",)),
        ],
    )
    def test_chaque_commande_recoit_ses_arguments(
        self, monkeypatch: Any, argv: list[str], cible: str, attendu: tuple[Any, ...]
    ) -> None:
        """Fige la correspondance entre les options et les paramètres.

        Une inversion entre `--ecran` et `--delai` ne casserait rien de visible
        à la lecture du code : le calibrage attendrait deux secondes sur le bon
        écran, ou zéro seconde sur le mauvais.
        """
        vus: list[tuple[Any, ...]] = []
        monkeypatch.setattr(cli, cible, lambda *a: vus.append(a) or 0)
        assert cli.main(argv) == 0
        assert vus == [attendu]

    def test_le_delai_de_calibrage_est_bien_un_flottant(self, monkeypatch: Any) -> None:
        vus: list[tuple[Any, ...]] = []
        monkeypatch.setattr(cli, "_commande_calibrer", lambda *a: vus.append(a) or 0)
        cli.main(["calibrer", "--delai", "2.5"])
        assert vus[0][0] == pytest.approx(2.5)


class TestErreurs:
    def test_une_panne_de_catalogue_sort_en_2_avec_un_message(
        self, monkeypatch: Any, capsys: Any
    ) -> None:
        """Régression : une trace d'exécution n'aide personne dans une console.

        `CatalogError` couvre le cas courant — pas de réseau, source
        injoignable, fichier illisible. Le joueur doit lire une phrase, pas
        vingt lignes de pile d'appels, et le code de sortie doit dire que ça a
        échoué pour qu'un script s'en aperçoive.
        """

        def casse(*a: Any) -> int:
            raise CatalogError("source injoignable")

        monkeypatch.setattr(cli, "_commande_catalogue", casse)
        assert cli.main(["catalogue"]) == 2
        assert "source injoignable" in capsys.readouterr().err

    def test_l_erreur_part_sur_la_sortie_d_erreur_pas_la_sortie_standard(
        self, monkeypatch: Any, capsys: Any
    ) -> None:
        """Sinon un `butin catalogue > fichier.txt` avalerait le message.

        La sortie standard porte le résultat, la sortie d'erreur porte ce qui
        a mal tourné. Les mélanger rend la commande inutilisable dans un tube.
        """

        def casse(*a: Any) -> int:
            raise CatalogError("pas de réseau")

        monkeypatch.setattr(cli, "_commande_catalogue", casse)
        cli.main(["catalogue"])
        capture = capsys.readouterr()
        assert capture.out == ""
        assert "pas de réseau" in capture.err


class TestReconnaissance:
    def test_un_texte_reconnu_sort_en_0_et_montre_l_identifiant(
        self, monkeypatch: Any, capsys: Any
    ) -> None:
        """L'identifiant numérique est LA chose qu'on vient chercher ici.

        C'est lui qui permet de retrouver l'objet dans le catalogue, dans les
        prix et dans la base de sessions. Un nom seul ne sert à rien pour
        diagnostiquer.
        """

        class FauxObjet:
            item_id = 16001

            def name(self) -> str:
                return "Pierre noire"

        class FauxMatch:
            item = FauxObjet()
            score = 97.5

            class method:
                value = "exact"

        monkeypatch.setattr(cli, "_charger", lambda *a, **k: object())
        monkeypatch.setattr(
            cli,
            "ItemMatcher",
            lambda catalogue: type("M", (), {"resolve": staticmethod(lambda t: FauxMatch())})(),
        )
        assert cli._commande_reconnaitre("Pierre noire") == 0
        sortie = capsys.readouterr().out
        assert "16001" in sortie
        assert "Pierre noire" in sortie

    def test_un_texte_non_reconnu_sort_en_1(self, monkeypatch: Any, capsys: Any) -> None:
        """⛔ Le code de sortie DOIT distinguer « rien trouvé » de « ça marche ».

        C'est le principe de la section 1 du guide, transposé à la ligne de
        commande : ne pas trouver est une réponse, et elle ne doit pas
        ressembler à un succès. Un script qui teste la reconnaissance en série
        n'a que ce code pour trier.
        """
        monkeypatch.setattr(cli, "_charger", lambda *a, **k: object())
        monkeypatch.setattr(
            cli,
            "ItemMatcher",
            lambda catalogue: type("M", (), {"resolve": staticmethod(lambda t: None)})(),
        )
        assert cli._commande_reconnaitre("zzzz") == 1
        assert "aucune correspondance" in capsys.readouterr().out
