"""Normalisation de texte OCR pour la reconnaissance d'objets en français.

C'est le module le plus spécifique au français de tout le projet, et la raison
principale pour laquelle un tracker de loot conçu pour le client anglais ne
fonctionne pas tel quel sur le client français.

Trois problèmes que l'anglais n'a pas :

1. Les accents. « Épée longue de Kzarka » sort de l'OCR tantôt avec, tantôt
   sans accent, et parfois avec le mauvais (É / È / Ê). Comparer des chaînes
   accentuées telles quelles fait rater des correspondances évidentes.
2. Les ligatures. Plusieurs objets FR contiennent « œ » (Cœur, Nœud). Le client
   les affiche en ligature, l'OCR les rend tantôt « œ », tantôt « ce », tantôt
   « oe ». Sans dépliage, ces objets sont structurellement inatteignables.
3. Les apostrophes et traits d'union. Le français en met partout (« Poudre
   d'âme », « Cristal noir tranchant »), et l'OCR alterne entre U+0027, U+2019,
   U+2018 et l'accent grave. Trois variantes d'apostrophe, trois chaînes
   différentes, aucune ne correspond au catalogue.

La stratégie est de replier les deux côtés de la comparaison (le nom du
catalogue et la ligne OCR) vers une forme canonique volontairement pauvre :
minuscules, sans accent, sans ponctuation décorative, espaces compactées. On
perd de l'information, mais on la perd des DEUX côtés, donc la comparaison
reste juste. Ce qui reste de bruit est absorbé par le score flou (matcher.py).

Les chiffres suivent un chemin SÉPARÉ (`fold_digits`) : sur un nom il faut
garder les lettres, sur une quantité il faut au contraire forcer les glyphes
ambigus vers des chiffres. Mélanger les deux ferait de « x1O » un nom d'objet.
"""

from __future__ import annotations

import re
import unicodedata

# Ligatures et caractères composés que la décomposition NFKD ne déplie pas
# toute seule. Appliqué AVANT la décomposition : « œ » n'a pas de forme
# décomposée canonique, c'est une lettre à part entière en Unicode.
_LIGATURES = {
    "œ": "oe",
    "Œ": "OE",
    "æ": "ae",
    "Æ": "AE",
    "ß": "ss",  # eszett, présent dans quelques noms importés
}

# Toutes les variantes d'apostrophe que l'OCR produit pour le même glyphe à
# l'écran. Repliées vers rien du tout : « d'âme » et « dame » se comparent
# alors à l'identique, ce qui est le comportement voulu (l'apostrophe ne porte
# aucune information discriminante entre deux objets).
_APOSTROPHES = "'’‘ʼ´`‛"

# Traits d'union, tirets et puces que le rendu du jeu peut produire. Repliés
# vers une espace : « Cristal noir-tranchant » et « Cristal noir tranchant »
# doivent tomber sur la même forme.
_DASHES = "-‐‑‒–—―−"

# Glyphes que l'OCR confond avec des chiffres sur la police du journal
# d'acquisition. Utilisé UNIQUEMENT sur une quantité déjà isolée, jamais sur
# un nom.
_DIGIT_CONFUSIONS = {
    "|": "1",
    "!": "1",
    "l": "1",
    "I": "1",
    "i": "1",
    "[": "1",
    "]": "1",
    "/": "1",
    "\\": "1",
    "O": "0",
    "o": "0",
    "Q": "0",
    "D": "0",
    "S": "5",
    "s": "5",
    "B": "8",
    "Z": "2",
    "z": "2",
    "G": "6",
    "T": "7",
}

_NON_ALNUM = re.compile(r"[^a-z0-9 ]")
_MULTI_SPACE = re.compile(r"\s+")


def strip_accents(text: str) -> str:
    """Retire les diacritiques en conservant les lettres de base.

    « Épée » devient « Epee », « Âme » devient « Ame ». Les ligatures sont
    dépliées avant la décomposition, car NFKD ne les touche pas.
    """
    for ligature, replacement in _LIGATURES.items():
        text = text.replace(ligature, replacement)
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def fold(text: str) -> str:
    """Replie un texte vers sa forme canonique de comparaison.

    Applique dans l'ordre : apostrophes supprimées, tirets convertis en
    espaces, ligatures et accents dépliés, minuscules, ponctuation restante
    supprimée, espaces compactées.

    L'ordre compte, sur deux points qui ont chacun cassé un cas réel :

    * Les apostrophes passent AVANT le dépliage des accents. L'accent aigu
      isolé « ´ » (U+00B4), que l'OCR produit couramment pour l'apostrophe, se
      décompose en NFKD vers « espace + accent combinant ». Traité après, il a
      donc déjà été transformé en espace et « d'énergie » devient « d energie »
      au lieu de « denergie », qui ne correspond plus au catalogue.
    * Les tirets passent AVANT la suppression de la ponctuation, sinon
      « noir-tranchant » devient « noirtranchant », qui ne correspond plus à la
      forme espacée du catalogue.
    """
    for ch in _APOSTROPHES:
        text = text.replace(ch, "")
    for ch in _DASHES:
        text = text.replace(ch, " ")
    text = strip_accents(text)
    text = text.lower()
    text = _NON_ALNUM.sub(" ", text)
    return _MULTI_SPACE.sub(" ", text).strip()


def fold_digits(text: str) -> str:
    """Force les glyphes ambigus vers des chiffres.

    Réservé aux quantités déjà isolées du nom. Appliqué à un nom, il
    transformerait « Poudre » en « P0udre » et casserait toute correspondance.
    """
    return "".join(_DIGIT_CONFUSIONS.get(ch, ch) for ch in text)


def is_meaningful(folded: str, min_letters: int = 3) -> bool:
    """Vrai si une forme repliée porte assez de signal pour tenter un match.

    Garde-fou contre les lignes où l'OCR n'a lu que du bruit (« ll », « x », un
    fragment de bordure). Sans ce filtre, le score flou finit toujours par
    trouver un objet court qui ressemble vaguement au bruit, et le tracker
    invente des drops qui n'ont jamais eu lieu.
    """
    return sum(ch.isalpha() for ch in folded) >= min_letters
