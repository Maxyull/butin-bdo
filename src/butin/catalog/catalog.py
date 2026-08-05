"""Catalogue d'objets indexé, prêt pour la reconnaissance.

`ItemCatalog` transforme le JSON brut en trois index :

* par identifiant, pour retrouver un objet à partir d'un événement de loot ou
  d'un prix du marché ;
* par nom français replié, pour la correspondance exacte, qui est le chemin
  rapide et de loin le plus fréquent ;
* la liste des noms repliés, pour la correspondance floue, qui ne sert que
  lorsque l'OCR a déformé le texte.

Un même nom français peut désigner plusieurs identifiants (les objets
d'apparence, les variantes saisonnières et les récompenses d'événement
partagent souvent un libellé). L'index conserve donc une liste et applique une
règle de départage explicite plutôt que d'écraser au hasard selon l'ordre
d'itération, qui produirait des prix différents d'une exécution à l'autre.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Iterator, Sequence
from pathlib import Path
from typing import Any

from .. import paths
from . import bdocodex, source
from . import overrides as overrides_module
from .models import LOCALE_EN, LOCALE_FR, Item
from .normalize import fold
from .overrides import VerifiedName

_log = logging.getLogger(__name__)


class ItemCatalog:
    """Accès indexé aux objets du jeu."""

    def __init__(self, items: Iterable[Item], *, locale: str = LOCALE_FR) -> None:
        self.locale = locale
        self._by_id: dict[int, Item] = {}
        self._by_folded: dict[str, list[int]] = {}

        for item in items:
            self._by_id[item.item_id] = item
            label = item.names.get(locale) or item.names.get(LOCALE_EN)
            if not label:
                continue
            folded = fold(label)
            if not folded:
                continue
            self._by_folded.setdefault(folded, []).append(item.item_id)

        # Départage stable : à nom égal, le plus petit identifiant gagne. Les
        # identifiants bas correspondent aux objets de base du jeu, les hauts
        # aux ajouts tardifs (apparences, événements). Cette règle vaut mieux
        # qu'un ordre arbitraire, mais elle reste une heuristique : quand elle
        # se trompe, la correction passe par une exception explicite dans les
        # données, jamais par un changement de cette règle.
        for ids in self._by_folded.values():
            ids.sort()

        self._folded_names: tuple[str, ...] = tuple(self._by_folded)

    # -- construction ----------------------------------------------------

    @classmethod
    def from_raw(
        cls,
        data: dict[str, Any],
        *,
        locale: str = LOCALE_FR,
        overrides: dict[int, VerifiedName] | None = None,
    ) -> ItemCatalog:
        """Construit le catalogue depuis la structure JSON amont.

        Les entrées mal formées sont ignorées avec un avertissement plutôt que
        de faire échouer la construction : un objet exotique ajouté en amont ne
        doit pas empêcher les 8000 autres de fonctionner.

        `overrides` remplace le nom français de la source amont par un nom
        recoupé à la main (voir overrides.py). Ces noms gagnent toujours : ils
        ont été confrontés au client français, la source amont non.
        """
        overrides = overrides or {}
        items: list[Item] = []
        skipped = 0
        for key, entry in data.items():
            try:
                item_id = int(entry["id"])
                names = entry["locale_name"]
                if not isinstance(names, dict):
                    raise TypeError("locale_name n'est pas un objet")
            except (KeyError, TypeError, ValueError):
                skipped += 1
                _log.debug("entrée de catalogue ignorée : %r", key)
                continue
            localized = {str(k): str(v) for k, v in names.items() if v}
            verified = overrides.get(item_id)
            if verified is not None:
                localized[LOCALE_FR] = verified.name
            items.append(
                Item(
                    item_id=item_id,
                    names=localized,
                    grade=_as_int(entry.get("grade")),
                    category_primary=_as_int(entry.get("category_primary")),
                    category_secondary=_as_int(entry.get("category_secondary")),
                    icon=str(entry.get("icon") or ""),
                )
            )
        if skipped:
            _log.warning("%d entrées de catalogue ignorées car mal formées", skipped)
        return cls(items, locale=locale)

    @classmethod
    def load(
        cls,
        *,
        path: Path | None = None,
        overrides_path: Path | None = None,
        locale: str = LOCALE_FR,
        allow_download: bool = True,
        names_source: str = "bdocodex",
    ) -> ItemCatalog:
        """Charge le catalogue depuis le cache, en téléchargeant si nécessaire.

        `allow_download=False` interdit tout accès réseau. Les tests s'en
        servent pour garantir qu'aucun test ne dépend d'internet.

        `names_source` vaut « bdocodex » par défaut, et « veliainn » pour
        l'ancienne source de marché. Ce défaut vient d'une mesure sur une vraie
        capture : voir `bdocodex.py`.
        """
        if names_source == "bdocodex":
            # Source de noms par défaut, et pour une raison mesurée : voir
            # bdocodex.py. Le catalogue de marché causait des attributions
            # FAUSSES, pas seulement des oublis.
            data = bdocodex.to_catalog_payload(bdocodex.load(allow_download=allow_download))
        else:
            path = path or paths.catalog_path()
            cached = source.load_cached(path)
            if cached is None:
                if not allow_download:
                    raise source.CatalogError(
                        f"aucun catalogue en cache dans {path} et téléchargement désactivé"
                    )
                cached = source.refresh(path)
            data = cached
        verified = overrides_module.load(overrides_path or overrides_module.default_path())
        if verified:
            _log.info("%d noms français vérifiés à la main appliqués", len(verified))
        return cls.from_raw(data, locale=locale, overrides=verified)

    # -- consultation ----------------------------------------------------

    def __len__(self) -> int:
        return len(self._by_id)

    def __iter__(self) -> Iterator[Item]:
        return iter(self._by_id.values())

    def __contains__(self, item_id: object) -> bool:
        return item_id in self._by_id

    def get(self, item_id: int) -> Item | None:
        return self._by_id.get(item_id)

    def by_exact_name(self, text: str) -> Item | None:
        """Correspondance exacte sur la forme repliée du nom.

        C'est le chemin rapide : sur une capture nette, la grande majorité des
        lignes se résolvent ici, sans jamais toucher au score flou.
        """
        ids = self._by_folded.get(fold(text))
        if not ids:
            return None
        return self._by_id[ids[0]]

    def ids_for_name(self, text: str) -> Sequence[int]:
        """Tous les identifiants partageant ce nom, ordre stable."""
        return tuple(self._by_folded.get(fold(text), ()))

    @property
    def folded_names(self) -> tuple[str, ...]:
        """Noms repliés, servant de dictionnaire au score flou."""
        return self._folded_names

    def item_for_folded(self, folded: str) -> Item | None:
        ids = self._by_folded.get(folded)
        return self._by_id[ids[0]] if ids else None

    def coverage(self, locale: str = LOCALE_FR) -> float:
        """Part des objets disposant d'un nom dans cette locale, entre 0 et 1.

        Sert de garde-fou : une chute brutale de la couverture française
        signale que la source amont a changé de format ou perdu une locale,
        bien avant que les utilisateurs ne remontent des drops non reconnus.
        """
        if not self._by_id:
            return 0.0
        covered = sum(1 for item in self._by_id.values() if item.has_locale(locale))
        return covered / len(self._by_id)


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
