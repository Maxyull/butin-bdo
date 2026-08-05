"""Banc d'essai du compteur sur des captures réelles.

Ce paquet ne fait pas partie du produit : il **mesure** le produit. Il existe
pour répondre à une seule question, celle qui décide si on peut publier ou non :

> Le compteur est-il juste, et si non, à combien près ?

Sans réponse chiffrée à ça, l'utilisateur voit un total sans savoir s'il vaut
quelque chose, ce qui est pire qu'un total absent.

⚠️ La leçon du 05/08/2026, à ne pas réapprendre
------------------------------------------------

Une première mesure a échoué en prenant **« les lignes distinctes vues »** pour
la vérité terrain. C'est faux : deux drops réellement identiques à quelques
secondes d'écart sont deux lignes du journal et une seule ligne distincte. La
référence sous-comptait pendant que le compteur additionnait, ce qui a donné un
« 2800 % » absurde. Il était visiblement cassé ; il aurait pu ne pas l'être, et
on aurait publié un chiffre faux en croyant l'avoir vérifié.

D'où la règle qui structure ce paquet : **aucun des trois nombres produits ne
sert de vérité aux deux autres.** Ils sont mesurés par des chemins qui ne
partagent rien, et c'est leur accord qui vaut preuve, pas l'un d'eux :

| Nombre | Module | Ce qu'il regarde | Ce qu'il ignore |
| --- | --- | --- | --- |
| le compteur | `replay` | la vraie boucle telle qu'elle tourne | rien |
| la référence | `assembly` | le texte de **toutes** les images | pixels, flou, garde-fous |
| l'empreinte | `fingerprints` | les montants de silver, tirés au hasard | toute position |
| le défilement | `pixels` | les pixels du journal | le texte, entièrement |

`assembly` et `fingerprints` mesurent la **même** grandeur, le nombre de lignes
de silver passées, sans partager autre chose que le découpage d'une ligne. Leur
accord est ce qui rend la référence croyable ; sans lui, le banc ne conclut rien
et le dit.

⚠️ `pixels` devait tenir ce rôle et **ne le tient pas** : mesuré sur la rafale
du 05/08/2026, il ne détecte aucun défilement, pour une raison structurelle
détaillée dans son en-tête. Il est conservé parce qu'un défaut mesuré et affiché
vaut mieux qu'un module supprimé et oublié, et parce que ce constat commande la
suite du projet.
"""

from .assembly import AssembledLine, Assembly, assemble, canon
from .fingerprints import Fingerprints, silver_fingerprints
from .pixels import PixelScroll, measure_scroll
from .replay import Replay, replay
from .report import BenchReport, Tally, build_report, tally_events, tally_lines
from .transcript import BenchFrame, Transcript

__all__ = [
    "AssembledLine",
    "Assembly",
    "BenchFrame",
    "BenchReport",
    "Fingerprints",
    "PixelScroll",
    "Replay",
    "Tally",
    "Transcript",
    "assemble",
    "build_report",
    "canon",
    "measure_scroll",
    "replay",
    "silver_fingerprints",
    "tally_events",
    "tally_lines",
]
