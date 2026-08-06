# Journal des modifications

Toutes les modifications notables de Butin sont consignées ici.

Le format suit [Keep a Changelog 2.0.0](https://keepachangelog.com/), et le
projet suit [Semantic Versioning 2.0.0](https://semver.org/). La politique de
version, ce qu'elle promet et ce qu'elle ne promet pas, est expliquée dans
[docs/versionnage.md](docs/versionnage.md).

## [Non publié]

## [0.3.0] - 2026-08-06

### Ajouté

- **Numéro de version affiché à côté du titre**, dans l'en-tête de la fenêtre
  principale, avec le bouton de mise à jour juste à côté quand une version
  plus récente existe. Remplace le bandeau pleine largeur de la 0.2.0.
- **Lien Discord**, dans l'application (en-tête, à côté des sliders langue et
  région) et dans le README, pour les questions, bogues et idées.
- **Badges au README** : état de la CI, dernière version publiée, licence,
  version de Python requise, Discord — tous vérifiés au chargement réel.

## [0.2.0] - 2026-08-06

### Modifié

- **La vérification de mise à jour se répète toutes les cinq minutes** tant
  que Butin reste ouvert, plutôt qu'une seule fois au lancement. Sur une
  session de farm de plusieurs heures, une Release publiée entre-temps
  n'aurait sinon jamais été signalée avant le prochain lancement. Toujours
  une notification seule.

## [0.1.0] - 2026-08-06

Première version publiée. Butin reste en `0.y.z`, ce qui veut dire, au sens de
Semantic Versioning, que **rien n'est stable et que tout peut changer à tout
moment** : les critères pour passer en `1.0.0` sont listés dans
[docs/versionnage.md](docs/versionnage.md), et ne sont pas encore tous
remplis.

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
- **Le taux de taxe se règle enfin, et il tient d'un lancement à l'autre.** Le
  calcul était juste depuis le début, mais personne ne pouvait dire au logiciel
  ce qu'il possède : tout le monde était donc valorisé au taux **sans aucun
  bonus**, soit 23 % de moins que ce que touche réellement un joueur avec
  abonnement. Une erreur systématique, qui se répète à l'identique à chaque
  session et qui ressemble à un farm pauvre. Trois cases dans les réglages —
  abonnement, anneau de marchand, renommée familiale — et non un pourcentage à
  saisir : le joueur sait s'il a un abonnement, il ne sait pas forcément que ça
  fait 84,5 %. Les réglages (langue, région, profil de taxe) sont désormais
  écrits dans `reglages.json`, à côté du calibrage.
- **Arrêter une session emmène sur cette session.** L'écran du farm en cours
  retombait à zéro dès l'arrêt, faute de session en cours : les quatre chiffres
  et le tableau du butin se vidaient d'un coup, sans rien dire que tout était
  enregistré dans l'onglet Historique. Du point de vue de quelqu'un qui vient de
  farmer deux minutes, ce qu'il a ramassé venait de disparaître.
- **L'image de chaque objet dans le récap**, à côté de son nom et de sa quantité
  totale. Un joueur reconnaît son butin à l'image avant d'avoir lu le nom,
  exactement comme il le reconnaît à la couleur de rareté. Le chemin de l'image
  était déjà dans l'export bdocodex qu'on télécharge pour les noms (68 747 sur
  68 747) : rien de nouveau n'est téléchargé pour les connaître, seules les
  images le sont, une fois chacune. Celles du butin connu sont préchargées au
  lancement dans un fil de fond, pour que le récap n'ait pas de trou pendant le
  farm. Une image absente **ne casse rien** : elle se cache sans décaler la
  ligne, et le drop reste compté et lisible.
- **Le panneau posé sur le jeu montre désormais le récap cumulé** et non le fil
  des drops un par un. Sur des heures de farm, « combien j'ai ramassé de Pierres
  noires » est la question ; « quel objet est tombé il y a quatre secondes » ne
  l'est plus au bout de dix minutes, et le fil défilait plus vite qu'on ne le
  lit. Une ligne s'anime quand sa quantité augmente, ce qui garde le signal
  « quelque chose vient de tomber ».
- **Mettre la session en pause**, depuis la fenêtre principale ou depuis le
  panneau posé sur le jeu. La capture s'arrête, et surtout **le temps arrête de
  compter** : le silver par heure divise le total par la durée, donc une pause
  repas de vingt minutes comptée comme du farm diviserait le résultat d'une
  heure de session par 1,3, sans que rien ne l'explique. La reprise repart d'une
  boucle neuve, dont la première lecture prend ce qui est à l'écran pour du
  passé : sans ça, reprendre recréditerait les dix-sept lignes encore
  affichées, c'est-à-dire inventerait des drops. La pause enregistre au passage
  le butin encore en attente, comme l'arrêt, et **se voit** dans le panneau,
  cadre compris — un total qui n'augmente plus est indistinguable d'un farm
  calme, et là c'est nous qui l'aurions arrêté. Schéma de base en version 2, les
  bases existantes sont migrées sans rien perdre.
- **Le calibrage depuis l'interface.** Il n'y a plus rien à taper : un bouton
  **Calibrer la zone** avec un décompte de cinq secondes pour basculer dans le
  jeu, et la page affiche **les lignes qu'elle a lues** dans la zone retenue.
  Montrer l'extrait n'est pas un confort : la détection cherche ce qui se répète
  verticalement et ne sait pas d'où vient l'image, un essai réel ayant calibré
  très proprement sur une capture du chat ouverte dans une visionneuse. La page
  dit aussi, en permanence, si la zone est calibrée, pour qu'on le sache **avant**
  de cliquer sur Démarrer.
- **Le bouton qui lance la capture.** L'interface ouvrait une session dans la
  base et **rien ne l'alimentait** : le compteur restait à zéro, ce qui est
  impossible à distinguer d'une session sans butin. La boucle tourne désormais
  dans un fil de fond, et l'interface affiche ce qu'elle compte comme ce qu'elle
  rate. Deux règles y sont tenues : un démarrage refusé, typiquement faute de
  calibrage, **referme la session** au lieu d'en laisser une vide qui ressemble
  à une vraie ; et toute exception du fil est **retenue et affichée**, parce
  qu'un fil mort en silence laisserait un total qui n'augmente plus sans rien
  pour distinguer la panne du farm calme.
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

- **Application de bureau**, à deux fenêtres, lancée par `butin-app` : une
  fenêtre principale (Réglages + Historique) et un panneau **translucide posé
  par-dessus le jeu** pendant le grind, sans cadre, toujours au-dessus, qui
  montre le récap cumulé du butin. Jusqu'ici Butin était une page à ouvrir
  dans un navigateur ; ce n'était pas encore un logiciel qu'on lance.
- **Mettre la session en pause**, avec le temps de pause déduit de la durée
  affichée dans le panneau et dans la fenêtre principale.
- **Un installeur Windows** (`installeur/butin.iss`, Inno Setup), à partir de
  la distribution autonome PyInstaller (`installeur/butin.spec`) : menu
  Démarrer, désinstallation propre, icône dédiée. Installation **par
  utilisateur, sans droits administrateur**, cohérente avec un logiciel qui
  n'écrit déjà que dans `Documents\BDO Tracker`. Vérifié pour de vrai : cycle
  install/lancement/désinstallation, et l'historique de farm de l'utilisateur
  reste intact après désinstallation.
- **Vérification de mise à jour au lancement.** Un bandeau prévient si une
  version plus récente est publiée sur GitHub Releases, avec un lien.
  Notification seule : Butin ne télécharge ni n'installe rien tout seul.

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

- `Path(__file__).resolve().parents[3]` était utilisé à trois endroits
  (`catalog/zones.py`, `catalog/overrides.py`, `market/book.py`) pour trouver
  `data/butin-connu.json` et `data/noms-verifies.json`, en supposant que le
  fichier source vit toujours dans un checkout du dépôt. Ce calcul se casse
  **en silence** dans une application PyInstaller figée, qui aplatit tout sous
  `sys._MEIPASS` : l'utilisateur verrait tous les objets sans zone de farm ni
  valeur au marchand, sans la moindre erreur pour le dire. Centralisé dans
  `paths.bundled_data_dir()`, qui détecte l'exécution figée et cherche au bon
  endroit dans les deux cas. Première pierre d'un installeur.
- **Un aperçu montre la zone calibrée, cadre dessiné dessus.** Jusqu'ici le
  calibrage ne rendait que des coordonnées et un extrait de texte : juste, mais
  un nombre de pixels ne dit rien à l'œil. Un essai réel avait calibré très
  proprement sur une capture du chat ouverte dans une visionneuse — une zone
  juste au pixel près, mais fausse quand même, parce que ce n'était pas le jeu.
  Voir le cadre posé sur sa propre capture d'écran rend cette confusion
  impossible d'un coup d'œil.
- ⭐ **Le calibrage se fait sur plusieurs images, pas une seule.** Mesuré sur une
  vraie session : la largeur trouvée variait de 468 à 542 px d'une image à
  l'autre, et trois calibrages successifs d'un joueur qui n'avait rien touché
  ont rendu 476, 560 puis 731 px pour la même fenêtre de chat. Ce n'était pas
  cosmétique : une zone une fois et demie trop large ralentit la reconnaissance
  pendant **toute la session** (1 439 ms contre 846 pour lire exactement les
  mêmes lignes), donc le compteur rate des lignes sans que rien ne le dise. Le
  calibrage prend désormais cinq images espacées et retient la **médiane** de
  chaque bord, qui écarte une mesure aberrante au lieu de s'y laisser tirer par
  une moyenne. Une image où le chat est masqué est ignorée plutôt que fatale.
- ⭐⭐ **Le compteur créditait le journal DÉJÀ À L'ÉCRAN au démarrage**, donc il
  **inventait des drops** — l'erreur que ce projet refuse avant toute autre.
  Trouvé au premier vrai farm, le 05/08/2026, et prouvé sur 600 images de
  Thornwood Forest : le chat était estompé au lancement, l'amorce s'est faite
  sur une lecture partielle de 4 lignes, et les lectures suivantes n'avaient
  donc plus aucun recouvrement avec elle. Les 23 lignes déjà affichées, datées
  de 16:40 à 17:14 pour une session ouverte à 17:19, sont passées pour neuves :
  **cinq objets que le joueur n'avait jamais ramassés**. Le jeu horodate chaque
  ligne, et cette heure était lue sans être utilisée ; elle sert désormais à
  refuser ce qui date d'avant la session. Mesuré sur la même rafale : de 104
  drops et 305 unités à 96 et 253, **zéro objet fantôme**. ⚠️ L'heure n'ayant
  pas de secondes, il reste au pire une minute d'historique, contre
  trente-neuf. Au passage, 7,6 % des heures étaient perdues sur une parenthèse
  pleine largeur rendue par la reconnaissance ; elle est acceptée.
- ⭐ **La fenêtre principale ne réagissait plus à rien.** Une vraie fin de ligne
  s'était glissée dans une chaîne de caractères du script de la page, ce qui est
  une erreur de syntaxe et fait tomber le bloc entier : plus de
  rafraîchissement, plus de bouton, plus de calibrage, plus de fil des drops.
  La page continuait de s'afficher normalement, avec ses tableaux vides et ses
  zéros, donc exactement comme une application qui vient de démarrer. Un
  garde-fou vérifie désormais qu'aucune chaîne des deux pages n'est coupée par
  une fin de ligne.
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

- `data/butin-connu.json` porte les **zones de farm** qui servent à nommer une
  session automatiquement, et elles sont encore **en anglais**.
- veliainn est périmé d'au moins une mise à jour du jeu sur les **noms**. Il
  n'est plus une source de noms, seulement de prix.
- **Le banc d'essai est juste sur les 30 secondes de farm mesurées** : 47 drops
  sur 47, quantité cumulée exacte, 45 lignes de silver sur 45, montant du
  silver à −1,5 %. ⚠️ Une seule rafale, un seul endroit de farm, une seule
  configuration d'écran, et des réglages balayés contre cette même rafale : ce
  qu'on peut annoncer et ce qu'on ne peut pas est écrit en partie 6 de
  [docs/banc-essai.md](docs/banc-essai.md). **Sur deux vraies sessions de farm
  complètes** (05/08/2026, Thornwood Forest), en revanche, aucun objet n'a été
  inventé : la première a trouvé un sur-comptage de +15 % sur le drop
  fréquent, cause corrigée (le journal déjà à l'écran au démarrage était
  compté), la seconde l'a confirmé sur neuf objets comparés à l'inventaire
  réel.
- La reconnaissance de texte coûte 336 ms par image sur une zone de 520 x 385,
  et **1 100 ms** sur une zone de 780 x 575. Le découplage de la boucle absorbe
  le premier chiffre, pas le second.
- Le garde-fou de stabilité est **inutilisable en l'état**. Il suppose un fond
  fixe, alors que le journal est transparent sur un monde qui bouge en
  permanence. La défense contre une lecture prise en pleine animation repose
  donc entièrement sur le vote multi-images.
- Le calibrage n'a été vérifié que sur **une seule résolution et une seule
  échelle d'interface**. Rien dans l'algorithme n'en dépend, tout y est mesuré
  plutôt que fixé, mais ce n'est pas la même chose que l'avoir vérifié.
- ⚠️ **Le direct sera moins précis que le banc, et on sait pourquoi.** Le banc
  rejoue 300 images où la mesure de défilement tourne toutes les 100 ms ; en
  vrai, la reconnaissance de texte bloque le même fil pendant une seconde, donc
  elle ne tourne qu'une fois par seconde. Le résultat du banc est un plafond,
  pas une promesse. Découpler les deux fils est faisable et mérite d'être mesuré
  en conditions réelles avant d'être décidé.
- Le calibrage ne suit pas un déplacement de la fenêtre de chat en cours de
  session. La bouger en jeu demande de recalibrer.
- L'installeur n'a été vérifié que sur la machine de développement, où Python
  et Visual C++ Redistributable sont déjà présents. Rien n'indique qu'il
  manque une dépendance native sur une machine vierge, mais rien ne l'a testé
  non plus.
- La vérification de mise à jour ne sert encore à rien tant qu'aucune version
  n'est publiée sur GitHub Releases.
- La reconnaissance n'est lancée que 22 fois sur 300 images, faute de pouvoir
  aller plus vite. Sans conséquence sur la rafale mesurée, mais sans marge non
  plus si un journal défilait deux fois plus vite.
