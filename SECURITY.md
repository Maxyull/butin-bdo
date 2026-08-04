# Politique de sécurité

## Signaler une faille

N'ouvrez pas d'issue publique pour une faille de sécurité.

Utilisez l'onglet **Security > Report a vulnerability** du dépôt, qui ouvre un
avis privé visible seulement par les mainteneurs.

Réponse sous 7 jours. Si la faille est confirmée, vous serez crédité dans le
correctif, sauf si vous préférez rester anonyme.

## Surface d'attaque

Butin est un logiciel de bureau sans serveur, sans compte et sans base de
données distante. Cela réduit beaucoup la surface, mais ne l'annule pas.

**Ce que Butin lit sans le contrôler :**

| Entrée | Origine | Protections |
| --- | --- | --- |
| Catalogue d'objets | `raw.githubusercontent.com` | HTTPS imposé, hôte en liste blanche, hôte revalidé après redirection, plafond de taille sur les octets lus, délais d'attente, analyse JSON stricte, validation de forme avant écriture, écriture atomique |
| Prix du marché | API publique du marché central | mêmes protections |
| Pixels de l'écran | capture d'écran locale | traités comme des images, jamais comme du code |
| Noms vérifiés | `data/noms-verifies.json` du dépôt | analyse stricte, échec net si mal formé |

**Ce que Butin n'écrit jamais :** rien dans le dossier d'installation de Black
Desert Online, rien hors des dossiers standards de l'utilisateur.

**Ce que Butin n'envoie jamais :** aucune donnée vous concernant ne quitte votre
machine. Il n'y a pas de télémétrie, pas de compte, pas de serveur.

## Choix de conception liés à la sécurité

**Aucune désérialisation exécutable.** Les données externes sont lues en JSON et
seulement en JSON. Ni `pickle`, ni `eval`, ni YAML : aucun de ces formats ne
peut être lu sans exécuter du code.

**Aucun binaire téléchargé à l'exécution.** Le moteur OCR arrive par `pip` avec
le reste des dépendances. Butin ne va jamais chercher d'exécutable sur internet
pendant qu'il tourne.

**Écriture atomique du cache.** Une coupure pendant l'écriture laisse l'ancien
cache intact plutôt qu'un fichier à moitié écrit.

**Dépendances surveillées.** `pip-audit` tourne en intégration continue et
Dependabot ouvre les mises à jour. Les actions GitHub sont épinglées par
empreinte de commit, pas par étiquette de version, qu'un amont peut déplacer.

**Recherche de secrets sur tout l'historique.** `gitleaks` scanne aussi les
anciens commits : sur un dépôt public, un secret retiré plus tard reste lisible.

## Vie privée

Une capture d'écran de Black Desert peut contenir votre pseudonyme, votre
guilde et le contenu du chat. C'est pourquoi :

- aucune capture n'est envoyée nulle part ;
- les captures de calibrage restent dans un dossier local exclu de git ;
- si vous joignez une capture à un rapport de bogue, **masquez le chat et le
  pseudonyme avant**.

## Versions suivies

Le projet est en développement actif avant sa première version publiée. Seule
la branche `main` reçoit des correctifs pour l'instant.
