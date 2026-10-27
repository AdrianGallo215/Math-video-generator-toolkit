"""Tests de las escenas base: alias de zoom, HUD fijo a camara, guias y sfx."""

import sys
import types
from pathlib import Path

import numpy as np
import pytest
from manim import MovingCameraScene, Square, Text, tempconfig

from toolkit.base_scene import PlantillaShort, Z_INDEX_GUIAS, Z_INDEX_HUD
from toolkit.utils_3d import PlantillaShort3D
from toolkit.utils_escalas import PlantillaShortZoom, zoom_out_exponencial


def _config_prueba(tmp_path) -> dict:
    """Config de manim para construir escenas sin escribir video."""
    return {
        "quality": "low_quality",
        "dry_run": True,
        "media_dir": str(tmp_path / "media"),
        "disable_caching": True,
    }


def _medidas_relativas(mob, frame) -> tuple[float, np.ndarray]:
    """(ancho_mob / ancho_frame, (centro_mob - centro_frame) / ancho_frame)."""
    ancho = frame.width
    return mob.width / ancho, (mob.get_center() - frame.get_center()) / ancho


def test_plantilla_zoom_es_alias_de_plantilla_short():
    assert issubclass(PlantillaShortZoom, MovingCameraScene)
    assert PlantillaShortZoom is PlantillaShort


def test_sfx_usa_ruta_sfx_y_add_sound(tmp_path, monkeypatch):
    """sfx() importa ruta_sfx de forma perezosa y delega en add_sound con la ganancia."""
    ruta_falsa = tmp_path / "sfx_pop.wav"
    modulo_falso = types.ModuleType("toolkit.audio_base")
    modulo_falso.ruta_sfx = lambda nombre: tmp_path / f"sfx_{nombre}.wav"
    monkeypatch.setitem(sys.modules, "toolkit.audio_base", modulo_falso)

    llamadas = []
    with tempconfig(_config_prueba(tmp_path)):
        for clase in (PlantillaShort, PlantillaShort3D):
            escena = clase()
            monkeypatch.setattr(
                escena, "add_sound", lambda archivo, gain=None, **kw: llamadas.append((archivo, gain))
            )
            escena.sfx("pop")
            escena.sfx("pop", ganancia_db=-3.0)

    assert llamadas == [
        (str(ruta_falsa), -8.0),
        (str(ruta_falsa), -3.0),
        (str(ruta_falsa), -8.0),
        (str(ruta_falsa), -3.0),
    ]


def test_zoom_out_exponencial_respeta_run_time(tmp_path):
    with tempconfig(_config_prueba(tmp_path)):
        escena = PlantillaShort()
        ancho = escena.camera.frame.width
        animacion = zoom_out_exponencial(escena, factor=4, run_time=2.5).build()
        assert animacion.run_time == pytest.approx(2.5)
        assert animacion.mobject.target.width == pytest.approx(ancho * 4)


@pytest.mark.render
def test_hud_mantiene_tamano_y_posicion_relativos_al_hacer_zoom(tmp_path):
    medidas = {}

    class EscenaHud(PlantillaShort):
        def construct(self):
            frame = self.camera.frame
            texto = Text("HUD").to_corner()
            cuadrado = Square()
            self.add(cuadrado)
            self.fijar_a_camara(texto)
            medidas["antes"] = _medidas_relativas(texto, frame)
            medidas["z"] = texto.z_index
            self.play(frame.animate.scale(3), run_time=0.5)
            medidas["despues_zoom"] = _medidas_relativas(texto, frame)
            self.play(frame.animate.shift([2.0, -1.0, 0.0]), run_time=0.5)
            medidas["despues_paneo"] = _medidas_relativas(texto, frame)
            # Cambio instantaneo + wait (frame congelado): el HUD debe sincronizarse igual.
            frame.scale(0.5)
            self.wait(0.2)
            medidas["despues_wait"] = _medidas_relativas(texto, frame)
            medidas["cuadrado_relativo"] = cuadrado.width / frame.width
            medidas["en_capa"] = texto in self.capa_hud.submobjects

    with tempconfig(_config_prueba(tmp_path)):
        EscenaHud().render()

    ancho_rel_0, centro_rel_0 = medidas["antes"]
    for clave in ("despues_zoom", "despues_paneo", "despues_wait"):
        ancho_rel, centro_rel = medidas[clave]
        assert ancho_rel == pytest.approx(ancho_rel_0, rel=0.02), clave
        assert np.allclose(centro_rel, centro_rel_0, atol=0.02 * abs(centro_rel_0).max()), clave
    assert medidas["z"] == Z_INDEX_HUD
    assert medidas["en_capa"]
    # El contenido del mundo NO sigue a la camara: se ve 1/1.5 de su tamano inicial relativo.
    assert medidas["cuadrado_relativo"] == pytest.approx(2.0 / (9.0 * 1.5), rel=0.02)


@pytest.mark.render
def test_soltar_de_camara_deja_el_mob_en_el_mundo(tmp_path):
    medidas = {}

    class EscenaSoltar(PlantillaShort):
        def construct(self):
            frame = self.camera.frame
            texto = Text("HUD")
            self.fijar_a_camara(texto)
            self.soltar_de_camara(texto)
            ancho = texto.width
            self.play(frame.animate.scale(2), run_time=0.3)
            medidas["ancho"] = (ancho, texto.width)
            medidas["en_capa"] = texto in self.capa_hud.submobjects
            medidas["en_escena"] = texto in self.get_mobject_family_members()

    with tempconfig(_config_prueba(tmp_path)):
        EscenaSoltar().render()

    ancho_antes, ancho_despues = medidas["ancho"]
    assert ancho_despues == pytest.approx(ancho_antes)
    assert not medidas["en_capa"]
    assert medidas["en_escena"]


@pytest.mark.render
def test_plantilla_3d_con_guias_construye(tmp_path):
    info = {}

    class Escena3D(PlantillaShort3D):
        def construct(self):
            texto = Text("Título 3D")
            self.fijar_a_camara(texto)
            self.move_camera(theta=1.0, run_time=0.3)
            info["guias"] = self.guias
            info["fijos"] = set(self.renderer.camera.fixed_in_frame_mobjects)
            info["texto"] = texto

    with tempconfig(_config_prueba(tmp_path)):
        Escena3D(mostrar_guias_seguras=True).render()

    assert info["guias"] is not None
    assert info["guias"].z_index >= Z_INDEX_GUIAS
    assert info["guias"] in info["fijos"]
    assert info["texto"] in info["fijos"]
    assert info["texto"].z_index == Z_INDEX_HUD


@pytest.mark.render
def test_plantilla_2d_con_guias_z_index_alto(tmp_path):
    info = {}

    class EscenaGuias(PlantillaShort):
        def construct(self):
            info["guias"] = self.guias
            info["familia"] = self.get_mobject_family_members()

    with tempconfig(_config_prueba(tmp_path)):
        EscenaGuias(mostrar_guias_seguras=True).render()

    guias = info["guias"]
    assert guias is not None
    assert guias.z_index >= 999
    assert all(m.z_index >= 999 for m in guias.get_family())
    assert guias in info["familia"]


@pytest.mark.render
def test_guias_por_variable_de_entorno(tmp_path, monkeypatch):
    monkeypatch.setenv("SHORT_GUIAS", "1")
    with tempconfig(_config_prueba(tmp_path)):
        escena = PlantillaShort()
        escena.setup()
        assert escena.guias is not None
    monkeypatch.setenv("SHORT_GUIAS", "0")
    with tempconfig(_config_prueba(tmp_path)):
        escena = PlantillaShort()
        escena.setup()
        assert escena.guias is None


@pytest.mark.render
def test_marca_de_agua_queda_en_zona_segura(tmp_path):
    from toolkit.layout import ZONA_SEGURA

    with tempconfig(_config_prueba(tmp_path)):
        escena = PlantillaShort()
        escena.setup()
        marca = Text("@canal")
        escena.fijar_marca_de_agua(marca)
        assert ZONA_SEGURA.contiene(marca)
        assert marca in escena.capa_hud.submobjects
        assert marca.get_fill_opacity() == pytest.approx(0.3)
