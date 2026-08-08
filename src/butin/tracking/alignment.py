"""Alignement de deux captures successives du journal d'acquisition.

C'est le cœur de l'anti-double-comptage, et la partie la plus difficile d'un
tracker de butin. Elle n'a rien à voir avec la langue : c'est pour elle que
partir du travail de janhnguyen/BDO-Loot-Tracker (MIT) valait mieux que
repartir de zéro.

**L'invariant.** Le journal est une file : les nouvelles lignes arrivent en bas
et tout remonte d'un cran. Donc les lignes communes à deux captures successives
forment un **suffixe** de l'ancienne image et un **préfixe** de la nouvelle.
Les lignes réellement nouvelles sont exactement `current[recouvrement:]`.

    ancienne          nouvelle
    ┌──────────┐
    │ ligne A  │      (a défilé hors écran)
    │ ligne B  │  ─┐  ┌──────────┐
    │ ligne C  │  ─┼─▶│ ligne B  │  ┐
    │ ligne D  │  ─┘  │ ligne C  │  ├─ recouvrement = 3
    └──────────┘      │ ligne D  │  ┘
                      │ ligne E  │  ◀── seule ligne réellement nouvelle
                      └──────────┘

**Pourquoi c'est délicat.** Le recouvrement n'est pas donné, il faut le
deviner. Et il existe un cas où le texte seul ne peut pas trancher : quand
plusieurs lignes identiques se suivent, ce qui arrive en permanence en farm
(dix « Pierre noire (arme) x1 » d'affilée). Plusieurs recouvrements sont alors
textuellement valides, et choisir le mauvais fait recompter des drops.

Trois garde-fous répondent à ce problème :

1. `expected_new`, une prédiction issue du **décalage en pixels** (voir
   `scroll.py`), qui est un signal totalement indépendant du texte. Quand le
   texte hésite, les pixels tranchent.
2. `is_glitch_frame`, qui refuse une image ayant brutalement perdu tout
   recouvrement. Une seule ligne fantôme décale tout et effondre le
   recouvrement à zéro, ce qui ferait recompter la fenêtre entière.
3. `is_implausible_jump`, qui refuse une image annonçant plus de nouvelles
   lignes qu'il n'est physiquement possible entre deux captures espacées d'un
   dixième de seconde.

Les trois sont bornés dans le temps : un vrai changement massif finit toujours
par être accepté, sinon le tracker se figerait sur un désaccord permanent.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from .models import ObservedLine
from .similarity import MatchConfig, line_similarity

# Nombre d'images consécutives sans recouvrement qu'on accepte d'ignorer avant
# de céder. Au-delà, on considère que l'écran a réellement changé.
GLITCH_MAX_SKIPS = 3

# En dessous de cette taille, l'image précédente n'était pas une vraie fenêtre
# de journal, donc perdre le recouvrement n'a rien d'anormal.
GLITCH_MIN_BASELINE = 3

# Plancher du nombre de nouvelles lignes qu'on accepte sans discuter entre deux
# lectures. Au-delà, l'appelant est censé fournir un plafond calculé sur le
# temps réellement écoulé : ce nombre-ci ne vaut que pour deux captures
# rapprochées.
PLAUSIBLE_MAX_NEW = 10

# Débit de lignes au-dessus duquel une estimation de recouvrement est presque
# sûrement fausse, quel que soit l'intervalle.
#
# 20 et non 3, qui est le débit mesuré sur une vraie session : ce plafond n'est
# pas là pour décrire le jeu, il est là pour attraper une estimation aberrante.
# Le calcul de marge de la boucle place la limite de bon fonctionnement à 16
# lignes par seconde ; un garde-fou doit se poser au-dessus de la limite qu'il
# protège, sans quoi il rejette du travail correct.
PLAUSIBLE_LINES_PER_SECOND = 20.0


def plausible_max_new(elapsed_s: float) -> int:
    """Nombre de nouvelles lignes acceptable après `elapsed_s` secondes.

    ⚠️ Exister est le correctif. `PLAUSIBLE_MAX_NEW` était appliqué tel quel,
    avec pour justification écrite que « le journal ne défile pas de dix lignes
    en un dixième de seconde ». C'était vrai de la cadence de **capture**, pas
    de celle de **lecture** : la reconnaissance ne tourne qu'une fois par
    seconde au mieux, et jusqu'à une fois toutes les deux secondes quand rien ne
    déclenche de lecture anticipée. En deux secondes, quatorze lignes nouvelles
    ne sont pas invraisemblables, elles sont ordinaires.

    Mesuré par le banc d'essai le 05/08/2026 : une lecture portant **14 lignes
    réellement nouvelles** était rejetée comme un saut invraisemblable, donc
    quatorze lignes de journal perdues d'un coup.

    Le plancher garantit que le plafond ne devient jamais plus sévère qu'avant
    sur un intervalle court.
    """
    return max(PLAUSIBLE_MAX_NEW, int(elapsed_s * PLAUSIBLE_LINES_PER_SECOND))


@dataclass(slots=True)
class AlignmentResult:
    """Résultat de l'alignement de deux captures."""

    overlap: int
    """Nombre de lignes communes retenues."""

    new_lines: list[ObservedLine]
    """Lignes réellement nouvelles, soit `current[overlap:]`."""

    confidence: float
    """Similarité moyenne des paires du recouvrement retenu, 0 si aucun."""

    zero_overlap: bool
    """Vrai seulement si les deux images sont non vides et ne partagent rien.

    C'est le cas suspect : soit l'écran a vraiment tout changé, soit l'OCR a
    produit une image aberrante. `is_glitch_frame` sert à trancher.
    """

    diagnostics: dict[str, Any] = field(default_factory=dict)
    """Détail du choix, conservé pour comprendre après coup un comptage faux.

    Un tracker qui se trompe sans laisser de trace n'est pas diagnosticable :
    l'utilisateur voit un chiffre, pas le raisonnement qui l'a produit.
    """


def _overlap_score(
    previous: Sequence[ObservedLine],
    current: Sequence[ObservedLine],
    k: int,
    cfg: MatchConfig,
) -> tuple[float, int] | None:
    """(similarité moyenne, paires en désaccord) si `k` tient, sinon None.

    Les paires pour un recouvrement `k` sont `previous[lp - k + j]` contre
    `current[j]`, pour j de 0 à k exclu.

    ⚠️ Un recouvrement est retenu quand une **part** suffisante de ses paires
    s'accordent, pas quand elles s'accordent toutes. La règle du tout ou rien
    laissait une seule ligne mal lue annuler un recouvrement de vingt : plus
    aucun `k` n'était valide, l'appelant concluait que rien ne se recouvrait, et
    `is_glitch_frame` jetait l'image entière. Mesuré par le banc d'essai sur 300
    images de vrai farm, **8 lectures sur 15 partaient ainsi à la poubelle**,
    alors qu'elles portaient chacune une vingtaine de lignes parfaitement
    lisibles.

    La moyenne rendue porte sur **toutes** les paires, y compris celles qui
    n'ont pas franchi le seuil. C'est ce qui fait de la confiance une mesure
    honnête du recouvrement retenu, et non de sa meilleure moitié.

    Le seuil et les deux populations qui le justifient sont documentés sur
    `MatchConfig.overlap_accept`.
    """
    if k == 0:
        # Vide de sens mais toujours valide : aucune paire à contredire.
        return (1.0, 0)
    lp = len(previous)
    total = 0.0
    accords = 0
    for j in range(k):
        similarity = line_similarity(previous[lp - k + j], current[j], cfg)
        total += similarity
        if similarity >= cfg.line_accept:
            accords += 1
    if accords / k < cfg.overlap_accept:
        return None
    return (total / k, k - accords)


def align(
    previous: Sequence[ObservedLine],
    current: Sequence[ObservedLine],
    cfg: MatchConfig | None = None,
    expected_new: int | None = None,
) -> AlignmentResult:
    """Aligne deux captures et renvoie les lignes réellement nouvelles.

    Sans `expected_new`, on retient le **plus grand** recouvrement valide,
    règle classique du suffixe/préfixe : plus le recouvrement est grand, moins
    on déclare de nouvelles lignes, donc moins on risque de recompter.

    Avec `expected_new` (prédiction en pixels), on retient le recouvrement
    valide le plus proche de ce que les pixels annoncent. C'est ce qui départage
    le mur de lignes identiques, où le texte seul ne peut pas choisir.
    """
    cfg = cfg or MatchConfig()
    lp, lc = len(previous), len(current)
    max_k = min(lp, lc)

    scores: dict[int, float] = {}
    mismatches: dict[int, int] = {}
    for k in range(max_k, -1, -1):
        score = _overlap_score(previous, current, k, cfg)
        if score is not None:
            scores[k], mismatches[k] = score

    positive = [k for k in scores if k > 0]
    largest_valid = max(positive) if positive else 0

    diagnostics: dict[str, Any] = {
        "previous_lines": lp,
        "current_lines": lc,
        "valid_overlaps": sorted(scores, reverse=True),
        "largest_valid": largest_valid,
        "expected_new": expected_new,
        "target_overlap": None,
        "disagreement": False,
        "mismatched_pairs": 0,
    }

    if expected_new is None:
        chosen = largest_valid
    else:
        target = max(0, lc - expected_new)
        diagnostics["target_overlap"] = target
        # ⛔ La prédiction choisit PARMI CE QUE LE TEXTE SOUTIENT, et le
        # recouvrement vide n'en fait pas partie tant qu'il existe autre chose.
        #
        # `k = 0` est toujours dans `scores`, avec la note maximale : il n'a
        # aucune paire à contredire. Tant qu'il restait candidat à égalité, une
        # prédiction pointant sur zéro le choisissait **quelle que soit** la
        # force du recouvrement textuel — et « rien en commun » est une
        # affirmation sur le CONTENU, que les pixels n'ont pas qualité à faire.
        # Ils peuvent dire « trois lignes ont défilé » ; ils ne peuvent pas dire
        # que ces deux lignes identiques sont deux lignes différentes.
        #
        # ⭐ Cas réel, session 0018 du 08/08/2026, à 18 secondes de session :
        # l'écran montrait deux lignes déjà vues plus une neuve, donc un
        # recouvrement de 2. La fenêtre de chat se remplissait encore, donc la
        # mesure de défilement n'avait aucun sens, et elle a prédit 3 nouvelles
        # lignes. Cible 0, recouvrements valides [2, 0], zéro choisi. Les deux
        # emplacements posés par l'amorce sont sortis de la liste, trois neufs
        # les ont remplacés, et un « Élixir d'expérience splendide » que le
        # joueur possédait AVANT la session a été crédité **6 261 unités**,
        # soit la moitié du total de la session.
        #
        # L'amorce avait parfaitement fait son travail ; c'est l'alignement qui
        # l'a défaite.
        #
        # ⚠️ Ce que ça coûte, dit franchement : un vrai renouvellement complet
        # de l'écran qui laisserait par hasard un recouvrement faible mais
        # valide sera sous-estimé, donc des drops manqués. C'est le bon sens de
        # l'erreur — un chiffre bas se rattrape, un chiffre inventé ne se voit
        # pas — et `is_glitch_frame` garde toujours le cas du recouvrement
        # réellement nul, que ce choix ne touche pas.
        candidats = positive or list(scores)
        chosen = min(candidats, key=lambda k: (abs(k - target), -k))
        diagnostics["disagreement"] = chosen != largest_valid
        diagnostics["vide_ecarte"] = bool(positive) and target == 0

    confidence = scores[chosen] if chosen > 0 else 0.0
    # Combien de paires du recouvrement retenu ne se ressemblaient pas. Une
    # valeur haute sur un comptage faux dit tout de suite où chercher : la
    # tolérance a laissé passer un recouvrement qu'elle n'aurait pas dû.
    diagnostics["mismatched_pairs"] = mismatches.get(chosen, 0)
    zero_overlap = chosen == 0 and lp > 0 and lc > 0
    if zero_overlap:
        diagnostics["reason"] = (
            f"aucun recouvrement n'a franchi le seuil ({cfg.line_accept}), "
            f"les {lc} lignes sont traitées comme nouvelles"
        )

    return AlignmentResult(
        overlap=chosen,
        new_lines=list(current[chosen:]),
        confidence=confidence,
        zero_overlap=zero_overlap,
        diagnostics=diagnostics,
    )


def is_glitch_frame(
    result: AlignmentResult,
    previous_length: int,
    consecutive_skips: int,
    *,
    max_skips: int = GLITCH_MAX_SKIPS,
    min_baseline: int = GLITCH_MIN_BASELINE,
) -> bool:
    """Vrai si une image bien remplie a brutalement perdu tout recouvrement.

    Une seule ligne fantôme, ou une ligne tellement abîmée qu'elle ne
    ressemble plus à rien, décale toutes les autres d'un cran et fait tomber le
    recouvrement à zéro. L'appelant recompterait alors la fenêtre entière.

    C'est presque toujours un raté passager de l'OCR plutôt qu'un vrai
    changement d'écran, d'où le rejet de l'image. Mais seulement `max_skips`
    fois de suite : au-delà, l'écran a probablement vraiment changé et
    s'entêter figerait le tracker.
    """
    return result.zero_overlap and previous_length >= min_baseline and consecutive_skips < max_skips


def is_implausible_jump(
    result: AlignmentResult,
    consecutive_skips: int,
    expected_new: int | None = None,
    *,
    max_new: int = PLAUSIBLE_MAX_NEW,
    max_skips: int = GLITCH_MAX_SKIPS,
) -> bool:
    """Vrai si une image annonce plus de nouvelles lignes que physiquement possible.

    Un nombre bien supérieur à ce que l'intervalle autorise signifie que le
    recouvrement a été mal estimé, ce qui est précisément la façon dont des
    doublons se glissent dans le total.

    ⚠️ `max_new` doit venir de `plausible_max_new(temps écoulé)`, pas de la
    valeur par défaut. Celle-ci ne vaut que pour deux lectures rapprochées, et
    l'appliquer à un intervalle de deux secondes fait rejeter des lectures
    parfaitement normales.

    Une confirmation par les pixels (`expected_new`) lève le plafond : deux
    signaux indépendants qui disent la même chose valent mieux que notre
    supposition sur ce qui est plausible.
    """
    new_count = len(result.new_lines)
    if new_count <= max_new or consecutive_skips >= max_skips:
        return False
    # La tolérance d'une ligne absorbe le cas où un drop arrive entre la mesure
    # de défilement et la capture du texte, décalage d'une image au plus.
    confirmed_by_pixels = expected_new is not None and new_count <= expected_new + 1
    return not confirmed_by_pixels
