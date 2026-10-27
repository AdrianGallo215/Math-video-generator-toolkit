"""Tests de la familia ``graficos`` del catálogo del guion (ejes, curva, punto_en_curva, tangente, vector,
descomponer_vector, trayectoria, mover_variable) y del parseo seguro de expresiones."""

from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path

import numpy as np
import pytest
import yaml

from toolkit.guion import registro
from toolkit.guion.catalogo.graficos import ErrorExpresion, parsear_funcion
from toolkit.guion.validar import validar

# --- parseo seguro de expresiones (función pura) -------------------------------------------------------------


@pytest.mark.parametrize(
    "texto, x, esperado",
    [
        ("x**2", 3.0, 9.0),
        ("x^2 - 1", 2.0, 3.0),
        ("2x + 1", 1.5, 4.0),
        ("sin(x)", math.pi / 2, 1.0),
        ("sqrt(x) + abs(-2)", 4.0, 4.0),
        ("exp(0) + log(E)", 7.0, 2.0),
        ("x/2 + pi", 2.0, 1.0 + math.pi),
        ("3", 10.0, 3.0),
    ],
)
def test_parsear_funcion_expresiones_validas(texto, x, esperado):
    f = parsear_funcion(texto)
    assert f(x) == pytest.approx(esperado)


def test_parsear_funcion_derivada_exacta():
    f = parsear_funcion("x^3 - 2x")
    assert f.derivada(2.0) == pytest.approx(10.0)
    assert f.texto == "x^3 - 2x"


def test_parsear_funcion_fuera_de_dominio_lanza_valueerror():
    f = parsear_funcion("sqrt(x)")
    with pytest.raises(ValueError):
        f(-1.0)
    g = parsear_funcion("1/x")
    with pytest.raises((ValueError, ZeroDivisionError)):
        g(0.0)


@pytest.mark.parametrize(
    "peligrosa",
    [
        "__import__('os').system('echo hola')",
        "x.__class__",
        "open('archivo')",
        "eval('1+1')",
        "exec('x=1')",
        "lambda y: y",
        "x; import os",
        "getattr(x, 'real')",
        "(x).real",
        "Symbol('y')",
        "y + 1",
        "x if x else 1",
        "[x for x in range(3)]",
        "'texto'",
        "x" * 300,
        "",
        "   ",
    ],
)
def test_parsear_funcion_rechaza_codigo_peligroso_o_invalido(peligrosa):
    with pytest.raises(ErrorExpresion):
        parsear_funcion(peligrosa)


def test_parsear_funcion_rechaza_expresiones_mal_formadas():
    for mala in ("x**", "sin(", "2 +* x", "sin"):
        with pytest.raises(ErrorExpresion):
            parsear_funcion(mala)


# --- validación de los ejemplos y del ciclo de vida -------------------------------------------------------------

PIEZAS = ("ejes", "curva", "punto_en_curva", "tangente", "vector", "trayectoria", "descomponer_vector", "mover_variable")
NARRACION = "Mira la curva: el punto sube, la tangente gira y el vector se descompone en dos partes."


def _guion(pasos: list[dict], narracion: str = NARRACION) -> dict:
    return {
        "version": 1,
        "meta": {"slug": "graficos", "titulo": "Gráficos", "clase": "Graficos"},
        "segmentos": [{"narracion": narracion, "pasos": pasos}],
    }


def _validar(tmp_path, datos: dict):
    ruta = tmp_path / "guion_tecnico.yaml"
    ruta.write_text(yaml.safe_dump(datos, allow_unicode=True), encoding="utf-8")
    return validar(ruta)


def _paso(nombre: str, **cambios) -> dict:
    import toolkit.guion.catalogo  # noqa: F401

    paso = dict(registro.CATALOGO[nombre].ejemplo)
    paso["en"] = "inicio"
    paso.update(cambios)
    return paso


def _cadena() -> list[dict]:
    """Todas las piezas, cada una en su palabra (grupos distintos, como en un guion real)."""
    return [
        _paso("ejes"),
        _paso("curva", en="curva"),
        _paso("punto_en_curva", en="punto"),
        _paso("mover_variable", en="sube", dur=1.0),
        _paso("tangente", en="tangente"),
        _paso("vector", en="vector"),
        _paso("descomponer_vector", en="descompone"),
        _paso("trayectoria", en="dos"),
        {"en": "partes", "hacer": "mover_variable", "objeto": "tiro", "a": 1, "dur": 1.0},
        {"en": "fin", "hacer": "quitar", "objeto": ["tiro", "comps", "v", "tg", "p", "parabola", "plano"]},
    ]


def test_todas_las_piezas_de_la_familia_estan_registradas_con_descripciones():
    import toolkit.guion.catalogo  # noqa: F401

    for nombre in PIEZAS:
        d = registro.CATALOGO[nombre]
        assert d.descripcion
        assert all(p.descripcion for p in d.params), nombre


def test_ejemplos_encadenados_con_sus_tipos_reales_validan_sin_errores_ni_avisos_de_ciclo(tmp_path):
    reporte = _validar(tmp_path, _guion(_cadena()))
    assert reporte.ok, reporte.texto()
    assert not [a for a in reporte.avisos if a.codigo in ("A4", "A8")], reporte.texto()


def test_curva_con_codigo_peligroso_es_error_e3(tmp_path):
    pasos = [_paso("ejes"), _paso("curva", funcion="__import__('os').system('dir')")]
    reporte = _validar(tmp_path, _guion(pasos))
    assert any(h.codigo == "E3" and "funcion" in h.mensaje for h in reporte.errores), reporte.texto()


@pytest.mark.parametrize("cambios", [{"x": [3, -3]}, {"y": [0]}, {"x": [-3, 3, 0]}])
def test_ejes_rangos_invalidos(tmp_path, cambios):
    reporte = _validar(tmp_path, _guion([_paso("ejes", **cambios)]))
    assert any(h.codigo == "E3" for h in reporte.errores), reporte.texto()


def test_mover_variable_requiere_objeto_o_variable_existente(tmp_path):
    base = [_paso("ejes"), _paso("curva"), _paso("punto_en_curva")]
    ambos = base + [{"en": "inicio", "hacer": "mover_variable", "objeto": "p", "variable": "t", "a": 1}]
    assert any(h.codigo == "E3" for h in _validar(tmp_path, _guion(ambos)).errores)
    fantasma = base + [{"en": "inicio", "hacer": "mover_variable", "variable": "t", "a": 1}]
    assert any(h.codigo == "E4" and "'t'" in h.mensaje for h in _validar(tmp_path, _guion(fantasma)).errores)


def test_variable_compartida_es_efecto_persistente_con_detener(tmp_path):
    pasos = [
        _paso("ejes"), _paso("curva"), _paso("punto_en_curva", variable="t"), _paso("tangente"),
        {"en": "inicio", "hacer": "mover_variable", "variable": "t", "a": 2},
    ]
    reporte = _validar(tmp_path, _guion(pasos))
    assert reporte.ok, reporte.texto()
    assert any(a.codigo == "A8" for a in reporte.avisos)  # la variable no se detuvo
    detenida = pasos + [{"en": "fin", "hacer": "detener", "objeto": "t"}]
    reporte = _validar(tmp_path, _guion(detenida))
    assert reporte.ok and not any(a.codigo == "A8" for a in reporte.avisos), reporte.texto()
    tarde = detenida + [{"en": "fin", "hacer": "mover_variable", "variable": "t", "a": 0}]
    assert any(h.codigo == "E4" for h in _validar(tmp_path, _guion(tarde)).errores)


def test_trayectoria_parametros_fisicos_invalidos(tmp_path):
    reporte = _validar(tmp_path, _guion([_paso("ejes"), _paso("trayectoria", angulo=200, rapidez=-1)]))
    mensajes = " ".join(h.mensaje for h in reporte.errores)
    assert "angulo" in mensajes and "rapidez" in mensajes


# --- construcción de objetos (sin escena) ------------------------------------------------------------------------


@pytest.fixture()
def ctx():
    import toolkit.guion.catalogo  # noqa: F401
    from toolkit.guion.contexto import ContextoGuion

    return ContextoGuion(None)


def _crear(ctx, id: str, tipo: str, **params):
    mob = ctx.crear(tipo, **params)
    ctx.registrar(id, mob)
    return mob


def _dentro_de_segura(mob) -> bool:
    from toolkit.layout import ZONA_SEGURA

    return ZONA_SEGURA.contiene(mob, tolerancia=0.02)


def test_ejes_encajan_en_la_zona_sin_encoger_los_numeros(ctx):
    from toolkit.estilos import FUENTE_MINIMA
    from toolkit.guion.contexto import ZONAS_BASE

    ejes = _crear(ctx, "plano", "ejes", x=[-3, 3, 1], y=[-1, 5, 1])
    assert ZONAS_BASE["principal"].contiene(ejes, tolerancia=0.02)
    numeros = ctx.parte(ejes, "numeros")
    assert len(numeros.submobjects) == 6 + 6  # sin el 0
    assert min(n.font_size for n in numeros.submobjects) >= FUENTE_MINIMA - 0.5
    assert ejes.width > 5.0  # llena la zona (escala real, no un recuadro diminuto)


def test_ejes_misma_escala_y_cuadricula(ctx):
    ejes = _crear(ctx, "plano", "ejes", x=[-2, 2, 1], y=[-4, 4, 1], misma_escala=True, cuadricula=True)
    interno = ejes.ejes_guion
    unidad_x = interno.c2p(1, 0)[0] - interno.c2p(0, 0)[0]
    unidad_y = interno.c2p(0, 1)[1] - interno.c2p(0, 0)[1]
    assert unidad_x == pytest.approx(unidad_y, rel=1e-3)
    assert _dentro_de_segura(ejes)


def test_curva_punto_y_tangente_siguen_a_la_variable(ctx):
    _crear(ctx, "plano", "ejes", x=[-3, 3, 1], y=[-1, 5, 1])
    curva = _crear(ctx, "parabola", "curva", de="plano", funcion="x^2/2")
    ejes = curva.ejes_guion
    punto = _crear(ctx, "p", "punto_en_curva", de="parabola", x=-1.5)
    tangente = _crear(ctx, "tg", "tangente", de="p")
    assert np.allclose(punto.get_center(), ejes.c2p(-1.5, 1.125), atol=1e-6)
    punto.tracker_guion.set_value(2.0)
    punto.update()
    tangente.update()
    assert np.allclose(punto.get_center(), ejes.c2p(2.0, 2.0), atol=1e-6)
    # la tangente pasa por el punto con la pendiente (en pantalla) de f'(2) = 2
    assert np.allclose(tangente.get_center(), punto.get_center(), atol=1e-6)
    direccion = tangente.get_end() - tangente.get_start()
    esperada = ejes.c2p(3.0, 4.0) - ejes.c2p(2.0, 2.0)
    assert abs(direccion[0] * esperada[1] - direccion[1] * esperada[0]) < 1e-6
    assert _dentro_de_segura(curva)


def test_curva_se_recorta_al_rango_visible(ctx):
    _crear(ctx, "plano", "ejes", x=[-3, 3, 1], y=[-1, 4, 1])
    curva = _crear(ctx, "hip", "curva", de="plano", funcion="1/x", color="rojo", etiqueta="f(x)=1/x")
    assert _dentro_de_segura(curva)
    assert set(curva.partes_guion) == {"curva", "etiqueta"}


def test_curva_sin_tramo_visible_es_error_claro(ctx):
    from toolkit.guion.esquema import ErrorGuion

    _crear(ctx, "plano", "ejes", x=[-3, 3, 1], y=[-1, 4, 1])
    with pytest.raises(ErrorGuion, match="tramo visible"):
        _crear(ctx, "c", "curva", de="plano", funcion="x + 100")


def test_referencia_de_tipo_equivocado_es_e3(ctx):
    from toolkit.guion.esquema import ErrorGuion

    _crear(ctx, "t", "texto", texto="Hola")
    with pytest.raises(ErrorGuion, match="no es unos ejes"):
        _crear(ctx, "c", "curva", de="t", funcion="x")


def test_punto_con_guias_y_etiqueta(ctx):
    _crear(ctx, "plano", "ejes", x=[-3, 3, 1], y=[-1, 5, 1])
    _crear(ctx, "parabola", "curva", de="plano", funcion="x^2/2")
    punto = _crear(ctx, "p", "punto_en_curva", de="parabola", x=1.0, guias=True, etiqueta="P")
    assert set(punto.partes_guion) == {"punto", "guias", "etiqueta"}
    punto.tracker_guion.set_value(2.0)
    punto.update()
    assert np.allclose(ctx.parte(punto, "punto").get_center(), punto.ejes_guion.c2p(2.0, 2.0), atol=1e-6)


def test_variable_compartida_y_detener_congela(ctx):
    _crear(ctx, "plano", "ejes", x=[-3, 3, 1], y=[-1, 5, 1])
    _crear(ctx, "parabola", "curva", de="plano", funcion="x^2/2")
    p1 = _crear(ctx, "p1", "punto_en_curva", de="parabola", x=0.0, variable="t")
    p2 = _crear(ctx, "p2", "punto_en_curva", de="parabola", x=9.0, variable="t")  # ya existe: manda la variable
    assert p1.tracker_guion is p2.tracker_guion
    assert ctx.efectos["t"].tipo == "variable"
    ctx.detener_efecto("t")
    antes = p1.get_center().copy()
    p1.tracker_guion.set_value(2.0)
    p1.update()
    assert np.allclose(p1.get_center(), antes)


def test_vector_y_trayectoria(ctx):
    from toolkit.motor_fisica import alcance

    _crear(ctx, "plano", "ejes", x=[0, 7, 1], y=[0, 3, 1])
    vec = _crear(ctx, "v", "vector", de="plano", componentes=[2, 1], etiqueta="\\vec{v}")
    assert _dentro_de_segura(vec)
    tiro = _crear(ctx, "tiro", "trayectoria", de="plano", rapidez=8, angulo=45, progreso=0)
    bola = ctx.parte(tiro, "proyectil")
    ejes = tiro.ejes_guion
    assert np.allclose(bola.get_center(), ejes.c2p(0, 0), atol=0.05)
    tiro.tracker_guion.set_value(1.0)
    tiro.update()
    assert np.allclose(bola.get_center(), ejes.c2p(alcance(8, 45), 0), atol=0.05)
    assert _dentro_de_segura(tiro)


def test_mover_variable_devuelve_animacion(ctx):
    from manim.animation.animation import prepare_animation

    _crear(ctx, "plano", "ejes")
    _crear(ctx, "parabola", "curva", de="plano", funcion="x^2/4")
    _crear(ctx, "p", "punto_en_curva", de="parabola", x=0)
    definicion = registro.CATALOGO["mover_variable"]
    params = registro.resolver_params(definicion, {"objeto": "p", "a": 1})
    params.pop("rate")  # lo aplica el runtime
    anim = prepare_animation(definicion.funcion(ctx, **params))
    anim.begin()
    anim.interpolate(1.0)
    assert ctx.obtener("p").tracker_guion.get_value() == pytest.approx(1.0)


# --- humo: el guion completo se ejecuta en una escena (dry_run) ----------------------------------------------------

TRES_LINEAS = (
    "from toolkit.guion.runtime import escena_desde_yaml\n\n\n"
    "class {clase}(escena_desde_yaml(\"guion_tecnico.yaml\")):\n    pass\n"
)


def _escena(tmp_path, datos: dict, nombre: str):
    from toolkit.narracion import MotorNarracion

    (tmp_path / "guion_tecnico.yaml").write_text(yaml.safe_dump(datos, allow_unicode=True), encoding="utf-8")
    ruta = tmp_path / "escena.py"
    ruta.write_text(TRES_LINEAS.format(clase=datos["meta"]["clase"]), encoding="utf-8")
    spec = importlib.util.spec_from_file_location(nombre, ruta)
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[nombre] = modulo
    spec.loader.exec_module(modulo)
    base = getattr(modulo, datos["meta"]["clase"])

    class Offline(base):
        def setup(self):
            super().setup()
            self._motor_narracion = MotorNarracion(dir_cache=tmp_path / "tts", permitir_red=False)

    return Offline


def _renderizar(tmp_path, clase):
    from manim import tempconfig

    config = {"quality": "low_quality", "dry_run": True, "media_dir": str(Path(tmp_path) / "media"),
              "disable_caching": True}
    with tempconfig(config):
        escena = clase()
        escena.render()
    return escena


def _restos(escena) -> list:
    return [m for m in escena.get_mobject_family_members()
            if m.get_num_points() > 0 and m not in escena.capa_hud.get_family() and m is not escena.camera.frame]


@pytest.mark.render
def test_humo_familia_graficos_en_escena(tmp_path):
    escena = _renderizar(tmp_path, _escena(tmp_path, _guion(_cadena()), "escena_humo_graficos"))
    ctx = escena.contexto_guion
    assert ctx.objetos == {} and ctx.efectos == {}
    assert not _restos(escena)
