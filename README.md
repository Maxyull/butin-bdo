# Butin

[![CI](https://img.shields.io/github/actions/workflow/status/Maxyull/butin-bdo/ci.yml?branch=main&label=CI&logo=github)](https://github.com/Maxyull/butin-bdo/actions/workflows/ci.yml)
[![Dernière version](https://img.shields.io/github/v/release/Maxyull/butin-bdo?label=version&color=d4a955)](https://github.com/Maxyull/butin-bdo/releases/latest)
[![Licence MIT](https://img.shields.io/badge/licence-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue?logo=python&logoColor=white)](pyproject.toml)
[![Discord](https://img.shields.io/badge/Discord-Communaut%C3%A9-5865F2?logo=discord&logoColor=white)](https://discord.gg/qCuvN2Zna7)

**Le suivi de butin pour Black Desert Online, enfin en français.**

Butin lit le journal d'acquisition pendant que vous farmez, reconnaît chaque
objet qui tombe, et vous dit ce que votre session a réellement rapporté en
silver par heure.

Les outils équivalents existent déjà. Aucun ne parle français. Butin est écrit
pour le client français dès la première ligne, pas traduit après coup.

> ⚠️ **Projet en version `0.y.z`** au sens de [Semantic
> Versioning](https://semver.org/) : rien n'est encore promis stable d'une
> version à l'autre, y compris le format de la base de sessions. Voir
> [État d'avancement](#état-davancement) pour ce qui marche aujourd'hui, et
> [Versions](#versions) pour ce que ça engage. Un installeur Windows est
> téléchargeable sur la [page des
> Releases](https://github.com/Maxyull/butin-bdo/releases/latest).

Une question, un bug, une idée : [le Discord](https://discord.gg/qCuvN2Zna7).

---

## Pourquoi ce projet existe

Si vous farmez sur le client français, les trackers existants vous laissent
deux options, toutes les deux mauvaises :

1. **Passer votre client en anglais.** Vous perdez la langue dans laquelle vous
   jouez, pour un outil censé vous aider.
2. **Tout saisir à la main.** À la fin d'une session de deux heures, personne ne
   le fait, et les chiffres qu'on ne mesure pas ne servent à rien.

Butin supprime le choix.

## Ce qui rend le français réellement difficile

Ce n'est pas une question de traduire des libellés d'interface. Trois problèmes
techniques rendent un tracker anglais inutilisable en français, et chacun est
traité dans le code.

**Les accents.** L'OCR rend « Épée longue de Kzarka » tantôt avec accent, tantôt
sans, tantôt avec le mauvais. Comparer les chaînes telles quelles fait rater des
correspondances évidentes.

**La ligature « œ ».** Unicode considère « œ » comme une lettre à part entière,
que la décomposition standard ne déplie pas. Sans traitement explicite, des
objets réels et courants comme **Nœud d'arbre ensanglanté** ou **Cœur transmuté
de Garmoth** sont *structurellement impossibles* à reconnaître, quel que soit le
réglage de l'OCR.

**Les noms qui ne diffèrent que par un mot.** « Éclat de cristal noir
**tranchant** » et « Éclat de cristal noir **dur** » sont deux objets distincts,
tous deux du loot courant, dont les prix n'ont rien à voir. Une lecture abîmée
de l'un ne doit jamais être comptée comme l'autre. Butin préfère refuser la
ligne plutôt que deviner.

## Principe de conception

> **Rater un drop donne un chiffre un peu bas. Inventer un drop donne un chiffre
> faux.** Les deux erreurs ne coûtent pas la même chose, donc les réglages ne
> sont pas symétriques.

Un chiffre légèrement sous-estimé reste exploitable. Un chiffre faux vous fait
changer de spot pour de mauvaises raisons, et rien dans l'interface ne vous
permet de vous en rendre compte. Partout où il y a un doute, Butin ne compte
pas.

C'est aussi pour cela que les noms d'objets sont **recoupés sur plusieurs bases
publiques** ([bdocodex](https://bdocodex.com/fr/) et
[garmoth](https://garmoth.com/) en référence, d'autres en confirmation) plutôt
que repris d'une source unique : un nom faux dans le catalogue rend un objet
définitivement invisible, sans le moindre message d'erreur.

## Est-ce autorisé ?

Butin **lit des pixels à l'écran**. Il ne lit jamais la mémoire du jeu,
n'injecte rien, ne modifie aucun fichier du client, n'automatise aucune action
et n'envoie aucune touche au jeu. C'est la même approche que les autres
trackers de butin utilisés par la communauté depuis des années.

Cela dit, personne ne peut vous garantir la position de Pearl Abyss à votre
place. Vous utilisez cet outil sous votre responsabilité.

## Vie privée

Butin ne collecte rien. Pas de compte, pas de télémétrie, pas de serveur.

Tout reste sur votre machine : la base de sessions dans votre dossier
utilisateur, le catalogue d'objets en cache. Les deux seules connexions sortantes
sont le téléchargement du catalogue d'objets et la consultation des prix du
marché central, toutes deux vers des sources publiques, toutes deux sans aucune
donnée vous concernant.

## Installation

Rien à installer manuellement à part Python : le moteur OCR arrive par `pip`.
C'est un choix délibéré, les trackers existants imposent d'installer Tesseract
à part et de régler le `PATH` à la main.

```bash
git clone https://github.com/Maxyull/butin-bdo
cd butin-bdo
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
```

## Utilisation

**Lancez `butin-app`.** Une fenêtre s'ouvre, et tout s'y fait. Pas d'adresse à
taper, pas de navigateur, pas de terminal.

### La fenêtre principale : réglages et historique

Deux onglets.

**Réglages** contient le dossier où sont enregistrées vos sessions, le calibrage
de la zone de chat, et le bouton qui lance le grind.

**Historique** liste vos sessions passées : durée, nombre d'objets, silver par
heure et total net, avec le détail du butin en cliquant sur une ligne.

### Le panneau en surimpression : pendant le grind

**Commencer le grind** vous laisse cinq secondes pour basculer dans le jeu, puis
pose un **panneau translucide par-dessus** : silver par heure, total net, durée,
et **chaque drop au moment où il tombe**, avec sa quantité, sa valeur et son nom
coloré selon la rareté du jeu.

Sans cadre, toujours au-dessus, déplaçable par sa barre de titre. C'est le seul
écran que vous regardez en farmant — la fenêtre principale est derrière le jeu.

Le bouton **Arrêter** du panneau referme la session et le panneau avec elle.

### Où sont vos sessions

Dans **Documents\BDO Butin** par défaut. Ce sont vos données : vous voudrez
les sauvegarder ou les retrouver, pas les chercher dans `%LOCALAPPDATA%`.

⚠️ Le dossier s'appelait **BDO Tracker** avant la version 0.10.0. Il est
renommé automatiquement au premier lancement, sans rien perdre. Si le
renommage échoue — dossier ouvert dans l'explorateur, antivirus — Butin
continue d'utiliser l'ancien nom plutôt que de vous montrer un historique vide.

Le dossier est affiché dans les réglages et se change. ⚠️ Le changement ne
déplace rien et prend effet **au prochain lancement** : la base de sessions est
ouverte à cet instant, et déplacer un fichier de base ouvert est le meilleur
moyen de le perdre.

### Le premier lancement

Ouvrez **Réglages**, choisissez le dossier si celui par défaut ne vous va pas,
puis **Calibrer la zone** avec le jeu devant vous et le journal d'acquisition
visible. La fenêtre affiche les lignes qu'elle a lues : vérifiez que c'est bien
votre chat avant de commencer.

### Pour diagnostiquer

Une ligne de commande existe à côté, et ne sert qu'à ça :

| Commande | Rôle |
| --- | --- |
| `butin` | ouvre la même fenêtre, mais avec un terminal derrière |
| `butin catalogue` | état du catalogue d'objets et couverture française |
| `butin calibrer` | calibrage sans fenêtre, affiche ce qu'il a lu |
| `butin interface` | sert l'interface dans un navigateur, sans fenêtre |
| `butin reconnaitre "<texte>"` | teste la reconnaissance d'un nom |

## État d'avancement

| Brique | État | Détail |
| --- | --- | --- |
| Normalisation française | ✅ fait | accents, ligatures, apostrophes, tirets |
| Catalogue d'objets par identifiant | ✅ fait | 68 714 objets bdocodex, noms FR, cache sécurisé |
| Reconnaissance floue + contrôle d'ambiguïté | ✅ fait | seuil, marge, restriction par spot |
| Anti-double-comptage entre images | ✅ fait | alignement, défilement, validation multi-images |
| Capture d'écran et OCR | ✅ fait | rapidocr, aucun binaire système à installer |
| Calibrage automatique de la zone | ✅ fait | trouve le chat, le pas de ligne, la règle de mesure |
| Prix du marché central | ✅ fait | arsha.io, cache local principal, repli marchand |
| Sessions et silver/heure | ✅ fait | SQLite local, taxe sur le vendable seulement |
| Interface web locale | ✅ fait | FR/EN, EU/NA, démarrage de la capture |
| Banc d'essai sur données réelles | ✅ fait | mesure la justesse du compteur |
| Noms vérifiés à la main | ⚙️ mécanisme prêt | recoupement bdocodex/garmoth, objet par objet |
| Application de bureau | ✅ fait | fenêtre principale + panneau posé sur le jeu, `butin-app` |
| Installeur Windows | ✅ fait | [Releases](https://github.com/Maxyull/butin-bdo/releases/latest), sans droits administrateur |
| Vérification de mise à jour | ✅ fait | notification seule, jamais d'installation automatique |

685 tests automatisés.

### Ce que le compteur vaut sur du vrai farm

Un banc d'essai mesure la justesse du compteur sur 300 captures d'une vraie
session, par **trois méthodes indépendantes** : la boucle telle qu'elle tourne,
un recalage du texte qui ignore les pixels et les garde-fous, et un comptage des
montants de silver qui n'utilise aucune notion de position.

Sur ces 30 secondes de farm : **47 drops comptés sur 47**, quantité cumulée
exacte, montant du silver à 1,5 % près.

⚠️ Une seule rafale, un seul endroit de farm, une seule configuration d'écran.
Ce qu'on peut en conclure, et ce qu'on ne peut pas, est écrit en partie 6 de
[docs/banc-essai.md](docs/banc-essai.md).

Le chemin pour y arriver vaut d'être lu : le premier passage du banc comptait
**12 drops sur 47**. Cinq défauts, tous mesurés puis corrigés, dont un qui
faisait *inventer* du silver et un autre qui jetait 9 lectures valides sur 15.

### Ce que mesure la simulation de bout en bout

L'anti-double-comptage est vérifié sur un journal simulé complet, pas seulement
pièce par pièce. Sur 3000 captures et plus de 500 drops, le total compté est
**exactement** le total tombé. Avec 15% des lectures volontairement abîmées,
609 drops sur 609 sont encore comptés et 99% des quantités restent exactes.

Deux résultats de cette simulation méritent d'être connus :

- **Quand le tracker n'y arrive pas, il sous-compte, il ne sur-compte jamais.**
  C'est le bon sens de l'erreur.
- **Attendre plus d'images avant de valider un drop dégrade le résultat.** Le
  réglage qu'on serait tenté d'augmenter par prudence fait perdre du butin : la
  ligne sort de l'écran avant d'atteindre le seuil. Confirmé sur données réelles
  à quatre cadences de lecture différentes. Un test empêche que ce réglage soit
  relevé sans le voir.

## Versions

Butin suit [Semantic Versioning](https://semver.org/), et son journal des
modifications suit [Keep a Changelog](https://keepachangelog.com/) :
[CHANGELOG.md](CHANGELOG.md).

La version actuelle est `0.4.0`. Le `0.` du début a un sens précis et n'est pas
de la modestie : **rien n'est stable, tout peut changer d'une version à
l'autre**, y compris le format de la base de sessions.

Ce que Butin s'engage à ne pas casser, les critères à remplir pour passer en
1.0.0, et pourquoi la convention Conventional Commits a été **écartée** : voir
[docs/versionnage.md](docs/versionnage.md).

## Développement

```bash
python -m pytest
```

Les conventions du projet, l'architecture et les pièges déjà rencontrés sont
documentés dans [docs/](docs/). À lire avant de contribuer :
[CONTRIBUTING.md](CONTRIBUTING.md).

## Origine

Butin dérive de
[janhnguyen/BDO-Loot-Tracker](https://github.com/janhnguyen/BDO-Loot-Tracker)
(MIT), qui a résolu la partie difficile et indépendante de la langue :
transformer une suite de captures en liste de drops sans jamais compter deux
fois. Le détail de ce qui est repris et de ce qui est neuf se trouve dans
[ATTRIBUTION.md](ATTRIBUTION.md).

## Soutenir

Butin est gratuit et le restera. Il n'a pas de version payante, pas de
publicité, et ne collecte rien : ce que vous farmez ne quitte pas votre
machine (voir [Vie privée](#vie-privée)).

Si l'outil vous fait gagner du temps et que vous voulez donner un coup de
pouce, c'est ici, et c'est entièrement facultatif :

[![Soutenir Butin sur PayPal](ressources/bouton-don-butin.png)](https://paypal.me/maxyull)

## Licence

[MIT](LICENSE).

Black Desert Online est une marque de Pearl Abyss. Butin est un outil
indépendant, sans lien ni approbation de Pearl Abyss.
