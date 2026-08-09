"""Réglages de l'utilisateur, retenus d'un lancement à l'autre.

Pourquoi sur disque, et pas seulement en mémoire
-------------------------------------------------

Le taux de taxe n'est pas une constante du jeu, c'est une propriété du **compte**
(voir `TaxProfile`). Tant qu'il ne vivait qu'en mémoire, il revenait au taux sans
aucun bonus à chaque lancement : quelqu'un qui a un abonnement voyait donc son
butin valorisé à 0,65 alors qu'il en touche 0,845, soit **23 % de moins** sur
tout ce qui passe par l'hôtel des ventes.

L'erreur est systématique, pas aléatoire : elle ne se compense pas d'une session
à l'autre, elle se répète à l'identique. Et rien à l'écran ne la distingue d'un
farm pauvre. Un réglage qu'il faut ressaisir à chaque lancement est donc un
réglage silencieusement faux la plupart du temps.

Ce que fait un fichier illisible
---------------------------------

Il rend les valeurs par défaut, il n'arrête pas le programme. Deux raisons :

1. le défaut est le taux **sans aucun bonus**, donc celui qui sous-estime. Le
   sens de l'erreur est le bon : rater du silver donne un chiffre un peu bas,
   en inventer donne un chiffre faux ;
2. l'interface affiche le taux obtenu **à côté** des cases à cocher, en
   permanence. Un retour au défaut se voit donc à l'écran, alors que refuser de
   démarrer retirerait à l'utilisateur le moyen d'aller corriger le fichier.

C'est l'inverse du choix fait pour le calibrage, qui lève : capturer la mauvaise
zone du jeu ne se voit **pas**, et donne un journal vide sans rien dire.

Chaque valeur est validée séparément
-------------------------------------

Une valeur refusée laisse la précédente en place et n'entraîne pas les autres :
le fichier est éditable à la main, et une renommée saisie en toutes lettres ne
doit pas faire perdre l'abonnement au passage. `updated` est le seul endroit où
ces règles vivent, et l'API comme le fichier y passent, sinon les deux chemins
finiraient par diverger.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from .. import paths
from ..market import Region
from .stats import TaxProfile

_log = logging.getLogger(__name__)

LANGUAGES = ("fr", "us")
"""Les deux langues du catalogue amont. Ce ne sont pas des codes ISO : « us »
est le nom que la source donne à l'anglais, et le changer ici casserait la
lecture des noms d'objets."""


@dataclass(frozen=True, slots=True)
class Settings:
    """Ce que l'utilisateur a choisi, et qui doit lui revenir au lancement suivant."""

    language: str = "fr"
    region: Region = Region.EU
    tax: TaxProfile = field(default_factory=TaxProfile)

    overlay_click_through: bool = True
    """Le panneau posé sur le jeu laisse-t-il passer la souris ?

    ⭐ Vrai par défaut, tranché par Maxime le 09/08/2026 : le panneau captait le
    survol, donc Windows réaffichait le curseur en plein jeu. Le défaut protège
    ce qui compte le plus — jouer — et le coût est réversible d'une case à
    cocher : le panneau ne reçoit plus de clic tant que c'est actif.

    ⚠️ Le seul réglage de ce fichier qui agisse sur une fenêtre plutôt que sur
    un calcul. Il est donc appliqué à l'ouverture du panneau ET à chaque
    changement, sinon la case dirait une chose et la fenêtre en ferait une
    autre."""

    @property
    def market_rate(self) -> float:
        """Part du prix affiché réellement reçue à l'hôtel des ventes."""
        return self.tax.net_rate

    def updated(
        self,
        *,
        language: object = None,
        region: object = None,
        value_pack: object = None,
        merchant_ring: object = None,
        family_fame: object = None,
        overlay_click_through: object = None,
    ) -> Settings:
        """Applique ce qui est valide, ignore le reste, et rend un nouveau réglage.

        `None` veut dire « pas touché », ce qui permet d'envoyer une seule case
        à cocher sans avoir à renvoyer tout le reste avec.
        """
        change: dict[str, Any] = {}

        if language is not None:
            if language in LANGUAGES:
                change["language"] = language
            else:
                _log.warning("langue inconnue ignorée : %r", language)

        if region is not None:
            try:
                change["region"] = Region(region)
            except ValueError:
                _log.warning("région inconnue ignorée : %r", region)

        if overlay_click_through is not None:
            if isinstance(overlay_click_through, bool):
                change["overlay_click_through"] = overlay_click_through
            else:
                _log.warning(
                    "souris traversante attendue booléenne, reçue %r", overlay_click_through
                )

        taxe: dict[str, Any] = {}
        for nom, valeur in (("value_pack", value_pack), ("merchant_ring", merchant_ring)):
            if valeur is None:
                continue
            if isinstance(valeur, bool):
                taxe[nom] = valeur
            else:
                _log.warning("%s attendu booléen, reçu %r", nom, valeur)

        if family_fame is not None:
            # `bool` d'abord : en Python `isinstance(True, int)` est vrai, et une
            # case à cocher envoyée dans le mauvais champ deviendrait sinon une
            # renommée de 1.
            if isinstance(family_fame, bool) or not isinstance(family_fame, int):
                _log.warning("renommée attendue entière, reçue %r", family_fame)
            elif family_fame < 0:
                _log.warning("renommée négative ignorée : %r", family_fame)
            else:
                taxe["family_fame"] = family_fame

        if taxe:
            change["tax"] = replace(self.tax, **taxe)
        return replace(self, **change)

    # -- disque ----------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "language": self.language,
            "region": self.region.value,
            "overlay_click_through": self.overlay_click_through,
            "tax": {
                "value_pack": self.tax.value_pack,
                "merchant_ring": self.tax.merchant_ring,
                "family_fame": self.tax.family_fame,
            },
        }

    @classmethod
    def from_dict(cls, data: object) -> Settings:
        """Relit des réglages, en gardant le défaut pour tout ce qui cloche."""
        if not isinstance(data, dict):
            _log.warning("réglages : objet attendu, reçu %s", type(data).__name__)
            return cls()
        taxe = data.get("tax")
        taxe = taxe if isinstance(taxe, dict) else {}
        return cls().updated(
            language=data.get("language"),
            region=data.get("region"),
            overlay_click_through=data.get("overlay_click_through"),
            value_pack=taxe.get("value_pack"),
            merchant_ring=taxe.get("merchant_ring"),
            family_fame=taxe.get("family_fame"),
        )

    def save(self, path: Path | None = None) -> Path:
        """Écrit les réglages, en JSON lisible et modifiable à la main."""
        cible = path or paths.settings_path()
        cible.parent.mkdir(parents=True, exist_ok=True)
        cible.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return cible

    @classmethod
    def load(cls, path: Path | None = None) -> Settings:
        """Relit les réglages, ou rend les défauts. Ne lève jamais.

        Voir l'en-tête du module : le défaut est le taux qui sous-estime, et il
        est affiché en permanence dans l'interface. S'arrêter ici priverait
        l'utilisateur du seul écran d'où il peut réparer.
        """
        source = path or paths.settings_path()
        if not source.exists():
            return cls()
        try:
            brut = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            _log.warning("réglages illisibles (%s), retour aux valeurs par défaut", exc)
            return cls()
        return cls.from_dict(brut)
