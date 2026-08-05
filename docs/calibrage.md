# Trouver la fenêtre de chat sur l'écran

Ce document explique comment Butin trouve tout seul où lire le journal
d'acquisition, et pourquoi c'était bloquant.

Le code est dans `src/butin/capture/calibrate.py`, ses tests dans
`tests/test_calibrate.py`, et il se lance par :

```
butin calibrer
```

## 1. Pourquoi c'était bloquant

La zone du journal était **codée en dur** : `(0, 700, 780, 1275)`, relevée à la
main sur un écran 2560 × 1440 avec une disposition d'interface donnée. Le pas
vertical entre deux lignes l'était aussi, et la bande où mesurer le défilement
également.

Personne d'autre que nous ne pouvait donc s'en servir. Et le mode de défaillance
est le pire qui soit : une zone mal cadrée donne un journal **parfaitement
vide**. Le compteur affiche zéro drop, aucune erreur n'apparaît nulle part, et
rien ne distingue « le cadrage est faux » de « il n'y a rien eu à compter ».

## 2. Le signal : les pastilles de canal, enfin utiles

⭐ La propriété qui a **disqualifié** les pastilles pour la mesure de défilement
est exactement celle qui les rend parfaites ici.

Elles sont **toutes identiques et espacées d'exactement un pas de ligne**. Pour
détecter un défilement d'une ligne, c'est rédhibitoire : le décalage superpose
une pastille sur sa voisine et ne change rien à l'image (0 décalage juste sur 37,
voir [banc-essai.md](banc-essai.md) partie 4 B). Pour **reconnaître le chat dans
un écran de jeu**, c'est le contraire : c'est la seule chose de l'image qui se
répète verticalement avec une période nette.

On cherche donc la colonne dont l'image **ressemble le plus à elle-même décalée
d'un cran**, et le cran en question est le pas de ligne. Les deux inconnues
tombent d'un coup.

## 3. Trois pièges, et ce qui les évite

**Un minimum global n'est pas une périodicité.** Sur un dégradé lisse, plus le
décalage est petit, plus les deux copies se ressemblent : le plus petit décalage
gagne toujours, sans que rien ne se répète. Mesuré sur les 12 captures d'écran
réelles, ce critère naïf désignait n'importe quoi dans **10 cas sur 12**. On
cherche donc un **creux local**, c'est-à-dire un décalage qui fait nettement
mieux que ses voisins.

**Ressembler à soi-même ne suffit pas, il faut du contenu.** Un ciel uniforme
ressemble parfaitement à lui-même décalé de n'importe quoi. Les rangées retenues
doivent à la fois s'accorder avec leur voisine d'un pas ET porter du contraste.

**Le pas n'est pas entier.** Il vaut 21,6 px et non 22 : les décalages réellement
observés sont 22, 43, 65, 86 et 108 px pour une à cinq lignes. Arrondir coûte 2 %
par ligne, ce qui ne se voit pas sur une ligne et dérive d'une ligne entière au
bout de cinquante. D'où l'interpolation sous-pixel, qui rend **21,7**.

## 4. La largeur se mesure par l'OCR, pas par la géométrie

Le bord droit est la seule des quatre inconnues que la géométrie ne donne pas
proprement. Le contraste entre les bandes de texte et les interlignes s'éteint
progressivement à mesure que les lignes se terminent, et sur un décor clair il
s'éteint **bien avant** la fin du texte.

Réglé sur trois captures, le critère géométrique rendait 447 px sur l'une et
1 725 sur l'autre : d'un côté des montants tronqués (« x10.00 » au lieu de
« x10,000,000 »), de l'autre quatre fois le coût de reconnaissance.

`measure_width` répond donc directement à la question posée : lire une fois une
zone volontairement large, et regarder **jusqu'où va le texte**. Le calibrage
est une opération unique, il peut payer une reconnaissance là où la boucle ne le
peut pas.

Trois filtres, tous géométriques et **aucun ne suppose la langue du client** :

* la rangée doit tomber sur la **phase des lignes du journal**, déduite des
  rangées elles-mêmes et non supposée. Une enseigne du décor n'a aucune raison
  de tomber sur ce reste ;
* elle doit **commencer à la même abscisse** que les autres, celle de la
  pastille de canal ;
* la lecture s'arrête au **premier vrai blanc** de la rangée. Nécessaire parce
  que l'OCR regroupe ses fragments par rangée : du texte du décor situé à la
  même hauteur qu'une ligne du chat, mais trois cents pixels plus loin, est rendu
  dans la même rangée. Sans cette coupure, la largeur mesurée était celle de
  l'écran entier.

Une marge de 25 % est ensuite ajoutée, volontairement asymétrique : une zone trop
large coûte du temps d'OCR, une zone trop étroite **tronque les noms d'objets**,
et un nom tronqué est un drop perdu en silence.

## 5. Ce que ça donne sur de vraies captures

Douze captures d'écran réelles en 2559 × 1439, dont la vérité terrain a été
établie par l'OCR : le chat est visible et lisible sur **trois**, masqué sur les
neuf autres.

| | Détection | Zone trouvée | Pas | Lignes de gain lues |
| --- | --- | --- | --- | --- |
| capture 11 | force 0,60 | 551 × 496 | 21,7 | **16 / 16** |
| capture 12 | force 0,52 | 455 × 501 | 21,7 | **16 / 16** |
| capture 15 | force 0,26 | 551 × 521 | 21,7 | **16 / 16** |
| les 9 autres | ≤ 0,06 | refus explicite | — | — |

**12 sur 12.** Aucune capture au chat masqué n'a produit de zone, et aucune des
trois capture lisibles n'a perdu une ligne. Les zones trouvées sont d'ailleurs
plus serrées que celle qui était codée en dur (780 × 575), donc moins coûteuses
à reconnaître.

Le seuil de détection est posé entre les deux populations mesurées : **0,26 à
0,60** pour un chat visible, **0,06 au plus** pour un chat masqué. Il vaut 0,15,
soit quatre fois le bruit et un tiers sous la plus faible vraie détection.

## 6. Ce que le calibrage ne fait pas

**Il ne devine pas plus large que ce que le texte affiché lui montre.** Si toutes
les lignes visibles au moment du calibrage sont courtes, la zone sera courte. La
marge de 25 % absorbe l'ordinaire, pas un journal entièrement rempli de noms
brefs. La commande le signale quand elle trouve moins de dix rangées.

**Il ne suit pas un déplacement de la fenêtre.** Bouger ou redimensionner le chat
en jeu demande de relancer `butin calibrer`. Détecter le décalage en cours de
session est faisable, ça n'est pas fait.

**Il n'a été validé que sur une seule résolution et une seule échelle
d'interface**, faute d'autres captures. Rien dans l'algorithme n'en dépend, tout
y est mesuré plutôt que fixé, mais ce n'est pas la même chose que l'avoir
vérifié.
