"""Butin — suivi de butin pour Black Desert Online, en français.

Le paquet est découpé en couches indépendantes, chacune testable seule :

* `catalog` — noms d'objets français, normalisation et reconnaissance
* `capture` — capture d'écran et OCR
* `tracking` — transformation d'images successives en événements de loot
* `market`  — prix du marché central
* `store`   — persistance des sessions

Aucune couche n'importe une couche située au-dessus d'elle.
"""

# Doit rester identique à la version de pyproject.toml. Un test le vérifie :
# deux sources de vérité qui divergent produisent un numéro faux à l'exécution,
# ce que personne ne remarque avant un rapport de bogue. Voir
# docs/versionnage.md pour la politique de version.
__version__ = "0.2.0"
