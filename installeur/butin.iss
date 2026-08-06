; Butin — installeur Windows (Inno Setup).
;
; Pourquoi une installation par utilisateur, sans droits administrateur
; -----------------------------------------------------------------------
; Butin n'écrit jamais dans Program Files ni dans le dossier du jeu : ses
; données vivent dans Documents\BDO Tracker (voir CLAUDE.md, section 2ter).
; Rien ne justifie donc de demander les droits administrateur pour
; l'installer lui-même. `PrivilegesRequired=lowest` évite l'invite UAC, et
; l'installation va dans le profil de l'utilisateur plutôt que dans
; Program Files, cohérent avec le reste du produit.
;
; Ce script prend `dist\butin\` en entrée, produit par `butin.spec`.
; Construire la distribution AVANT de compiler ce script :
;
;     .venv\Scripts\pyinstaller installeur\butin.spec --noconfirm
;     iscc installeur\butin.iss
;
; Écrit dans `dist\butin-<version>-installation.exe`, à côté de `dist\butin\`
; (même dossier ignoré par git, voir `.gitignore` : un installeur pèse
; plusieurs centaines de mégaoctets et se reconstruit à l'identique).
;
; ⚠️ MyAppVersion est manuel, pas lu depuis `pyproject.toml` : automatiser
; cette lecture est noté comme travail futur dans LISEZ-MOI.md
; (« automatiser la construction »), à ne faire qu'une fois le format de
; distribution stabilisé. Jusque-là, le mettre à jour à la main à chaque
; publication, en même temps que `pyproject.toml` et `__init__.py`
; (voir docs/versionnage.md, étape 3 de la procédure de publication).

#define MyAppName "Butin"
#define MyAppVersion "0.2.0"
#define MyAppPublisher "Maxyull"
#define MyAppURL "https://github.com/Maxyull/butin-bdo"
#define MyAppExeName "butin.exe"

[Setup]
; GUID fixe pour ce produit : Inno Setup s'en sert pour reconnaître une
; installation existante d'une version à l'autre (mise à jour propre plutôt
; que deux installations côte à côte). Ne JAMAIS le changer.
AppId={{B7E5B5B4-6D9F-4B9B-9B3A-9F6C2F8D9B2E}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=butin-{#MyAppVersion}-installation
SetupIconFile=butin.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; Dépôt et interface en français : l'installeur aussi.
ShowLanguageDialog=no

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "desktopicon"; Description: "Créer un raccourci sur le Bureau"; GroupDescription: "Raccourcis supplémentaires :"; Flags: unchecked

[Files]
; ignoreversion : les fichiers de dist\butin\ n'ont pas de numéro de version
; individuel (modèles OCR, page web) — comparer un numéro qui n'existe pas
; empêcherait toute mise à jour de les remplacer.
Source: "..\dist\butin\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Désinstaller {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Lancer {#MyAppName}"; Flags: nowait postinstall skipifsilent

; Pas de section [UninstallDelete] pointant vers Documents\BDO Tracker ou les
; réglages de l'utilisateur : ce sont SES données (historique de farm), pas
; des fichiers de l'application. Désinstaller Butin ne doit pas les emporter,
; au même titre qu'un changement de dossier de stockage ne déplace rien
; (voir CLAUDE.md, section 2ter). Seul {app} (le dossier d'installation
; lui-même) est retiré, comportement par défaut d'Inno Setup.
