# Le banc d'essai, et ce qu'il a mesuré

Ce document dit **ce que le compteur vaut aujourd'hui**, chiffres à l'appui, et
comment ces chiffres ont été obtenus. Il n'a pas d'autre but : sans lui, le
total affiché par le tracker est un nombre dont personne, pas même nous, ne
connaît la justesse.

Le code du banc est dans `src/butin/bench/`, ses tests dans
`tests/test_bench.py`, et il se lance par `scripts/banc_essai.py`.

## 1. Le résultat, en une ligne

> Sur 30 secondes de farm réel, le compteur enregistre **47 drops sur 47**, une
> **quantité cumulée exacte** (129 sur 129), **45 lignes de silver sur 45**, et
> un montant de silver à **−1,5 %**.

⚠️ **Ce que ce chiffre ne dit pas.** Il est mesuré sur **une seule rafale de
30 secondes**, à un seul endroit de farm, sur une seule configuration d'écran.
Il dit que le compteur est juste sur ces 300 images ; il ne dit pas qu'il l'est
partout. Les réglages ayant été balayés contre cette même rafale, le risque de
surajustement est réel et traité en partie 6.

### Historique des mesures

| Date | Drops | Quantité | Silver | Ce qui a changé |
| --- | --- | --- | --- | --- |
| 05/08, mesure initiale | 12 / 47 | −70,5 % | **+32,5 %** | — |
| 05/08, cause D corrigée | 12 / 47 | −70,5 % | −25,9 % | le silver ne compte que les lignes nouvelles |
| 05/08, cause C corrigée | 41 / 47 | −8,5 % | −22,8 % | les garde-fous ne jettent plus les lectures valides |
| 05/08, cause B corrigée | 46 / 47 | −1,6 % | −24,1 % | la mesure de défilement fonctionne enfin |
| 05/08, cause E corrigée | 46 / 47 | −1,6 % | +0,4 % | le silver passe par le vote multi-images |
| 05/08, seuil recalé | **47 / 47** | **+0,0 %** | **−1,5 %** | valider après 2 observations et non 3 |

Quatre choses se lisent dans ce tableau, et les quatre comptent :

* la cause D **n'améliore pas le total, elle en inverse le signe**. Le compteur
  cesse d'inventer du gain et se contente d'en rater, ce qui est le seul
  comportement acceptable ici ;
* la cause C fait passer la perte de **74,5 % à 12,8 %** et les images jetées de
  9 à 0. C'était le plus gros levier du lot ;
* la cause B la ramène à **2,1 %** et donne au banc sa troisième mesure
  indépendante, muette jusque-là ;
* la cause E ne touche pas aux objets et **corrige le silver à elle seule**, ce
  qui montre que les deux se comptaient par des chemins différents alors qu'ils
  n'auraient jamais dû.

Aucune de ces causes n'a jamais été dans la logique d'anti-double-comptage
elle-même.

## 2. Les données

300 images dans `D:\DEV\bdo\echantillons\`, préfixe `_farm-20260805-014459`,
hors dépôt et volontairement : une capture de Black Desert contient le chat de
guilde, donc des pseudonymes de tiers.

| | |
| --- | --- |
| images | 300 |
| pas | 100 ms, soit 30 s de jeu |
| zone | 780 × 575 px, pixels natifs, sans redimensionnement |
| contenu | fin de pack, journal qui défile en continu |
| lignes visibles | 24 |
| lignes passées | 92 |

Le journal alterne une ligne de silver et une ligne d'objet, toutes portant la
même heure `(01:45)` : un pack entier meurt dans la même minute.

## 3. Comment on sait que la mesure est juste

C'est la partie qui a déjà échoué une fois. Le 05/08/2026, un script jetable
prenait **« les lignes distinctes vues » pour la vérité terrain** et annonçait
un écart de 2 800 %. C'était faux : deux drops identiques à quelques secondes
d'écart sont deux lignes du journal et un seul texte distinct, donc la référence
sous-comptait pendant que le compteur additionnait. Le résultat était
visiblement cassé ; il aurait pu ne pas l'être.

La règle qui en découle : **aucun nombre ne sert de vérité aux autres.** Le banc
en produit plusieurs, par des chemins qui ne partagent rien, et c'est leur
accord qui vaut preuve.

| Nombre | Comment | Ce qu'il ignore |
| --- | --- | --- |
| le compteur | la vraie boucle, rejouée | rien |
| la référence | recalage du texte sur les 300 images | pixels, score flou, garde-fous |
| l'empreinte | montants de silver distincts | toute notion de position |
| le défilement | pixels du journal | le texte |

**Résultat de la corroboration :** 45 lignes de silver par recalage contre 48
par empreinte, soit **−6,2 %**, avec 0,1 collision de montant attendue et 53
lectures par empreinte en médiane. L'écart s'explique entièrement par la
première image, où le lecteur n'a retrouvé que 10 des 12 lignes de silver
visibles : un montant raté sur cette image-là n'entre pas dans le passé et se
retrouve compté comme nouveau.

Deux méthodes qui ne partagent que le découpage d'une ligne, et qui tombent à
6 % l'une de l'autre sur un nombre qu'aucune des deux ne pouvait deviner : c'est
ce qui rend la référence utilisable.

### Ce que la référence sait faire, et ce qu'elle ne sait pas

Elle relit **toutes** les images, là où la boucle n'en lit qu'une fraction, et
tranche chaque position au vote sur des dizaines de lectures. C'est ce qui lui
permet de travailler à l'**égalité exacte**, sans score flou, sans prédiction en
pixels et sans garde-fou.

Deux limites, mesurées et non corrigées :

* **le texte périodique la met en défaut.** Dix lignes identiques d'affilée
  rendent plusieurs placements également valides et elle retient le plus sobre,
  donc sous-compte. Ce cas ne se produit pas ici (0 % de lignes voisines
  identiques), et il est figé dans un test pour qu'il ne surprenne personne ;
* **une image dont aucune ligne ne se recale** est signalée et n'ajoute rien,
  plutôt que corrigée. Sur cette rafale : zéro image dans ce cas.

### Deux réglages qu'il a fallu mesurer pour trouver

Ils sont notés ici parce que les deux premières versions du banc étaient fausses
à cause d'eux, et qu'aucun raisonnement ne les aurait donnés.

**L'égalité porte sur le texte sans ses espaces.** Deux lectures d'une même
ligne physique à 100 ms d'intervalle sont identiques au caractère près dans
**31 %** des cas, et dans **70 %** une fois les espaces retirés. La différence
est du découpage : rapidocr rend « obtenu : » ou « obtenu: », « Vous avez » ou
« Vousavez », selon la façon dont il a groupé ses fragments. L'espacement vient
du lecteur, pas du jeu. Avec l'égalité sur le texte brut, le recalage échouait
sur **268 images sur 300** et la référence annonçait 6 081 lignes au lieu de 92.

**Le recalage compte les accords, il ne soustrait pas les désaccords.** Noter
« accords moins désaccords » paraissait plus prudent et était faux : **13 images
sur 300** ont un contenu strictement inchangé et assez de bruit de glyphe
(« duclair », « （01:45) ») pour que les désaccords l'emportent. Le bon placement
tombait sous zéro, le placement sans aucun recouvrement gagnait avec zéro, et la
référence déclarait une fenêtre entière de lignes nouvelles. À elles seules, ces
13 images ajoutaient **312 lignes fantômes sur 374**.

## 4. Les six causes, et ce que chacune coûtait

Aucune des quatre causes n'est dans l'anti-double-comptage. Elles sont toutes en
amont, et elles se composent.

### A. La reconnaissance coûte 1 100 ms, pas 336

Mesuré sur cette rafale, médiane sur 300 images, moteur préchauffé. Les 336 ms
du 04/08 avaient été mesurées sur une zone de **520 × 385** ; celle-ci fait
**780 × 575**, soit 2,3 fois plus de pixels.

Conséquence directe : la boucle ne peut lire qu'environ **une image sur onze**,
et `LoopConfig.ocr_min_interval_s`, réglé à 0,35 s, promet une cadence que la
machine ne sait pas tenir.

### B. La mesure de défilement en pixels ne détectait rien — CORRIGÉ

Zéro détection sûre sur les 299 transitions, et zéro décalage juste sur les 37
transitions où une ligne est réellement apparue.

**La colonne des pastilles était la pire des bandes essayées**, et la raison est
structurelle : les pastilles `Système` sont toutes identiques et espacées
d'exactement un pas de ligne. Un défilement d'une ligne superpose la pastille
`n` sur la pastille `n+1` et ne change donc rien. C'est précisément la colonne
aveugle à ce qu'on lui demandait de voir. Le chiffre de 3,9 contre 11,3 qui
l'avait fait retenir comparait deux captures de scènes **différentes** : il
mesurait le bruit du décor, pas un défilement.

Cette cause en entraînait une autre, plus coûteuse encore. La boucle ne
déclenche la reconnaissance que si un défilement a été détecté, ou à défaut au
bout de son minuteur de repli de 2 secondes. Sans détection, c'était toujours le
repli : **15 images lues sur 300**.

**Ce qui marche.** Deux changements, et le second est celui qui compte.

*La bande.* La colonne du **texte** au lieu de celle des pastilles, parce que
deux lignes du journal ne portent jamais les mêmes lettres aux mêmes endroits.

*La comparaison.* Un **masque de pixels clairs** au lieu des niveaux de gris.
Le texte du journal est peint en clair, le monde du jeu est sombre : sur ces
captures, la médiane de la zone est à **21 sur 255**. En niveaux de gris, le
décor occupe toute la surface et pèse donc plus lourd que les lettres ; le
masque le fait disparaître, et il ne reste que ce qui défile.

| Mesure | Décalages justes | Fausses détections |
| --- | --- | --- |
| gris, colonne des pastilles | **0 / 37** | 0 / 262 |
| gris, colonne du texte | 17 / 37 | 0 / 262 |
| **masque clair, colonne du texte** | **32 / 37** | **0 / 262** |

Sur les 5 transitions qu'elle rate, la nouvelle mesure rend **0 et non un
mauvais décalage** : juste ou muette, jamais trompeuse. C'est la propriété qui
compte, parce qu'une prédiction fausse ferait recompter du butin alors qu'une
absence de prédiction fait seulement retomber sur le texte seul.

**Deux critères de sûreté, tous deux nécessaires**, et le second a été ajouté
après qu'un test l'a mis en défaut :

* le décalage doit expliquer une **part** du désaccord restant. Mesuré : les 32
  décalages justes expliquent 0,030 au minimum, les 262 transitions sans
  défilement 0, et une image de bruit uniforme 0,006. Le seuil est à 0,02 ;
* le recouvrement obtenu doit atteindre un **plancher absolu**. Sans lui, deux
  contenus sans aucun rapport passaient : sur des pixels étrangers l'un à
  l'autre, il existe toujours un décalage qui gagne un peu par hasard. Mesuré :
  les décalages justes atteignent 0,433 au minimum, deux contenus sans rapport
  plafonnent vers 0,1. Le seuil est à 0,30.

**Et le pas vertical n'est pas 21 px, il est 21,6.** Les décalages réellement
observés sont 22, 43, 65, 86 et 108 px pour une à cinq lignes, parfaitement
linéaires. La valeur de 21 relevée à l'œil sur les pastilles était basse de 3 %.

**Après correction :** 22 images lues au lieu de 15, et le banc gagne sa
troisième mesure indépendante. Elle compte **70 lignes** passées là où le
recalage du texte en compte 92 : l'écart tient aux 5 transitions manquées, qui
sont justement les plus grosses.

### C. Huit des quinze lectures étaient jetées — CORRIGÉ

Sur les 15 images lues, **8 étaient écartées** par le garde-fou « image
aberrante : recouvrement perdu d'un coup », et une neuvième par « saut
invraisemblable ». Il ne restait que **6 lectures utiles sur 300 images**.

Deux défauts distincts, tous deux des garde-fous qui se déclenchaient sur du
travail correct.

**`_overlap_score` exigeait que toutes les paires passent le seuil.** Il
renvoyait `None` dès qu'**une seule** paire de lignes tombait dessous. Entre
deux lectures espacées de 2 secondes, le recouvrement porte sur une vingtaine de
lignes ; il suffisait que l'OCR en abîme une pour qu'aucun recouvrement ne soit
jugé valide. L'appelant concluait que rien ne se recouvrait, et `is_glitch_frame`
faisait alors exactement son travail sur une alerte qui n'aurait pas dû être
levée.

Le seuil de remplacement n'est pas posé au jugé. En comparant chaque lecture au
recouvrement que la référence sait exact :

| Recouvrement | Part des paires qui s'accordent |
| --- | --- |
| le vrai | **74 % à 100 %** |
| le meilleur des faux | **50 % au plus** |

`MatchConfig.overlap_accept` vaut donc **0,60**, à 14 points de chacune des deux
bornes. Les mauvais scores du vrai recouvrement valent tous autour de 0,47,
c'est-à-dire exactement le plafond appliqué à une ligne dont l'objet n'a pas été
reconnu : ce sont des ratés de lecture isolés, pas un désaccord de fond.

**Le plafond de vraisemblance supposait une cadence que la boucle n'a pas.**
`PLAUSIBLE_MAX_NEW` valait 10, justifié par « le journal ne défile pas de dix
lignes en un dixième de seconde ». C'est vrai de la cadence de **capture**, pas
de celle de **lecture** : la reconnaissance ne tourne qu'une fois par seconde au
mieux, et une fois toutes les deux secondes quand rien ne déclenche de lecture
anticipée. Sur cette rafale, les lectures portent jusqu'à **14 lignes réellement
nouvelles**, et celle-là était rejetée. Le plafond suit maintenant le temps
réellement écoulé, avec un plancher qui garantit qu'il ne devient jamais plus
sévère qu'avant.

**Après correction :** 15 lectures, **0 écartée**, et le butin reconnu puis
perdu passe de 21 à **1**. Les drops comptés passent de 12 à **41 sur 47**.

### D. Le silver était compté sur toute la fenêtre à chaque lecture — CORRIGÉ

`CaptureLoop._read` faisait `self.total_silver += sum(ligne.silver for ligne in
parsed)`, où `parsed` est la fenêtre **entière**, pas les lignes nouvelles. Une
ligne de silver reste affichée une dizaine de secondes, donc se retrouvait dans
toutes les lectures de cet intervalle et était additionnée autant de fois.

Mesuré : 123 409 comptés contre 93 161 réels, soit **+32,5 %**. Et encore, avec
6 lectures utiles seulement ; à cadence normale l'erreur aurait été bien plus
grosse. C'était le seul défaut du lot qui fasse **inventer** du gain plutôt
qu'en rater, donc le plus grave au regard du principe qui tranche tous les
arbitrages du projet.

**Corrigé** : le silver suit maintenant le même découpage `result.overlap:` que
les objets, donc il ne peut plus s'en désynchroniser. Après correction, le banc
rend **68 996 contre 93 161, soit −25,9 %**. Le reste de l'écart n'est plus
imputable au silver : c'est la même perte que sur les objets, causes B et C.

Deux tests de régression le figent dans `tests/test_loop.py`, tous deux vérifiés
en échec sans le correctif.

### E. Le silver ne passait pas par le vote multi-images — CORRIGÉ

Trouvé en cherchant pourquoi l'écart sur le silver restait à −24,1 % quand celui
sur les objets était tombé à −2,1 %.

Un objet est tranché au **vote sur toutes les lectures** de sa ligne, par
`tracking/staging.py`. Le silver, lui, est lu une fois : à la première
apparition de la ligne, et jamais revu. Or le montant est un nombre à quatre
chiffres que l'OCR rate souvent.

Mesuré sur la rafale : **13,6 % des lectures de lignes de silver ont un montant
illisible** (470 sur 3 456). Le découpage rend alors la quantité 1 avec un
doute, ce qui est le bon choix pour un objet mais coûte environ deux mille
silver pour une ligne de pièces. La référence, qui tranche chaque position au
vote sur des dizaines de lectures, n'a le même problème que sur **4 lignes sur
45**.

Le sens de l'erreur restait le bon : on sous-comptait. Mais c'était une perte
évitable, et de la même forme que les précédentes : un mécanisme existant qui
n'est pas branché là où il faudrait.

**Corrigé** : une ligne de silver occupe désormais un emplacement de suivi comme
n'importe quelle autre, et son montant est tranché au **même vote pondéré** que
la quantité d'un objet. Les lectures dont le marqueur était illisible pèsent
0,4 contre 1, donc elles attestent la présence de la ligne sans pouvoir décider
du montant.

**Cette correction a forcé le banc à s'améliorer**, et c'est intéressant. Le
compteur est passé de −24,1 % à **+5,8 %** contre le recalage du texte, ce qui
semblait le faire sur-compter. En réalité le recalage rend 4 de ses 45 lignes
avec un montant illisible, donc comptées 1 au lieu de deux mille : c'est **lui**
qui était 5 % trop bas.

Il a fallu une mesure capable d'arbitrer, et les empreintes de montants la
donnent : en ne retenant que les montants vus au moins trois fois, elles rendent
**98 157** silver. Le compteur en rendait 98 565, soit **+0,4 %**. La leçon vaut
d'être retenue : sur le nombre de lignes le recalage fait autorité, sur les
montants il ne vaut pas mieux que le compteur, et comparer deux mesures de même
qualité n'apprend rien.

### F. Le seuil de validation était trop haut d'une unité

Une fois les quatre causes traitées, il restait un drop manquant sur 47 et
1,6 % de quantité. Un balayage des réglages de la boucle contre le banc a montré
qu'un seul d'entre eux bouge le résultat : `min_sightings`, le nombre
d'observations concordantes exigées avant de valider une ligne.

Drops comptés sur 47 et écart sur la quantité cumulée, à quatre cadences de
lecture :

| seuil | OCR 0,7 s | OCR 1,1 s | OCR 1,5 s | OCR 2,2 s |
| --- | --- | --- | --- | --- |
| 1 | 44, −14,7 % | 47, −13,2 % | 47, −6,2 % | 44, −3,1 % |
| **2** | **43, −5,4 %** | **47, +0,0 %** | **47, −0,8 %** | **43, −3,9 %** |
| 3 | 43, −5,4 % | 46, −1,6 % | 43, −7,0 % | 35, −15,5 % |
| 4 | 43, −5,4 % | 41, −9,3 % | 40, −10,1 % | 20, −57,4 % |

Deux effets contraires se lisent dans ce tableau. Attendre **une** observation
de plus protège des ratés de lecture : à 1, tous les drops sont trouvés mais
leurs quantités sont fausses de 13 %, faute de vote. Attendre **davantage** fait
sortir la ligne de l'écran avant qu'elle n'atteigne le seuil, et c'est une perte
sèche.

2 est le meilleur des quatre valeurs à **chacune** des quatre cadences, ce qui
en fait un choix mesuré et non un point de chance. Il a aussi le bon sens
d'erreur : il sous-compte le silver là où 3 le sur-compte.

## 5. Ce que ça commande pour la suite

1. ~~**Corriger le silver** (cause D).~~ **Fait.** De +32,5 % à −25,9 %, donc du
   mauvais côté au bon.
2. ~~**Ne plus jeter les lectures valides** (cause C).~~ **Fait.** De −74,5 % à
   −12,8 %, images jetées de 9 à 0.
3. ~~**Trouver une règle de mesure du défilement qui marche** (cause B).~~
   **Fait.** De −12,8 % à −2,1 %, et le banc gagne sa troisième mesure.
4. ~~**Faire passer le silver par le vote multi-images** (cause E).~~ **Fait.**
   De −24,1 % à −1,5 % sur le montant.
5. ~~**Recaler le seuil de validation** (cause F).~~ **Fait.** 47 drops sur 47.
6. **Recaler le budget d'OCR sur la taille réelle de la zone** (cause A). Non
   bloquant : la boucle lit assez d'images pour ne rien perdre sur cette rafale.

Reste le **calibrage de la zone**, qui n'est pas une cause du banc mais la
condition pour qu'un utilisateur autre que nous puisse s'en servir.

## 6. Ce qu'on n'a pas le droit d'annoncer

Le banc dit que le compteur est juste **sur cette rafale**. Trois réserves, à
lever avant d'écrire « ce compteur est juste » quelque part de public.

**Une seule rafale.** 30 secondes, un seul endroit de farm, deux objets, une
seule configuration d'écran. Le journal y alterne silver et objet, toutes les
lignes portant la même minute, et il n'y contient **aucune conversation de
joueurs** alors que le canal `Système` est normalement entrelacé avec elle.

**Les réglages ont été balayés contre cette même rafale.** C'est du
surajustement en puissance. Deux garde-fous ont été appliqués, et ils ne
suppriment pas le risque, ils le réduisent :

* un réglage n'a été retenu que s'il a un **mécanisme explicable**, pas
  seulement un meilleur chiffre. Le seul modifié, `min_sightings`, l'a été sur
  un compromis déjà écrit noir sur blanc avant la mesure ;
* il devait **dominer à quatre cadences de lecture différentes**, pas seulement
  à celle de la machine du jour. Les réglages qui bougeaient de façon
  non monotone, comme `ocr_max_idle_s`, ont été laissés tels quels précisément
  pour ça.

Trois réglages se sont révélés être sur un **plateau** et non sur une crête, ce
qui est rassurant : la part de paires qui doivent s'accorder donne le même
résultat de 0,40 à 0,70, le seuil de clarté de 90 à 150, et le pas vertical de
21,0 à 21,9.

**La géométrie est relevée sur un seul écran.** Les bandes de mesure, en
fraction de la largeur, et le pas vertical de 21,6 px viennent d'un 2560 × 1440
avec une échelle d'interface donnée. Rien ne garantit qu'ils tiennent ailleurs,
et c'est exactement ce que le calibrage de la zone doit résoudre.

Ce qu'on peut dire aujourd'hui, et rien de plus : **sur 30 secondes de farm réel
mesurées de trois façons indépendantes, le compteur n'a raté aucun drop et
n'en a inventé aucun.**

## 7. Relancer le banc

```
python -X utf8 scripts/banc_essai.py
```

La première exécution reconnaît les 300 images, ce qui prend quelques minutes,
et écrit une **transcription** à côté d'elles. Les suivantes la relisent et
rendent le rapport en quelques secondes.

⚠️ La transcription reste hors dépôt pour la même raison que les images : le
journal d'acquisition est le canal `Système` du chat, donc entrelacé avec la
conversation des joueurs. Les tests du banc n'en utilisent aucune, ils
fabriquent leurs propres rafales avec une vérité connue d'avance.
