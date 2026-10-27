"""Tests de scripts/capturar_fotogramas.py: captura de fotogramas y hojas de contacto
para QA visual, a partir de un mp4 sintetico generado con PyAV."""

from __future__ import annotations

from pathlib import Path

import av
import numpy as np
import pytest
from PIL import Image

from scripts.capturar_fotogramas import (
    _coords_pixeles,
    _generar_tiempos,
    capturar,
)

ANCHO_VIDEO = 540
ALTO_VIDEO = 960
DURACION_S = 4
COLORES_POR_SEGUNDO = [
    (255, 0, 0),
    (0, 255, 0),
    (0, 0, 255),
    (255, 255, 0),
]


def _crear_video_sintetico(ruta: Path) -> Path:
    """Crea un mp4 de DURACION_S segundos, 540x960, un color solido distinto por
    segundo (1 fotograma por segundo)."""
    with av.open(str(ruta), mode="w") as contenedor:
        flujo = contenedor.add_stream("libx264", rate=1)
        flujo.width = ANCHO_VIDEO
        flujo.height = ALTO_VIDEO
        flujo.pix_fmt = "yuv420p"
        for color in COLORES_POR_SEGUNDO:
            arreglo = np.zeros((ALTO_VIDEO, ANCHO_VIDEO, 3), dtype=np.uint8)
            arreglo[:, :] = color
            frame = av.VideoFrame.from_ndarray(arreglo, format="rgb24")
            for paquete in flujo.encode(frame):
                contenedor.mux(paquete)
        for paquete in flujo.encode():
            contenedor.mux(paquete)
    return ruta


@pytest.fixture
def video_sintetico(tmp_path: Path) -> Path:
    return _crear_video_sintetico(tmp_path / "sintetico.mp4")


def test_coords_pixeles_convierte_esquinas_de_la_zona_segura():
    zona = (-3.15, 3.15, -4.0, 5.6)
    x0, y0, x1, y1 = _coords_pixeles(zona, ancho=900, alto=1600)
    assert x0 == pytest.approx((1.35 / 9) * 900)
    assert x1 == pytest.approx((7.65 / 9) * 900)
    assert y0 == pytest.approx((2.4 / 16) * 1600)
    assert y1 == pytest.approx((12.0 / 16) * 1600)
    assert 0 <= x0 < x1 <= 900
    assert 0 <= y0 < y1 <= 1600


def test_generar_tiempos_usa_tiempos_explicitos_si_se_dan():
    tiempos = _generar_tiempos(duracion=4.0, cada=None, tiempos=[0.5, 3, 10.2])
    assert tiempos == [0.5, 3.0]


def test_generar_tiempos_usa_cada_por_defecto():
    tiempos = _generar_tiempos(duracion=4.0, cada=None, tiempos=None)
    assert tiempos[0] == 0.0
    assert tiempos[1] == pytest.approx(2.0)
    assert tiempos[-1] <= 4.0


def test_generar_tiempos_respeta_paso_cada(mensaje="cada=1 sobre 4s da 5 instantes"):
    tiempos = _generar_tiempos(duracion=4.0, cada=1.0, tiempos=None)
    assert tiempos == pytest.approx([0.0, 1.0, 2.0, 3.0, 4.0])


def test_capturar_genera_fotogramas_y_hoja(video_sintetico, tmp_path):
    salida = tmp_path / "qa"
    rutas = capturar(video=video_sintetico, salida=salida, cada=1.0)

    assert len(rutas) >= 4
    hojas = [r for r in rutas if r.name.startswith("hoja_")]
    fotogramas = [r for r in rutas if r.name.startswith("f_")]
    assert len(hojas) == 1
    assert len(fotogramas) >= 4
    for ruta in rutas:
        assert ruta.exists()

    # El primer fotograma (t=0) debe ser predominantemente rojo, el color del primer segundo.
    primero = sorted(fotogramas)[0]
    imagen = Image.open(primero).convert("RGB")
    r, g, b = imagen.getpixel((imagen.width // 2, imagen.height // 2))
    assert r > 200 and g < 60 and b < 60


def test_capturar_con_guias_no_falla_sin_toolkit_layout(video_sintetico, tmp_path):
    salida = tmp_path / "qa_guias"
    rutas = capturar(video=video_sintetico, salida=salida, cada=2.0, guias=True)
    assert any(r.name.startswith("hoja_") for r in rutas)
