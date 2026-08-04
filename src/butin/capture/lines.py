"""Découpage d'une ligne de chat en objet et quantité.

Le seul module de la chaîne qui dépend de la **langue du client** et du format
exact de son journal d'acquisition. Tout le reste est aveugle à ça.

Le format n'est pas deviné : il a été relevé sur de vraies captures du client
français, et chaque piège traité ici a été vu sur une image réelle. Le détail,
avec les captures à l'appui, est dans `docs/journal-acquisition.md`. Le lire
avant de toucher aux expressions régulières ci-dessous.

Rappel du format observé ::

    Système   Vous avez obtenu : ⬦[Humus noir] x3 (20:13)
    Système   Vous avez obtenu : ⬦[Anneau de Tuvala]. (20:20)
    Système   Vous avez obtenu : ⬦[Pièces] x10,000,000 (21:56)
    Général   [Maxyy] : gz on officer xD (21:38)

La stratégie de découpage, dans l'ordre, et pourquoi cet ordre :

1. **Retirer l'heure finale.** Elle contient des chiffres et un deux-points,
   donc elle est exactement ce qu'un analyseur de quantité laxiste avale.
   La retirer d'abord supprime le problème au lieu de s'en défendre partout.
2. **Ancrer sur la formule d'annonce.** C'est le seul filtre fiable : le canal
   `Système` publie aussi des lignes qui ne sont pas du butin, et la
   conversation des joueurs ressemble structurellement à une ligne de butin
   (crochets, deux-points, heure entre parenthèses).
3. **Prendre du premier crochet ouvrant au DERNIER crochet fermant.** Un nom
   d'objet peut contenir des crochets, `[[Serendia] Boîte de tenue de Cleia]`.
   S'arrêter au premier `]` donne « [Serendia » et rate l'objet pour toujours.
4. **Lire la quantité dans ce qui reste.** Absence de quantité et point final
   valent 1, ce qui n'est pas la même chose qu'un `x` illisible.

Tout ce qui se trouve entre le deux-points et le premier crochet est jeté sans
examen : c'est la petite icône de l'objet, que l'OCR rend en glyphes parasites.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from rapidfuzz import fuzz

from ..catalog.matcher import ItemMatcher, Scope
from ..catalog.normalize import fold, fold_digits
from ..tracking.models import ObservedLine

# Heure de fin de ligne. Le « h » est accepté en plus du deux-points parce que
# l'OCR confond régulièrement les deux sur cette police.
_STAMP_RE = re.compile(r"\(\s*(\d{1,2}\s*[:h.]\s*\d{2})\s*\)\s*$")

# Marqueur de quantité. Accepte la croix de multiplication typographique et
# l'astérisque, deux lectures fréquentes du « x » sur fond clair.
#
# Le groupe capture volontairement n'importe quoi, et non une liste de glyphes
# plausibles. Le restreindre ferait échouer la correspondance entière sur une
# quantité illisible comme « x?? », donc retomberait dans la branche « aucun
# marqueur », c'est-à-dire une CERTITUDE de quantité 1 là où il y a justement un
# doute. Le doute serait perdu au lieu d'être transmis au vote multi-images.
_QTY_RE = re.compile(r"^\s*[xX×✕*]\s*(.*)$")

# Glyphes que l'OCR rend à la place du crochet fermant. Relevé sur de vraies
# captures : le `l` minuscule est le cas observé, les autres sont de la même
# famille (un trait vertical). Utilisé UNIQUEMENT en repli, jamais en premier.
_CONFUSABLE_CLOSING = "]lIJ1|)}"

# Ce qui peut suivre un crochet fermant : rien, un point, ou une quantité.
# Cette condition est ce qui empêche le repli tolérant de prendre le premier
# `l` du nom pour le crochet.
_TAIL_RE = re.compile(r"^\s*(\.\s*|[xX×✕*].*)?$")

# Séparateurs de milliers à retirer avant conversion. L'espace insécable est
# inclus : c'est le séparateur typographique français, et il apparaîtra si le
# client est un jour localisé plus finement.
_GROUPING = str.maketrans("", "", ",.  ")


@dataclass(frozen=True, slots=True)
class ChatLineFormat:
    """Ce qui dépend de la langue du client, isolé en données.

    Volontairement des données et non du code : le jour où quelqu'un fournit
    une capture d'un client allemand ou espagnol, il doit pouvoir l'ajouter
    sans toucher à la logique de découpage, qui est la même partout.
    """

    announce_prefixes: tuple[str, ...] = ("Vous avez obtenu",)
    """Formule qui introduit un gain. Comparée de façon tolérante."""

    silver_names: tuple[str, ...] = ("Pièces",)
    """Noms qui désignent du silver et non un objet.

    `[Pièces] x10,000,000` est du silver direct. Le chercher au marché central
    donnerait zéro, ou pire le prix d'un objet homonyme.
    """

    prefix_threshold: float = 80.0
    """Score minimal pour reconnaître la formule d'annonce, sur 100.

    Tolérant par nécessité : la formule est lue par-dessus le décor du jeu et
    perd régulièrement une lettre. Mais pas au point d'accepter n'importe quoi,
    sinon les messages des joueurs repassent le filtre.
    """

    folded_prefixes: tuple[str, ...] = field(init=False)
    folded_silver: frozenset[str] = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "folded_prefixes", tuple(fold(p) for p in self.announce_prefixes))
        object.__setattr__(
            self, "folded_silver", frozenset(fold(name) for name in self.silver_names)
        )


DEFAULT_FORMAT = ChatLineFormat()


@dataclass(frozen=True, slots=True)
class LineParts:
    """Découpage purement textuel d'une ligne, sans consulter le catalogue.

    Séparé de la reconnaissance d'objet pour que le découpage soit testable
    seul. Une erreur de découpage et une erreur de reconnaissance n'ont ni la
    même cause ni la même correction, et les mélanger rend les deux
    indiagnosticables.
    """

    name: str
    qty: int = 1
    quantity_uncertain: bool = False
    stamp: str = ""
    """Heure lue, telle quelle. Jamais convertie en objet date ici : ça
    demanderait une date et poserait la question du fuseau, pour un besoin qui
    n'existe pas encore."""


def split_line(raw: str, fmt: ChatLineFormat = DEFAULT_FORMAT) -> LineParts | None:
    """Découpe une ligne de chat, ou renvoie None si ce n'est pas un gain.

    Renvoyer None est le cas le plus fréquent et parfaitement normal : la
    fenêtre contient surtout de la conversation et des messages système sans
    rapport avec le butin.
    """
    text = raw.strip()
    if not text:
        return None

    stamp = ""
    match_stamp = _STAMP_RE.search(text)
    if match_stamp is not None:
        stamp = match_stamp.group(1).replace(" ", "").replace(".", ":").replace("h", ":")
        text = text[: match_stamp.start()].rstrip()

    open_at = text.find("[")
    if open_at == -1:
        return None

    if not _looks_like_announce(text[:open_at], fmt):
        return None

    close_at = _find_closing_bracket(text, open_at)
    if close_at <= open_at:
        return None

    name = text[open_at + 1 : close_at].strip()
    if not name:
        return None

    qty, uncertain = _read_quantity(text[close_at + 1 :])
    return LineParts(name=name, qty=qty, quantity_uncertain=uncertain, stamp=stamp)


def _find_closing_bracket(text: str, open_at: int) -> int:
    """Trouve le crochet fermant du nom, même mal lu par l'OCR.

    Mesuré sur de vraies captures : le modèle rend régulièrement le `]` final
    en `l`, ce qui donne `[Boucle d'oreille de Tuvalal.`. Une recherche stricte
    échoue, la ligne est rejetée, et **le drop est perdu en silence**. C'était 2
    des 6 gains ratés sur une capture réelle, sur deux fonds sur trois.

    D'abord la recherche stricte, qui couvre la grande majorité des lignes et ne
    peut pas se tromper. Ensuite seulement le repli tolérant, et uniquement sur
    un glyphe **suivi de la fin de ligne, d'un point ou d'une quantité**. Sans
    cette condition de queue, le premier `l` venu du nom serait pris pour le
    crochet et couperait le nom en plein milieu.

    Le repli peut se tromper d'un caractère quand l'OCR a mangé le crochet
    entièrement : `[Cristal.` donnerait « Cristа » au lieu de « Cristal ». C'est
    acceptable, et bien meilleur que la situation actuelle : le score flou
    rattrape une lettre manquante, alors qu'il ne rattrape jamais une ligne
    jamais rendue.
    """
    strict = text.rfind("]")
    if strict > open_at:
        return strict

    for index in range(len(text) - 1, open_at, -1):
        if text[index] in _CONFUSABLE_CLOSING and _TAIL_RE.match(text[index + 1 :]):
            return index
    return -1


def _looks_like_announce(head: str, fmt: ChatLineFormat) -> bool:
    """Vrai si le texte avant le crochet contient la formule d'annonce.

    Comparaison partielle et tolérante : `head` contient aussi la pastille de
    canal et les glyphes parasites de l'icône, donc une égalité stricte ne
    correspondrait jamais. `partial_ratio` cherche la meilleure sous-chaîne, ce
    qui est exactement la question posée.
    """
    folded_head = fold(head)
    if not folded_head:
        return False
    return any(
        fuzz.partial_ratio(prefix, folded_head) >= fmt.prefix_threshold
        for prefix in fmt.folded_prefixes
    )


def _read_quantity(tail: str) -> tuple[int, bool]:
    """Lit la quantité qui suit le nom. Renvoie (quantité, incertaine).

    Trois cas, et le premier est celui qu'on rate quand on ne l'a pas vu en
    vrai : **une quantité de 1 ne s'écrit jamais `x1`**. Elle s'écrit par
    l'absence de marqueur, et la ligne se termine par un point collé au crochet
    fermant.
    """
    match = _QTY_RE.match(tail)
    if match is None:
        # Pas de marqueur : quantité 1, et c'est une certitude, pas un repli.
        return (1, False)

    # Les séparateurs sont retirés APRÈS le repliage des glyphes : « x1 000 »
    # doit valoir 1000, donc l'espace interne est un séparateur de milliers et
    # non une fin de nombre.
    digits = fold_digits(match.group(1).strip()).translate(_GROUPING)
    if not digits.isdigit():
        # Un marqueur était là mais reste illisible. Compter 1 est le choix qui
        # sous-estime plutôt que d'inventer, et le doute est transmis pour que
        # le vote multi-images le pondère au lieu de l'oublier.
        return (1, True)

    value = int(digits)
    if value <= 0:
        return (1, True)
    return (value, False)


@dataclass(frozen=True, slots=True)
class ParsedLine:
    """Une ligne de gain reconnue, prête pour la couche de suivi."""

    observed: ObservedLine
    stamp: str = ""
    silver: int = 0
    """Montant de silver quand la ligne en annonce, sinon 0.

    Le silver ne passe jamais par une recherche de prix : il est déjà exprimé
    dans l'unité finale.
    """

    @property
    def is_silver(self) -> bool:
        return self.silver > 0


def parse_line(
    raw: str,
    matcher: ItemMatcher,
    *,
    fmt: ChatLineFormat = DEFAULT_FORMAT,
    scope: Scope | None = None,
) -> ParsedLine | None:
    """Découpe une ligne puis reconnaît l'objet. None si ce n'est pas un gain.

    Une ligne dont l'objet n'est pas reconnu est quand même renvoyée, avec
    `item` à None. Elle ne deviendra jamais un drop, mais elle occupe une place
    à l'écran et l'alignement de deux captures repose sur les positions : la
    jeter décalerait tout ce qui suit et ferait recompter du butin déjà compté.
    """
    parts = split_line(raw, fmt)
    if parts is None:
        return None

    folded_name = fold(parts.name)

    if folded_name in fmt.folded_silver:
        return ParsedLine(
            observed=ObservedLine(
                raw=raw.strip(),
                item=None,
                qty=parts.qty,
                name_confidence=1.0,
                quantity_uncertain=parts.quantity_uncertain,
            ),
            stamp=parts.stamp,
            silver=parts.qty,
        )

    match = matcher.resolve(parts.name, scope=scope)
    return ParsedLine(
        observed=ObservedLine(
            raw=raw.strip(),
            item=match.item if match is not None else None,
            qty=parts.qty,
            name_confidence=(match.score / 100.0) if match is not None else 0.0,
            quantity_uncertain=parts.quantity_uncertain,
        ),
        stamp=parts.stamp,
    )


def parse_frame(
    lines: list[str],
    matcher: ItemMatcher,
    *,
    fmt: ChatLineFormat = DEFAULT_FORMAT,
    scope: Scope | None = None,
) -> list[ParsedLine]:
    """Découpe une capture entière, dans l'ordre du plus ancien au plus récent.

    Les lignes qui ne sont pas des gains sont retirées ici, et c'est voulu :
    elles n'occupent pas une place dans le journal d'acquisition, elles
    appartiennent à un autre canal. Les lignes de gain dont l'objet reste
    inconnu, elles, sont conservées.
    """
    parsed = [parse_line(raw, matcher, fmt=fmt, scope=scope) for raw in lines]
    return [line for line in parsed if line is not None]
