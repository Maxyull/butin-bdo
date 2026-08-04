# Politique de version

Trois conventions publiques ont été examinées avant d'être adoptées ou écartées.
Aucune n'a été prise parce qu'elle est répandue : chacune est justifiée par ce
qu'elle apporte à ce projet précis, et l'une d'elles est **refusée**.

| Convention | Décision |
| --- | --- |
| [Semantic Versioning 2.0.0](https://semver.org/) | adoptée |
| [PEP 440](https://peps.python.org/pep-0440/) | adoptée, elle s'impose |
| [Keep a Changelog 2.0.0](https://keepachangelog.com/) | adoptée |
| [Conventional Commits 1.0.0](https://www.conventionalcommits.org/) | **refusée**, voir plus bas |

## Semantic Versioning

`MAJEUR.MINEUR.CORRECTIF`, où l'on incrémente le majeur sur une rupture de
compatibilité, le mineur sur un ajout compatible, le correctif sur une
correction compatible.

### La déclaration d'API publique, qui n'est pas optionnelle

Semantic Versioning l'exige : « un logiciel utilisant Semantic Versioning DOIT
déclarer une API publique ». Sans cette déclaration, dire qu'une version est
majeure ou mineure ne veut rien dire, puisque rien ne définit ce qui casse.

Butin est un logiciel de bureau et non une bibliothèque, donc sa surface
publique n'est pas évidente. Elle est déclarée ici :

**Fait partie de l'API publique**, et une rupture impose un majeur :

- les **commandes et options de la ligne de commande** (`butin catalogue`,
  `butin reconnaitre`) et leurs codes de sortie ;
- le **format du fichier de calibrage** que l'utilisateur conserve entre deux
  sessions ;
- le **schéma de la base de sessions**, qui contient un historique de farm que
  personne n'accepterait de perdre à une mise à jour ;
- le **format de `data/noms-verifies.json`**, alimenté à la main sur la durée.

**N'en fait PAS partie**, et peut changer sur un correctif :

- toute fonction ou classe Python du paquet `butin`. Le paquet n'est pas publié
  sur PyPI et n'est pas destiné à être importé par un tiers. Le jour où il le
  serait, cette ligne devra changer, et ce serait une rupture majeure ;
- les seuils de reconnaissance, les réglages du prétraitement, la cadence de
  capture. Ce sont des réglages internes que la mesure fera bouger ;
- le contenu du catalogue, qui vient d'une source amont mise à jour chaque jour.

### Pourquoi `0.y.z` et ce que ça vous promet

Butin est en version zéro, ce que Semantic Versioning définit ainsi : « la
version majeure zéro est destinée au développement initial. Tout PEUT changer à
tout moment. »

**C'est une promesse d'instabilité, pas une modestie de façade.** Le format de
la base de sessions n'est pas figé, la ligne de commande peut changer de nom
d'option, et rien n'oblige à une migration de données entre deux versions
`0.y`.

### Ce qu'il faut pour passer en 1.0.0

Pas une date, des critères. Tant qu'ils ne sont pas tous remplis, on reste en
`0.y.z` même si le logiciel paraît fini :

1. une session de farm complète fonctionne de bout en bout, sans intervention ;
2. le schéma de la base de sessions est figé, avec un mécanisme de migration ;
3. la couverture du catalogue est résolue (voir
   [couverture-du-catalogue.md](couverture-du-catalogue.md)), parce qu'un
   tracker qui reconnaît un objet sur huit ne peut pas prétendre à une version
   stable ;
4. le format du fichier de calibrage est figé.

## PEP 440, la convention que Python impose

Semantic Versioning et l'écosystème Python ne parlent pas tout à fait la même
langue, et c'est PEP 440 qui gagne dès qu'un `pyproject.toml` est en jeu : les
outils Python refusent une version qui ne s'y conforme pas.

Les différences qui comptent :

| Intention | Semantic Versioning | PEP 440 |
| --- | --- | --- |
| pré-version alpha | `1.0.0-alpha.1` | `1.0.0a1` |
| version candidate | `1.0.0-rc.1` | `1.0.0rc1` |
| en développement | pas de notion | `1.0.0.dev0` |

**La version actuelle est `0.1.0.dev0`**, et le suffixe est délibéré. `0.1.0`
tout court signifierait que la version 0.1.0 est publiée, ce qui est faux :
aucune version ne l'est. `.dev0` se trie avant `0.1.0` et rend cette confusion
impossible. Il tombera au moment de la première publication.

## Keep a Changelog

[`CHANGELOG.md`](../CHANGELOG.md) suit ce format : une section `Non publié` en
haut, les versions ensuite de la plus récente à la plus ancienne, chacune datée
au format `AAAA-MM-JJ`, et les modifications groupées par nature (Ajouté,
Modifié, Déprécié, Retiré, Corrigé, Sécurité).

Le principe qui compte le plus ici est le premier de la spécification : **un
journal des modifications s'écrit pour des humains, pas pour des machines.** Un
journal généré depuis les messages de commit ne dit que ce qui a été fait, pas
ce que ça change pour la personne qui utilise le logiciel. Il est donc écrit à
la main.

Une section supplémentaire, `Connu et non résolu`, sort du format standard. Elle
est assumée : les limites connues d'une version sont ce qu'un utilisateur a le
plus besoin de lire avant de l'installer, et les cacher jusqu'à ce qu'il les
découvre lui-même serait malhonnête.

## Conventional Commits : refusée, et pourquoi

La convention préfixe chaque message de commit d'un type (`feat:`, `fix:`,
`docs:`), ce qui permet à un outil de déduire tout seul s'il faut incrémenter le
mineur ou le correctif.

**Son bénéfice est l'automatisation de la publication. Ce projet ne publie pas
automatiquement.** Adopter la contrainte sans prendre le bénéfice, c'est du
cérémonial.

Elle coûte par ailleurs quelque chose ici. Les messages de commit de ce dépôt
sont des phrases françaises à l'impératif qui expliquent **pourquoi** un
changement existe, souvent sur plusieurs paragraphes. Un préfixe anglais en tête
d'un message français est une incohérence de plus dans un dépôt dont la langue
est une décision assumée.

**Condition de réexamen :** le jour où la publication devient automatique, par
exemple si Butin est distribué sur PyPI ou par un installeur versionné, la
convention reprend tout son sens et devra être adoptée. Ce n'est pas un refus de
principe, c'est un refus tant que le bénéfice est nul.

## Procédure de publication

1. Vérifier que les critères de la version visée sont remplis.
2. Déplacer le contenu de `Non publié` sous un titre de version daté dans
   `CHANGELOG.md`, et recréer une section `Non publié` vide.
3. Mettre à jour la version dans `pyproject.toml` **et** dans
   `src/butin/__init__.py`. Un test vérifie que les deux concordent : deux
   sources de vérité qui divergent produisent un numéro de version faux à
   l'exécution, ce que personne ne remarque avant un rapport de bogue.
4. Fusionner, puis étiqueter le commit de fusion `v<version>`.
5. Créer la publication GitHub à partir de la section du journal.
