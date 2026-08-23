"""Rend le paquet `ht` importable quel que soit le répertoire d'appel de pytest."""
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))
