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
- **Boucle de capture à deux vitesses.** La capture et la mesure de défilement
  tournent toutes les 100 ms, la reconnaissance de texte seulement quand il y a
  quelque chose à lire. Le défilement accumulé entre deux lectures alimente la
  prédiction de l'alignement, qui devient plus fine qu'avec une boucle unique.
- **Prix du marché central** par région (EU, NA et les autres), avec une chaîne
  de repli qui donne toujours une valeur et dit toujours d'où elle vient : prix
  frais, prix périmé daté, valeur au marchand, ou inconnu. Un échec réseau
  n'interrompt jamais une session.
- **Sessions de farm et silver par heure.** Base SQLite locale, numérotée dès la
  première version pour que l'historique survive aux mises à jour. La taxe de
  l'hôtel des ventes ne s'applique qu'aux objets vendables, jamais au butin
  vendu au marchand ni au silver ramassé. Les objets non valorisés et les prix
  périmés sont comptés et affichés à part.
- **Interface web locale** (`butin interface`), avec les deux sélecteurs
  demandés : langue FR/EN pour les noms d'objets, région EU/NA pour les prix.
  Servie par la bibliothèque standard, sur la boucle locale uniquement, sans
  aucune dépendance ajoutée. Les objets sans valeur connue et les prix périmés
  y sont signalés explicitement plutôt que noyés dans le total.
- **Interface en ligne de commande** minimale : état du catalogue, test de
  reconnaissance d'un nom, et calibrage de la zone.
- **Calibrage automatique de la fenêtre de chat** (`butin calibrer`). Trouve
  seul où lire le journal, le pas vertical entre deux lignes, et la bande où
  mesurer le défilement, en cherchant la colonne de l'image qui **ressemble le
  plus à elle-même décalée d'un cran** : les pastilles de canal sont toutes
  identiques et espacées d'exactement un pas de ligne. Mesuré sur 12 captures
  d'écran réelles, **12 sur 12** : les trois où le chat est lisible sont
  trouvées et rendent leurs 16 lignes de gain entières, les neuf où il est
  masqué sont refusées avec un message explicite.
  [docs/calibrage.md](docs/calibrage.md).
- **Banc d'essai sur données réelles** (`butin.bench`, `scripts/banc_essai.py`).
  Il rejoue la vraie boucle sur une rafale de captures et dit **de combien le
  compteur se trompe**, ce qui est la condition pour publier quoi que ce soit.
  Sa règle de conception : aucun des nombres qu'il produit ne sert de vérité aux
  autres. Le compteur est comparé à un recalage du texte qui ignore les pixels,
  le score flou et les garde-fous, lui-même corroboré par un comptage des
  montants de silver qui n'utilise aucune notion de position. Résultat mesuré et
  causes détaillées dans [docs/banc-essai.md](docs/banc-essai.md).

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
- **Le silver était compté sur toute la fenêtre du journal à chaque lecture**,
  au lieu des seules lignes nouvelles. Une ligne restant affichée une dizaine de
  secondes, son montant était additionné autant de fois qu'elle était relue.
  Mesuré par le banc d'essai : **123 409 silver comptés pour 93 161 réels, soit
  +32,5 %**, et avec seulement 6 lectures exploitées sur 300 images. C'était le
  seul défaut connu qui fasse **inventer** du gain plutôt qu'en rater. Après
  correction, l'écart est de −25,9 %, donc du bon côté.
- **Une seule ligne mal lue annulait un recouvrement de vingt.** L'alignement
  exigeait que *toutes* les paires de lignes franchissent le seuil de
  similarité ; il suffisait donc d'un raté d'OCR pour qu'aucun recouvrement ne
  soit jugé valide et que l'image entière soit rejetée comme aberrante. Un
  recouvrement est désormais retenu quand une **part** suffisante de ses paires
  s'accordent, seuil posé au milieu de deux populations mesurées : le vrai
  recouvrement accorde 74 à 100 % de ses paires, le meilleur des faux jamais
  plus de 50 %.
- **Le plafond de vraisemblance supposait deux lectures espacées de 100 ms**,
  alors que la reconnaissance ne tourne qu'une fois par seconde au mieux. Une
  lecture portant 14 lignes réellement nouvelles était rejetée comme un saut
  invraisemblable. Le plafond suit maintenant le temps réellement écoulé, avec
  un plancher qui garantit qu'il ne devient jamais plus sévère qu'avant.
  Mesuré : ces deux corrections ramènent les images jetées de 9 à **0**, le
  butin reconnu puis perdu de 21 à **1**, et la perte de **74,5 % à 12,8 %**.
- **Le montant de silver était lu une seule fois**, alors que les objets étaient
  déjà tranchés au vote sur toutes les lectures de leur ligne. Or le montant est
  un nombre à quatre chiffres, bien plus fragile qu'un nom que la
  reconnaissance floue rattrape : **13,6 % des lectures de lignes de silver en
  ont un d'illisible**, et chaque raté coûtait environ deux mille silver sans
  rattrapage possible. Le silver passe désormais par le même vote pondéré que
  les quantités d'objets. Écart ramené de −24,1 % à −1,5 %.
- **Le seuil de validation était trop haut d'une unité.** Exiger trois
  observations concordantes plutôt que deux fait sortir des lignes de l'écran
  avant qu'elles n'y parviennent. Balayé à quatre cadences de lecture : deux
  observations donnent le meilleur résultat à **chacune** des quatre, et le bon
  sens d'erreur. Dernier drop manquant récupéré, quantité cumulée exacte.
- ⛔ **La mesure de défilement en pixels ne détectait rien.** Elle prenait pour
  règle la colonne des pastilles de canal, qui sont toutes identiques et
  espacées d'exactement un pas de ligne : un défilement d'une ligne superpose
  une pastille sur sa voisine et n'y change rien. Zéro décalage juste sur les 37
  transitions réelles. Elle compare désormais la colonne du **texte** sur un
  **masque de pixels clairs**, qui fait disparaître le décor du jeu visible à
  travers le fond transparent : **32 décalages justes sur 37**, aucune fausse
  détection sur 262 transitions immobiles, et jamais de décalage faux (elle est
  juste ou muette). Le pas vertical, mesuré au passage, est de **21,6 px** et
  non 21. La perte tombe de 12,8 % à **2,1 %**.

### Connu et non résolu

- Le catalogue du marché ne reconnaît qu'un objet sur huit du butin réel.
  **Résolu par bdocodex** (98 % de jointure contre 5 %), mais la bascule du
  moteur de reconnaissance vers cette source n'est pas encore faite : pour
  l'instant `data/butin-connu.json` existe sans être branché. Voir
  [docs/couverture-du-catalogue.md](docs/couverture-du-catalogue.md).
- veliainn est périmé d'au moins une mise à jour du jeu sur les **noms**. Il
  n'est plus une source de noms, seulement de prix.
- **Le compteur est juste sur les 30 secondes de farm mesurées** : 47 drops sur
  47, quantité cumulée exacte, 45 lignes de silver sur 45, montant du silver à
  −1,5 %. ⚠️ Une seule rafale, un seul endroit de farm, une seule configuration
  d'écran, et des réglages balayés contre cette même rafale : ce qu'on peut
  annoncer et ce qu'on ne peut pas est écrit en partie 6 de
  [docs/banc-essai.md](docs/banc-essai.md).
- La reconnaissance de texte coûte 336 ms par image sur une zone de 520 x 385,
  et **1 100 ms** sur une zone de 780 x 575. Le découplage de la boucle absorbe
  le premier chiffre, pas le second.
- Le garde-fou de stabilité est **inutilisable en l'état**. Il suppose un fond
  fixe, alors que le journal est transparent sur un monde qui bouge en
  permanence. La défense contre une lecture prise en pleine animation repose
  donc entièrement sur le vote multi-images.
- Aucune interface graphique. **Le calibrage de la zone, lui, est fait**, mais
  n'a été vérifié que sur une seule résolution et une seule échelle
  d'interface : rien dans l'algorithme n'en dépend, tout y est mesuré plutôt que
  fixé, mais ce n'est pas la même chose que l'avoir vérifié.
- Le calibrage ne suit pas un déplacement de la fenêtre de chat en cours de
  session. La bouger en jeu demande de relancer `butin calibrer`.
- La reconnaissance n'est lancée que 22 fois sur 300 images, faute de pouvoir
  aller plus vite. Sans conséquence sur la rafale mesurée, mais sans marge non
  plus si un journal défilait deux fois plus vite.
