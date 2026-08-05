"""Point d'entrée pour PyInstaller, qui délègue au vrai point d'entrée du paquet.

`butin/app.py` utilise des imports relatifs (`from . import paths`), donc il ne
peut pas être le script figé directement : Python le refuserait avec « attempted
relative import with no known parent package », exactement comme le refuserait
un `python src/butin/app.py` lancé à la main plutôt qu'un `python -m butin.app`.

Ce fichier existe uniquement pour ça : il importe le paquet normalement, comme
le ferait le point d'entrée `butin-app` de `pyproject.toml`, puis délègue.
"""

from butin.app import main

if __name__ == "__main__":
    raise SystemExit(main())
