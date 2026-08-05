# Le banc d'essai, et ce qu'il a mesuré

Ce document dit **ce que le compteur vaut aujourd'hui**, chiffres à l'appui, et
comment ces chiffres ont été obtenus. Il n'a pas d'autre but : sans lui, le
total affiché par le tracker est un nombre dont personne, pas même nous, ne
connaît la justesse.

Le code du banc est dans `src/butin/bench/`, ses tests dans
`tests/test_bench.py`, et il se lance par `scripts/banc_essai.py`.

## 1. Le résultat, en une ligne

> Sur 30 secondes de farm réel, le compteur enregistre **41 drops sur 47**, soit
> une perte de **12,8 %** (**8,5 %** en quantité cumulée), et **71 910 silver
> sur 93 161**, soit **−22,8 %**.

Toujours pas publiable, mais plus pour la même raison : le compteur ne se trompe
plus, il **manque d'images**. Les deux causes qui restent sont en amont de lui.

### Historique des mesures

| Date | Drops | Quantité | Silver | Ce qui a changé |
| --- | --- | --- | --- | --- |
| 05/08, mesure initiale | 12 / 47 | −70,5 % | **+32,5 %** | — |
| 05/08, cause D corrigée | 12 / 47 | −70,5 % | **−25,9 %** | le silver ne compte que les lignes nouvelles |
| 05/08, cause C corrigée | **41 / 47** | **−8,5 %** | −22,8 % | les garde-fous ne jettent plus les lectures valides |

Deux façons de lire ce tableau, et les deux comptent :

* la correction de la cause D **n'améliore pas le total, elle en inverse le
  signe**. Le compteur cesse d'inventer du gain et se contente d'en rater, ce
  qui est le seul comportement acceptable ici ;
* la correction de la cause C fait passer la perte de **74,5 % à 12,8 %**, et
  ramène les images jetées de 9 à **0** et le butin reconnu puis perdu de 21 à
  **1**. C'était bien le plus gros levier du lot.

Les causes restantes sont en partie 4. Aucune n'a jamais été dans la logique
d'anti-double-comptage elle-même.

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

## 4. Pourquoi le compteur perd les trois quarts du butin

Aucune des quatre causes n'est dans l'anti-double-comptage. Elles sont toutes en
amont, et elles se composent.

### A. La reconnaissance coûte 1 100 ms, pas 336

Mesuré sur cette rafale, médiane sur 300 images, moteur préchauffé. Les 336 ms
du 04/08 avaient été mesurées sur une zone de **520 × 385** ; celle-ci fait
**780 × 575**, soit 2,3 fois plus de pixels.

Conséquence directe : la boucle ne peut lire qu'environ **une image sur onze**,
et `LoopConfig.ocr_min_interval_s`, réglé à 0,35 s, promet une cadence que la
machine ne sait pas tenir.

### B. La mesure de défilement en pixels ne détecte rien

Zéro détection sûre sur les 299 transitions. Testé sur quatre bandes, contre les
92 lignes que la référence sait passées :

| Bande mesurée | Détections sûres | Décalage juste à ±3 px |
| --- | --- | --- |
| pastilles de canal, 0 à 90 px | 0 / 20 | **0 / 20** |
| une seule pastille, 10 à 45 px | 0 / 20 | 0 / 20 |
| colonne du texte, 170 à 710 px | 0 / 20 | 9 / 20 |
| zone entière | 0 / 20 | 5 / 20 |

**La colonne des pastilles est la pire des quatre**, et la raison est
structurelle : les pastilles `Système` sont toutes identiques et espacées de
21 px. Un défilement d'exactement une ligne superpose la pastille `n` sur la
pastille `n+1` et ne change donc rien. C'est précisément la colonne qui ne peut
pas voir un défilement d'une ligne.

Les colonnes de texte voient le bon décalage une fois sur deux, mais jamais
assez nettement pour franchir le critère de sûreté : le décor transparent qui
bouge derrière pèse plus lourd que les lettres.

Le chiffre de 3,9 contre 11,3 qui avait fait retenir cette colonne comparait
deux captures de scènes **différentes** : il mesurait le bruit du décor, pas un
défilement.

Cette cause en entraîne une autre, plus coûteuse encore. La boucle ne déclenche
la reconnaissance que si un défilement a été détecté, ou à défaut au bout de son
minuteur de repli de 2 secondes. Sans détection, c'est toujours le repli qui
s'applique : **15 images lues sur 300**, soit une par 2 secondes, là où la seule
contrainte machine en autoriserait 27.

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

## 5. Ce que ça commande pour la suite

Dans cet ordre, et parce que le banc le montre :

1. ~~**Corriger le silver** (cause D).~~ **Fait.** L'erreur est passée de
   +32,5 % à −25,9 %, donc du mauvais côté au bon.
2. ~~**Ne plus jeter les lectures valides** (cause C).~~ **Fait.** La perte est
   passée de 74,5 % à 12,8 %, et les images jetées de 9 à 0.
3. **Trouver une règle de mesure du défilement qui marche** (cause B), ou
   assumer de s'en passer et régler la cadence autrement. Le calibrage de la
   zone, déjà prévu, devra de toute façon trancher où mesurer.
4. **Recaler le budget d'OCR sur la taille réelle de la zone** (cause A).

Les deux qui restent sont la **même** question posée deux fois : la boucle ne
lit que 15 images sur 300. Sans mesure de défilement elle retombe sur son
minuteur de repli de 2 secondes ; avec une reconnaissance à 1 100 ms elle ne
pourrait de toute façon pas dépasser 27 lectures. Ce qui reste de perte n'est
plus un défaut de comptage, c'est un manque d'images.

L'écart sur le silver (−22,8 %) est plus grand que sur les drops (−12,8 %) pour
la même raison : une ligne de silver n'est comptée qu'à sa première apparition,
alors qu'un objet est tranché au vote sur plusieurs lectures. Avec 15 lectures
pour 92 lignes, le vote rattrape ce que la première apparition rate.

Le banc se relance après chaque correction et rend le même rapport : c'est
exactement ce pour quoi il a été écrit.

## 6. Relancer le banc

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
