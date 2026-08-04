# Contribuer à Butin

Merci de vouloir aider. Ce fichier dit comment le projet fonctionne pour que
vous n'ayez pas à le deviner.

## Langue du projet

Butin s'adresse aux joueurs francophones, donc **tout ce qui est lu par un
humain est en français** : ce README, la documentation, les commentaires, les
messages de commit, les issues, les pull requests, et l'interface.

**Le code lui-même est en anglais** : noms de modules, de fonctions, de
variables. Les bibliothèques utilisées le sont, l'écosystème Python aussi, et
mélanger les deux dans une même ligne se lit mal.

```python
def resolve(self, text: str, *, scope: Scope | None = None) -> Match | None:
    """Renvoie l'objet correspondant, ou None si rien de sûr n'est trouvé."""
```

## Mise en place

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
pytest
```

## Avant d'ouvrir une pull request

```bash
ruff check src tests
ruff format src tests
mypy
pytest
```

L'intégration continue lance exactement ces quatre commandes, plus `pip-audit`.

## Politique de tests

Chaque correction de bogue et chaque fonctionnalité arrive avec **deux** tests,
pas un :

1. **Un test unitaire**, qui vérifie que la logique fait ce qu'elle doit faire.
2. **Un test de régression**, qui empêche le bogue de revenir par un autre
   chemin, et dont la docstring raconte le cas réel rencontré.

Un test de régression sans explication ne sert qu'une fois. Écrivez ce qui
serait cassé sans lui, concrètement :

```python
def test_deplie_la_ligature_oe(self) -> None:
    """Régression : « Nœud d'arbre ensanglanté » est un vrai drop.

    NFKD ne décompose pas « œ », qui est une lettre à part entière en
    Unicode. Sans dépliage explicite, ce nom et tous ceux contenant « œ »
    sont structurellement impossibles à reconnaître, quel que soit le seuil
    du score flou.
    """
```

## Données de test réelles

Les tests utilisent de **vrais** noms d'objets avec leurs **vrais**
identifiants, jamais des valeurs inventées. Un jeu de test inventé passe à côté
des cas qui cassent réellement : la ligature de « Nœud », le couple
« tranchant » / « dur » qui ne diffère que par un mot, les cinq objets qui
partagent le nom « Jeune dragon écarlate ».

## Ajouter un nom vérifié

Les noms français sont recoupés à la main dans
[`data/noms-verifies.json`](data/noms-verifies.json).

**bdocodex** et **garmoth** font référence, d'autres bases confirment. Une
entrée doit citer **au moins deux sources distinctes dont au moins une
référence**. Un test échoue tant qu'une entrée ne respecte pas cette règle,
pour qu'un recoupement commencé ne soit pas pris pour acquis.

```json
"4998": {
  "nom": "Éclat de cristal noir tranchant",
  "sources": ["bdocodex", "garmoth"],
  "verifie_le": "2026-08-04"
}
```

## Le principe qui tranche les arbitrages

> Rater un drop donne un chiffre un peu bas. Inventer un drop donne un chiffre
> faux.

Les deux erreurs ne coûtent pas la même chose. Un chiffre légèrement
sous-estimé reste exploitable, un chiffre faux fait changer de spot pour de
mauvaises raisons sans que rien ne le signale. Quand un réglage arbitre entre
les deux, il penche vers ne pas compter.

Si votre changement rend la reconnaissance plus permissive, dites dans la pull
request ce qui garantit qu'elle ne devient pas plus fausse.

## Branches et commits

Pas de commit direct sur `main`, même pour une ligne. Une branche, une pull
request, fusion quand la CI est verte.

Messages de commit en français, à l'impératif :

```
Déplie la ligature « œ » avant la décomposition NFKD
```

## Vie privée dans les rapports de bogue

Une capture d'écran de Black Desert contient souvent votre pseudonyme, votre
guilde et le chat. **Masquez-les avant de joindre une image.** Le dépôt est
public et son historique est permanent.
