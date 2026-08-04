# Le journal d'acquisition du client français

Relevé le 04/08/2026 sur de **vraies captures** du client français, en
2560 × 1440, fenêtré. Tout ce qui suit est observé, pas supposé. Chaque piège
listé ici a été vu sur une image réelle, et pas un n'aurait été deviné.

## Où il vit

Le journal d'acquisition n'est **pas une fenêtre séparée**. C'est le canal
`Système` de la fenêtre de chat, en bas à gauche par défaut. Conséquence
directe : les lignes de butin sont **entrelacées avec la conversation des
joueurs**, et il faut les trier.

Le fond est **transparent sur le monde du jeu**. Ce n'est pas un aplat sombre
sur lequel l'OCR aurait la vie facile : le texte se lit par-dessus de l'herbe,
de la pierre, un cheval qui bouge. C'est la difficulté principale du
prétraitement d'image, et c'est aussi pourquoi la stabilité entre deux images
compte autant.

## Format d'une ligne

```
Système   Vous avez obtenu : ⬦[Humus noir] x3 (20:13)
Système   Vous avez obtenu : ⬦[Anneau de Tuvala]. (20:20)
Système   Vous avez obtenu : ⬦[Pièces] x10,000,000 (21:56)
Général   [Maxyy] : gz on officer xD (21:38)
```

De gauche à droite : une pastille de canal sur fond sombre, la formule
d'annonce, une petite icône de l'objet, le nom entre crochets, éventuellement
une quantité, et l'heure entre parenthèses.

## Les pièges, dans l'ordre de ce qu'ils coûtent

### 1. Quantité 1 : pas de « x », mais un point

C'est le piège le plus coûteux, parce qu'il est silencieux.

| Ce qui est écrit | Quantité réelle |
| --- | --- |
| `[Anneau de Tuvala].` | **1** |
| `[Pierre noire] x3` | 3 |

Une quantité de 1 ne s'écrit **jamais** `x1`. Elle s'écrit par l'absence de
quantité, et la ligne se termine alors par un **point** collé au crochet
fermant. Un analyseur qui cherche `x(\d+)` et se rabat sur 1 quand il ne trouve
rien tombe juste ici par accident, mais pour la mauvaise raison, et il tombera
faux ailleurs.

### 2. Les milliers sont séparés par des virgules

`[Pièces] x10,000,000`

Une expression régulière sur `x(\d+)` s'arrête à `10` et compte dix pièces au
lieu de dix millions. Il faut consommer les virgules avant de convertir.

### 3. L'heure entre parenthèses termine chaque ligne

`(20:13)`, `(21:56)`. Elle ne fait partie ni du nom ni de la quantité. Elle
contient des chiffres et des deux-points, donc elle est exactement le genre de
chose qu'un analyseur trop permissif avale comme une quantité.

Elle est aussi utile : elle donne l'heure du drop à la minute, ce qui permettra
plus tard de recouper une session sans faire confiance à notre propre horloge.

### 4. Un nom d'objet peut contenir des crochets

`[[Serendia] Boîte de tenue de Cleia]`

Observé tel quel. Les objets liés à un événement ou à une région portent une
étiquette entre crochets **à l'intérieur** de leur propre nom. Chercher le
premier `]` rencontré donne « [Serendia » et rate l'objet pour toujours.

Il faut apparier le crochet ouvrant avec le **dernier** crochet fermant utile,
ou compter la profondeur.

### 5. Toutes les lignes `Système` ne sont pas du butin

`[ Edmund ] (21:44)`

Ligne système sans formule d'annonce. Il faut **ancrer sur « Vous avez obtenu »**
et rejeter le reste, plutôt que de supposer que tout ce qui est système et
contient des crochets est un drop.

### 6. La conversation des joueurs est mélangée

`Général  [Maxyy] : gz on officer xD (21:38)`

Un message de chat contient des crochets (le pseudo), un deux-points, une heure
entre parenthèses, et parfois un « x » suivi de lettres. Il ressemble
structurellement à une ligne de butin. Seuls la pastille de canal et l'ancrage
sur la formule les distinguent.

Cette ligne précise contient « xD », qui est un piège parfait pour un analyseur
de quantité laxiste.

### 7. `[Pièces]` n'est pas un objet du marché

`Vous avez obtenu : [Pièces] x10,000,000`

C'est du silver directement, pas un objet à revendre. Il doit alimenter le total
sans jamais passer par une recherche de prix au marché central, sous peine de
compter zéro ou, pire, le prix d'un objet homonyme.

### 8. Une icône se glisse entre le deux-points et le crochet

Une vignette de l'objet, quelques pixels. L'OCR la rend en glyphes parasites.
Tout ce qui se trouve entre `:` et le premier `[` doit être jeté.

### 9. Typographie française

« obtenu **:** » avec une espace **avant** le deux-points. Une expression
régulière écrite d'après l'anglais (`obtenu:`) ne correspond à rien.

Les apostrophes des noms (`Boucle d'oreille`) sont déjà gérées par
`catalog/normalize.py`.

## Géométrie mesurée

Mesuré sur la capture réelle, pas estimé : détection des pastilles de canal par
seuillage, puis écart médian entre leurs centres.

| Grandeur | Valeur en 2560 × 1440 |
| --- | --- |
| Pas vertical entre deux lignes | **21 px** |
| Hauteur de la pastille de canal | 16 px |
| Lignes visibles simultanément | une vingtaine |

Le pas vertical est la grandeur qui alimente `expected_new_lines`
(`tracking/scroll.py`) : c'est elle qui convertit un défilement en pixels en
nombre de lignes. Elle dépend de la résolution et de l'échelle de l'interface,
donc elle doit être **mesurée au calibrage**, jamais codée en dur. Les 21 px
ci-dessus servent de valeur de départ plausible et de test de non-régression.

## Ce que l'OCR fait de tout ça, mesuré

Relevé le 04/08/2026 sur trois captures réelles avec des fonds différents.

**Le crochet fermant est lu « l ».** `[Boucle d'oreille de Tuvalal.` Cas
observé, pas théorique : il coûtait 2 des 6 gains ratés, sur deux fonds sur
trois. Une recherche stricte du `]` rejetait la ligne, donc perdait le drop
**en silence**. `lines.py` accepte désormais un glyphe confondable en repli,
mais uniquement s'il est suivi de la fin de ligne, d'un point ou d'une
quantité, sans quoi le premier « l » du nom serait pris pour le crochet.

**Le modèle perd les accents.** « Systeme », « Pieces », « Boite ». Sans
conséquence : `catalog/normalize.py` les retire des deux côtés de la
comparaison de toute façon. C'est précisément pour ça que le repliage existe.

**Le pas vertical mesuré sur les rangées rendues par l'OCR est de 21,5 px**,
contre 21 px mesuré directement sur les pixels. L'écart valide la remise à
l'échelle des coordonnées après agrandissement.

## Couleur du nom selon la rareté

Observé : blanc, vert, bleu, jaune ou orange, rouge ou violet. La couleur porte
la rareté et pourrait aider à isoler le nom du fond. Piste non exploitée pour
l'instant, notée ici pour ne pas la redécouvrir.

## Ce qui reste à relever

Aucune capture disponible ne montre encore :

- une **session de farm dense**, où plusieurs objets identiques tombent
  d'affilée. C'est le cas du mur de lignes identiques que
  `tracking/alignment.py` ne peut trancher qu'avec la mesure de défilement.
- le comportement quand le chat est **replié ou masqué**.
- une autre résolution que 2560 × 1440, pour vérifier que le pas vertical suit
  bien l'échelle de l'interface.
