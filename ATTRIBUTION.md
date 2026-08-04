# Origine et attributions

Butin n'est pas parti d'une page blanche, et ce fichier dit précisément ce qu'il
doit à qui.

## Travail d'origine

**[janhnguyen/BDO-Loot-Tracker](https://github.com/janhnguyen/BDO-Loot-Tracker)**,
sous licence MIT, Copyright (c) 2026 janhnguyen.

Butin en est dérivé. Ce projet a résolu la partie difficile et entièrement
indépendante de la langue d'un tracker de butin : transformer une suite de
captures d'écran en une liste de drops sans jamais compter deux fois le même.
C'est là que se trouve la vraie difficulté, et refaire ce travail à zéro aurait
pris des semaines pour aboutir aux mêmes conclusions.

Les idées et le code repris, adaptés puis réécrits ici :

| Concept repris | Où il vit dans Butin | État |
| --- | --- | --- |
| Confusions de chiffres propres à la police du jeu | `src/butin/catalog/normalize.py` | fait |
| Comparaison tolérante de deux lignes lues | `src/butin/tracking/similarity.py` | fait |
| Alignement de deux captures par suffixe et préfixe | `src/butin/tracking/alignment.py` | fait |
| Garde-fous image aberrante et saut invraisemblable | `src/butin/tracking/alignment.py` | fait |
| Détection du défilement par comparaison de pixels | `src/butin/tracking/scroll.py` | fait |
| Attente de stabilité avant lecture | `src/butin/tracking/stability.py` | fait |
| Validation d'un drop après accord de plusieurs images | `src/butin/tracking/staging.py` | fait |

La colonne « état » est tenue à jour au fur et à mesure du portage. Elle dit ce
qui dérive réellement du travail d'origine à cet instant, pas ce qui est prévu.

### Ce qui a changé en cours de portage

Le portage n'est pas une copie. Les différences de fond :

- **Comparaison par identifiant d'objet et non par nom.** Deux lectures
  abîmées du même objet donnent deux chaînes différentes mais le même
  identifiant. Comparer les chaînes coûte plus cher et se trompe davantage.
- **Le doute sur une quantité est enregistré au moment de la lecture**
  (`quantity_uncertain`) et pèse moins au vote, au lieu d'être oublié.
- **Typage strict** vérifié par mypy sur l'ensemble du paquet.
- **Départage reproductible** à égalité de voix, pour que deux exécutions sur
  la même capture donnent le même résultat.

La licence MIT d'origine est reproduite dans [LICENSE](LICENSE), aux côtés de la
nôtre, conformément à sa clause de conservation de la mention de copyright.

## Ce que Butin apporte

Le travail d'origine cible le client anglais et ne peut pas fonctionner en
français sans une refonte de sa couche de données. Butin apporte :

- une identification des objets par **identifiant numérique** et non par nom,
  seule façon de gérer plusieurs langues ;
- une **normalisation française** (accents, ligature « œ », variantes
  d'apostrophe) sans laquelle des objets entiers sont inatteignables ;
- une **contre-vérification des noms** recoupée sur plusieurs bases publiques ;
- un moteur **OCR sans binaire externe**, là où l'original impose une
  installation manuelle de Tesseract ;
- un **contrôle d'ambiguïté** qui refuse de trancher entre deux objets voisins
  plutôt que d'attribuer un drop au hasard.

## Sources de données

**[andreivreja/veliainn-market-resources](https://github.com/andreivreja/veliainn-market-resources)**
publie chaque jour la base d'objets du jeu, identifiants et noms en quatorze
langues dont le français. C'est ce jeu de données qui rend un tracker français
possible sans traduire plusieurs milliers de noms à la main.

Les noms sont ensuite recoupés à la main contre **[bdocodex](https://bdocodex.com/fr/)**
et **[garmoth](https://garmoth.com/)** comme références, d'autres bases publiques
servant à confirmer en cas de divergence. Voir
[data/noms-verifies.json](data/noms-verifies.json).

Les prix proviennent de l'API publique du marché central.

## Marque et éditeur

Black Desert Online est une marque de Pearl Abyss. Butin est un outil
indépendant, sans lien ni approbation de Pearl Abyss.
