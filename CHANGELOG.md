# Journal des modifications

Toutes les modifications notables de Butin sont consignées ici.

Le format suit [Keep a Changelog 2.0.0](https://keepachangelog.com/), et le
projet suit [Semantic Versioning 2.0.0](https://semver.org/). La politique de
version, ce qu'elle promet et ce qu'elle ne promet pas, est expliquée dans
[docs/versionnage.md](docs/versionnage.md).

## [Non publié]

Rien n'a encore été publié. Butin est en `0.y.z`, ce qui veut dire, au sens de
Semantic Versioning, que **rien n'est stable et que tout peut changer à tout
moment**. Les critères à remplir pour publier la première version sont listés
dans [docs/versionnage.md](docs/versionnage.md).

### Ajouté

- **Reconnaissance des noms d'objets français.** Normalisation des accents, de
  la ligature « œ », des variantes d'apostrophe et des tirets. Sans elle, des
  objets réels et courants comme « Nœud d'arbre ensanglanté » sont
  structurellement impossibles à reconnaître.
- **Catalogue d'objets indexé par identifiant numérique** et non par nom, seule
  façon de gérer plusieurs langues et de retrouver un prix de marché. 8344
  objets, 99,7 % de couverture française.
- **Correspondance exacte puis floue**, avec une marge d'ambiguïté qui refuse de
  trancher entre deux objets voisins plutôt que d'attribuer un drop au hasard.
- **Restriction par spot de farm**, qui limite les candidats aux objets qui
  tombent réellement à l'endroit où l'on se trouve.
- **Couche de noms vérifiés à la main**, recoupés sur bdocodex et garmoth, avec
  une règle de deux sources distinctes dont une référence, tenue par un test.
- **Anti-double-comptage** : alignement de deux captures par recouvrement,
  détection du défilement par comparaison de pixels, attente de stabilité avant
  lecture, et validation d'un drop seulement après accord de plusieurs images.
- **Capture d'écran** d'une région, en niveaux de gris, avec refus explicite
  d'une région qui déborde de l'écran.
- **Reconnaissance de texte** par rapidocr, avec un prétraitement mesuré
  (agrandissement x2 puis étirement de contraste) qui porte la lecture exacte de
  9 lignes sur 30 à 24 sur 30.
- **Découpage des lignes du journal d'acquisition français**, avec le format du
  client isolé en données pour qu'une autre langue s'ajoute sans toucher à la
  logique.
- **Interface en ligne de commande** minimale : état du catalogue et test de
  reconnaissance d'un nom.

- **Base de butin français** (`data/butin-connu.json`) : 362 objets avec leur
  nom anglais, leur nom français, leur valeur en silver par niveau
  d'amélioration, et pour 102 d'entre eux la **zone de farm** où ils tombent.
  Ces zones donnent enfin des données au mécanisme de restriction par spot.
- **Script de jointure reproductible** (`scripts/joindre_butin.py`) entre la
  liste de butin curée à la main et la base complète de bdocodex.

- **Premier nom vérifié à la main** : `Pierre noire`. Le jeu a fusionné
  « Pierre noire (arme) » et « (armure) » en un seul objet, ce que veliainn n'a
  pas suivi. Sans cette correction, le drop le plus fréquent du jeu était
  reconnu **par accident**, avec un seul point de marge, et aurait désigné le
  mauvais objet si la fusion s'était faite dans l'autre sens.

### Sécurité

- Téléchargement du catalogue durci : HTTPS imposé, hôte en liste blanche
  revalidé après redirection, plafond de taille sur les octets réellement lus,
  délais d'attente sur connexion et sur lecture, analyse JSON stricte,
  validation de forme avant écriture et écriture atomique.
- Aucune désérialisation exécutable. Les données externes sont lues en JSON et
  seulement en JSON.
- Intégration continue : `pip-audit`, CodeQL et `gitleaks` sur tout
  l'historique, actions GitHub épinglées par empreinte de commit.

### Corrigé

- Le crochet fermant d'un nom d'objet, que l'OCR rend parfois en « l », faisait
  échouer le découpage et **perdait le drop en silence**. Mesuré sur une capture
  réelle : deux des six gains ratés.
- L'accent aigu isolé « ´ », lecture fréquente de l'apostrophe, se décomposait
  en espace avant d'être traité, ce qui transformait « d'énergie » en
  « d energie » et cassait la correspondance.
- Un `python_version` figé pour mypy contredisait la matrice d'intégration
  continue et arrêtait l'analyse sur une erreur de syntaxe dans une dépendance.
- `pip-audit --strict` échouait sur le paquet du projet lui-même, absent de
  PyPI.

### Connu et non résolu

- Le catalogue du marché ne reconnaît qu'un objet sur huit du butin réel.
  **Résolu par bdocodex** (98 % de jointure contre 5 %), mais la bascule du
  moteur de reconnaissance vers cette source n'est pas encore faite : pour
  l'instant `data/butin-connu.json` existe sans être branché. Voir
  [docs/couverture-du-catalogue.md](docs/couverture-du-catalogue.md).
- veliainn est périmé d'au moins une mise à jour du jeu sur les **noms**. Il
  n'est plus une source de noms, seulement de prix.
- La reconnaissance de texte coûte 336 ms par image, contre 100 ms envisagés.
  Le calcul de marge tient encore, l'arbitrage de cadence n'est pas tranché.
- Aucune boucle de capture ni interface : les briques existent, l'assemblage
  non.
