"""Calcul du silver par heure.

Le chiffre unique sur lequel tout le logiciel est jugé. Trois pièges le rendent
faux si on ne les traite pas, et tous les trois vont dans le sens de la
surestimation, c'est-à-dire le mauvais.

1. La taxe ne s'applique pas à tout
------------------------------------

Vendre à l'hôtel des ventes coûte une taxe. Vendre au marchand n'en coûte
aucune. Appliquer la même taxe aux deux **sous-estime** le trash loot, qui est
justement l'essentiel du revenu d'une session de farm.

Ne l'appliquer nulle part **surestime** tout le reste, ce qui est pire : le
joueur croit gagner ce qu'il ne touchera jamais.

Chaque valeur porte donc sa provenance (`PriceSource`), et la taxe suit la
provenance et non l'objet.

2. Le taux dépend du compte, pas du jeu
----------------------------------------

Le taux net dépend de ce que le joueur possède : abonnement, anneau de marchand
et autres bonus se cumulent. Il n'y a donc **pas** de bon taux par défaut, il y
a le taux de CE joueur.

`MARKET_RATE_BASE` est le taux sans aucun bonus. Il est là pour que le logiciel
donne un chiffre plausible avant réglage, et il doit être remplacé par le taux
réel de l'utilisateur dès que l'interface le permet. Un taux faux applique une
erreur **systématique** au total, pas une erreur aléatoire qui se compenserait.

3. Un objet non valorisé n'est pas un objet qui vaut zéro
----------------------------------------------------------

Un drop dont le prix est inconnu compte pour zéro dans le total, faute de mieux.
Mais il est compté **à part** et affiché comme tel : un total calculé alors que
la moitié des objets sont inconnus n'a pas la même valeur qu'un total complet, et
seul l'utilisateur peut juger si ça lui suffit.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..market import PriceBook, PriceSource

MARKET_RATE_BASE = 0.65
"""Part reçue sans aucun bonus. L'hôtel des ventes prélève 35%.

Ce n'est PAS le taux à utiliser tel quel : voir `TaxProfile`, qui le compose
avec ce que possède le joueur.
"""

# Les bonus ne s'additionnent pas au taux, ils MULTIPLIENT le taux de base.
# C'est ce qui explique le chiffre bien connu de 84,5% avec l'abonnement :
# 0,65 x 1,30 = 0,845, et non 0,65 + 0,30. Additionner donnerait 0,95, soit une
# surestimation de 12% sur chaque vente.
VALUE_PACK_BONUS = 0.30
MERCHANT_RING_BONUS = 0.05

# Paliers de renommée familiale, confirmés par l'INFOBULLE EN JEU, ce qui est
# la source la plus forte possible, au-dessus de tout site tiers :
#
#     1000 : +0,5 % de gains sur les ventes au Marché commun
#     4000 : +1 %
#     7000 : +1,5 %  (et « Chances de butin +10 % », sans effet sur la taxe)
#
# Le palier à 7000 augmente aussi le taux de drop. Ça ne change rien au calcul
# de la taxe, mais ça vaut d'être noté : ça veut dire qu'un joueur très renommé
# ramasse davantage ET perd moins à la vente, donc deux sessions comparées entre
# deux comptes ne sont pas comparables sans ce contexte.
FAME_TIERS: tuple[tuple[int, float], ...] = (
    (7000, 0.015),
    (4000, 0.010),
    (1000, 0.005),
)


@dataclass(frozen=True, slots=True)
class TaxProfile:
    """Ce que possède le joueur, et qui détermine sa part reçue.

    Le taux n'est pas une constante du jeu mais une propriété du **compte**.
    Le demander sous forme de cases à cocher plutôt que d'un pourcentage évite
    à l'utilisateur de calculer lui-même, donc de se tromper : il sait s'il a
    un abonnement, il ne sait pas forcément que ça fait 84,5%.
    """

    value_pack: bool = False
    merchant_ring: bool = False
    family_fame: int = 0

    @property
    def fame_bonus(self) -> float:
        for seuil, bonus in FAME_TIERS:
            if self.family_fame >= seuil:
                return bonus
        return 0.0

    @property
    def net_rate(self) -> float:
        """Part du prix affiché réellement reçue, de 0 à 1."""
        multiplicateur = 1.0 + self.fame_bonus
        if self.value_pack:
            multiplicateur += VALUE_PACK_BONUS
        if self.merchant_ring:
            multiplicateur += MERCHANT_RING_BONUS
        return MARKET_RATE_BASE * multiplicateur


VENDOR_RATE = 1.0
"""Part reçue en vendant au marchand : la totalité, il n'y a pas de taxe."""

SECONDS_PER_HOUR = 3600.0


@dataclass(frozen=True, slots=True)
class Stats:
    """Résultat chiffré d'une session, avec ce qui le rend interprétable."""

    duration_s: float
    gross_market: int = 0
    """Valeur affichée des objets vendables, AVANT taxe."""

    net_market: int = 0
    """Ce qui reste après taxe. C'est ce que le joueur touche vraiment."""

    vendor: int = 0
    """Objets vendus au marchand. Pas de taxe."""

    silver_direct: int = 0
    """Silver ramassé tel quel. Ni prix ni taxe."""

    unknown_items: int = 0
    """Nombre d'objets dont la valeur est inconnue, comptés pour zéro."""

    stale_prices: int = 0
    """Objets valorisés avec un prix périmé. Le total reste utilisable, mais
    ce n'est pas un cours du jour et ça doit se voir."""

    items_counted: int = 0
    per_source: dict[str, int] = field(default_factory=dict)

    @property
    def total(self) -> int:
        """Silver net total de la session."""
        return self.net_market + self.vendor + self.silver_direct

    @property
    def per_hour(self) -> float:
        """Silver net par heure. Zéro tant que la session est trop courte.

        Le garde-fou n'est pas une commodité : sur les premières secondes, la
        division donne des valeurs absurdes de plusieurs milliards par heure,
        qu'un utilisateur pourrait prendre au sérieux le temps qu'elles se
        stabilisent.
        """
        if self.duration_s < 60:
            return 0.0
        return self.total / (self.duration_s / SECONDS_PER_HOUR)

    @property
    def is_complete(self) -> bool:
        """Vrai si tous les objets ont pu être valorisés."""
        return self.unknown_items == 0

    @property
    def coverage(self) -> float:
        """Part des objets valorisés, de 0 à 1."""
        if not self.items_counted:
            return 1.0
        return 1.0 - self.unknown_items / self.items_counted


def compute(
    quantities: dict[tuple[int, int], int],
    book: PriceBook,
    *,
    duration_s: float,
    silver_direct: int = 0,
    market_rate: float = MARKET_RATE_BASE,
    now: float | None = None,
) -> Stats:
    """Calcule les statistiques d'une session.

    `quantities` associe (identifiant, niveau d'amélioration) à une quantité,
    tel que `SessionStore.quantities` le rend.
    """
    brut_marche = 0
    marchand = 0
    inconnus = 0
    perimes = 0
    total_objets = 0
    par_source: dict[str, int] = {}

    for (item_id, sid), qty in quantities.items():
        prix = book.price(item_id, sid=sid, now=now)
        valeur = prix.value * qty
        total_objets += qty
        par_source[prix.source.value] = par_source.get(prix.source.value, 0) + valeur

        if prix.source is PriceSource.UNKNOWN:
            inconnus += qty
            continue
        if prix.source is PriceSource.VENDOR:
            marchand += valeur
            continue

        brut_marche += valeur
        if prix.source is PriceSource.MARKET_STALE:
            perimes += qty

    return Stats(
        duration_s=duration_s,
        gross_market=brut_marche,
        net_market=int(brut_marche * market_rate),
        vendor=int(marchand * VENDOR_RATE),
        silver_direct=silver_direct,
        unknown_items=inconnus,
        stale_prices=perimes,
        items_counted=total_objets,
        per_source=par_source,
    )
