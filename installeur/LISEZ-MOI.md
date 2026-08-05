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

## Ce qui manque encore, dans l'ordre

1. **Un vrai installeur.** Ce qu'on a est un dossier à copier-coller, pas une
   installation Windows normale : pas d'entrée dans le menu Démarrer, pas de
   désinstallation propre, pas de mise à jour. La suite logique est
   [Inno Setup](https://jrsoftware.org/isinfo.php), qui prend `dist\butin\` en
   entrée et produit un `.exe` d'installation classique. Pas fait ici : c'est
   un outil externe, à installer et vérifier sur une machine à part avant de
   l'ajouter à ce dossier.
2. **Une icône.** L'exécutable a l'icône par défaut de PyInstaller. Cosmétique,
   mais c'est la première chose qu'on voit dans l'explorateur de fichiers.
3. **Vérifier sur une machine sans Python ni Visual C++ Redistributable
   installés.** Cette vérification a eu lieu sur la machine de développement,
   où tout est déjà présent. `onnxruntime` a des dépendances natives ; rien
   n'indique qu'il en manque, mais rien ne l'a testé non plus sur un poste
   vraiment vierge.
4. **Automatiser la construction.** Pour l'instant c'est une commande à taper
   à la main. Un script ou une étape d'intégration continue viendra une fois
   le format de distribution stabilisé (installeur compris) : automatiser un
   format qui va encore changer serait du travail à refaire.

## Fichiers de ce dossier

- `butin.spec` : la configuration PyInstaller, commentée sur le pourquoi de
  chaque choix.
- `lancer_butin.py` : le point d'entrée figé, qui délègue à `butin.app.main`.
