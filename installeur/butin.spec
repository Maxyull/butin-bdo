# -*- mode: python ; coding: utf-8 -*-
"""Construit une distribution autonome de Butin, sans Python ni pip.

Pourquoi ce fichier, et pas seulement une commande PyInstaller
-----------------------------------------------------------------

Un simple `pyinstaller src/butin/app.py` échouerait déjà : ce fichier utilise
des imports relatifs, donc il ne peut pas être le script figé directement,
voir `lancer_butin.py`. Et deviner tout seul quelles données embarquer
échouerait en silence : la page web de l'interface, le butin connu du dépôt, et
les modèles du moteur de reconnaissance vivent tous dans des dossiers que
PyInstaller n'inspecte pas tout seul. Ce fichier rend ces décisions explicites,
relisibles, et reproductibles.

Ce que ça résout
-----------------

**Sans console** (`console=False`) : un point d'entrée `[project.scripts]`
ouvrirait une fenêtre de terminal noire à côté de l'application, ce qui est la
différence entre un logiciel et un script qu'on a lancé. `butin.app:main` est
déjà le lanceur pensé pour ça.

**Les données du dépôt** (`data/butin-connu.json`, `data/noms-verifies.json`) :
`paths.bundled_data_dir()` cherche sous `sys._MEIPASS` une fois figé. Sans les
embarquer ici au même chemin relatif (`data/`), le programme démarrerait
normalement mais afficherait tous les objets sans zone de farm ni valeur au
marchand, EN SILENCE — exactement le mode de défaillance que ce projet refuse.

**La page web** (`src/butin/ui/static/`) : `ui/server.py` la sert depuis un
chemin relatif à son propre fichier. Elle doit atterrir au même chemin relatif
dans la distribution figée (`butin/ui/static/`) pour que ce calcul reste juste.

**Les modèles du moteur de reconnaissance** (rapidocr-onnxruntime, ~15 Mo) :
PyInstaller ne les voit pas tout seul, ce sont des données pures dans le
paquet, pas du code. `collect_data_files` les récupère avec leur
`config.yaml`, au même endroit relatif que dans le paquet installé — c'est ce
chemin-là que rapidocr utilise pour les retrouver, figé ou non.

**L'icône** (`installeur/butin.ico`) : sans elle, `butin.exe` porte l'icône par
défaut de PyInstaller, la première chose vue dans l'explorateur de fichiers ou
le menu Démarrer. Générée en interne (gemme dorée sur fond sombre, pas d'actif
téléchargé), en sept résolutions de 16 à 256 px pour rester lisible aussi bien
en petite icône de barre des tâches qu'en grande vignette.

Usage
-----

    .venv\\Scripts\\pyinstaller installeur\\butin.spec

Écrit dans `dist/butin/`, un dossier autonome. `dist/butin/butin.exe` est ce
qu'on distribue, désormais via un vrai installeur Windows (`installeur/butin.iss`,
Inno Setup) plutôt qu'un dossier à copier-coller : voir `installeur/LISEZ-MOI.md`.

⚠️ Ni `dist/` ni `build/` ne sont versionnés : voir `.gitignore`. Une
distribution figée pèse plusieurs centaines de mégaoctets, et se reconstruit à
l'identique depuis ce fichier, il n'y a donc aucune raison de la garder dans
l'historique.
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

RACINE = Path(SPECPATH).parent  # noqa: F821 — SPECPATH est injecté par PyInstaller

a = Analysis(  # noqa: F821 — Analysis/EXE/COLLECT sont injectés par PyInstaller
    [str(RACINE / "installeur" / "lancer_butin.py")],
    pathex=[str(RACINE / "src")],
    datas=[
        (str(RACINE / "src" / "butin" / "ui" / "static"), "butin/ui/static"),
        (str(RACINE / "data" / "butin-connu.json"), "data"),
        (str(RACINE / "data" / "noms-verifies.json"), "data"),
        *collect_data_files("rapidocr_onnxruntime"),
    ],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="butin",
    console=False,
    # ⚠️ Sans console : c'est le point qui fait la différence entre un
    # logiciel et un script qu'on a lancé, voir la note d'en-tête de app.py.
    icon=str(RACINE / "installeur" / "butin.ico"),
)

COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    name="butin",
)
