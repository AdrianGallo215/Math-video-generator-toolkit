"""Tests del catálogo de algoritmos del guion técnico (arreglo, puntero, código, cuadrícula, pila y sus verbos)."""

from pathlib import Path

import pytest
import yaml
from manim import tempconfig

import toolkit.guion.catalogo  # noqa: F401  (registra las piezas)
from toolkit.guion import registro
from toolkit.guion.catalogo.algoritmos import celdas_de_parte
from toolkit.guion.contexto import ContextoGuion
from toolkit.guion.validar import guion_de_ejemplo, validar

ARR = {"en": "inicio", "hacer": "mostrar", "id": "arr", "tipo": "arreglo", "valores": [1, 2, 3, 4, 5, 6, 7, 8],
       "columnas_max": 4}
PUNTERO = {"en": "inicio", "hacer": "mostrar", "id": "p_lo", "tipo": "puntero", "nombre": "lo", "arreglo": "arr",
           "en_celda": 0}
CODIGO = {"en": "inicio", "hacer": "mostrar", "id": "cod", "tipo": "codigo", "lineas": ["a = 1", "b = 2", "c = 3"]}
CUAD = {"en": "inicio", "hacer": "mostrar", "id": "cuad", "tipo": "cuadricula", "n": 4, "cabeceras": True}
PILA = {"en": "inicio", "hacer": "mostrar", "id": "pila", "tipo": "pila", "elementos": ["f(2)"]}
PREVIOS = {
    "puntero": [ARR], "apuntar": [ARR, PUNTERO], "colorear": [ARR], "restablecer_celdas": [ARR],
    "atenuar_rango": [ARR], "intercambiar": [ARR], "comparar": [ARR], "paso_busqueda": [ARR],
    "paso_burbuja": [ARR], "resaltar_linea": [CODIGO], "cursor": [CUAD], "expandir": [CUAD], "apilar": [PILA],
    "desapilar": [PILA],
}
PIEZAS = ["arreglo", "puntero", "codigo", "cuadricula", "pila", "apuntar", "colorear", "atenuar_rango",
          "restablecer_celdas", "intercambiar", "comparar", "resaltar_linea", "expandir", "cursor", "apilar",
          "desapilar", "paso_busqueda", "paso_burbuja"]


def _validar(tmp_path: Path, datos: dict):
    ruta = tmp_path / "guion_tecnico.yaml"
    ruta.write_text(yaml.safe_dump(datos, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return validar(ruta)


def _guion(pasos: list[dict], **extra) -> dict:
    datos = guion_de_ejemplo("texto")
    datos["segmentos"] = [{"narracion": "Un ejemplo breve de esta pieza.", "pasos": pasos}]
    datos.update(extra)
    return datos


def _errores(tmp_path, pasos, **extra) -> str:
    reporte = _validar(tmp_path, _guion(pasos, **extra))
    return " | ".join(f"{h.codigo}: {h.mensaje}" for h in reporte.errores)


# --- función pura -------------------------------------------------------------------------------------


def test_celdas_de_parte():
    assert celdas_de_parte("fila:1", 3) == [(1, 0), (1, 1), (1, 2)]
    assert celdas_de_parte("columna:2", 3) == [(0, 2), (1, 2), (2, 2)]
    assert celdas_de_parte("celda:2,1", 3) == [(2, 1)]
    assert len(celdas_de_parte(None, 4)) == 16
    assert celdas_de_parte("cuadrante:id", 4) == [(2, 2), (2, 3), (3, 2), (3, 3)]
    assert celdas_de_parte("cuadrante:si", 4) == [(0, 0), (0, 1), (1, 0), (1, 1)]
    assert len(celdas_de_parte("cuadrante:sd", 16)) == 64


@pytest.mark.parametrize("parte, dice", [
    ("fila:9", "fuera de la cuadrícula"), ("fila:x", "número entero"), ("celda:1", "celda:fila,columna"),
    ("cuadrante:zz", "Cuadrantes"), ("diagonal", "desconocida"),
])
def test_celdas_de_parte_errores_dicen_que_corregir(parte, dice):
    with pytest.raises(ValueError, match=dice):
        celdas_de_parte(parte, 4)


def test_cuadrante_pide_n_par():
    with pytest.raises(ValueError, match="par"):
        celdas_de_parte("cuadrante:si", 3)


# --- registro y ejemplos --------------------------------------------------------------------------------


def test_todas_las_piezas_estan_registradas_con_descripciones():
    for nombre in PIEZAS:
        d = registro.CATALOGO[nombre]
        assert d.descripcion and d.ejemplo["hacer"] in (nombre, "mostrar")
        assert d.ciclo is not None, nombre
        for p in d.params:
            assert p.descripcion, f"{nombre}.{p.nombre} sin descripción"


@pytest.mark.parametrize("nombre", PIEZAS)
def test_ejemplo_valida(tmp_path, nombre):
    reporte = _validar(tmp_path, guion_de_ejemplo(nombre, previos=[dict(p) for p in PREVIOS.get(nombre, [])]))
    assert reporte.ok, reporte.texto()


# --- validación: qué corregir ------------------------------------------------------------------------------


def test_puntero_fuera_del_arreglo(tmp_path):
    texto = _errores(tmp_path, [ARR, {**PUNTERO, "en_celda": 8}])
    assert "en_celda=8" in texto and "0-7" in texto


def test_puntero_sobre_algo_que_no_es_arreglo(tmp_path):
    texto = _errores(tmp_path, [CODIGO, {**PUNTERO, "arreglo": "cod"}])
    assert "'cod' es de tipo 'codigo'" in texto


def test_apuntar_a_un_objeto_que_no_es_puntero_y_rango(tmp_path):
    assert "es de tipo 'arreglo'" in _errores(tmp_path, [ARR, {"en": "inicio", "hacer": "apuntar", "objeto": "arr", "a": 1}])
    texto = _errores(tmp_path, [ARR, PUNTERO, {"en": "inicio", "hacer": "apuntar", "objeto": "p_lo", "a": 99}])
    assert "a=99" in texto


def test_codigo_linea_larga_y_linea_inexistente(tmp_path):
    largo = {**CODIGO, "lineas": ["x" * 25]}
    assert "25 caracteres" in _errores(tmp_path, [largo])
    texto = _errores(tmp_path, [CODIGO, {"en": "inicio", "hacer": "resaltar_linea", "objeto": "cod", "linea": 4}])
    assert "linea=4" in texto


def test_codigo_tamano_menor_a_la_fuente_minima_es_e8(tmp_path):
    assert "E8" in _errores(tmp_path, [{**CODIGO, "tamano": 20}])


def test_arreglo_demasiado_grande(tmp_path):
    texto = _errores(tmp_path, [{**ARR, "valores": list(range(40))}])
    assert "entre 1 y 32" in texto


def test_colorear_indices_y_partes_de_cuadricula(tmp_path):
    texto = _errores(tmp_path, [ARR, {"en": "inicio", "hacer": "colorear", "objeto": "arr", "indices": [3, 30]}])
    assert "índice=30" in texto
    texto = _errores(tmp_path, [CUAD, {"en": "inicio", "hacer": "colorear", "objeto": "cuad.fila:7"}])
    assert "fuera de la cuadrícula" in texto
    ok = _errores(tmp_path, [CUAD, {"en": "inicio", "hacer": "colorear", "objeto": "cuad.cuadrante:sd", "color": "rojo"}])
    assert ok == ""


def test_expandir_actualiza_el_tamano_para_validar_partes_y_topes(tmp_path):
    pasos = [CUAD, {"en": "inicio", "hacer": "expandir", "objeto": "cuad"},
             {"en": "inicio", "hacer": "colorear", "objeto": "cuad.fila:7"}]
    assert _errores(tmp_path, pasos) == ""  # 4 -> 8: la fila 7 existe tras expandir
    pasos = [{**CUAD, "n": 8}] + [{"en": "inicio", "hacer": "expandir", "objeto": "cuad"}] * 2
    assert "máx. 16" in _errores(tmp_path, pasos)


def test_cursor_necesita_fila_o_columna(tmp_path):
    assert "'fila' y/o 'columna'" in _errores(tmp_path, [CUAD, {"en": "inicio", "hacer": "cursor", "objeto": "cuad"}])


def test_pila_vacia_y_llena(tmp_path):
    assert "vacía" in _errores(tmp_path, [PILA, {"en": "inicio", "hacer": "desapilar", "objeto": "pila"},
                                          {"en": "inicio", "hacer": "desapilar", "objeto": "pila"}])
    apilar = {"en": "inicio", "hacer": "apilar", "objeto": "pila", "elemento": "f"}
    assert "máx." in _errores(tmp_path, [PILA] + [apilar] * 6)


def test_intercambiar_fuera_de_rango(tmp_path):
    assert "j=8" in _errores(tmp_path, [ARR, {"en": "inicio", "hacer": "intercambiar", "objeto": "arr", "i": 0, "j": 8}])


# --- integración con calculos: ---------------------------------------------------------------------------------

VALORES_V03 = [3, 8, 12, 17, 21, 25, 30, 34, 41, 47, 52, 58, 63, 70, 77, 85]
CALCULOS = {"traza": {"motor": "busqueda_binaria", "valores": VALORES_V03, "objetivo": 58}}


def test_referencias_a_la_traza_alimentan_los_parametros(tmp_path):
    pasos = [
        {**ARR, "valores": VALORES_V03, "columnas_max": 8},
        {**PUNTERO, "en_celda": "{traza.0.mid}"},
        {"en": "inicio", "hacer": "apuntar", "objeto": "p_lo", "a": "{traza.1.mid}"},
        {"en": "inicio", "hacer": "atenuar_rango", "objeto": "arr", "desde": "{traza.0.lo}", "hasta": "{traza.0.mid}"},
        {"en": "inicio", "hacer": "paso_busqueda", "objeto": "arr", "traza": "{traza}", "n": 1, "lo": "p_lo"},
    ]
    reporte = _validar(tmp_path, _guion(pasos, calculos=CALCULOS))
    assert reporte.ok, reporte.texto()
    assert reporte.guion.segmentos[0].pasos[1].params["en_celda"] == 7  # {traza.0.mid} con su tipo (entero)


def test_traza_incompatible_con_el_arreglo(tmp_path):
    pasos = [ARR, {"en": "inicio", "hacer": "paso_busqueda", "objeto": "arr", "traza": "{traza}", "n": 0}]
    texto = _errores(tmp_path, pasos, calculos=CALCULOS)
    assert "solo tiene 8 celdas" in texto


def test_paso_burbuja_con_la_traza_del_motor(tmp_path):
    calculos = {"traza": {"motor": "burbuja", "valores": [4, 3, 2, 1]}}
    pasos = [{**ARR, "valores": [4, 3, 2, 1]},
             {"en": "inicio", "hacer": "paso_burbuja", "objeto": "arr", "traza": "{traza}", "n": 1}]
    assert _errores(tmp_path, pasos, calculos=calculos) == ""
    pasos[1]["n"] = 99
    assert "n=99" in _errores(tmp_path, pasos, calculos=calculos)


# --- construcción sin escena (geometría y estado) ------------------------------------------------------------


@pytest.fixture
def ctx():
    return ContextoGuion(None, None)


def _crear(ctx, id, tipo, **params):
    mob = ctx.crear(tipo, **params)
    ctx.registrar(id, mob)
    return mob


def _accion(ctx, nombre, **params):
    d = registro.CATALOGO[nombre]
    return d.funcion(ctx, **registro.resolver_params(d, params))


def _correr(*animaciones):
    for a in animaciones:
        a.begin()
        a.interpolate(1.0)
        a.finish()


def test_arreglo_dos_filas_de_ocho_y_celdas_direccionables(ctx):
    arr = _crear(ctx, "arr", "arreglo", valores=VALORES_V03, columnas_max=8, indices=False, espacio_filas=1.35)
    fila_a, fila_b = arr.celdas[:8], arr.celdas[8:]
    assert abs(fila_a[0].get_y() - fila_a[7].get_y()) < 1e-6 and fila_b[0].get_y() < fila_a[0].get_y()
    assert abs(fila_a[0].get_x() - fila_b[0].get_x()) < 1e-6  # columnas alineadas
    hueco = fila_a[0].get_bottom()[1] - fila_b[0].get_top()[1]
    assert hueco > 0.8  # aloja un puntero entre filas
    assert ctx.obtener("arr.celda11") is arr.celda(11)
    assert ctx.obtener("arr.3") is arr.celda(3)


def test_celda_direccionada_sigue_al_intercambio(ctx):
    arr = _crear(ctx, "arr", "arreglo", valores=[5, 1, 9])
    antes = arr.celda(0)
    _accion(ctx, "intercambiar", objeto="arr", i=0, j=2)
    assert ctx.obtener("arr.celda2") is antes and arr.valores == [9, 1, 5]


def test_arreglo_dentro_de_la_zona_segura(ctx):
    from toolkit.layout import ZONA_SEGURA

    arr = _crear(ctx, "arr", "arreglo", valores=VALORES_V03, columnas_max=8)
    assert arr.get_left()[0] >= ZONA_SEGURA.x_min and arr.get_right()[0] <= ZONA_SEGURA.x_max


def test_puntero_apunta_a_la_celda_y_se_desliza(ctx):
    arr = _crear(ctx, "arr", "arreglo", valores=list(range(8)))
    p = _crear(ctx, "p", "puntero", nombre="lo", arreglo="arr", en_celda=1, direccion="abajo")
    assert abs(p.flecha.get_center()[0] - arr.celda(1).get_center()[0]) < 1e-6
    _correr(_accion(ctx, "apuntar", objeto="p", a=6))
    assert abs(p.flecha.get_center()[0] - arr.celda(6).get_center()[0]) < 1e-6


def test_puntero_copiado_no_clona_el_arreglo(ctx):
    _crear(ctx, "arr", "arreglo", valores=[1, 2, 3])
    p = _crear(ctx, "p", "puntero", nombre="i", arreglo="arr", en_celda=0)
    assert p.copy().arreglo_ref() is ctx.objetos["arr"]


def test_colorear_arreglo_por_rango_y_cuadricula_por_cuadrante(ctx):
    arr = _crear(ctx, "arr", "arreglo", valores=list(range(6)))
    _correr(*_accion(ctx, "colorear", objeto="arr", desde=1, hasta=3, color="verde"))
    assert [arr.celda(k).caja.get_fill_opacity() > 0.5 for k in range(6)] == [False, True, True, True, False, False]
    cuad = _crear(ctx, "cuad", "cuadricula", n=4)
    _correr(*_accion(ctx, "colorear", objeto="cuad.cuadrante:id", color="rojo", opacidad=0.7))
    rellenas = {(r, c) for r in range(4) for c in range(4) if cuad.celda(r, c).get_fill_opacity() > 0.5}
    assert rellenas == {(2, 2), (2, 3), (3, 2), (3, 3)}


def test_atenuar_y_restablecer(ctx):
    arr = _crear(ctx, "arr", "arreglo", valores=list(range(6)))
    _correr(_accion(ctx, "atenuar_rango", objeto="arr", desde=0, hasta=2))
    assert arr.celda(0).caja.get_stroke_opacity() < 0.5 < arr.celda(5).caja.get_stroke_opacity()
    _correr(*_accion(ctx, "restablecer_celdas", objeto="arr"))
    assert arr.celda(0).caja.get_stroke_opacity() == pytest.approx(1.0)


def test_expandir_conserva_el_contorno_y_el_color(ctx):
    cuad = _crear(ctx, "cuad", "cuadricula", n=8, cabeceras=True)
    _correr(*_accion(ctx, "colorear", objeto="cuad.celda:0,0", color="rojo", opacidad=0.7))
    esquina = cuad.grupo_celdas.get_corner([-1, 1, 0]).copy()
    ancho, cab_ancho = cuad.grupo_celdas.width, cuad.grupo_cab_sup.width
    animacion = _accion(ctx, "expandir", objeto="cuad")
    (cerrar,) = ctx._pendientes
    _correr(animacion)
    cerrar()
    assert cuad.n == 16 and len(cuad.celdas) == 256 and len(cuad.grupo_celdas.submobjects) == 256
    assert len(cuad.cab_sup) == 16 and len(cuad.cab_izq) == 16
    assert abs(cuad.grupo_celdas.get_corner([-1, 1, 0]) - esquina).max() < 1e-6
    assert abs(cuad.grupo_celdas.width - ancho) < 1e-6  # el contorno exterior no cambia
    assert abs(cuad.grupo_cab_sup.width - cab_ancho) < 1e-6
    assert cuad.celda(0, 0).get_fill_opacity() == pytest.approx(0.7)
    assert cuad.celda(0, 0).width == pytest.approx(cuad.celda(15, 15).width)
    assert ctx.obtener("cuad.cuadrante:si") is not None


def test_cursor_se_crea_se_desliza_y_se_quita(ctx):
    cuad = _crear(ctx, "cuad", "cuadricula", n=4, cabeceras=True)
    assert cuad.cursor_fila.get_stroke_opacity() == 0
    _correr(*_accion(ctx, "cursor", objeto="cuad", fila=1, columna=2))
    assert cuad.cursor_fila.get_stroke_opacity() > 0.9
    assert abs(cuad.cursor_col.get_center()[0] - cuad.cab_sup[2].get_center()[0]) < 1e-6
    assert abs(cuad.cursor_fila.get_center()[1] - cuad.cab_izq[1].get_center()[1]) < 1e-6
    _correr(*_accion(ctx, "cursor", objeto="cuad", quitar=True))
    assert cuad.cursor_fila.get_stroke_opacity() == 0


def test_resaltar_linea_mueve_la_franja(ctx):
    cod = _crear(ctx, "cod", "codigo", lineas=["a = 1", "b = 2", "c = 3"])
    _correr(_accion(ctx, "resaltar_linea", objeto="cod", linea=3))
    assert abs(cod.resaltado.get_y() - cod.y_linea(3)) < 1e-6
    assert cod.linea_activa == 3


def test_pila_apilar_y_desapilar(ctx):
    pila = _crear(ctx, "pila", "pila", elementos=["f(3)"])
    _accion(ctx, "apilar", objeto="pila", elemento="f(2)")
    assert pila.elementos == ["f(3)", "f(2)"]
    _accion(ctx, "desapilar", objeto="pila")
    assert pila.elementos == ["f(3)"]


def test_paso_busqueda_mueve_punteros_y_atenua_lo_descartado(ctx):
    arr = _crear(ctx, "arr", "arreglo", valores=VALORES_V03, columnas_max=8)
    for id, nombre, k in (("lo", "lo", 0), ("hi", "hi", 15), ("mid", "mid", 7)):
        _crear(ctx, id, "puntero", nombre=nombre, arreglo="arr", en_celda=k)
    traza = [{"lo": 0, "hi": 15, "mid": 7, "comparacion": "<"}, {"lo": 8, "hi": 15, "mid": 11, "comparacion": "=="}]
    _correr(*_accion(ctx, "paso_busqueda", objeto="arr", traza=traza, n=1, lo="lo", hi="hi", mid="mid"))
    assert abs(ctx.objetos["lo"].flecha.get_center()[0] - arr.celda(8).get_center()[0]) < 1e-6
    assert abs(ctx.objetos["mid"].flecha.get_center()[0] - arr.celda(11).get_center()[0]) < 1e-6
    assert arr.celda(3).caja.get_stroke_opacity() < 0.5  # descartada
    assert arr.celda(12).caja.get_stroke_opacity() > 0.9  # sigue viva


def test_paso_burbuja_intercambia_segun_la_traza(ctx):
    arr = _crear(ctx, "arr", "arreglo", valores=[3, 1, 2])
    _accion(ctx, "paso_burbuja", objeto="arr", traza=[{"accion": "intercambiar", "i": 0, "j": 1}], n=0)
    assert arr.valores == [1, 3, 2]


# --- humo (construyen escenas) -------------------------------------------------------------------------------------

GUION_HUMO = {
    "version": 1,
    "meta": {"slug": "humo_algoritmos", "titulo": "Humo algoritmos", "clase": "HumoAlgoritmos"},
    "calculos": CALCULOS,
    "zonas": {"arriba": {"de": "principal", "filas": [0.5, 0.5], "fila": 0},
              "abajo": {"de": "principal", "filas": [0.5, 0.5], "fila": 1}},
    "segmentos": [
        {"narracion": "Un arreglo con sus punteros y una cuadrícula.", "pasos": [
            {"en": "inicio", "hacer": "mostrar", "id": "arr", "tipo": "arreglo", "valores": VALORES_V03,
             "columnas_max": 8, "indices": False, "espacio_filas": 1.2, "zona": "arriba"},
            {"en": "inicio", "hacer": "mostrar", "id": "mid", "tipo": "puntero", "nombre": "mid", "arreglo": "arr",
             "en_celda": "{traza.0.mid}", "color": "amarillo"},
            {"en": "punteros", "hacer": "paso_busqueda", "objeto": "arr", "traza": "{traza}", "n": 0, "mid": "mid"},
            {"en": "cuadrícula", "hacer": "mostrar", "id": "cuad", "tipo": "cuadricula", "n": 8, "cabeceras": True,
             "zona": "abajo"},
        ]},
        {"narracion": "Se duplica y aparece el código y una pila.", "pasos": [
            {"en": "inicio", "hacer": "cursor", "objeto": "cuad", "fila": 1, "columna": 3},
            {"en": "inicio", "hacer": "mostrar", "id": "pila", "tipo": "pila", "elementos": ["f(1)"], "zona": "abajo"},
            {"en": "duplica", "hacer": "expandir", "objeto": "cuad"},
            {"en": "duplica", "hacer": "colorear", "objeto": "cuad.cuadrante:sd", "color": "rojo", "opacidad": 0.7},
            {"en": "aparece", "hacer": "apilar", "objeto": "pila", "elemento": "f(2)"},
            {"en": "código", "hacer": "desapilar", "objeto": "pila"},
            {"en": "fin", "hacer": "quitar", "objeto": ["arr", "mid", "cuad", "pila"]},
            {"en": "fin", "hacer": "mostrar", "id": "cod", "tipo": "codigo",
             "lineas": ["while lo <= hi:", "  mid = (lo + hi) // 2"]},
            {"en": "fin", "hacer": "resaltar_linea", "objeto": "cod", "linea": 2},
        ]},
    ],
}


@pytest.mark.render
def test_humo_algoritmos_construye_en_borrador(tmp_path, monkeypatch):
    from toolkit.guion.runtime import escena_desde_yaml
    from toolkit.narracion import MotorNarracion

    monkeypatch.setenv("SHORT_TTS_OFFLINE", "1")
    ruta = tmp_path / "guion_tecnico.yaml"
    ruta.write_text(yaml.safe_dump(GUION_HUMO, allow_unicode=True, sort_keys=False), encoding="utf-8")
    base = escena_desde_yaml(ruta)

    class Humo(base):
        def setup(self):
            super().setup()
            self._motor_narracion = MotorNarracion(dir_cache=tmp_path / "tts", permitir_red=False)

    cfg = {"quality": "low_quality", "dry_run": True, "media_dir": str(tmp_path / "media"), "disable_caching": True}
    with tempconfig(cfg):
        escena = Humo()
        escena.render()
    assert set(escena.contexto_guion.objetos) == {"cod"}
