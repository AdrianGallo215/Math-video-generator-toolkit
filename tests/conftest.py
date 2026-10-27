"""Configuracion compartida de pytest: raiz del repo en sys.path y fixtures comunes."""

import sys
from pathlib import Path

import pytest

RAIZ_REPO = Path(__file__).resolve().parents[1]

if str(RAIZ_REPO) not in sys.path:
    sys.path.insert(0, str(RAIZ_REPO))


@pytest.fixture
def raiz_repo() -> Path:
    """Devuelve la ruta absoluta a la raiz del repositorio."""
    return RAIZ_REPO


@pytest.fixture
def dir_temporal_media(tmp_path) -> Path:
    """Devuelve una ruta temporal para usar como directorio de media en tests."""
    return tmp_path / "media"
