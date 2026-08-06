"""Un journal de diagnostic par session de farm.

Pourquoi ce module existe
--------------------------

⭐ Dans toute l'histoire de ce projet, **trois hypothèses fausses ont été tuées
par une trace d'exécution et aucune par le raisonnement.** Le sur-comptage du
05/08 a été trouvé en journalisant les entrées et sorties de l'alignement sur
cinquante et une lectures : le tableau « précédentes=4, courantes=23,
recouvrement=0, neuves=23 », répété quatre fois, se lit en une seconde et vaut
mieux que trois heures de relecture.

Jusqu'ici il fallait rejouer une rafale d'images enregistrées à la main pour
obtenir ça. Désormais **chaque session en produit une**, sans rien demander au
joueur : quand un chiffre paraît faux, le fichier est déjà là.

Ce que le fichier contient, et pourquoi
----------------------------------------

Un `.jsonl` : une ligne d'en-tête, puis une ligne par lecture, puis un bilan.
Ce format se lit à l'œil, se filtre avec n'importe quel outil, et surtout
s'écrit **au fil de l'eau** : une session qui se termine par un plantage garde
tout ce qui a précédé, ce qu'un fichier écrit d'un bloc à la fin perdrait
précisément dans le cas qui nous intéresse le plus.

Trois garanties, toutes prises pour la même raison — un outil de diagnostic ne
doit jamais devenir la cause du problème :

**Il n'interrompt jamais la capture.** Toute panne d'écriture est avalée et
notée une fois. Perdre le journal est ennuyeux, perdre la session ne l'est pas.

**Il est borné.** Une session de six heures produit des dizaines de milliers de
lectures. Au-delà du plafond, on cesse d'écrire les lectures ET **on le dit**
dans le bilan : une troncature silencieuse ferait lire « voilà tout ce qui
s'est passé » à un fichier incomplet.

**Il ne contient rien de personnel.** Le journal d'acquisition est le canal
Système du chat, mais l'OCR lit la zone calibrée telle quelle : si un message
de guilde y passe, il finit ici. Le fichier reste donc **sur la machine du
joueur** et n'est jamais envoyé automatiquement — c'est lui qui choisit de le
joindre, et le bouton de rapport n'envoie que le résumé.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import __version__, paths

_log = logging.getLogger(__name__)

#: Nom du dossier, à côté des sessions. Visible exprès : c'est ce qu'on
#: demandera au joueur de joindre à un rapport.
DOSSIER = "rapports"

#: Au-delà, on cesse d'écrire les lectures. 20 000 lignes couvrent environ
#: cinq heures de farm à une lecture par seconde, et pèsent quelques mégaoctets.
MAX_LECTURES = 20_000


def dossier_des_rapports(racine: Path | None = None) -> Path:
    return (racine or paths.storage_root()) / DOSSIER


@dataclass
class SessionJournal:
    """Écrit le journal d'une session, ligne par ligne.

    Créé au démarrage de la capture, fermé à son arrêt. Un journal dont
    `chemin` est `None` n'écrit rien : c'est l'état d'une session lancée sans
    disque accessible, et le reste du programme n'a pas à le savoir.
    """

    session_id: int
    chemin: Path | None = None
    lectures: int = 0
    ecartees: int = 0
    tronque: bool = False
    _pannes: int = 0
    _debut: float = field(default_factory=time.time)

    @classmethod
    def ouvrir(
        cls,
        session_id: int,
        *,
        racine: Path | None = None,
        entete: dict[str, Any] | None = None,
    ) -> SessionJournal:
        """Crée le fichier et y écrit l'en-tête. Ne lève jamais."""
        journal = cls(session_id=session_id)
        try:
            dossier = dossier_des_rapports(racine)
            dossier.mkdir(parents=True, exist_ok=True)
            horodatage = time.strftime("%Y%m%d-%H%M%S", time.localtime(journal._debut))
            journal.chemin = dossier / f"session-{session_id:04d}-{horodatage}.jsonl"
            journal._ecrire(
                {
                    "type": "entete",
                    "session": session_id,
                    "version": __version__,
                    "debut": journal._debut,
                    **(entete or {}),
                }
            )
        except OSError as exc:
            _log.warning("journal de diagnostic indisponible : %s", exc)
            journal.chemin = None
        return journal

    def lecture(self, trace: dict[str, Any] | None, *, maintenant: float | None = None) -> None:
        """Note une lecture. Les tours sans reconnaissance ne produisent rien.

        Un tour sans OCR n'apprend rien sur le comptage et il y en a dix par
        seconde : les écrire noierait les cinquante qui comptent.
        """
        if trace is None or self.chemin is None:
            return
        if self.lectures >= MAX_LECTURES:
            self.tronque = True
            return
        self.lectures += 1
        if trace.get("etape") == "ecartee":
            self.ecartees += 1
        instant = time.time() if maintenant is None else maintenant
        self._ecrire({"type": "lecture", "t": round(instant - self._debut, 2), **trace})

    def fermer(self, bilan: dict[str, Any] | None = None) -> None:
        """Écrit le bilan et arrête d'écrire. Appelable plusieurs fois sans
        dommage : arrêter une session déjà arrêtée ne doit pas produire une
        seconde fin de fichier qui contredirait la première."""
        if self.chemin is None:
            return
        self._ecrire(
            {
                "type": "bilan",
                "duree_s": round(time.time() - self._debut, 1),
                "lectures_ecrites": self.lectures,
                "images_ecartees": self.ecartees,
                # ⚠️ Dit explicitement que le fichier est incomplet. Sans ça, on
                # lirait « voilà tout ce qui s'est passé » sur un extrait.
                "tronque": self.tronque,
                "plafond": MAX_LECTURES if self.tronque else None,
                "pannes_d_ecriture": self._pannes,
                **(bilan or {}),
            }
        )
        self.chemin = None

    def _ecrire(self, objet: dict[str, Any]) -> None:
        if self.chemin is None:
            return
        try:
            with self.chemin.open("a", encoding="utf-8") as fichier:
                fichier.write(json.dumps(objet, ensure_ascii=False) + "\n")
        except OSError as exc:
            # ⛔ Une panne d'écriture ne doit JAMAIS interrompre la capture. Le
            # journal sert à comprendre une session ; le faire échouer sur un
            # disque plein reviendrait à casser ce qu'il devait observer.
            self._pannes += 1
            if self._pannes == 1:
                _log.warning("écriture du journal impossible : %s", exc)
