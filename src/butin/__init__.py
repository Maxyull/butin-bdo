"""Butin — suivi de butin pour Black Desert Online, en français.

Le paquet est découpé en couches indépendantes, chacune testable seule :

* `catalog` — noms d'objets français, normalisation et reconnaissance
* `capture` — capture d'écran et OCR
* `tracking` — transformation d'images successives en événements de loot
* `market`  — prix du marché central
* `store`   — persistance des sessions

Aucune couche n'importe une couche située au-dessus d'elle.
"""

__version__ = "0.1.0"
