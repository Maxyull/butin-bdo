"""Comparaison de deux lignes observées.

Sert à répondre à une seule question, posée des centaines de fois par seconde :
« ces deux lignes, lues sur deux images différentes, sont-elles la même ligne
physique du journal ? »

Dérivé de `core/fuzzy.py` de janhnguyen/BDO-Loot-Tracker (MIT), avec une
différence de fond : la comparaison se fait par **identifiant d'objet** et non
par nom. Deux lignes résolues au même objet sont identiques, point final, quel
que soit le texte brut lu de part et d'autre. Comparer des chaînes de nom coûte
plus cher et se trompe davantage, puisque deux lectures abîmées du même objet
donnent deux chaînes différentes alors qu'elles ont déjà été résolues au même
identifiant.

Le score textuel ne sert donc plus que pour les lignes **non résolues**, qu'on
ne peut comparer que par leur texte brut.

Deux modes d'échec de l'OCR sont traités séparément :

* le bruit dans le texte, absorbé par un rapport de similarité ;
* la confusion de chiffres dans les quantités, traitée par une table explicite.
  « 68 » lu au lieu de « 88 » n'est pas un drop différent, c'est la même ligne
  mal lue, et la traiter comme différente casserait l'alignement.
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher

from .models import ObservedLine

# Paires de chiffres que l'OCR intervertit sur la police du journal
# d'acquisition. Stockées en frozenset pour que l'ordre n'ait pas d'importance.
_CONFUSABLE_DIGITS: frozenset[frozenset[str]] = frozenset(
    frozenset(pair) for pair in ("68", "17", "56", "38", "89", "08", "06", "58", "27")
)


@dataclass(frozen=True, slots=True)
class MatchConfig:
    """Réglages de tolérance de la comparaison de lignes."""

    text_threshold: float = 0.82
    """Similarité minimale entre deux textes bruts pour les tenir pour égaux.
    Ne s'applique qu'aux lignes non résolues."""

    digit_confusion: bool = True
    """Traiter deux quantités confondables comme égales."""

    quantite_tronquee: bool = True
    """Traiter « 1 face à n » comme une même ligne dont la quantité a été perdue.

    ⭐ Ce n'est pas une tolérance de plus, c'est une propriété du format. Le jeu
    **n'écrit jamais `x1`** : il écrit 1 par une **absence** de quantité suivie
    d'un point collé au crochet (voir `docs/journal-acquisition.md`). Or une
    absence est exactement ce que produit une lecture tronquée en fin de ligne.

    Relevé le 07/08/2026 dans le journal d'une vraie session, sur un objet qui
    ne tombe qu'en x2, x5, x7 et x10 :

        ...ancestrale] x2 (16:32)     la ligne
        ...ancestrale]. (16:32)       la MÊME, sa quantité rabotée

    La seconde ne ressemblait plus à la première, donc elle était déclarée
    nouvelle, donc créditée : **un drop inventé**. Cinq fois dans une session,
    pour sept unités de trop.

    ⚠️ Le prix, assumé : un vrai drop de 1 qui suit un drop du même objet dans
    la même minute peut être fondu dans le précédent, donc perdu. C'est le sens
    acceptable de l'erreur — rater un drop donne un chiffre un peu bas, en
    inventer un donne un chiffre faux.
    """

    line_accept: float = 0.70
    """Score minimal pour considérer que deux lignes sont la même ligne
    physique du journal."""

    overlap_accept: float = 0.60
    """Part des paires qui doivent s'accorder pour qu'un recouvrement soit
    valide.

    ⚠️ Une **part**, et non la totalité. Exiger que toutes les paires passent
    revient à laisser une seule ligne mal lue annuler un recouvrement de vingt,
    ce qui fait rejeter l'image entière. Mesuré par le banc le 05/08/2026 sur
    300 images de vrai farm : **8 lectures sur 15 étaient jetées** pour cette
    raison.

    La valeur est posée au milieu de deux populations mesurées, pas au jugé.
    Sur ces mêmes images, en comparant chaque lecture au recouvrement que la
    référence sait exact :

    | Recouvrement | Part des paires qui s'accordent |
    | --- | --- |
    | le vrai | **74 % à 100 %** |
    | le meilleur des faux | **50 % au plus** |

    0,60 tombe à 14 points de chacune des deux bornes. Les mauvais scores du
    vrai recouvrement valent tous autour de 0,47, c'est-à-dire exactement le
    plafond appliqué à une ligne dont l'objet n'a pas été reconnu : ce sont des
    ratés de lecture isolés, pas un désaccord de fond.
    """

    name_weight: float = 0.6
    qty_weight: float = 0.4

    different_qty_penalty: float = 0.5
    """Multiplicateur appliqué quand l'objet correspond mais pas la quantité.

    Même objet et quantité franchement différente, c'est probablement un
    SECOND drop du même objet, pas la même ligne qui a défilé. D'où la
    pénalité plutôt qu'un rejet : le doute existe dans les deux sens.
    """


def _ratio(a: str, b: str) -> float:
    if a == b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def digit_confusable(a: int, b: int) -> bool:
    """Vrai si deux quantités ne diffèrent que par des chiffres confondables.

    Exige le même nombre de chiffres et que chaque position divergente forme
    une paire connue. « 168 » et « 188 » oui, « 16 » et « 160 » non : perdre un
    chiffre entier n'est pas une confusion de glyphe, c'est une lecture d'une
    tout autre valeur.
    """
    if a == b:
        return False
    sa, sb = str(a), str(b)
    if len(sa) != len(sb):
        return False
    # strict=True : les deux chaînes ont la même longueur, vérifié juste au-dessus.
    # Le dire explicitement fait échouer bruyamment si cette garantie disparaît,
    # là où zip tronquerait en silence et validerait une comparaison partielle.
    return all(
        frozenset((x, y)) in _CONFUSABLE_DIGITS for x, y in zip(sa, sb, strict=True) if x != y
    )


def quantities_match(a: int, b: int, cfg: MatchConfig | None = None) -> tuple[bool, float]:
    """Compare deux quantités. Renvoie (correspondance, confiance de 0 à 1)."""
    cfg = cfg or MatchConfig()
    if a == b:
        return (True, 1.0)
    if cfg.digit_confusion and digit_confusable(a, b):
        # Confiance volontairement basse : la correspondance est acceptée pour
        # ne pas casser l'alignement, mais elle reste une hypothèse.
        return (True, 0.75)
    if cfg.quantite_tronquee and quantite_perdue(a, b):
        # Encore plus basse que la confusion de chiffres : là on ne compare
        # même pas deux lectures d'un nombre, on suppose qu'un nombre a
        # disparu. Assez pour éviter d'inventer un drop, assez peu pour qu'un
        # meilleur recouvrement l'emporte ailleurs.
        return (True, 0.60)
    return (False, 0.0)


#: Au-delà, « 1 face à n » n'est plus traité comme une troncature.
#:
#: ⛔ Borne tirée des lectures réelles, pas posée au jugé. Les troncatures
#: observées le 07/08/2026 perdent ` x2`, ` x5` ou ` x7`, soit deux ou trois
#: caractères, **tout en gardant l'heure intacte** (`. (16:32)`). Perdre
#: ` x7000` et conserver la parenthèse qui suit n'est pas la même panne : c'est
#: une autre lecture, et la traiter comme une troncature ferait fondre un vrai
#: drop unitaire dans une pile de sept mille.
#:
#: Deux chiffres laissent de la marge au-dessus de ce qui a été vu, sans aller
#: jusqu'aux montants.
QUANTITE_TRONQUABLE_MAX = 99


def quantite_perdue(a: int, b: int) -> bool:
    """Vrai si l'une des deux quantités vaut 1 et l'autre une petite valeur.

    ⭐ 1 est le seul nombre que le jeu n'écrit pas. Il le rend par une absence
    (`[Objet].` et non `[Objet] x1`), donc une lecture qui rabote la fin de la
    ligne produit un « 1 » indiscernable d'un vrai. Voir
    `MatchConfig.quantite_tronquee`.

    ⛔ Le code ne dit pas laquelle des deux lectures est la bonne, seulement que
    l'écart n'est **pas une preuve** de second drop.
    """
    if (a == 1) == (b == 1):
        return False
    return max(a, b) <= QUANTITE_TRONQUABLE_MAX


def items_match(
    a: ObservedLine, b: ObservedLine, cfg: MatchConfig | None = None
) -> tuple[bool, float]:
    """Compare l'objet de deux lignes.

    Chemin rapide par identifiant quand les deux lignes sont résolues, repli
    textuel sinon.
    """
    cfg = cfg or MatchConfig()
    if a.item_id is not None and b.item_id is not None:
        same = a.item_id == b.item_id
        return (same, 1.0 if same else 0.0)

    # Au moins une ligne non résolue : seul le texte brut est comparable.
    ratio = _ratio(a.raw.lower(), b.raw.lower())
    return (ratio >= cfg.text_threshold, ratio)


def line_similarity(a: ObservedLine, b: ObservedLine, cfg: MatchConfig | None = None) -> float:
    """Confiance de 0 à 1 que deux lignes sont la même ligne physique.

    Même objet et même quantité (ou quantité confondable) donne un score haut :
    c'est une ligne qui a défilé d'un cran. Même objet et quantité franchement
    différente donne un score bas : c'est probablement un second drop. Objet
    différent donne un score très bas.
    """
    cfg = cfg or MatchConfig()
    item_ok, item_score = items_match(a, b, cfg)

    if not item_ok:
        # Plafonné bas pour qu'un recouvrement de lignes dissemblables ne
        # puisse jamais franchir le seuil d'acceptation.
        return 0.5 * item_score

    qty_ok, qty_score = quantities_match(a.qty, b.qty, cfg)
    if qty_ok:
        return cfg.name_weight * item_score + cfg.qty_weight * qty_score
    return cfg.different_qty_penalty * item_score
