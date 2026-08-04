"""Interface web locale.

Servie par la bibliothèque standard, sur la boucle locale uniquement. Voir
`server.py` pour la note de sécurité avant de toucher à l'adresse d'écoute.
"""

from .server import DEFAULT_PORT, HOST, AppState, build_server, serve

__all__ = ["DEFAULT_PORT", "HOST", "AppState", "build_server", "serve"]
