"""Tests de scripts/manim_runner.py: construccion del comando, entorno de
render y renders reales (marcados @pytest.mark.render) sobre escenas legado."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from scripts.manim_runner import (
    RAIZ,
    construir_comando,
    ejecutar_manim,
    entorno_render,
)

RUTA_HITO1 = RAIZ / "ejemplos" / "legado" / "test_hito1.py"
RUTA_HITO6_ROTO = RAIZ / "ejemplos" / "legado" / "test_hito6_broken.py"


def test_construir_comando_no_incluye_preview_y_usa_media_dir(tmp_path):
    comando = construir_comando("escena.py", "MiClase", calidad="borrador", media_dir=tmp_path)

    assert "-p" not in comando
    assert "--preview" not in comando
    assert "--media_dir" in comando
    indice = comando.index("--media_dir")
    assert comando[indice + 1] == str(tmp_path)
    assert "-ql" in comando
    assert "MiClase" in comando


def test_entorno_render_pythonpath_absoluto():
    env = entorno_render("media")

    assert env["SHORT_CALIDAD"] == "media"
    assert env["PYTHONIOENCODING"] == "utf-8"
    rutas = env["PYTHONPATH"].split(os.pathsep)
    assert str(RAIZ) in rutas
    assert Path(rutas[0]).is_absolute()


def test_entorno_render_auditar_agrega_variable():
    env = entorno_render("borrador", auditar=True)

    assert env["SHORT_AUDITAR"] == "1"


@pytest.mark.render
def test_ejecutar_manim_render_exitoso_genera_mp4(tmp_path):
    resultado = ejecutar_manim(
        str(RUTA_HITO1), "PruebaSistema", calidad="borrador", media_dir=tmp_path
    )

    assert resultado.exito is True
    assert bool(resultado) is True
    assert resultado.ruta_video is not None
    assert resultado.ruta_video.exists()
    assert resultado.ruta_video.parent.name == "960p30"
    assert resultado.reporte_error is None


@pytest.mark.render
def test_ejecutar_manim_render_fallido_genera_reporte_con_nameerror(tmp_path):
    ruta_reporte = RUTA_HITO6_ROTO.parent / "reporte_error.json"
    try:
        resultado = ejecutar_manim(
            str(RUTA_HITO6_ROTO), "VideoRoto", calidad="borrador", media_dir=tmp_path
        )

        assert resultado.exito is False
        assert bool(resultado) is False
        assert resultado.ruta_video is None
        assert resultado.reporte_error == ruta_reporte
        assert ruta_reporte.exists()

        contenido = json.loads(ruta_reporte.read_text(encoding="utf-8"))
        assert "NameError" in contenido["traceback_completo"] or "NameError" in contenido["excepcion_principal"]
        assert contenido["calidad"] == "borrador"
    finally:
        if ruta_reporte.exists():
            ruta_reporte.unlink()
