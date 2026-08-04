"""Simulation complète du journal, de bout en bout.

Les tests unitaires vérifient chaque pièce isolément. Celui-ci vérifie la seule
chose dont l'utilisateur se soucie : **le total compté est-il exactement le
total tombé ?**

Un tracker de butin ne se juge pas sur la justesse de son alignement ni sur la
qualité de son vote, mais sur ce chiffre unique. Un défaut qui ne se voit pas
dans les tests unitaires (une ligne recomptée une fois sur cinquante) se voit
immédiatement ici, parce qu'on compare une somme à une somme.

Le simulateur reproduit un vrai journal : une fenêtre de taille fixe, des
lignes qui arrivent par le bas, tout qui remonte d'un cran, et une capture bien
plus rapide que le rythme des drops, donc chaque ligne relue de nombreuses fois.
"""

from __future__ import annotations

import random
from collections import Counter

from butin.catalog import ItemCatalog
from butin.tracking import LootStager, align
from butin.tracking.models import ObservedLine

WINDOW = 8
"""Nombre de lignes visibles simultanément dans le journal."""

ITEMS = (16001, 16002, 4998, 4997, 721003, 5956, 44195, 5005)

# Quantités choisies pour former des paires confondables par l'OCR
# (1 contre 7, 6 contre 8), afin que le bruit simulé reproduise le vrai mode
# d'échec plutôt qu'un bruit arbitraire.
QUANTITIES = (1, 6)
_CONFUSIONS = {1: 7, 6: 8}


def make_line(catalog: ItemCatalog, item_id: int, qty: int) -> ObservedLine:
    item = catalog.get(item_id)
    if item is None:  # pragma: pas de couverture
        raise AssertionError(f"objet {item_id} absent du catalogue de test")
    return ObservedLine(raw=f"[{item.name()}] x{qty}", item=item, qty=qty, name_confidence=1.0)


class LogSimulator:
    """Journal d'acquisition : file de taille fixe, les lignes remontent."""

    def __init__(self, window: int = WINDOW) -> None:
        self.window = window
        self.history: list[ObservedLine] = []

    def push(self, line: ObservedLine) -> None:
        self.history.append(line)

    def frame(self) -> list[ObservedLine]:
        """Ce qui est visible à l'écran, du plus ancien au plus récent."""
        return list(self.history[-self.window :])


def corrupt(line: ObservedLine, rng: random.Random, rate: float) -> ObservedLine:
    """Applique un raté d'OCR réaliste à une lecture.

    Deux modes reproduits, ceux qui arrivent vraiment :
    la confusion de chiffres dans la quantité, et la ligne illisible.
    """
    roll = rng.random()
    if roll < rate / 2:
        return ObservedLine(
            raw=line.raw,
            item=line.item,
            qty=_CONFUSIONS.get(line.qty, line.qty),
            name_confidence=line.name_confidence,
        )
    if roll < rate:
        return ObservedLine(raw=line.raw, item=None, qty=line.qty, name_confidence=0.0)
    return line


def run_session(
    catalog: ItemCatalog,
    *,
    steps: int,
    seed: int,
    item_pool: tuple[int, ...] = ITEMS,
    noise: float = 0.0,
    use_pixel_hint: bool = True,
    min_sightings: int = 2,
) -> tuple[Counter[tuple[int, int]], Counter[tuple[int, int]], LootStager]:
    """Joue une session simulée et renvoie (tombé, compté, stager)."""
    rng = random.Random(seed)
    sim = LogSimulator()
    stager = LootStager(min_sightings=min_sightings)

    # Butin déjà à l'écran au lancement du tracker : il appartient au passé et
    # ne doit jamais être compté.
    for _ in range(WINDOW):
        sim.push(make_line(catalog, rng.choice(item_pool), rng.choice(QUANTITIES)))

    baseline = sim.frame()
    stager.seed(baseline)
    previous = baseline

    dropped: Counter[tuple[int, int]] = Counter()
    counted: Counter[tuple[int, int]] = Counter()

    for _ in range(steps):
        # La capture tourne bien plus vite que les drops : la plupart des tours
        # ne voient rien de nouveau, ce qui est exactement la situation où un
        # tracker mal conçu recompte ce qui est déjà à l'écran.
        new_count = rng.choices((0, 0, 0, 1, 2), k=1)[0]
        for _ in range(new_count):
            item_id = rng.choice(item_pool)
            qty = rng.choice(QUANTITIES)
            sim.push(make_line(catalog, item_id, qty))
            dropped[(item_id, qty)] += 1

        current = [corrupt(line, rng, noise) for line in sim.frame()]
        hint = min(new_count, WINDOW) if use_pixel_hint else None

        result = align(previous, current, expected_new=hint)
        for event in stager.observe(result.overlap, current):
            counted[(event.item.item_id, event.qty)] += 1

        previous = current

    for event in stager.flush():
        counted[(event.item.item_id, event.qty)] += 1

    return dropped, counted, stager


class TestComptageExact:
    def test_objets_distincts_sans_indice_pixel(self, catalog: ItemCatalog) -> None:
        """Cas le plus favorable : le texte suffit à aligner.

        Aucune aide des pixels, aucun bruit. Si le total diverge ici, le défaut
        est structurel et non un problème de conditions difficiles.
        """
        dropped, counted, _ = run_session(catalog, steps=300, seed=1, use_pixel_hint=False)
        assert counted == dropped

    def test_avec_indice_pixel(self, catalog: ItemCatalog) -> None:
        dropped, counted, _ = run_session(catalog, steps=300, seed=2)
        assert counted == dropped

    def test_le_butin_deja_present_n_est_jamais_compte(self, catalog: ItemCatalog) -> None:
        """Régression : sans ligne de base, on compterait huit drops du passé."""
        dropped, counted, _ = run_session(catalog, steps=200, seed=3)
        assert sum(counted.values()) == sum(dropped.values())

    def test_session_longue(self, catalog: ItemCatalog) -> None:
        """Une session réelle dure des heures, pas trois cents images.

        Un recomptage rare, invisible sur une session courte, devient évident
        sur la durée : c'est exactement le défaut qu'un utilisateur signalerait
        sans pouvoir le reproduire.
        """
        dropped, counted, _ = run_session(catalog, steps=3000, seed=4)
        assert counted == dropped
        assert sum(dropped.values()) > 500, "la simulation doit générer du volume"


class TestMurDeLignesIdentiques:
    """Le cas qui fait rater un tracker naïf.

    Un seul objet, une seule quantité : toutes les lignes du journal sont
    strictement identiques. Le texte ne peut plus dire de combien la fenêtre a
    défilé, seuls les pixels le peuvent.
    """

    def test_avec_indice_pixel_le_total_reste_exact(self, catalog: ItemCatalog) -> None:
        dropped, counted, _ = run_session(
            catalog, steps=400, seed=5, item_pool=(16001,), use_pixel_hint=True
        )
        assert counted == dropped

    def test_sans_indice_pixel_on_sous_compte_mais_on_ne_sur_compte_jamais(
        self, catalog: ItemCatalog
    ) -> None:
        """Régression : le mode dégradé doit rater, jamais inventer.

        Sans les pixels, l'alignement retient le recouvrement maximal et ne
        voit pas passer les lignes identiques. Le total est donc bas, ce qui
        est le bon sens de l'erreur : un chiffre un peu bas reste exploitable,
        un chiffre gonflé ferait changer de spot pour rien.
        """
        dropped, counted, _ = run_session(
            catalog, steps=400, seed=6, item_pool=(16001,), use_pixel_hint=False
        )
        assert sum(counted.values()) <= sum(dropped.values())


def item_totals(counts: Counter[tuple[int, int]]) -> Counter[int]:
    """Ramène un décompte (objet, quantité) à un décompte par objet."""
    return Counter(key[0] for key in counts.elements())


class TestResistanceAuBruit:
    """Ce que le vote sauve, et ce qu'il ne sauve pas.

    Deux garanties de nature différente, qu'il ne faut pas confondre :

    * **combien de drops** ont eu lieu, préservé même sous fort bruit ;
    * **quelle quantité** portait chacun, dégradé progressivement.

    La première est celle qui compte pour un tracker : une ligne comptée deux
    fois ou jamais comptée fausse la structure du total. Une quantité mal lue
    sur un drop isolé se dilue dans la somme.
    """

    def test_le_vote_absorbe_les_ratés_de_lecture(self, catalog: ItemCatalog) -> None:
        """15% des lectures abîmées, ce qui est déjà pessimiste en pratique.

        Mesuré : 609 drops sur 609 comptés, 99,0% des quantités exactes, aucune
        perte. C'est tout l'intérêt d'attendre plusieurs images : une ligne est
        relue des dizaines de fois, donc la majorité reste saine.
        """
        dropped, counted, stager = run_session(
            catalog, steps=1000, seed=7, noise=0.15, min_sightings=3
        )

        assert item_totals(counted) == item_totals(dropped)
        assert sum(counted.values()) == sum(dropped.values())
        assert stager.lost_resolved == 0

        exact_qty = sum((counted & dropped).values())
        assert exact_qty / sum(dropped.values()) >= 0.98

    def test_bruit_fort(self, catalog: ItemCatalog) -> None:
        """30% de lectures abîmées, au-delà de ce qu'on observe en pratique.

        La garantie se dégrade proprement plutôt que de s'effondrer : le nombre
        de drops reste juste à 99% près, les quantités à 90%. Ce test fige ce
        plancher, pour qu'une modification qui le ferait chuter se voie.
        """
        dropped, counted, _ = run_session(catalog, steps=1000, seed=7, noise=0.30, min_sightings=3)

        assert sum(counted.values()) >= 0.99 * sum(dropped.values())
        assert sum(counted.values()) <= sum(dropped.values())

        exact_qty = sum((counted & dropped).values())
        assert exact_qty / sum(dropped.values()) >= 0.90

    def test_attendre_plus_longtemps_degrade_le_resultat(self, catalog: ItemCatalog) -> None:
        """Régression : le réglage qu'on serait tenté d'augmenter par prudence.

        Exiger plus d'observations avant de valider semble plus sûr. C'est
        faux : la ligne sort de l'écran avant d'atteindre le seuil, et le drop
        est perdu pour de bon. Mesuré sur la même session bruitée, en passant
        de 3 à 7 observations exigées, les pertes passent de 0 à 24 drops.

        Ce test existe pour que quiconque relève ce seuil « pour plus de
        sûreté » voie immédiatement ce que ça coûte.
        """
        _, _, rapide = run_session(catalog, steps=1000, seed=7, noise=0.30, min_sightings=3)
        _, _, lent = run_session(catalog, steps=1000, seed=7, noise=0.30, min_sightings=7)

        assert rapide.lost_resolved == 0
        assert lent.lost_resolved > 20


class TestEcranFige:
    def test_mille_images_sans_nouveau_drop_ne_comptent_rien(self, catalog: ItemCatalog) -> None:
        """Le scénario du joueur qui s'arrête de farmer sans couper le tracker.

        Le journal garde ses dernières lignes affichées. Elles sont relues mille
        fois. Un tracker sans validation par emplacement les compterait mille
        fois.
        """
        rng = random.Random(9)
        sim = LogSimulator()
        stager = LootStager(min_sightings=2)

        for _ in range(WINDOW):
            sim.push(make_line(catalog, rng.choice(ITEMS), 1))

        frame = sim.frame()
        stager.seed(frame)

        total = 0
        for _ in range(1000):
            result = align(frame, frame, expected_new=0)
            total += len(stager.observe(result.overlap, frame))

        assert total == 0
        assert stager.flush() == []


class TestPerteMesuree:
    def test_une_capture_trop_lente_est_signalee_pas_masquee(self, catalog: ItemCatalog) -> None:
        """Quand le tracker rate du butin, il doit le savoir et le dire.

        Ici la fenêtre entière défile entre deux captures, donc des lignes
        sortent avant d'avoir été vues deux fois. Elles sont perdues, ce qui est
        inévitable, mais le compteur doit le refléter : une perte silencieuse
        ferait croire à un total juste.
        """
        stager = LootStager(min_sightings=2)
        base = [make_line(catalog, ITEMS[0], 1) for _ in range(WINDOW)]
        stager.seed(base)

        for index in range(1, 6):
            frame = [make_line(catalog, ITEMS[index % len(ITEMS)], 1) for _ in range(WINDOW)]
            stager.observe(overlap=0, current_lines=frame)

        assert stager.dropped_unconfirmed > 0
        assert stager.lost_resolved > 0
