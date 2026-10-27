"""Tests de scripts/scaffold_video.py (T20): crea guion.md/escena.py/video.yaml,
no sobrescribe lo existente, la escena compila y el yaml valida con el esquema T12."""

from __future__ import annotations

import py_compile
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from scripts.producir_video import cargar_configuracion  # noqa: E402
from scripts.scaffold_video import crear_scaffold  # noqa: E402


def test_scaffold_crea_los_tres_archivos(tmp_path):
    directorio = tmp_path / "v99_prueba"

    creados = crear_scaffold(directorio, titulo="Prueba de scaffold", nombre_clase="EscenaPrueba")

    assert (directorio / "guion.md").is_file()
    assert (directorio / "escena.py").is_file()
    assert (directorio / "video.yaml").is_file()
    assert {p.name for p in creados} == {"guion.md", "escena.py", "video.yaml"}


def test_guion_incluye_las_secciones_obligatorias(tmp_path):
    directorio = tmp_path / "v98_prueba"
    crear_scaffold(directorio, titulo="Prueba", nombre_clase="EscenaPrueba")

    guion = (directorio / "guion.md").read_text(encoding="utf-8")

    for seccion in ("Idea clave", "Gancho", "Tabla de segmentos", "Paleta semántica", "Checklist QA"):
        assert seccion in guion, f"falta la seccion {seccion!r} en guion.md"
    for columna in ("Narración", "Visual", "Ancla", "Duración est."):
        assert columna in guion, f"falta la columna {columna!r} en la tabla de segmentos"


def test_no_sobrescribe_guion_existente_y_crea_solo_lo_que_falta(tmp_path):
    directorio = tmp_path / "v97_prueba"
    directorio.mkdir(parents=True)
    (directorio / "guion.md").write_text("contenido escrito a mano por G-VNN", encoding="utf-8")

    creados = crear_scaffold(directorio, titulo="Prueba", nombre_clase="EscenaPrueba")

    assert (directorio / "guion.md").read_text(encoding="utf-8") == "contenido escrito a mano por G-VNN"
    assert {p.name for p in creados} == {"escena.py", "video.yaml"}
    assert (directorio / "escena.py").is_file()
    assert (directorio / "video.yaml").is_file()


def test_falla_si_los_tres_archivos_ya_existen(tmp_path):
    directorio = tmp_path / "v96_prueba"
    crear_scaffold(directorio, titulo="Prueba", nombre_clase="EscenaPrueba")

    with pytest.raises(FileExistsError):
        crear_scaffold(directorio, titulo="Prueba", nombre_clase="EscenaPrueba")


def test_escena_generada_compila(tmp_path):
    directorio = tmp_path / "v95_prueba"
    crear_scaffold(directorio, titulo="Prueba con ñ y tildes: ¿cómo?", nombre_clase="EscenaPrueba")

    py_compile.compile(str(directorio / "escena.py"), doraise=True)


def test_video_yaml_generado_valida_con_el_esquema_t12(tmp_path):
    directorio = tmp_path / "v94_prueba"
    crear_scaffold(directorio, titulo="Prueba", nombre_clase="EscenaPrueba")

    config = cargar_configuracion(directorio / "video.yaml")

    assert config.slug == "v94_prueba"
    assert len(config.escenas) == 1
    assert config.escenas[0].clase == "EscenaPrueba"
    assert config.escenas[0].archivo == (directorio / "escena.py").resolve()
