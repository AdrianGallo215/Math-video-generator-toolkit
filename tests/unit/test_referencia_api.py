"""Verifica que docs/agentes/toolkit_reference.md cite API real (T20).

Extrae cada referencia con forma ``toolkit.<modulo>.<nombre>`` o
``scripts.<modulo>.<nombre>`` del documento e importa ``<modulo>`` comprobando que
``<nombre>`` existe. Así la referencia no puede quedar desactualizada en silencio: si
alguien renombra o borra una función/clase citada, este test falla.
"""

from __future__ import annotations

import importlib
import re
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

RUTA_REFERENCIA = RAIZ / "docs" / "agentes" / "toolkit_reference.md"

# ``paquete.modulo.nombre`` (paquete = toolkit|scripts); no exige backticks porque el
# documento también menciona símbolos dentro de bloques de código.
_PATRON_REFERENCIA = re.compile(r"\b(toolkit|scripts)\.([a-z_][a-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)\b")


def _referencias_citadas() -> list[tuple[str, str, str]]:
    texto = RUTA_REFERENCIA.read_text(encoding="utf-8")
    vistas: list[tuple[str, str, str]] = []
    for coincidencia in _PATRON_REFERENCIA.finditer(texto):
        terna = coincidencia.groups()
        if terna not in vistas:
            vistas.append(terna)
    return vistas


def test_referencia_existe() -> None:
    assert RUTA_REFERENCIA.is_file(), f"Falta {RUTA_REFERENCIA}"


def test_referencia_no_esta_vacia() -> None:
    referencias = _referencias_citadas()
    # Umbral bajo (no es un conteo exacto): solo detecta que el documento se vació o
    # que el patron de extraccion dejo de encontrar nada por un cambio de formato.
    assert len(referencias) > 50, (
        f"Solo se citaron {len(referencias)} simbolos toolkit./scripts. en la referencia; "
        "revisa que docs/agentes/toolkit_reference.md no se haya vaciado."
    )


@pytest.mark.parametrize("paquete,modulo,nombre", _referencias_citadas())
def test_simbolo_citado_es_importable(paquete: str, modulo: str, nombre: str) -> None:
    modulo_completo = f"{paquete}.{modulo}"
    mod = importlib.import_module(modulo_completo)
    assert hasattr(mod, nombre), (
        f"{modulo_completo}.{nombre} no existe: docs/agentes/toolkit_reference.md "
        "cita una API que ya no coincide con el código."
    )
