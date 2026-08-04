# Butin

**Le suivi de butin pour Black Desert Online, enfin en français.**

Butin lit le journal d'acquisition pendant que vous farmez, reconnaît chaque
objet qui tombe, et vous dit ce que votre session a réellement rapporté en
silver par heure.

Les outils équivalents existent déjà. Aucun ne parle français. Butin est écrit
pour le client français dès la première ligne, pas traduit après coup.

> ⚠️ **Projet en construction.** Le noyau de reconnaissance française fonctionne
> et est testé. La capture d'écran, l'interface et le calcul de session ne sont
> pas encore terminés. Voir [État d'avancement](#état-davancement) pour ce qui
> marche vraiment aujourd'hui. Il n'y a pas encore de version téléchargeable.

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

## État d'avancement

| Brique | État | Détail |
| --- | --- | --- |
| Normalisation française | ✅ fait | accents, ligatures, apostrophes, tirets |
| Catalogue d'objets par identifiant | ✅ fait | 8344 objets, noms FR, mise en cache sécurisée |
| Reconnaissance floue + contrôle d'ambiguïté | ✅ fait | seuil, marge, restriction par spot |
| Noms vérifiés à la main | ⚙️ mécanisme prêt | recoupement bdocodex/garmoth à faire, objet par objet |
| Anti-double-comptage entre images | ✅ fait | alignement, défilement, validation multi-images |
| Capture d'écran et OCR | ⛔ à faire | |
| Prix du marché central | ⛔ à faire | |
| Sessions et silver/heure | ⛔ à faire | |
| Interface | ⛔ à faire | |

194 tests automatisés couvrent les briques marquées comme faites.

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
  ligne sort de l'écran avant d'atteindre le seuil. Mesuré, en passant de 3 à 7
  observations exigées, les pertes passent de 0 à 24 drops sur la même session.
  Un test empêche que ce réglage soit relevé sans le voir.

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

## Licence

[MIT](LICENSE).

Black Desert Online est une marque de Pearl Abyss. Butin est un outil
indépendant, sans lien ni approbation de Pearl Abyss.
