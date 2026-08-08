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
#define MyAppVersion "0.11.0"
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
; ⛔ La fermeture pendant une mise à jour en un clic.
;
; `CloseApplications=force` fait fermer Butin par le Gestionnaire de
; redémarrage de Windows. Sans elle, l'installeur échouerait à écrire
; par-dessus un exécutable en cours d'exécution.
;
; ⛔ `RestartApplications` est passé à **no** le 07/08/2026, et ce n'est pas un
; renoncement : c'est le contraire.
;
; Il valait `yes`, et le relancement reposait donc entièrement sur le
; Gestionnaire de redémarrage de Windows. Constaté par Maxime en jouant :
; **Butin ne revenait pas** après une mise à jour. L'application se fermait,
; les fichiers étaient remplacés, et plus rien.
;
; Le relancement est désormais une ligne explicite de la section [Run],
; conditionnée à `/RELANCER`. Un mécanisme qu'on peut lire, tester et voir
; échouer, au lieu d'un comportement du système qu'on espère.
;
; ⚠️ Les deux ne doivent JAMAIS être actifs ensemble : le Gestionnaire de
; redémarrage et la section [Run] rouvriraient chacun leur exemplaire, et deux
; Butin en parallèle voudraient dire deux fils de capture sur la même session.
;
; ⛔ Corollaire à ne jamais défaire : l'application ne doit PAS se fermer
; elle-même après avoir lancé l'installeur. Se fermer avant que le
; Gestionnaire de redémarrage ait enregistré le processus l'empêche de faire
; son travail de fermeture propre. Voir `src/butin/autoupdate.py`.
CloseApplications=force
RestartApplications=no
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
; Installation manuelle : la case « Lancer Butin » de la dernière page.
; `skipifsilent` la retire en mode silencieux, ce qui est correct ICI — mais
; c'était la seule chose qui relançait l'application, et la mise à jour en un
; clic passe justement en `/VERYSILENT`. Voir la ligne suivante.
Filename: "{app}\{#MyAppExeName}"; Description: "Lancer {#MyAppName}"; Flags: nowait postinstall skipifsilent

; ⛔ Le relancement après une mise à jour en un clic, EXPLICITE.
;
; Il reposait avant sur `RestartApplications=yes` seul, c'est-à-dire sur le
; Gestionnaire de redémarrage de Windows. Constaté par Maxime le 07/08/2026 :
; Butin ne revenait pas. L'application se fermait, les fichiers étaient
; remplacés, et plus rien — ce qui, vu du joueur, ressemble à une mise à jour
; qui casse le logiciel.
;
; On ne dépend plus du Gestionnaire de redémarrage pour rouvrir : il ferme
; (`CloseApplications=force`), et c'est cette ligne qui rouvre. Un mécanisme
; explicite, qui se vérifie en lançant l'installeur.
;
; ⚠️ `/RELANCER` et non « toujours en silencieux » : `construire.ps1` installe
; aussi en silencieux pour vérifier le paquet, et il n'a aucune raison
; d'ouvrir une fenêtre à ce moment-là. Seule la mise à jour le demande.
Filename: "{app}\{#MyAppExeName}"; Flags: nowait; Check: RelancementDemande

; Pas de section [UninstallDelete] pointant vers Documents\BDO Tracker ou les
; réglages de l'utilisateur : ce sont SES données (historique de farm), pas
; des fichiers de l'application. Désinstaller Butin ne doit pas les emporter,
; au même titre qu'un changement de dossier de stockage ne déplace rien
; (voir CLAUDE.md, section 2ter). Seul {app} (le dossier d'installation
; lui-même) est retiré, comportement par défaut d'Inno Setup.

[Code]
{ ⚠️ Inno Setup n'a PAS de `CmdLineParamExists`, contrairement à ce qu'une
  première version de ce fichier affirmait en commentaire. ISCC l'a refusée
  net : « Unknown identifier ». Le parcours de `ParamStr` ci-dessous est
  l'idiome habituel, et il faut l'écrire soi-même.

  `CompareText` ignore la casse, donc `/relancer` marche aussi. }
function ParametrePresent(const Valeur: string): Boolean;
var
  I: Integer;
begin
  Result := False;
  for I := 1 to ParamCount do
    if CompareText(ParamStr(I), Valeur) = 0 then
    begin
      Result := True;
      Exit;
    end;
end;

{ Vrai quand la mise à jour en un clic a demandé le relancement.

  ⛔ Ne pas remplacer par `WizardSilent()`. Toute installation silencieuse
  relancerait alors l'application, y compris celle que `construire.ps1` fait
  pour vérifier le paquet — une fenêtre s'ouvrirait au milieu d'une
  construction, et le test d'installation ne testerait plus la même chose que
  ce qu'un joueur exécute. }
function RelancementDemande(): Boolean;
begin
  Result := ParametrePresent('/RELANCER');
end;
