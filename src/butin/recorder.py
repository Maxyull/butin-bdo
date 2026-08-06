"""Pont entre la boucle de capture et la base des sessions.

Le dernier maillon. `capture/loop.py` sait produire des drops confirmés,
`store/db.py` sait les garder : ce module les relie, et rien d'autre. Il est à
la racine du paquet parce qu'il n'appartient ni à l'un ni à l'autre, et que les
faire se connaître directement créerait une dépendance dont aucune des deux
couches n'a besoin.

Écrire tout de suite, pas à la fin
-----------------------------------

Chaque tour écrit ce qu'il vient de confirmer. Accumuler en mémoire pour tout
enregistrer à l'arrêt serait plus efficace et perdrait **toute la session** au
moindre plantage, à la moindre coupure de courant, au moindre arrêt brutal du
jeu. Une session de farm dure des heures : c'est exactement le genre de perte
qu'on ne pardonne pas à un outil dont le seul rôle est de compter.

Le coût est nul en pratique : un tour produit zéro à quelques drops, et SQLite
écrit ça sans qu'on le remarque, très loin des 336 ms que coûte déjà la
reconnaissance de texte du même tour.

Un enregistreur ne décide de rien
----------------------------------

Il ne choisit ni quand démarrer, ni quand s'arrêter, ni ce qui compte comme un
drop. Il prend ce que la boucle a **déjà confirmé** et le range. Toute la
prudence est en amont, dans le vote multi-images de `staging.py`, et elle ne
doit pas être rejouée ici sous une autre forme.
"""

from __future__ import annotations

import logging

from .capture.loop import CaptureLoop, TickResult
from .catalog.zones import detect_spot, load_zone_translations, load_zones
from .store import LootRow, SessionStore

_log = logging.getLogger(__name__)


class SessionRecorder:
    """Fait tourner la boucle et range ce qu'elle confirme."""

    def __init__(self, loop: CaptureLoop, store: SessionStore, session_id: int) -> None:
        self.loop = loop
        self.store = store
        self.session_id = session_id
        self.recorded_events = 0
        self.recorded_silver = 0
        self._seen_ids: set[int] = set()
        self._zones = load_zones()
        self._zone_translations = load_zone_translations()
        self.skipped_frames = 0
        """Images écartées par les garde-fous. Une valeur qui grimpe signale un
        problème de calibrage, pas une absence de butin, et c'est la seule façon
        de distinguer les deux depuis l'extérieur."""

    def tick(self, now: float) -> TickResult:
        """Un tour de boucle, puis enregistrement immédiat de ce qu'il a donné."""
        resultat = self.loop.tick(now)
        if resultat.skipped_reason:
            self.skipped_frames += 1
            _log.debug("image écartée : %s", resultat.skipped_reason)
        self._persist(resultat, now)
        return resultat

    def flush(self, now: float) -> int:
        """Valide et enregistre les drops encore en attente, à l'arrêt.

        Sans ça, le butin vu une ou deux fois seulement au moment où l'on
        arrête serait perdu, alors qu'il est bien tombé.
        """
        evenements = self.loop.flush()
        lignes = [
            LootRow(item_id=event.item.item_id, qty=event.qty, at=now) for event in evenements
        ]
        ecrites = self.store.add_loot(self.session_id, lignes)
        self.recorded_events += ecrites
        return ecrites

    @property
    def detected_spot(self) -> str | None:
        """Spot déduit du trash loot observé, ou None si ce n'est pas net.

        Le trash loot est propre à son spot : c'est lui qui permet de nommer une
        session sans rien demander à l'utilisateur, qui oublierait de le faire.

        Rendu en français quand la traduction existe : le produit est pensé
        pour le client français dès la première ligne, un nom de session en
        anglais serait la seule chose de tout le produit à ne pas l'être.
        Repli sur l'anglais quand la zone n'a pas encore de traduction, plutôt
        que de rendre None : un nom en anglais reste plus utile qu'aucun nom.
        """
        zone_en = detect_spot(self._seen_ids, self._zones)
        if zone_en is None:
            return None
        return self._zone_translations.get(zone_en, zone_en)

    def _persist(self, resultat: TickResult, now: float) -> None:
        if resultat.events:
            self._seen_ids.update(event.item.item_id for event in resultat.events)
            spot = self.detected_spot
            if spot is not None:
                # N'écrase jamais un nom saisi à la main : c'est le store qui
                # applique cette règle, pas l'appelant.
                self.store.set_spot(self.session_id, spot)
            lignes = [
                LootRow(item_id=event.item.item_id, qty=event.qty, at=now)
                for event in resultat.events
            ]
            self.recorded_events += self.store.add_loot(self.session_id, lignes)

        if resultat.silver:
            # Le silver suit un chemin séparé : il est déjà exprimé dans l'unité
            # finale et ne doit jamais passer par une recherche de prix.
            self.store.add_silver(self.session_id, resultat.silver)
            self.recorded_silver += resultat.silver
