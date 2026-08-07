# Construire une distribution autonome de Butin

Jusqu'ici, utiliser Butin demandait de cloner le dépôt et de lancer `pip`.
`installeur/butin.spec` produit une distribution qui n'a besoin ni de Python ni
de `pip` : un dossier à copier, avec `butin.exe` dedans.

## Ce qui est fait

```
python -m pip install -e ".[installeur]"
.venv\Scripts\pyinstaller installeur\butin.spec --noconfirm
```

Écrit `dist\butin\`, environ 236 Mo. `dist\butin\butin.exe` est le lanceur
sans console (le même que `butin-app` en développement) ; toutes ses
dépendances vivent à côté, dans `dist\butin\_internal\`.

**Vérifié pour de vrai le 05/08/2026**, pas seulement « ça compile » :

- la fenêtre s'ouvre, avec le bon titre, et sert la page correctement ;
- le moteur de reconnaissance (rapidocr-onnxruntime, le morceau le plus à
  risque : 15 Mo de modèles `.onnx` qu'aucun hook PyInstaller standard ne sait
  trouver tout seul) lit une vraie capture d'écran et rend le bon texte,
  vérifié sur un exécutable figé séparé qui ne fait que ça ;
- le catalogue d'objets et les données du dépôt (`data/butin-connu.json`) sont
  bien à leur place et lisibles — c'est précisément ce que corrige
  `paths.bundled_data_dir()`, une régression silencieuse trouvée en préparant
  cette distribution : `Path(__file__).resolve().parents[N]` suppose un
  checkout git, et se trompe de dossier sans la moindre erreur une fois figé.

## Pourquoi un fichier `.spec` et pas une simple commande

Trois choses que PyInstaller ne devine pas tout seul, détaillées dans
`butin.spec` :

1. `butin/app.py` a des imports relatifs, donc ne peut pas être le script figé
   directement — `lancer_butin.py` existe pour ça.
2. La page web (`butin/ui/static/`) et les données du dépôt
   (`data/butin-connu.json`, `data/noms-verifies.json`) doivent atterrir aux
   mêmes chemins relatifs qu'en développement, sinon le code qui les cherche
   se trompe.
3. Les modèles du moteur OCR sont des données pures dans le paquet
   `rapidocr_onnxruntime`, qu'aucun hook standard ne rapatrie automatiquement.

## L'installeur Windows : FAIT et vérifié pour de vrai (06/08/2026)

`butin.iss` ([Inno Setup](https://jrsoftware.org/isinfo.php), installé via
`winget install JRSoftware.InnoSetup`) prend `dist\butin\` en entrée et produit
un vrai `.exe` d'installation :

```
.venv\Scripts\pyinstaller installeur\butin.spec --noconfirm
iscc installeur\butin.iss
```

Écrit `dist\butin-<version>-installation.exe`. **Installation par utilisateur,
sans droits administrateur** (`PrivilegesRequired=lowest`,
`{localappdata}\Programs\Butin`) : cohérent avec un logiciel qui n'écrit déjà
nulle part ailleurs que dans le profil de l'utilisateur (voir CLAUDE.md,
section 2ter).

**Vérifié pour de vrai sur cette machine**, cycle complet en silencieux
(`/VERYSILENT /SUPPRESSMSGBOXES`) :

- installation : `butin.exe` en place, raccourci Menu Démarrer créé, la
  fenêtre s'ouvre avec le bon titre ;
- désinstallation : `butin.exe` et le raccourci disparaissent, le dossier
  d'installation est retiré en entier ;
- ⚠️ **le point qui comptait le plus** : `Documents\BDO Tracker` (l'historique
  réel de farm de Maxime, pas une donnée de test) est resté **intact** après
  la désinstallation. `butin.iss` n'a délibérément aucune section
  `[UninstallDelete]` qui y pointerait : voir le commentaire de tête du
  fichier.

**L'icône** (`butin.ico`) est faite aussi : une bourse dorée au trait facetté
sur fond sombre, en sept résolutions de 16 à 256 px, embarquée à la fois dans
`butin.exe` (via `butin.spec`) et dans l'installeur lui-même (`SetupIconFile`
dans `butin.iss`).

⚠️ Ce paragraphe a décrit jusqu'au 07/08/2026 « une gemme dorée » « générée en
interne (PIL, aucun actif téléchargé) ». Les deux étaient faux : le dessin est
une bourse, et il ne sort pas de PIL. Il vient d'un modèle d'image, PIL ne fait
que le détourage et le rendu de chaque résolution. La provenance exacte est
dans `ATTRIBUTION.md`, qui est l'endroit où ce dépôt en répond.

## La construction en une commande : FAIT (06/08/2026)

```
installeur\construire.ps1
```

Enchaîne PyInstaller puis ISCC, et **refuse de construire** si `MyAppVersion`
dans `butin.iss` diverge de la version dans `pyproject.toml`, plutôt que de
produire un installeur qui affiche le mauvais numéro en silence. Testé pour
de vrai : code de sortie 0, installeur produit et daté fraîchement, message
d'erreur clair et actionnable si Inno Setup est introuvable ou si les deux
versions divergent.

Les deux gestes qu'il remplace restent utilisables séparément si besoin
(`.venv\Scripts\pyinstaller installeur\butin.spec --noconfirm` puis
`iscc installeur\butin.iss`), mais `MyAppVersion` reste alors à vérifier à
la main.

La vérification de mise à jour au lancement (`src/butin/update.py`) est
faite aussi, demandée par Maxime le 06/08/2026 : Butin signale une nouvelle
version disponible par un bouton à côté du numéro de version, sans jamais la
télécharger ni l'installer seul. Trois versions sont publiées depuis
(`v0.1.0`, `v0.2.0`, `v0.3.0`), elle a donc quelque chose à comparer.

## Ce qui manque encore

**Vérifier sur une machine sans Python ni Visual C++ Redistributable
installés.** Toutes les vérifications ci-dessus ont eu lieu sur la machine de
développement, où tout est déjà présent. `onnxruntime` a des dépendances
natives ; rien n'indique qu'il en manque, mais rien ne l'a testé sur un poste
vraiment vierge (pas de VM disponible ici).

## Fichiers de ce dossier

- `butin.spec` : la configuration PyInstaller, commentée sur le pourquoi de
  chaque choix.
- `lancer_butin.py` : le point d'entrée figé, qui délègue à `butin.app.main`.
- `butin.iss` : le script Inno Setup, commenté sur le pourquoi de chaque choix
  (installation sans droits administrateur, données utilisateur jamais
  supprimées à la désinstallation, version à resynchroniser à la main).
- `butin.ico` : l'icône de l'application et de l'installeur, sept résolutions.
- `construire.ps1` : enchaîne PyInstaller et Inno Setup, vérifie la
  synchronisation de version avant de construire.
