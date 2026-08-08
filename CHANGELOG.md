# Journal des modifications

Toutes les modifications notables de Butin sont consignées ici.

Le format suit [Keep a Changelog 2.0.0](https://keepachangelog.com/), et le
projet suit [Semantic Versioning 2.0.0](https://semver.org/). La politique de
version, ce qu'elle promet et ce qu'elle ne promet pas, est expliquée dans
[docs/versionnage.md](docs/versionnage.md).

## [Non publié]

### Ajouté

- **⭐ Un parcours guidé, et un seul bouton pour tout commencer.** « Commencer le
  grind » calibre ta zone, démarre la session, te demande d'ouvrir ton
  inventaire pour la photo de départ, puis te montre ton écran pour que tu
  vérifies que rien ne recouvre le chat.

  À l'arrêt, il reprend la photo d'arrivée et te pose la seule question qui
  compte : **le compte est bon ?** Si tu réponds non, le rapport part et
  l'archive complète est préparée, prête à déposer.

### Modifié

- **Le bouton « Soutenir Butin » porte enfin sa vraie icône**, le cœur facetté
  doré du kit, et il a échangé sa place avec ton pseudonyme dans l'en-tête.

### Retiré

- **Le fil des drops et le tableau du butin de l'onglet Session.** Le panneau
  posé sur le jeu montre le récap pendant le farm — c'est le seul écran qu'on
  regarde en farmant — et l'Historique le montre après. Cette fenêtre-ci est
  derrière le jeu : personne ne l'a jamais lue pendant une session.

- **Le bouton « Calibrer la zone ».** Il se faisait à part, donc il s'oubliait —
  et une zone non calibrée donne un compteur à zéro qui ressemble à un farm
  pauvre. Le calibrage fait maintenant partie du démarrage, avec son message et
  ses doutes affichés.

## [0.12.1] - 2026-08-08

### Ajouté

- **⭐ Deux captures d'inventaire par session : « Inventaire de départ » et
  « Inventaire d'arrivée ».** C'est ce qui rend enfin utilisable la seule vérité
  de Butin qui ne passe par aucune lecture d'écran.

  Il n'y en avait qu'une, et la seconde écrasait la première : une session ne
  pouvait donc pas être comparée à elle-même. La différence entre les deux bouts
  est la seule chose qui puisse dire si le compteur se trompe.

  L'ordre : démarre la session, prends le départ, farme, prends l'arrivée,
  arrête. ⚠️ Le départ se prend **après** avoir lancé la session.

### Corrigé

- **La pastille dorée vide, à côté du numéro de version, a disparu.** C'était le
  bouton de mise à jour : il ne devait s'afficher que lorsqu'une version plus
  récente existe, et il restait là en permanence, vide, même à jour.

### Modifié

- **⛔ Les schémas « ce qu'il faut voir » sont redessinés d'après de vrais
  écrans, et l'un d'eux accusait la mauvaise fenêtre.** L'inventaire s'ouvre à
  droite et ne recouvre rien : ce sont les fenêtres de **gauche** qui gênent,
  menu Échap, Mes informations, boîte aux lettres.

  Et il manquait le cas le plus dangereux : une fenêtre qui ne mange que le
  **haut** de la zone. Butin continue alors de compter, sur un tiers de ce qui
  passe. Un compteur arrêté finit par se voir ; un compteur qui compte à moitié
  ressemble à un farm calme.

- **Tout ce qui te concerne est passé en haut à droite** : ton pseudonyme
  Discord, le bouton pour t'en détacher, et le soutien. Sur la ligne du titre.

- **Ton pseudonyme Discord s'affiche en haut à droite, sur la ligne du titre.**
  « Suis-je connecté, et sous quel nom » est une question qu'on se pose en
  permanence : c'est ce nom qui apparaît dans le salon quand tu signales un
  bogue. Il reste donc visible.

- **Se connecter à Discord a déménagé dans les Réglages**, avec le lien vers le
  salon et le bouton de soutien. Se connecter ne se fait qu'une fois : ça n'a
  rien à faire dans l'onglet qu'on ouvre quand quelque chose ne va pas.

## [0.12.0] - 2026-08-08

### Ajouté

- **Un bouton « Se déconnecter » à côté de ton compte Discord.** Il n'y avait
  aucun moyen de détacher un compte une fois rattaché.

  ⚠️ **Ce qu'il fait exactement, parce que ça compte ici :** Butin oublie qui tu
  es sur Discord, et tes prochains rapports partent sous un nouveau pseudonyme
  anonyme. Deux choses qu'il ne peut pas faire à ta place : le serveur de
  rapports garde l'ancien rattachement, et l'autorisation reste donnée côté
  Discord tant que tu ne la retires pas toi-même dans *Paramètres →
  Applications autorisées*.

- **Un bouton « Soutenir Butin »**, sous les boutons Discord dans l'onglet
  Rapport. Entièrement facultatif : Butin est gratuit et le restera, sans
  version payante ni publicité.

### Corrigé

- **⛔ Butin te dit quand ta zone est trop étroite et coupe les noms d'objets.**
  C'était une panne muette de plus, et la plus coûteuse : une session réelle a
  tourné **462 secondes pour zéro objet compté**, avec une zone de 448 px là où
  la même fenêtre de chat en demandait 662.

  Un nom coupé n'est pas reconnu, donc le drop est perdu **sans que rien ne le
  dise**. Et sans l'heure en fin de ligne, le refus du vieux journal ne
  fonctionne plus non plus : une zone trop étroite casse les deux protections
  d'un coup.

  Le calibrage passait pourtant tous ses contrôles — force 0,41, 25 rangées —
  parce qu'aucun ne regardait le **texte**. Il vérifie maintenant que les
  lignes lues se terminent bien par leur heure, comme le jeu les écrit.

- **⛔ Plus de drops inventés au démarrage quand le chat se remplit.** Une
  session réelle a compté **6 261 unités d'un objet possédé avant de lancer**,
  soit la moitié de son total.

  Dans les premières secondes, la fenêtre de chat n'est pas encore pleine, donc
  la mesure de défilement ne veut rien dire. Une prédiction fausse pouvait
  alors annuler l'état de départ et faire recompter tout ce qui était déjà à
  l'écran.

  Mesuré sur huit sessions réelles rejouées : **6 302 unités inventées en
  moins**, et au passage **des lignes perdues en moins** aussi (51 → 4 sur
  l'une d'elles).

- **Les barres de défilement suivent enfin le thème sombre.** Elles restaient
  blanches, dans la fenêtre principale comme dans le panneau posé sur le jeu —
  et là, une bande blanche pleine hauteur par-dessus le décor était le contraire
  de ce que ce panneau doit faire.

## [0.11.0] - 2026-08-08

### Ajouté

- **Deux boutons « Ce qu'il faut voir » et « Mon écran », sous le calibrage.**
  Le premier montre un schéma : le journal d'acquisition entier dans le cadre,
  et rien par-dessus. Il montre aussi les **deux erreurs qui coûtent des
  objets** — l'inventaire ou le menu Échap posés sur la zone lue.

  ⛔ Ce n'est pas décoratif. Une vraie session a laissé le menu Échap devant le
  chat pendant **4 minutes** : **560 objets manquants sur 4 080**, et le
  compteur affichait son total comme si de rien n'était.

  Le second prend une photo de ton écran, cadre orangé sur la zone que Butin
  lit, pour que tu compares. Compte à rebours de 5 secondes, le temps de
  basculer sur le jeu. L'image reste chez toi.

### Modifié

- **La fenêtre principale est passée à quatre onglets** : `Session`,
  `Historique`, `Réglages`, `Rapport`. Ce qu'on refait à chaque lancement
  (calibrer, démarrer) est séparé de ce qu'on règle une fois (dossier, taxe,
  langue, région) et de ce qu'on n'ouvre qu'en cas de problème.

- **Les quatre chiffres de l'en-tête ont été retirés** (silver par heure, total
  net, durée, objets valorisés). Ils sont déjà dans le panneau posé sur le jeu,
  qui est le seul écran regardé en farmant, et dans l'Historique, qui est
  l'écran regardé après.

## [0.10.0] - 2026-08-08

### Modifié

- **Ton dossier de sessions s'appelle maintenant `Documents\BDO Butin`.** Il
  s'appelait `BDO Tracker`, un nom qui ne disait plus celui du logiciel.

  **Le renommage est automatique et ne te fait rien perdre.** Au premier
  lancement, tout le dossier est renommé : tes sessions, tes réglages, ton
  calibrage, tes journaux de lecture et tes captures d'inventaire.

  ⚠️ Si le renommage échoue — dossier ouvert dans l'explorateur, antivirus —
  Butin continue d'utiliser l'ancien nom plutôt que de t'afficher un historique
  vide. Tes données ne sont jamais perdues, au pire elles ne bougent pas.

  ⚠️ Si tu avais choisi ton propre dossier dans les réglages, rien ne change :
  ton choix passe avant.

## [0.9.1] - 2026-08-08

### Corrigé

- **⛔ « Capturer mon inventaire » capture maintenant ton inventaire.** Dans la
  0.9.0, il ne pouvait pas : pour cliquer sur le bouton, la fenêtre de Butin
  doit être devant, et elle recouvre le jeu. La capture prenait donc Butin, pas
  ton inventaire.

  Elle part désormais **6 secondes après le clic**, avec un compte à rebours
  affiché : tu cliques, tu bascules sur le jeu, tu ouvres ton inventaire, et
  l'image se prend toute seule.

  La consigne affichée demandait d'ailleurs l'impossible — « ouvre ton
  inventaire avant de cliquer » — elle dit maintenant l'ordre réel.

## [0.9.0] - 2026-08-08

### Ajouté

- **Un bouton « Capturer mon inventaire ».** L'inventaire est la seule vérité
  qui ne passe par aucune reconnaissance d'écran : le compteur et le banc
  d'essai lisent les mêmes pixels avec le même moteur, donc ils peuvent se
  tromper ensemble, et seul un inventaire compté à la main peut les contredire
  tous les deux.

  Jusqu'ici cette vérité n'existait que dans ta tête, recopiée à la main. Une
  session finie sans ce geste était perdue : l'inventaire, lui, continue de
  bouger.

  ⚠️ **Ouvre ton inventaire dans le jeu avant de cliquer.** La capture prend
  l'écran tel qu'il est, elle ne peut pas deviner.

  ⛔ Elle ne touche jamais au jeu : aucune frappe, aucun clic envoyé au client.
  Elle reste sur ton disque et part avec l'archive, si tu la déposes.

### Modifié

- **Les fenêtres rouvrent là où tu les avais laissées.** Le panneau est placé à
  la main, par-dessus le jeu, à l'endroit précis où il ne gêne pas. Une mise à
  jour le rouvrait au centre, donc il fallait le replacer à chaque version.

  ⚠️ Une position devenue invisible n'est jamais réutilisée : si tu débranches
  un écran, la fenêtre revient à sa place par défaut plutôt que de s'ouvrir
  dans le vide.

## [0.8.1] - 2026-08-08

### Ajouté

- **⛔ Butin te dit quand il ne voit plus le chat.** C'était la panne
  invisible : le logiciel tourne, le calibrage est bon, et pourtant plus rien
  n'est compté. À l'écran, ça ressemble exactement à un farm calme.

  Sur une vraie session, un menu ouvert a recouvert le chat pendant **quatre
  minutes**. Butin a continué d'afficher son total et son silver par heure sans
  un mot, et il manquait **560 objets sur 4 080**.

  Le panneau affiche maintenant, en rouge : « Le chat n'est plus visible depuis
  4 min 7 s — rien n'est compté. Un menu le recouvre, ou la fenêtre a bougé. »

  ⚠️ Ça prévient, ça n'arrête rien. Ouvrir ta carte dix secondes ne doit pas te
  faire perdre ce qui est déjà compté.

### Modifié

- **Le panneau grandit avec le nombre d'objets.** Il était figé, et au-delà
  d'une certaine hauteur les objets n'étaient ni coupés ni signalés : ils
  étaient **absents**. Il suit maintenant sa liste, sans jamais dépasser une
  taille qui couvrirait ton écran de jeu — au-delà, la liste défile.

- **L'écran d'autorisation Discord est annoncé avant de s'ouvrir.** Il affiche
  « Rubin » et non « Butin », parce que les deux logiciels partagent le même
  serveur. Se le voir demander sans prévenir ressemble à du hameçonnage, et se
  méfier serait la bonne réaction.

## [0.8.0] - 2026-08-07

### Corrigé

- **⛔ Butin n'invente plus de drop quand la reconnaissance rabote une
  quantité.** Sur une vraie session, il a compté **492 objets pour 477
  réellement ramassés**. Sept de ces quinze unités de trop viennent d'ici.

  Le jeu n'écrit jamais « x1 » : il indique 1 en n'écrivant **aucune**
  quantité. Quand la lecture coupe la fin d'une ligne, elle produit exactement
  la même chose — et cette ligne amputée ressemblait alors à un second drop,
  d'une unité, qui n'avait jamais eu lieu.

  Une ligne dont la quantité a disparu est désormais reconnue comme la même
  ligne, pas comme une nouvelle.

  ⚠️ Ce que ça coûte, dit franchement : un vrai drop d'un seul exemplaire qui
  suit un drop du même objet dans la même minute peut maintenant être fondu
  dans le précédent, donc manqué. C'est voulu. Un chiffre un peu bas se
  rattrape, un chiffre inventé ne se voit pas.

  ⚠️ Et ça n'explique pas tout : sur les quinze unités d'écart de cette
  session, huit restent inexpliquées.

### Retiré

- **Le lien « Voir la version » de l'en-tête.** Il ne servait que si la mise à
  jour automatique échouait ; dans ce cas il reste le message d'erreur et le
  bouton « Réessayer ».

## [0.7.0] - 2026-08-07

### Corrigé

- **⛔ Butin te prévient quand le calibrage est mauvais, au lieu de l'accepter
  en silence.** C'était le vrai coupable des chiffres qui ne veulent rien dire.

  Sur une session réelle, un recalibrage en cours de route a remplacé une zone
  de 22 rangées par une de 5, avec un pas de ligne presque double. Résultat :
  **29 lectures sur 38 ne voyaient plus rien**, et l'écran affichait « Zone
  calibrée » comme si tout allait bien. Un compteur qui ne compte rien ressemble
  à un farm pauvre, et rien ne permettait de faire la différence.

  Le calibrage passait chaque contrôle de justesse, et personne ne regardait la
  combinaison. Maintenant, un bloc rouge liste ce qui cloche et te dit quand le
  calibrage d'avant était meilleur.

  ⭐ À retenir : ce n'est pas le nombre de lignes de chat qui fausse le
  comptage. Avec un bon calibrage, une session a compté **107 objets pour 107
  réellement ramassés**, sur 22 rangées.

### Modifié

- **Le jeu passe devant la reconnaissance.** Elle tournait à la même priorité
  que le reste, sur toutes les unités du processeur, et ça se sentait en
  jouant.

  Le fil de capture demande maintenant à être servi après le jeu. Mesuré à
  charge réaliste : **+27,8 % de temps processeur rendu au jeu, pour 2,1 % de
  reconnaissance en plus**, sans perdre une seule lecture ni une seule ligne.

  ⚠️ Rien de ce qui est lu ne change : c'est une question d'ordre de passage,
  pas de calcul.

## [0.6.0] - 2026-08-07

### Ajouté

- **Un bouton « Préparer une archive », sous le rapport de bogue.** Écrire
  « le compteur se trompe » ne suffit pas à comprendre pourquoi : la réponse
  est dans le journal de lecture, ligne par ligne, et personne ne va copier
  quinze mille lignes dans un salon. Le bouton rassemble les trois derniers
  journaux, tes réglages, ton calibrage, un contexte technique et une image de
  la zone lue, puis ouvre le dossier sur l'archive.

  **Elle n'est envoyée à personne.** Elle contient les messages des autres
  joueurs, parce que la reconnaissance lit la zone de chat telle quelle : c'est
  à toi de décider si tu la déposes, et son contenu s'affiche avant pour que tu
  saches ce qu'il y a dedans. Ton identifiant de contributeur n'y entre jamais.

- **Un bouton « Se connecter à Discord », à côté du lien vers le salon.** Une
  fois le compte rattaché, l'en-tête affiche « Connecté en tant que … », et tes
  rapports de bogue portent ton pseudonyme au lieu d'un numéro anonyme.

  Le pseudonyme vient toujours du serveur, jamais d'un champ à remplir : sans
  ça, n'importe qui pourrait signaler un problème sous le nom d'un autre joueur.

  ⚠️ L'écran d'autorisation de Discord annonce « Rubin » : les deux logiciels
  partagent le même serveur, et c'est lui qui est enregistré.

### Corrigé

- **⛔ Butin se relance après une mise à jour.** Il ne revenait pas :
  l'application se fermait, les fichiers étaient remplacés, et plus rien. Vu de
  l'extérieur, une mise à jour qui fait disparaître le logiciel pour de bon.

  La réouverture était confiée au Gestionnaire de redémarrage de Windows, qui
  ne la faisait pas. Elle est maintenant demandée explicitement à l'installeur,
  et vérifiée sur une vraie installation.

## [0.5.1] - 2026-08-07

### Modifié

- **Le contrôle d'une session se fait maintenant objet par objet, et on ne
  demande plus un écart mais le nombre réel.** Cliquer « Écart » déplie la
  liste de ce que la session a compté, du plus nombreux au moins nombreux, et
  il suffit d'écrire à côté combien tu en as vraiment dans ton inventaire. La
  soustraction, c'est le logiciel qui la fait.

  Un objet laissé vide reste **« pas vérifié »**, et c'est une réponse
  valable : certains objets partent dans un autre inventaire et personne n'ira
  les compter. Ils ne sont donc jamais comptés comme justes, ce qui ferait
  passer pour vérifié quelque chose que personne n'a regardé.

  Les objets les plus nombreux arrivent en premier parce que c'est là que le
  compteur se trompe : vérifier les trois premiers suffit le plus souvent.
  Le constat part dans le salon Discord avec le détail par objet — un écart
  global ne dit pas **où** ça dérape, alors que c'est toute la question.

### Corrigé

- **L'en-tête n'affiche plus rien quand il n'y a rien à afficher.** Il montrait
  jusqu'à trois éléments — un bouton, un lien et une phrase — pour annoncer
  qu'aucune mise à jour n'était disponible. La phrase, en particulier, restait
  affichée indéfiniment, bien après que sa cause avait disparu. Quand une
  version existe, il n'y a plus qu'un seul bouton à côté du numéro ; le lien
  vers la page de la version n'apparaît qu'en cas d'échec, là où il sert.

- **La marque de l'en-tête est plus grande.** À 22 px, son trait fin se lisait
  mal — le même défaut qui la rendait illisible dans la barre des tâches.

- **Des drops étaient perdus quand la reconnaissance collait deux mots.** Le
  jeu écrit « Sceau de l'Agent » ; la lecture rend parfois « Sceau del'Agent »,
  ou remplace le `l` par un `I` majuscule. Le nom recollé ne correspondait plus
  à rien et le drop disparaissait sans un mot. Les noms qui contiennent « l' »
  cumulent les deux défauts, donc ce sont eux qui disparaissaient le plus.

  La comparaison ignore désormais les espaces et ne distingue plus les glyphes
  qui se ressemblent. Deux objets réellement différents qui deviendraient
  indistinguables sont refusés plutôt que devinés : mieux vaut un drop manquant
  qu'un drop attribué au mauvais objet.

- **L'icône du logiciel était illisible en petit.** Dans la barre des tâches et
  dans la liste de l'explorateur de fichiers — donc là où on la regarde le plus
  souvent — elle n'apparaissait que comme une tache sombre. Le trait doré, fin,
  se noyait dans le fond en rapetissant. Il est désormais épaissi et éclairci
  aux petites tailles, et le sac se reconnaît à 16 px comme à 256.

### Connu et non résolu

- ⛔ **Le sur-comptage signalé le 07/08 n'est toujours pas résolu.** La cause
  n'est pas tranchée : on ne sait pas encore si le jeu affiche réellement la
  même ligne plusieurs fois ou si c'est la lecture qui la duplique.

  Ce qui change avec cette version : le **contrôle objet par objet** et le
  **fichier de diagnostic** donnent enfin de quoi le mesurer au lieu de le
  deviner. Si un total te paraît trop élevé, compare à ton inventaire et dis-le
  avec le bouton « Écart » — c'est la seule chose qui puisse trancher.

- **La mise à jour en un clic fonctionne à partir de la 0.5.0.** Depuis une
  version antérieure, il faut installer à la main une dernière fois.

## [0.5.0] - 2026-08-07

### Modifié

- **Le bouton de mise à jour installe désormais la nouvelle version et rouvre
  Butin tout seul**, au lieu d'ouvrir la page GitHub et de laisser tout le
  reste à faire à la main. Un clic, une barre d'état, et le logiciel se
  rouvre : le même geste que dans Rubin.

  L'installeur téléchargé est **vérifié avant d'être exécuté** : s'il ne
  correspond pas exactement à ce que la version publiée annonce, rien n'est
  écrit sur le disque et rien n'est lancé. Une mise à jour ratée le dit,
  laisse le bouton réessayer, et le lien vers la page des versions reste
  offert à côté pour ceux qui préfèrent lire les notes ou installer à la main.

- **Le bouton Discord porte enfin le logo de Discord.** Celui d'avant était un
  dessin fait à la main qui ne ressemblait à rien de reconnaissable. Il est
  aussi devenu un vrai bouton plein, au lieu d'un contour si discret qu'il se
  confondait avec les réglages posés à côté.

- **Butin a son icône**, dans la barre des tâches, dans l'explorateur de
  fichiers et dans les deux fenêtres du logiciel.

- **La fenêtre principale se manipule au clavier.** Chaque bouton, chaque case
  et chaque champ montre désormais où l'on se trouve quand on navigue à la
  touche de tabulation ; il n'y en avait que deux qui le faisaient.

### Ajouté

- **Bouton « Envoyer le rapport »** dans les Réglages : signaler un problème
  part directement dans le salon Discord, avec la date et un pseudonyme, sans
  quitter l'application. La version, la zone calibrée et l'état de la capture
  sont joints automatiquement — un rapport sans ces informations oblige à un
  aller-retour que personne ne fera après avoir perdu une session de farm.
  Rien d'autre ne part, et rien ne part sans ce bouton.

  Le message passe par un relais sur `rubin.maxyull.fr` : **Butin ne connaît
  jamais l'adresse du salon Discord**. C'est délibéré. L'application est
  distribuée publiquement, donc une adresse d'envoi embarquée dedans serait
  lisible par n'importe quel joueur, le salon deviendrait ouvert au spam, et
  la refermer obligerait à republier l'application entière.

  Un identifiant anonyme, tiré au sort une fois et gardé sur cette machine,
  permet de reconnaître deux rapports du même joueur ; il ne contient rien qui
  identifie la personne ni la machine.

- **Une colonne « Contrôle » dans l'Historique.** Après une session, deux
  boutons : le compte était **exact**, ou il y avait un **écart** — et dans ce
  cas, de combien d'unités. C'est comparé à votre inventaire dans le jeu, donc
  à quelque chose que le logiciel ne peut pas lire lui-même, et c'est la seule
  façon de savoir s'il compte juste. Le constat part dans le salon Discord
  avec le contexte de la session.

  Une session non contrôlée reste marquée comme telle : ne pas savoir n'est
  pas la même chose que savoir que c'était bon.

- **Un fichier de diagnostic par session**, dans `Documents\BDO Tracker\rapports`.
  Il note ce que la reconnaissance a lu et ce qui en a été compté, ligne par
  ligne. Quand un chiffre paraît faux, tout ce qu'il faut pour comprendre est
  déjà écrit, sans qu'on ait eu à prévoir le problème.

  Il reste **sur votre machine** et n'est jamais envoyé tout seul : le
  logiciel lit la zone de chat telle qu'elle est, donc un message d'un autre
  joueur qui y passerait s'y retrouverait aussi. C'est à vous de le joindre à
  un rapport si vous le voulez.

### Connu et non résolu

- ⛔ **Un sur-comptage a été signalé le 07/08 et n'est PAS résolu dans cette
  version.** Sur une session de deux minutes, le compteur a annoncé 2 113
  unités d'un même objet, pour un total de 6,78 milliards de silver par heure
  qui n'est pas crédible. La lecture montrait la même ligne trois fois de
  suite ; on ne sait pas encore si le jeu l'a réellement affichée trois fois
  ou si c'est la lecture qui l'a dupliquée.

  **C'est justement ce que la colonne « Contrôle » et le fichier de diagnostic
  de cette version servent à trancher.** En attendant, un total qui vous
  paraît trop élevé l'est probablement : comparez à votre inventaire avant de
  vous fier au chiffre.

- **L'envoi de rapports vers Discord n'est pas encore branché côté serveur.**
  Le bouton existe et le dit franchement quand vous cliquez, plutôt que de
  faire semblant.

- **La mise à jour en un clic ne fonctionnera qu'à partir de cette version.**
  Les versions 0.1.0 à 0.4.0 ne publiaient pas l'empreinte qui permet de
  vérifier l'installeur avant de l'exécuter : mettre à jour depuis l'une
  d'elles se fait à la main, une dernière fois.

## [0.4.0] - 2026-08-06

### Ajouté

- **Bouton « Recalibrer » dans le panneau posé sur le jeu**, utilisable
  PENDANT une session sans avoir à l'arrêter. Jusqu'ici, si le joueur
  déplaçait la fenêtre de chat du jeu en cours de farm, la zone calibrée
  restait fausse jusqu'à la fin de la session — recalibrer demandait de
  quitter le panneau et de revenir aux Réglages. Recalibrer suspend la
  capture, enregistre la nouvelle zone, puis relance avec une boucle neuve
  (même garantie que la reprise après pause : la première lecture n'invente
  rien de ce qui est déjà à l'écran), sans jamais faire repartir le total à
  zéro. Pas de détection automatique d'un déplacement : uniquement un geste
  explicite du joueur, conformément au principe qui tranche tout dans ce
  projet (rater un drop est acceptable, en inventer ne l'est jamais).
- **Les zones de farm sont traduites en français**, et une session est
  désormais nommée automatiquement dans cette langue (`Mine de fer
  abandonnée`, pas `Abandoned Iron Mine`) : la seule chose du produit qui
  restait en anglais malgré lui. 94 zones recoupées entre bdocodex et
  bdolytics, 66 par les deux sources, 28 par bdolytics seul faute de
  marqueur correspondant sur la carte de bdocodex (source primaire au même
  titre, pas une traduction tierce). Une zone sans traduction connue reste
  affichée en anglais plutôt que de ne rien afficher.

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
