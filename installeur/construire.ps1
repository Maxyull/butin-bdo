<#
    Construit l'installeur Windows de Butin en une seule commande.

    Pourquoi ce script, et pas continuer à taper les commandes à la main
    -----------------------------------------------------------------------

    Jusqu'ici, produire un installeur demandait trois gestes séparés,
    documentés dans installeur/LISEZ-MOI.md :

        .venv\Scripts\pyinstaller installeur\butin.spec --noconfirm
        iscc installeur\butin.iss

    plus un troisième geste invisible dans la commande elle-même : vérifier à
    l'œil que `MyAppVersion` dans butin.iss est toujours celui de
    pyproject.toml avant de lancer ISCC. Ce troisième geste est justement
    celui que butin.iss signale en commentaire d'en-tête comme manuel et
    oubliable (« ⚠️ MyAppVersion est manuel, pas lu depuis pyproject.toml »).
    Un oubli n'échoue pas bruyamment : ISCC compile quand même, et produit un
    installeur qui s'affiche sous un numéro de version différent de celui
    réellement empaqueté. C'est exactement le genre de défaillance silencieuse
    que ce projet refuse (voir CLAUDE.md, section 1 : « inventer un drop donne
    un chiffre faux » — ici, inventer un numéro de version donne un installeur
    qui ment sur son propre contenu).

    Ce script rend donc ce contrôle systématique plutôt que mémorisé, et
    enchaîne les deux commandes de construction pour qu'il n'y ait plus qu'un
    seul geste à exécuter et à retenir.

    Usage
    -----

        installeur\construire.ps1

    À lancer depuis la racine du dépôt (comme les deux commandes qu'il
    remplace). Écrit dans dist\butin\ (la distribution PyInstaller) puis
    dist\butin-<version>-installation.exe (l'installeur Inno Setup), comme
    avant — ce script ne change aucun des deux formats de sortie, il ne fait
    qu'enchaîner et vérifier.
#>

$ErrorActionPreference = "Stop"

# Racine du dépôt = dossier parent de installeur\, où que ce script soit
# appelé depuis. Éviter de dépendre du répertoire courant : une des deux
# commandes qu'il remplace (iscc installeur\butin.iss) est déjà sensible à
# ça, autant ne pas ajouter une deuxième source d'erreur au même endroit.
$racineDepot = Split-Path -Parent $PSScriptRoot

$cheminPyproject = Join-Path $racineDepot "pyproject.toml"
$cheminIss = Join-Path $racineDepot "installeur\butin.iss"
$cheminSpec = Join-Path $racineDepot "installeur\butin.spec"
$cheminPyinstaller = Join-Path $racineDepot ".venv\Scripts\pyinstaller.exe"

# --- 1. Lire la version depuis pyproject.toml ---------------------------
#
# Une regex simple suffit : la ligne est écrite à la main dans un format
# fixe (voir pyproject.toml), pas besoin d'un vrai parseur TOML pour une
# seule clé qu'on sait déjà où trouver.
$ligneVersion = Select-String -Path $cheminPyproject -Pattern '^version\s*=\s*"([^"]+)"' | Select-Object -First 1
if (-not $ligneVersion) {
    Write-Error "Impossible de trouver la ligne « version = ""..."" » dans $cheminPyproject."
    exit 1
}
$versionPyproject = $ligneVersion.Matches[0].Groups[1].Value

# --- 2. Vérifier que butin.iss est synchrone avec pyproject.toml --------
#
# C'est le contrôle que ce script existe pour automatiser : sans lui, un
# oubli de synchronisation ne se voit qu'après coup, en lisant le numéro
# affiché par l'installeur déjà produit — trop tard pour un installeur déjà
# publié. On préfère arrêter la construction ici, avant même d'appeler
# PyInstaller, plutôt que de la laisser aboutir avec un mensonge dedans.
$ligneIss = Select-String -Path $cheminIss -Pattern '^#define MyAppVersion "([^"]+)"' | Select-Object -First 1
if (-not $ligneIss) {
    Write-Error "Impossible de trouver la ligne « #define MyAppVersion ""..."" » dans $cheminIss."
    exit 1
}
$versionIss = $ligneIss.Matches[0].Groups[1].Value

if ($versionIss -ne $versionPyproject) {
    Write-Error @"
Version désynchronisée entre pyproject.toml et installeur\butin.iss :

    pyproject.toml       -> $versionPyproject
    installeur\butin.iss -> $versionIss

Ce sont deux sources de vérité tenues à la main (voir le commentaire
d'en-tête de butin.iss). Corriger MyAppVersion dans installeur\butin.iss
pour qu'il vaille "$versionPyproject", puis relancer ce script.
"@
    exit 1
}

Write-Output "Version : $versionPyproject (pyproject.toml et butin.iss synchrones)."

# --- 3. Construire la distribution PyInstaller ---------------------------
Write-Output "Construction de dist\butin\ (pyinstaller installeur\butin.spec)..."
& $cheminPyinstaller $cheminSpec --noconfirm
if ($LASTEXITCODE -ne 0) {
    Write-Error "PyInstaller a échoué (code $LASTEXITCODE). Voir la sortie ci-dessus."
    exit 1
}

# --- 4. Trouver ISCC.exe et compiler l'installeur -------------------------
#
# Inno Setup s'installe soit dans le profil utilisateur, soit dans
# Program Files (x86), selon les options choisies à l'installation (winget
# ou l'installeur graphique) — les deux existent en pratique selon la
# machine. Chercher les deux plutôt que de supposer un seul chemin, et
# échouer avec un message actionnable si aucun n'existe, pas une erreur
# PowerShell brute du style « le terme 'iscc.exe' n'est pas reconnu ».
$candidatsIscc = @(
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
)
$cheminIscc = $candidatsIscc | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $cheminIscc) {
    Write-Error @"
ISCC.exe introuvable. Emplacements essayés :
$(($candidatsIscc | ForEach-Object { "  - $_" }) -join "`n")

Inno Setup 6 n'est pas installé, ou l'est ailleurs. L'installer via :
    winget install JRSoftware.InnoSetup
"@
    exit 1
}

Write-Output "Compilation de l'installeur (ISCC : $cheminIscc)..."
& $cheminIscc $cheminIss
if ($LASTEXITCODE -ne 0) {
    Write-Error "ISCC a échoué (code $LASTEXITCODE). Voir la sortie ci-dessus."
    exit 1
}

# --- 5. Afficher le résultat ----------------------------------------------
#
# OutputDir et OutputBaseFilename dans butin.iss fixent ce chemin ; le
# reconstruire ici plutôt que de le deviner dans les logs d'ISCC.
$cheminInstalleur = Join-Path $racineDepot "dist\butin-$versionPyproject-installation.exe"

if (Test-Path $cheminInstalleur) {
    $tailleMo = [Math]::Round((Get-Item $cheminInstalleur).Length / 1MB, 1)
    Write-Output "Installeur produit : $cheminInstalleur ($tailleMo Mo)"

    # --- 6. Publier l'empreinte à côté de l'installeur --------------------
    #
    # ⛔ Ce fichier n'est pas un à-côté : sans lui, la mise à jour en un clic
    # REFUSE de s'installer. `autoupdate.download_installer` télécharge
    # l'installeur ET son `.sha256`, compare en mémoire, et n'écrit rien si
    # les deux ne correspondent pas.
    #
    # TLS garantit que le fichier vient bien de GitHub ; il ne garantit pas
    # que c'est le BON fichier. Une construction interrompue ou une release
    # mal publiée produirait un binaire corrompu qu'on s'apprêterait à
    # exécuter avec les droits de l'utilisateur.
    #
    # ⚠️ Les deux fichiers doivent être joints à la Release GitHub, pas
    # seulement l'exécutable. Format `sha256sum` : empreinte, deux espaces,
    # nom du fichier.
    $empreinte = (Get-FileHash -Path $cheminInstalleur -Algorithm SHA256).Hash.ToLower()
    $nomFichier = Split-Path $cheminInstalleur -Leaf
    $cheminEmpreinte = "$cheminInstalleur.sha256"
    "$empreinte  $nomFichier" | Out-File -FilePath $cheminEmpreinte -Encoding ascii -NoNewline
    Write-Output "Empreinte publiée : $cheminEmpreinte"
    Write-Output "  $empreinte"
    Write-Output ""
    Write-Output "Joindre LES DEUX fichiers a la Release GitHub :"
    Write-Output "  gh release upload v<version> `"$cheminInstalleur`" `"$cheminEmpreinte`""
} else {
    # ISCC a rendu un code de sortie 0 mais le fichier attendu n'est pas là :
    # signaler plutôt que de laisser croire que tout s'est bien passé.
    Write-Error "ISCC a terminé sans erreur mais $cheminInstalleur est introuvable. Vérifier OutputDir et OutputBaseFilename dans butin.iss."
    exit 1
}
