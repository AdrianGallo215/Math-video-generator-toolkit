"""Tests de ContextoGuion: zonas derivadas, colores, referencias "id.parte", ciclo de vida y colocación."""

import pytest
from manim import Square, VGroup, tempconfig

from toolkit.base_scene import PlantillaShort
from toolkit.estilos import AZUL, FUENTE_CUERPO
from toolkit.guion.contexto import COLORES, ContextoGuion, construir_zonas, separar_ref
from toolkit.guion.esquema import DefZona, ErrorGuion
from toolkit.layout import ZONA_PRINCIPAL, ZONA_SEGURA
from toolkit.tipografia import Texto


def _config(tmp_path) -> dict:
    return {"quality": "low_quality", "dry_run": True, "media_dir": str(tmp_path / "media"), "disable_caching": True}


def test_construir_zonas_deriva_filas_y_columnas():
    zonas = construir_zonas(
        {
            "arriba": DefZona("arriba", "principal", filas=[1, 1], indice=0),
            "izq": DefZona("izq", "arriba", columnas=[1, 1], indice=0, espacio=0.3),
        }
    )
    assert {"titulo", "principal", "subtitulos", "segura", "arriba", "izq"} <= set(zonas)
    assert zonas["arriba"].y_max == pytest.approx(ZONA_PRINCIPAL.y_max)
    assert zonas["arriba"].alto == pytest.approx(ZONA_PRINCIPAL.alto / 2)
    assert zonas["izq"].x_min == pytest.approx(ZONA_PRINCIPAL.x_min)
    assert zonas["izq"].ancho == pytest.approx((ZONA_PRINCIPAL.ancho - 0.3) / 2)


def test_construir_zonas_de_inexistente_es_e5_con_sugerencia():
    with pytest.raises(ErrorGuion) as info:
        construir_zonas({"a": DefZona("a", "principl", filas=[1, 1], indice=0)})
    (h,) = info.value.hallazgos
    assert h.codigo == "E5" and "principal" in h.mensaje


def test_separar_ref():
    assert separar_ref("eq0") == ("eq0", None)
    assert separar_ref("eq0.16") == ("eq0", "16")
    assert separar_ref("g.a.b") == ("g", "a.b")


def test_colores_por_nombre():
    assert COLORES["azul"] == AZUL
    ctx = ContextoGuion(escena=None)
    assert ctx.color("azul") == AZUL
    with pytest.raises(ErrorGuion) as info:
        ctx.color("azl")
    assert info.value.hallazgos[0].codigo == "E6"
    assert "azul" in info.value.hallazgos[0].mensaje


def test_registrar_obtener_parte_y_quitar(tmp_path):
    with tempconfig(_config(tmp_path)):
        escena = PlantillaShort()
        ctx = ContextoGuion(escena)
        a, b = Square(), Square()
        grupo = VGroup(a, b)
        grupo.partes_guion = {"a": a, "b": b}
        ctx.registrar("g", grupo)
        ctx.registrar("a", a)
        assert ctx.obtener("g") is grupo
        assert ctx.obtener("g.b") is b
        assert ctx.obtener("g.0") is a  # índice de submobject
        with pytest.raises(ErrorGuion) as info:
            ctx.obtener("gg")
        assert "'g'" in info.value.hallazgos[0].mensaje  # sugiere el id parecido
        with pytest.raises(ErrorGuion):
            ctx.registrar("g", Square())  # id vivo duplicado
        escena.add(a, b)
        ctx.quitar("g")
        assert "g" not in ctx.objetos
        assert a not in escena.mobjects and b not in escena.mobjects
        ctx.registrar("g", Square())  # reutilizable tras quitar


def test_quitar_un_miembro_lo_saca_del_grupo(tmp_path):
    with tempconfig(_config(tmp_path)):
        ctx = ContextoGuion(PlantillaShort())
        a, b = Square(), Square()
        grupo = VGroup(a, b)
        grupo.partes_guion = {"a": a, "b": b}
        grupo.miembros_guion = ["a", "b"]
        ctx.registrar("g", grupo)
        ctx.registrar("a", a)
        ctx.quitar("a")
        assert a not in grupo.submobjects
        assert "a" not in grupo.partes_guion


def test_colocar_relativo_queda_dentro_de_la_zona_segura(tmp_path):
    with tempconfig(_config(tmp_path)):
        ctx = ContextoGuion(PlantillaShort())
        ancla = Texto("Arriba", tamano=FUENTE_CUERPO)
        ctx.colocar(ancla, "titulo")
        ctx.registrar("t", ancla)
        largo = Texto("una etiqueta bastante larga para el ancho", tamano=FUENTE_CUERPO)
        ctx.colocar(largo, {"de": "t", "lado": "arriba", "espacio": 0.3})
        assert ZONA_SEGURA.contiene(largo)
        debajo = Texto("abajo", tamano=FUENTE_CUERPO)
        ctx.colocar(debajo, {"de": "t", "lado": "abajo", "espacio": 0.3})
        assert debajo.get_top()[1] == pytest.approx(ancla.get_bottom()[1] - 0.3, abs=1e-6)


def test_efectos_persistentes(tmp_path):
    ctx = ContextoGuion(escena=None)
    llamado = []
    ctx.iniciar_efecto("cam", "camara", detener=lambda c: llamado.append(True))
    with pytest.raises(ErrorGuion):
        ctx.iniciar_efecto("cam", "camara", detener=lambda c: None)
    ctx.detener_efecto("cam")
    assert llamado == [True] and "cam" not in ctx.efectos
    with pytest.raises(ErrorGuion):
        ctx.detener_efecto("cam")
