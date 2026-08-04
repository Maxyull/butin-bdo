# Le catalogue du marché ne couvre pas le butin

**Mesuré le 04/08/2026 sur de vraies captures : 1 objet reconnu sur 8.**

C'est la découverte la plus lourde du projet. Elle invalide une hypothèse de
départ qui semblait évidente, et elle serait passée inaperçue jusqu'à ce que des
joueurs signalent des sessions à moitié vides sans pouvoir dire pourquoi.

## La mesure

Huit noms relevés dans le journal d'acquisition d'une vraie session, confrontés
au catalogue `veliainn-market-resources` par comparaison sur forme repliée :

| Nom affiché en jeu | Dans le catalogue ? |
| --- | --- |
| `Pain moelleux` | ✅ oui, identifiant 9260 |
| `Pièces` | ❌ absent |
| `Humus noir` | ❌ absent |
| `Anneau de Tuvala` | ❌ absent |
| `Boucle d'oreille de Tuvala` | ❌ absent |
| `Boîte de costume de soldat de Serendia` | ❌ absent |
| `[Serendia] Boîte de tenue de Cleia` | ❌ absent |
| `Pierre noire` | ❌ absent, mais **deux voisins** |

## Pourquoi

`items.json` de veliainn est un **catalogue de marché**. Il liste ce qui
s'échange à l'hôtel des ventes, parce que c'est ce qu'il sert à faire : donner
des prix.

Or une grande partie du butin réel ne s'échange pas :

- l'**équipement de saison** (Tuvala) est lié au personnage ;
- les **coffres et boîtes** de récompense sont liés ;
- les objets de **quête** ne sont pas marchands ;
- les **pièces** sont une monnaie, pas un objet.

Le catalogue est donc parfaitement adapté à sa fonction, et inadapté à celle
qu'on lui a donnée. Confondre « base de prix » et « base d'objets » était
l'erreur.

## Le cas `Pierre noire`, plus grave que les autres

Les autres absences donnent une non-reconnaissance : le drop n'est pas compté,
c'est une perte visible dans le compteur de lignes non résolues.

`Pierre noire` fait pire. Le catalogue contient `Pierre noire (arme)` et
`Pierre noire (armure)`, deux objets réels, deux prix différents. Une lecture de
`Pierre noire` est à distance égale des deux.

La marge d'ambiguïté de `catalog/matcher.py` fait alors exactement ce pour quoi
elle a été écrite : elle **refuse de trancher**. C'est le bon comportement, et
il produit ici le pire résultat possible, puisque la pierre noire est l'un des
drops les plus fréquents du jeu.

Explication la plus probable, **à vérifier** : les captures montrent de
l'équipement Tuvala, donc un serveur de saison, où existe une « Pierre noire »
distincte servant à l'amélioration Tuvala, liée au personnage donc absente du
marché. Ce n'est pas une troncature d'affichage mais un troisième objet. À
confirmer sur bdocodex avant d'agir dessus.

## Ce que ça change

**Une base d'objets et une base de prix sont deux choses différentes.**

| Besoin | Source | État |
| --- | --- | --- |
| Nom français de **tout** objet lootable | bdocodex, garmoth | à faire |
| Prix de marché des objets échangeables | veliainn, arsha | en place |

Un objet lié n'a pas de prix de marché, et c'est normal : il ne contribue pas au
silver par heure. Mais il doit être **reconnu et compté**, sans quoi
l'utilisateur voit un journal muet là où il a bien reçu quelque chose.

## Conséquence sur `data/noms-verifies.json`

Ce fichier a été écrit pour **corriger** un nom du catalogue. Il doit aussi
pouvoir en **ajouter** un que le catalogue ne contient pas, et lever une
ambiguïté entre deux voisins.

Trois besoins distincts, aujourd'hui un seul est couvert :

1. corriger un nom faux → couvert
2. déclarer un objet hors marché, sans prix → à faire
3. lever une ambiguïté en désignant l'identifiant retenu → à faire

## Ce qui reste à décider

Le recoupement des noms sur bdocodex et garmoth, déjà prévu, devient le chemin
critique du projet et non plus une passe de qualité. La question ouverte est
son ampleur : recouper les quelques centaines d'objets de farm courant suffit
pour un produit utile, recouper les milliers d'objets du jeu n'est pas
raisonnable à la main.

Piste la plus probable : importer la base complète de bdocodex comme source de
noms, et réserver le recoupement manuel aux objets où les sources divergent.
