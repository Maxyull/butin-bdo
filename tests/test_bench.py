"""Tests du banc d'essai.

Le banc est l'outil qui décidera si on annonce « ce compteur est juste » ou
« juste à X % près ». **Un banc faux vaut moins que pas de banc**, parce qu'on
croirait au chiffre qu'il donne. Ces tests existent donc pour vérifier le
vérificateur.

La méthode est la même partout : un flux de lignes est fabriqué ici, donc sa
vérité est connue **avant** toute mesure, puis déroulé dans une fenêtre comme le
journal du jeu le fait. Les images sont des textures reproductibles, une par
ligne physique, ce qui donne un défilement en pixels réel et vérifiable sans
dépendre de l'OCR.

Les textes de gain reprennent le format relevé sur de vraies captures du client
français, et les noms d'objets sont réels avec leurs vrais identifiants.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest

from butin.bench import (
    BenchFrame,
    BenchReport,
    Transcript,
    assemble,
    build_report,
    canon,
    measure_scroll,
    replay,
    silver_fingerprints,
    tally_lines,
)
from butin.capture.loop import LoopConfig
from butin.capture.screen import GrayImage
from butin.catalog import ItemMatcher

LARGEUR = 90
"""Largeur des images de test, calée sur `LoopConfig.ruler_width` pour que la
colonne servant de règle couvre toute l'image."""

HAUTEUR_LIGNE = 21
"""Pas vertical mesuré en jeu en 2560 x 1440, repris ici pour que le défilement
en pixels se convertisse en lignes avec la même arithmétique qu'en vrai."""


FOND = 20
"""Niveau du décor du jeu vu à travers le fond transparent du chat. La médiane
mesurée sur les vraies captures est de 21 sur 255."""

ENCRE = 230
"""Niveau du texte du journal, peint en clair."""


def _bande(ligne: int, *, encre: int = ENCRE) -> GrayImage:
    """Une rangée du journal : un fond sombre et quelques marques claires.

    ⚠️ La fidélité de cette image compte plus qu'il n'y paraît. Une première
    version tirait chaque pixel au hasard sur toute l'échelle de gris, ce qui
    donnait **55 % de pixels clairs** là où une vraie capture du chat en a
    **8 %**. La mesure de défilement travaille sur un masque de pixels clairs :
    sur une image à moitié allumée, il existe toujours un décalage qui améliore
    un peu le recouvrement par pur hasard, et le test « mesurait » un
    comportement que le code ne rencontre jamais.

    Le motif de colonnes est propre à la ligne, comme l'est un vrai texte : deux
    lignes du journal ne portent jamais les mêmes lettres aux mêmes endroits.
    """
    bande = np.full((HAUTEUR_LIGNE, LARGEUR), FOND, dtype=np.uint8)
    tirage = np.random.default_rng(ligne)
    colonnes = tirage.choice(LARGEUR, size=LARGEUR // 6, replace=False)
    bande[4:15, colonnes] = encre
    return bande


def _image(fenetre: Sequence[int]) -> GrayImage:
    empilees: GrayImage = np.vstack([_bande(ligne) for ligne in fenetre])
    return empilees


def _gain(nom: str, qty: int | None = None, *, heure: str = "01:45") -> str:
    """Une ligne de gain au format du client français.

    `qty=None` rend la forme unitaire, qui ne s'écrit JAMAIS « x1 » mais par
    l'absence de quantité et un point collé au crochet fermant.
    """
    quantite = "." if qty is None else f" x{qty}"
    return f"Système Vous avez obtenu : [{nom}]{quantite} ({heure})"


@dataclass(frozen=True)
class Rafale:
    """Une rafale fabriquée, avec la vérité que personne n'a eu à deviner."""

    frames: tuple[BenchFrame, ...]
    truth: tuple[str, ...]
    """Lignes réellement apparues APRÈS la première image. Celles de la première
    image appartiennent au passé : ni le compteur ni la référence ne les
    comptent."""

    @property
    def images(self) -> tuple[GrayImage, ...]:
        return tuple(frame.image for frame in self.frames)

    @property
    def textes(self) -> tuple[tuple[str, ...], ...]:
        return tuple(frame.lines for frame in self.frames)


def _rafale(flux: Sequence[str], *, fenetre: int, images_par_ligne: int = 1) -> Rafale:
    """Déroule un flux connu dans une fenêtre glissante.

    `images_par_ligne` simule une capture plus rapide que le rythme des drops :
    à 100 ms d'intervalle et un drop par seconde, la même fenêtre est capturée
    dix fois avant de bouger. C'est le régime normal en jeu.
    """
    frames: list[BenchFrame] = []
    index = 0
    for fin in range(fenetre, len(flux) + 1):
        debut = fin - fenetre
        for _ in range(images_par_ligne):
            frames.append(
                BenchFrame(
                    index=index,
                    image=_image(range(debut, fin)),
                    lines=tuple(flux[debut:fin]),
                )
            )
            index += 1
    return Rafale(frames=tuple(frames), truth=tuple(flux[fenetre:]))


def _flux_pierres(nombre: int) -> list[str]:
    """Des pierres noires, avec des quantités qui tournent.

    Les quantités tournent pour qu'aucune ligne ne soit identique à sa voisine,
    ce qui correspond à la mesure faite sur les vraies captures : 0 % de lignes
    voisines strictement identiques sur 274 lignes réelles.
    """
    return [_gain("Pierre noire (arme)", (index % 3) + 1) for index in range(nombre)]


def _flux_observe(paires: int) -> list[str]:
    """Le motif exact relevé sur la rafale du 05/08/2026.

    Une ligne de silver puis une ligne d'objet, en alternance, toutes portant la
    même heure parce qu'un pack entier meurt dans la même minute. Les montants
    de silver sont tous différents, les quantités d'objet non.
    """
    lignes: list[str] = []
    for index in range(paires):
        lignes.append(_gain("Pièces", 1800 + index * 37))
        lignes.append(_gain("Poudre spirituelle du clair de lune", (index % 3) + 1))
    return lignes


TOUT_LIRE = LoopConfig(ocr_min_interval_s=0.0, ocr_max_idle_s=0.0, min_sightings=2)
"""Réglage qui fait lire toutes les images, pour isoler l'anti-double-comptage
de la question de la cadence. Les deux se mesurent séparément."""


# -- reconstruction de la suite ------------------------------------------


def test_assemblage_retrouve_la_suite_connue() -> None:
    """Sur un flux fabriqué, la référence doit rendre exactement ce flux."""
    rafale = _rafale(_flux_pierres(30), fenetre=10)
    assemblage = assemble(rafale.textes)

    assert tuple(ligne.text for ligne in assemblage.stream) == rafale.truth
    assert assemblage.baseline == 10
    assert assemblage.replaced == ()


def test_assemblage_resiste_a_une_lecture_abimee() -> None:
    """Une ligne mal lue sur une image ne doit pas dévier la reconstruction.

    C'est ce que l'égalité stricte gagne à voir les 300 images plutôt qu'une
    sur quatre : la lecture abîmée est minoritaire face à toutes les lectures
    nettes de la même position, et le vote la corrige.
    """
    rafale = _rafale(_flux_pierres(30), fenetre=10)
    textes = [list(image) for image in rafale.textes]
    textes[7][3] = "Systeme Vous avez obtenu : [Pierre n0ire (arme] xB (01:45)"

    assemblage = assemble([tuple(image) for image in textes])

    assert tuple(ligne.text for ligne in assemblage.stream) == rafale.truth
    assert assemblage.replaced == ()


def test_l_egalite_porte_sur_le_texte_sans_espaces() -> None:
    """Régression : l'espacement de l'OCR n'appartient pas à la ligne.

    Mesuré le 05/08/2026 sur les 300 images réelles. Deux lectures d'une même
    ligne physique à 100 ms d'intervalle sont identiques au caractère près dans
    31 % des cas, et dans 70 % une fois les espaces retirés : le moteur rend
    « obtenu : » ou « obtenu: », « Vous avez » ou « Vousavez », selon la façon
    dont il a groupé ses fragments sur cette image-là.

    Avec l'égalité sur le texte brut, le recalage échouait sur **268 images sur
    300** et la référence annonçait 6 081 lignes passées au lieu de 92.
    """
    assert canon("Vous avez obtenu : [Pièces]") == canon("Vousavezobtenu:[Pièces]")

    rafale = _rafale(_flux_pierres(30), fenetre=10)
    textes = [list(image) for image in rafale.textes]
    for image in textes[5:]:
        image[2] = image[2].replace(" : ", ":").replace("Vous avez", "Vousavez")

    assemblage = assemble([tuple(image) for image in textes])

    assert assemblage.replaced == ()
    assert len(assemblage.stream) == len(rafale.truth)


def test_le_bruit_de_glyphe_ne_fait_pas_perdre_le_fil() -> None:
    """Régression : les désaccords ne doivent pas primer sur les accords.

    Le premier recalage notait « accords moins désaccords », ce qui paraissait
    prudent. Mesuré sur la rafale du 05/08/2026, **13 images sur 300** ont un
    contenu strictement inchangé et assez de bruit de glyphe pour que les
    désaccords l'emportent : le bon placement passait sous zéro, le placement
    sans aucun recouvrement gagnait avec zéro, et la référence déclarait une
    fenêtre entière de lignes nouvelles. À elles seules ces 13 images
    ajoutaient 312 lignes fantômes sur 374.

    Ici plus de la moitié des lignes d'une image sont abîmées, et le fil doit
    tenir quand même.
    """
    rafale = _rafale(_flux_pierres(30), fenetre=10)
    textes = [list(image) for image in rafale.textes]
    for position in range(6):
        textes[14][position] = textes[14][position].replace("lune", "lunel") + "~"

    assemblage = assemble([tuple(image) for image in textes])

    assert assemblage.replaced == ()
    assert len(assemblage.stream) == len(rafale.truth)


def test_assemblage_signale_une_image_sans_aucun_recouvrement() -> None:
    """Quand le recalage échoue, la référence sur-compte et le dit.

    C'est le mode de défaillance de ce module, et il est laissé visible plutôt
    que corrigé : ces images sont exactement les cas à regarder à la main,
    comme le demande la conception du banc. Une correction automatique les
    ferait disparaître du rapport sans les rendre justes.
    """
    rafale = _rafale(_flux_pierres(30), fenetre=10)
    textes = [list(image) for image in rafale.textes]
    textes[9] = [_gain("Pierre de Caphras", 9) for _ in range(10)]

    assemblage = assemble([tuple(image) for image in textes])

    # L'image suivante ne se recale pas non plus : la suite reconstruite se
    # termine désormais par le contenu parasite. Le banc signale les deux, ce
    # qui est la bonne trace pour comprendre après coup.
    assert assemblage.replaced[0] == 9
    assert len(assemblage.stream) > len(rafale.truth)


def test_assemblage_ignore_une_image_vide() -> None:
    """Chat replié ou écran de chargement : aucune ligne lue ne dit rien.

    Traiter une image vide comme un journal vidé ferait perdre le recouvrement
    et recompter la fenêtre entière à l'image suivante.
    """
    rafale = _rafale(_flux_pierres(30), fenetre=10)
    textes: list[tuple[str, ...]] = list(rafale.textes)
    textes[12] = ()

    assemblage = assemble(textes)

    assert assemblage.empty == (12,)
    assert tuple(ligne.text for ligne in assemblage.stream) == rafale.truth


def test_assemblage_compte_deux_fois_un_drop_qui_tombe_deux_fois() -> None:
    """Deux drops identiques à quelques secondes sont DEUX lignes, pas une.

    C'est le cœur du piège du 05/08/2026 : la mesure ratée prenait « les
    lignes distinctes vues » pour la vérité terrain, alors que le même objet,
    dans la même quantité et la même minute, s'écrit exactement pareil deux
    fois. La référence doit compter deux lignes physiques là où il n'existe
    qu'un seul texte.
    """
    identique = _gain("Pierre noire (arme)", 1)
    # Le remplissage ne contient volontairement aucune pierre noire : la
    # question posée est le nombre de fois que CE texte revient, et un
    # remplissage qui en produirait aussi rendrait le test illisible.
    remplissage = [_gain("Pierre de Caphras", (index % 4) + 2) for index in range(10)]
    flux = [*remplissage, identique, _gain("Fragment de mémoire", 5), identique]
    rafale = _rafale(flux, fenetre=6)

    assemblage = assemble(rafale.textes)
    apparues = [ligne.text for ligne in assemblage.stream]

    assert apparues.count(identique) == 2
    assert len(apparues) == len(rafale.truth)


# -- défilement mesuré en pixels -----------------------------------------


def test_defilement_pixels_compte_les_lignes_passees() -> None:
    """Le comptage par les pixels doit tomber sur le nombre de lignes passées.

    Aucune lettre n'est lue ici : c'est la propriété qui rend cette mesure
    utilisable pour corroborer la reconstruction par le texte.
    """
    rafale = _rafale(_flux_pierres(30), fenetre=10)

    defilement = measure_scroll(rafale.images, row_height_px=HAUTEUR_LIGNE)

    assert defilement.rows == pytest.approx(len(rafale.truth), abs=0.5)
    assert defilement.unsure == ()
    assert defilement.coverage == pytest.approx(1.0)


def test_defilement_pixels_ecarte_une_mesure_non_sure() -> None:
    """Une image sans rapport n'est pas comptée comme un défilement nul.

    Zéro affirmerait que rien n'a bougé, ce qui est une information, et une
    information fausse. La mesure est écartée et signalée à la place.
    """
    rafale = _rafale(_flux_pierres(30), fenetre=10)
    images = list(rafale.images)
    # Une image qui n'a rien à voir : d'autres marques, aux mêmes proportions
    # qu'une vraie capture. Un aplat de bruit ne testerait rien de réel.
    images[15] = np.vstack([_bande(1000 + index) for index in range(10)])

    defilement = measure_scroll(images, row_height_px=HAUTEUR_LIGNE)

    assert 15 in defilement.unsure
    assert 16 in defilement.unsure
    assert defilement.coverage < 1.0


# -- rejeu de la vraie boucle ---------------------------------------------


def test_le_rejeu_compte_chaque_ligne_une_seule_fois(matcher: ItemMatcher) -> None:
    """La boucle, à cadence suffisante, doit compter la vérité exactement."""
    rafale = _rafale(_flux_pierres(30), fenetre=10)

    resultat = replay(rafale.frames, matcher, config=TOUT_LIRE)

    assert len(resultat.events) == len(rafale.truth)
    assert resultat.lost_resolved == 0
    assert resultat.skipped == ()


def test_le_rejeu_additionne_les_quantites(matcher: ItemMatcher) -> None:
    """Perdre une ligne perd sa quantité : aucun total affiché ne la rattrape.

    Confirmé par Maxime le 05/08/2026. Le banc compare donc les quantités
    cumulées et pas seulement le nombre d'événements, sans quoi rater un « x3 »
    coûterait autant que rater un « x1 » dans la mesure.
    """
    rafale = _rafale(_flux_pierres(30), fenetre=10)
    attendu = sum((index % 3) + 1 for index in range(10, 30))

    resultat = replay(rafale.frames, matcher, config=TOUT_LIRE)

    assert sum(event.qty for event in resultat.events) == attendu


def test_le_rejeu_fait_lire_une_image_sur_quatre_a_la_vraie_cadence(
    matcher: ItemMatcher,
) -> None:
    """Le rejeu doit refléter la cadence réelle, pas une cadence idéale.

    L'OCR coûte 336 ms mesurées et la boucle capture toutes les 100 ms : elle
    ne peut donc lire qu'environ une image sur quatre. Un banc qui les lirait
    toutes flatterait le compteur d'un facteur quatre en information.
    """
    rafale = _rafale(_flux_pierres(40), fenetre=10, images_par_ligne=2)

    resultat = replay(rafale.frames, matcher, config=LoopConfig(), interval_s=0.10)

    lues = len(resultat.read_frames)
    assert lues < len(rafale.frames) / 3
    assert resultat.read_frames[0] == 0


def test_le_rejeu_refuse_une_rafale_vide(matcher: ItemMatcher) -> None:
    with pytest.raises(ValueError, match="rafale vide"):
        replay((), matcher)


# -- le rapport et ce qu'il autorise à dire -------------------------------


def _rapport(rafale: Rafale, matcher: ItemMatcher, config: LoopConfig) -> BenchReport:
    return build_report(
        replay(rafale.frames, matcher, config=config),
        assemble(rafale.textes),
        measure_scroll(rafale.images, row_height_px=HAUTEUR_LIGNE),
        silver_fingerprints(rafale.textes),
        matcher,
        frames=len(rafale.frames),
        interval_s=0.10,
    )


def test_le_rapport_corrobore_le_recalage_par_les_empreintes(matcher: ItemMatcher) -> None:
    """Deux méthodes qui ne partagent presque rien doivent tomber d'accord.

    Le recalage suit chaque ligne de position en position ; les empreintes ne
    font que compter des montants distincts, sans aucune notion de position.
    C'est cet accord, et lui seul, qui rend la référence croyable : sans lui,
    rien ne dirait laquelle des deux se trompe.
    """
    # Trois images par ligne : une empreinte n'est retenue qu'après avoir été
    # vue plusieurs fois, ce qui est le cas normal en jeu où une ligne reste
    # affichée plusieurs secondes. À une image par ligne, les dernières du flux
    # n'auraient pas le temps d'être revues.
    rafale = _rafale(_flux_observe(24), fenetre=12, images_par_ligne=3)

    rapport = _rapport(rafale, matcher, TOUT_LIRE)

    assert rapport.corroboration == pytest.approx(0.0, abs=1e-9)
    assert rapport.event_gap == pytest.approx(0.0, abs=1e-9)
    assert rapport.within_ceiling


def test_les_empreintes_sont_une_borne_basse_jamais_haute() -> None:
    """Une collision de montants fait sous-compter, jamais l'inverse.

    C'est ce qui autorise à s'en servir : un recalage AU-DESSUS des empreintes
    est normal, un recalage en dessous est une contradiction. Ici deux lignes
    de silver portent volontairement le même montant.
    """
    flux = [
        _gain("Pièces", 1800),
        _gain("Pierre noire (arme)", 2),
        _gain("Pièces", 1800),
        _gain("Pierre noire (arme)", 3),
        _gain("Pièces", 1900),
        _gain("Pierre noire (arme)", 1),
    ]
    rafale = _rafale(flux, fenetre=2)

    empreintes = silver_fingerprints(rafale.textes)
    reelles = sum(1 for ligne in rafale.truth if "Pièces" in ligne)

    assert empreintes.distinct < reelles
    assert empreintes.expected_collisions > 0


def test_les_empreintes_ignorent_un_montant_illisible() -> None:
    """Un « x » lu de travers ne doit pas confondre deux lignes en une.

    Le découpage rend alors la quantité 1 avec un doute. Retenir ce 1 comme
    empreinte fondrait toutes les lignes abîmées en une seule, et ferait
    sous-compter sans que rien ne le signale.
    """
    flux = [
        _gain("Pièces", 1800),
        "Système Vous avez obtenu : [Pièces] x?? (01:45)",
        "Système Vous avez obtenu : [Pièces] x?! (01:45)",
        _gain("Pièces", 1900),
    ]
    rafale = _rafale(flux, fenetre=1)

    empreintes = silver_fingerprints(rafale.textes)

    assert empreintes.distinct == 1
    assert empreintes.occurrences == 2


def test_le_rapport_mesure_la_perte_quand_la_cadence_ne_suit_pas(
    matcher: ItemMatcher,
) -> None:
    """Une cadence trop lente perd du butin, et le banc doit le chiffrer.

    Le sens de l'erreur est le bon : le compteur sous-compte au lieu
    d'inventer. Mais une perte non mesurée reste une perte, et c'est
    exactement le nombre que le banc existe pour produire.
    """
    # Une fenêtre courte et un journal rapide : une ligne sort de l'écran avant
    # que la boucle, qui ne lit qu'une image sur quatre, ait pu la voir deux
    # fois. C'est exactement la panne que le banc doit chiffrer.
    rafale = _rafale(_flux_pierres(60), fenetre=4)

    rapport = _rapport(rafale, matcher, LoopConfig())

    assert rapport.replay.lost_resolved > 0
    assert rapport.event_gap is not None
    assert rapport.event_gap < 0
    assert rapport.within_ceiling


def test_les_lignes_distinctes_ne_sont_pas_la_verite_terrain(matcher: ItemMatcher) -> None:
    """Le résultat absurde de 2800 % du 05/08/2026, figé pour ne pas le refaire.

    Un script jetable avait pris « les lignes distinctes vues » comme vérité
    terrain. Sur le motif réellement observé, un drop de silver puis un drop
    d'objet en alternance dans la même minute, l'objet ne prend que trois
    textes différents pour vingt lignes réelles : la référence sous-comptait
    d'un facteur sept pendant que le compteur additionnait.

    Ce test vérifie les deux moitiés du piège. Les textes distincts
    sous-comptent grossièrement, et la reconstruction de `assembly`, elle,
    retrouve le bon nombre.
    """
    rafale = _rafale(_flux_observe(24), fenetre=12)
    lignes_objet = [ligne for ligne in rafale.truth if "Poudre" in ligne]

    distincts = len(set(lignes_objet))
    reference = tally_lines([ligne.text for ligne in assemble(rafale.textes).stream], matcher)

    assert distincts == 3
    assert reference.events == len(lignes_objet)
    assert reference.events > distincts * 5


def test_le_mur_de_lignes_identiques_met_la_reference_en_defaut(
    matcher: ItemMatcher,
) -> None:
    """Limite connue de la référence, écrite pour qu'elle ne surprenne personne.

    Quand le texte est périodique, plusieurs placements sont également
    valides et le recalage retient le plus sobre, donc sous-compte. C'est le
    « mur de lignes identiques » du journal, mesuré absent de la rafale du
    05/08 (0 % de lignes voisines identiques sur 274) mais possible ailleurs.

    Ce que le test fige, c'est que la mesure par les pixels, elle, ne s'y
    trompe pas quand elle fonctionne : sur des lignes réellement distinctes en
    pixels, elle compte le bon nombre là où le texte ne le peut pas.
    """
    identiques = [_gain("Pierre noire (arme)") for _ in range(30)]
    rafale = _rafale(identiques, fenetre=10)

    rapport = _rapport(rafale, matcher, TOUT_LIRE)

    assert rapport.reference_lines < len(rafale.truth)
    assert rapport.pixels_usable
    assert rapport.scroll.rows == pytest.approx(len(rafale.truth), abs=0.5)


def test_le_rapport_declare_la_mesure_en_pixels_inoperante(matcher: ItemMatcher) -> None:
    """Zéro détection n'est pas « zéro ligne défilée », et le rapport le dit.

    C'est exactement ce qui est arrivé sur la rafale réelle : la colonne des
    pastilles est périodique, un défilement d'une ligne y superpose une
    pastille sur sa voisine et n'y change rien. Présenter « 0,0 ligne » comme
    un résultat aurait laissé croire à un journal immobile alors que 92 lignes
    y sont passées.
    """
    rafale = _rafale(_flux_pierres(20), fenetre=8)
    fige = tuple(rafale.frames[0].image for _ in rafale.frames)

    rapport = build_report(
        replay(rafale.frames, matcher, config=TOUT_LIRE),
        assemble(rafale.textes),
        measure_scroll(fige, row_height_px=HAUTEUR_LIGNE),
        silver_fingerprints(rafale.textes),
        matcher,
        frames=len(rafale.frames),
        interval_s=0.10,
    )

    assert not rapport.pixels_usable
    assert "INOPÉRANT" in rapport.render()


def test_le_rapport_se_rend_en_francais(matcher: ItemMatcher) -> None:
    """Le rapport est fait pour être collé dans une PR, donc lisible tel quel."""
    rafale = _rafale(_flux_pierres(30), fenetre=10)

    rendu = _rapport(rafale, matcher, TOUT_LIRE).render()

    assert "La référence est-elle croyable ?" in rendu
    assert "Pierre noire (arme)" in rendu


# -- transcription ---------------------------------------------------------


def test_transcription_aller_retour(tmp_path: Path) -> None:
    """Une transcription relue doit rendre exactement ce qui a été écrit."""
    rafale = _rafale(_flux_pierres(20), fenetre=8)
    origine = Transcript.from_frames(rafale.textes, source="essai", interval_s=0.1)

    chemin = tmp_path / "transcription.jsonl"
    origine.write(chemin)

    assert Transcript.read(chemin) == origine


def test_transcription_refuse_un_trou(tmp_path: Path) -> None:
    """Une image manquante décalerait tout le rejeu d'un cran, en silence.

    La mesure de défilement compare l'image n à l'image n-1 : deux images qui
    ne se suivent pas ne sont pas espacées de 100 ms, et le banc rendrait un
    chiffre plausible et faux plutôt qu'une erreur.
    """
    chemin = tmp_path / "trouee.jsonl"
    chemin.write_text(
        '{"version": 1, "source": "essai", "interval_s": 0.1, "frames": 2}\n'
        '{"index": 0, "lines": ["a"]}\n'
        '{"index": 2, "lines": ["b"]}\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="discontinue"):
        Transcript.read(chemin)


def test_appariement_refuse_un_decalage(tmp_path: Path) -> None:
    """Rejouer 20 textes sur 19 images ne doit pas produire un chiffre."""
    rafale = _rafale(_flux_pierres(20), fenetre=8)
    transcription = Transcript.from_frames(rafale.textes, source="essai", interval_s=0.1)

    with pytest.raises(ValueError, match="appariement impossible"):
        transcription.pair(rafale.images[:-1])
