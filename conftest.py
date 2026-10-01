"""Conftest de raíz: asegura que `src` sea importable al correr `pytest`
desde cualquier directorio, sin necesitar instalar el proyecto como
paquete (`pip install -e .`) ni configurar `PYTHONPATH` a mano.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
