"""Tests de toolkit/auditor_layout.py: hallazgos de layout sin renderizar (salvo el último)."""

import json

import pytest
from manim import MathTex, Text, VGroup, tempconfig

from toolkit.auditor_layout import (
    Hallazgo,
    _capa_excluida,
    _es_familiar,
    auditar_escena,
    escribir_reporte,
    textos_visibles,
)
from toolkit.base_scene import PlantillaShort
from toolkit.layout import ZONA_SEGURA, ZONA_SUBTITULOS


def _config_prueba(tmp_path) -> dict:
    """Config de manim para construir escenas sin escribir video (ver test_base_scene.py)."""
    return {
        "quality": "low_quality",
        "dry_run": True,
        "media_dir": str(tmp_path / "media"),
        "disable_caching": True,
    }


def _escena(tmp_path, **kwargs) -> PlantillaShort:
    with tempconfig(_config_prueba(tmp_path)):
        escena = PlantillaShort(**kwargs)
        escena.setup()
    return escena


def test_texto_dentro_de_zona_segura_no_genera_hallazgos(tmp_path):
    escena = _escena(tmp_path)
    texto = Text("Hola")
    escena.add(texto)
    assert auditar_escena(escena) == []


def test_texto_fuera_de_zona_genera_fuera_de_zona(tmp_path):
    escena = _escena(tmp_path)
    texto = Text("Hola").move_to([0, 7, 0])
    escena.add(texto)
    hallazgos = auditar_escena(escena)
    assert any(h.tipo == "fuera_de_zona" for h in hallazgos)
    assert all(isinstance(h, Hallazgo) for h in hallazgos)


def test_dos_textos_superpuestos_generan_solapamiento(tmp_path):
    escena = _escena(tmp_path)
    a = Text("Uno")
    b = Text("Dos").move_to(a.get_center())
    escena.add(a, b)
    hallazgos = auditar_escena(escena)
    assert any(h.tipo == "solapamiento_texto" for h in hallazgos)


def test_mathtex_y_sus_propios_submobjects_no_cuentan_como_solapamiento(tmp_path):
    escena = _escena(tmp_path)
    ecuacion = MathTex("x^2 + y^2 = r^2")
    escena.add(ecuacion)
    hallazgos = auditar_escena(escena)
    assert not any(h.tipo == "solapamiento_texto" for h in hallazgos)


def test_es_familiar_detecta_relacion_padre_hijo():
    interior = Text("x")
    contenedor = VGroup(interior, Text("y"))
    assert _es_familiar(interior, contenedor)
    assert not _es_familiar(Text("a"), Text("b"))


def test_texto_pequeno_genera_hallazgo(tmp_path):
    escena = _escena(tmp_path)
    texto = Text("chiquito", font_size=10)
    escena.add(texto)
    hallazgos = auditar_escena(escena)
    assert any(h.tipo == "texto_pequeno" for h in hallazgos)


def test_texto_de_tamano_normal_no_genera_texto_pequeno(tmp_path):
    escena = _escena(tmp_path)
    texto = Text("Normal", font_size=40)
    escena.add(texto)
    hallazgos = auditar_escena(escena)
    assert not any(h.tipo == "texto_pequeno" for h in hallazgos)


def test_capa_hud_y_guias_quedan_excluidas_de_la_auditoria(tmp_path):
    escena = _escena(tmp_path, mostrar_guias_seguras=True)
    texto_hud = Text("HUD")
    escena.fijar_a_camara(texto_hud)
    assert auditar_escena(escena) == []
    assert texto_hud not in textos_visibles(escena)


def test_subtitulos_quedan_excluidos_de_la_auditoria(tmp_path):
    escena = _escena(tmp_path)
    # Los subtítulos viven en la capa HUD: no cuentan como "contenido" aunque tengan Text propios.
    assert id(escena.subtitulos) in _capa_excluida(escena)
    assert escena.subtitulos not in textos_visibles(escena)


def test_contenido_que_invade_zona_subtitulos_con_subtitulos_activos(tmp_path):
    escena = _escena(tmp_path)
    texto = Text("Invasor", font_size=60).move_to(ZONA_SUBTITULOS.centro)
    escena.add(texto)
    # Simula un bloque de subtítulos "visible ahora" sin depender de narración/TTS real.
    escena.subtitulos._bloque_mostrado = object()
    hallazgos = auditar_escena(escena)
    assert any(h.tipo == "invade_subtitulos" for h in hallazgos)


def test_sin_subtitulos_activos_no_hay_invade_subtitulos(tmp_path):
    escena = _escena(tmp_path)
    texto = Text("Ok", font_size=60).move_to(ZONA_SUBTITULOS.centro)
    escena.add(texto)
    assert escena.subtitulos._bloque_mostrado is None
    hallazgos = auditar_escena(escena)
    assert not any(h.tipo == "invade_subtitulos" for h in hallazgos)


def test_texto_normal_no_invade_zona_subtitulos(tmp_path):
    escena = _escena(tmp_path)
    texto = Text("Normal").move_to(ZONA_SEGURA.centro)
    escena.add(texto)
    escena.subtitulos._bloque_mostrado = object()
    hallazgos = auditar_escena(escena)
    assert not any(h.tipo == "invade_subtitulos" for h in hallazgos)


def test_escribir_reporte_deduplica_por_tipo_y_objetos_y_conserva_primer_tiempo(tmp_path):
    hallazgos = [
        Hallazgo(0.5, "fuera_de_zona", "a", ["Text('a')"]),
        Hallazgo(0.1, "fuera_de_zona", "a", ["Text('a')"]),
        Hallazgo(1.0, "texto_pequeno", "b", ["Text('b')"]),
    ]
    ruta = tmp_path / "auditoria_layout.json"
    escribir_reporte(hallazgos, ruta)
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    assert len(datos) == 2
    fuera = next(d for d in datos if d["tipo"] == "fuera_de_zona")
    assert fuera["tiempo"] == pytest.approx(0.1)


@pytest.mark.render
def test_play_acumula_hallazgos_y_tear_down_escribe_reporte(tmp_path, monkeypatch):
    monkeypatch.setenv("SHORT_AUDITAR", "1")

    class EscenaAuditada(PlantillaShort):
        def construct(self):
            texto = Text("Fuera de zona").move_to([0, 7, 0])
            self.add(texto)
            self.wait(0.1)

    with tempconfig(_config_prueba(tmp_path)):
        EscenaAuditada().render()

    ruta = tmp_path / "media" / "EscenaAuditada" / "auditoria_layout.json"
    assert ruta.exists()
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    assert any(d["tipo"] == "fuera_de_zona" for d in datos)


@pytest.mark.render
def test_sin_short_auditar_no_escribe_reporte(tmp_path, monkeypatch):
    monkeypatch.delenv("SHORT_AUDITAR", raising=False)

    class EscenaSinAuditar(PlantillaShort):
        def construct(self):
            texto = Text("Fuera de zona").move_to([0, 7, 0])
            self.add(texto)
            self.wait(0.1)

    with tempconfig(_config_prueba(tmp_path)):
        EscenaSinAuditar().render()

    ruta = tmp_path / "media" / "EscenaSinAuditar" / "auditoria_layout.json"
    assert not ruta.exists()


def test_marco_de_camara_no_cuenta_como_contenido():
    from toolkit.auditor_layout import _capa_excluida
    from manim import ScreenRectangle

    class Camara:
        frame = ScreenRectangle(height=16)

    class Escena:
        camera = Camara()

    assert id(Camara.frame) in _capa_excluida(Escena())
