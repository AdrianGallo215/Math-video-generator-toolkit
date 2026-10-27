"""Tests de la familia ``algebra`` del catálogo del guion: tipos ``ecuacion`` y ``derivacion``, verbos
``siguiente_paso`` y ``resultado_final``, y ``transformar`` extendido a ecuaciones (tokens que vuelan)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

import toolkit.guion.catalogo  # noqa: F401  (registra las piezas)
from toolkit.estilos import AMARILLO, AZUL, COLOR_SEMANTICO, NARANJA
from toolkit.guion import registro
from toolkit.guion.catalogo.algebra import (
    mapa_de_colores,
    mapa_de_tokens,
    pasos_de_derivacion,
    tokens_de_tex,
)
from toolkit.guion.validar import guion_de_ejemplo, validar

PIEZAS = ("ecuacion", "derivacion", "siguiente_paso", "resultado_final")
LATEX_V02 = [
    "x^2 + 6 x = 16",
    "x^2 + 6 x + 9 = 16 + 9",
    "(x+3)^2 = 16 + 9",
    "(x+3)^2 = 25",
    r"x + 3 = \pm 5",
    r"x = 2 \quad x = - 8",
]
RESOLVER_V02 = {"motor": "completar_cuadrado", "coefs": [1, 6, -16]}
MAPA_V02 = {3: "naranja", 6: "naranja", 9: "naranja", 25: "amarillo"}


# --- funciones puras ----------------------------------------------------------------------------------------


def test_tokens_de_tex_lista_normaliza_y_convierte_numeros():
    assert tokens_de_tex(["x^2", "+", 6, "x", "=", 16]) == ("x^2", "+", "6", "x", "=", "16")


def test_tokens_de_tex_string_se_tokeniza():
    assert tokens_de_tex("x^2 + 6x = 16") == ("x^2", "+", "6", "x", "=", "16")


@pytest.mark.parametrize("malo", ["", [], ["  "], None, 3])
def test_tokens_de_tex_vacio_o_invalido(malo):
    with pytest.raises(ValueError):
        tokens_de_tex(malo)


def test_tokens_de_tex_rechaza_llaves_desbalanceadas():
    with pytest.raises(ValueError, match="llaves"):
        tokens_de_tex([r"\frac{1", "}{2}"])


def test_mapa_de_colores_suma_al_semantico_con_claves_numericas():
    mapa = mapa_de_colores(MAPA_V02)
    assert mapa["x"] == COLOR_SEMANTICO["x"] == AZUL
    assert mapa["3"] == NARANJA and mapa["25"] == AMARILLO
    with pytest.raises(ValueError, match="color"):
        mapa_de_colores({"3": "fucsia"})


def test_mapa_de_tokens_convierte_claves_y_valores_a_texto():
    assert mapa_de_tokens({16: 25, "x^2": "(x+3)^2"}) == {"16": "25", "x^2": "(x+3)^2"}
    assert mapa_de_tokens(None) == {}


def test_pasos_de_derivacion_completar_cuadrado_reproduce_v02():
    pasos = pasos_de_derivacion(resolver=RESOLVER_V02)
    assert [p.latex for p in pasos] == LATEX_V02


def test_pasos_de_derivacion_manuales_en_tres_formas():
    pasos = pasos_de_derivacion(pasos=[
        ["2", "x", "=", "8"],
        "x = 8 / 2",
        {"tex": ["x", "=", "4"], "explicacion": "Dividimos", "resaltar": [2]},
    ])
    assert [p.tokens for p in pasos] == [("2", "x", "=", "8"), ("x", "=", "8", "/", "2"), ("x", "=", "4")]
    assert pasos[2].explicacion == "Dividimos" and pasos[2].resaltar == (2,)


def test_pasos_de_derivacion_acepta_la_salida_de_calculos():
    from toolkit.guion.esquema import MOTORES

    salida = MOTORES["completar_cuadrado"](1, 6, -16)
    pasos = pasos_de_derivacion(pasos=salida)
    assert [p.latex for p in pasos] == LATEX_V02
    assert pasos[1].resaltar == (5, 9)


def test_pasos_de_derivacion_tomar_y_explicaciones():
    pasos = pasos_de_derivacion(resolver=RESOLVER_V02, tomar=[0, 3, 5], explicaciones=["Partimos", None, ""])
    assert [p.latex for p in pasos] == [LATEX_V02[0], LATEX_V02[3], LATEX_V02[5]]
    assert [p.explicacion for p in pasos] == ["Partimos", "Sumamos: 16 + 9 = 25", ""]


@pytest.mark.parametrize(
    "kw, fragmento",
    [
        ({}, "resolver"),
        ({"resolver": RESOLVER_V02, "pasos": [["x"]]}, "resolver"),
        ({"resolver": {"motor": "magia", "coefs": [1, 2, 3]}}, "motor"),
        ({"resolver": {"motor": "cuadratica", "coefs": [1, 2]}}, "coefs"),
        ({"resolver": {"motor": "cuadratica", "coefs": [0, 2, 1]}}, "0"),
        ({"pasos": []}, "paso"),
        ({"resolver": RESOLVER_V02, "tomar": [9]}, "tomar"),
        ({"resolver": RESOLVER_V02, "explicaciones": ["a"] * 7}, "explicaciones"),
    ],
)
def test_pasos_de_derivacion_errores_dicen_que_corregir(kw, fragmento):
    with pytest.raises(ValueError, match=fragmento):
        pasos_de_derivacion(**kw)


# --- partes direccionables de una ecuación (construye MathTex: LaTeX) --------------------------------------


def test_partes_de_ecuacion_tokens_ocurrencias_rangos_y_lados():
    from toolkit.algebra_visual import Ecuacion
    from toolkit.guion.catalogo.algebra import anotar_partes

    eq = anotar_partes(Ecuacion("x^2", "+", "6", "x", "+", "9", "=", "16", "+", "9"))
    partes = eq.partes_guion
    assert partes["16"] is eq[7]
    assert partes["9"] is eq[5] and partes["9#2"] is eq[9] and partes["9#1"] is eq[5]
    assert list(partes["0:3"]) == [eq[0], eq[1], eq[2]]
    assert list(partes["izquierda"]) == list(eq[:6]) and list(partes["derecha"]) == list(eq[7:])
    assert "9#3" not in partes and "5:2" not in partes and "0:99" not in partes
    copia = eq.copy()
    assert copia.partes_guion["16"] is copia[7]  # la copia apunta a sus propios tokens


# --- validación estática (ciclo de vida y parámetros) ---------------------------------------------------------


def _validar(tmp_path: Path, datos: dict, **kw):
    ruta = tmp_path / "guion_tecnico.yaml"
    ruta.write_text(yaml.safe_dump(datos, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return validar(ruta, **kw)


def _guion(pasos: list[dict], narracion: str = "Uno dos tres cuatro cinco seis siete ocho.", **extra) -> dict:
    datos = {
        "version": 1,
        "meta": {"slug": "alg", "titulo": "Álgebra", "clase": "Alg"},
        "segmentos": [{"narracion": narracion, "pasos": pasos}],
    }
    datos.update(extra)
    return datos


def _p(en, hacer, **params):
    return {"en": en, "hacer": hacer, **params}


DER = _p("inicio", "mostrar", id="der", tipo="derivacion", resolver=RESOLVER_V02, modo="acumular", max_visibles=2)


@pytest.mark.parametrize("nombre", PIEZAS)
def test_ejemplo_de_cada_pieza_valida(tmp_path, nombre):
    definicion = registro.CATALOGO[nombre]
    assert definicion.descripcion and all(p.descripcion for p in definicion.params)
    reporte = _validar(tmp_path, guion_de_ejemplo(nombre))
    assert reporte.ok, reporte.texto()


def test_ecuacion_valida_colores_y_llaves(tmp_path):
    malo = _p("inicio", "mostrar", id="e", tipo="ecuacion", tex=["x", "=", "1"], mapa={"x": "fucsia"})
    assert "E6" in [h.codigo for h in _validar(tmp_path, _guion([malo])).errores]
    malo = _p("inicio", "mostrar", id="e", tipo="ecuacion", tex=[r"\frac{1", "}{2}"])
    errores = _validar(tmp_path, _guion([malo])).errores
    assert any(h.codigo == "E3" and "llaves" in h.mensaje for h in errores)
    chico = _p("inicio", "mostrar", id="e", tipo="ecuacion", tex="x = 1", tamano=20)
    assert "E8" in [h.codigo for h in _validar(tmp_path, _guion([chico])).errores]


def test_derivacion_parametros_invalidos(tmp_path):
    doble = dict(DER, pasos=[["x"]])
    errores = _validar(tmp_path, _guion([doble])).errores
    assert any(h.codigo == "E3" and "resolver" in h.mensaje for h in errores)
    relativa = dict(DER, zona={"de": "otro", "lado": "abajo"})
    errores = _validar(tmp_path, _guion([_p("inicio", "mostrar", id="otro", tipo="texto", texto="a"), relativa])).errores
    assert any(h.codigo == "E3" and "zona" in h.mensaje for h in errores)


def test_siguiente_paso_cuenta_los_pasos_disponibles(tmp_path):
    pasos = [DER] + [_p("inicio", "siguiente_paso", objeto="der") for _ in range(5)]
    assert _validar(tmp_path, _guion(pasos)).ok
    sobra = pasos + [_p("inicio", "siguiente_paso", objeto="der")]
    errores = _validar(tmp_path, _guion(sobra)).errores
    assert any(h.codigo == "E3" and "6 pasos" in h.mensaje for h in errores), errores


def test_siguiente_paso_y_resultado_final_exigen_una_derivacion(tmp_path):
    texto = _p("inicio", "mostrar", id="der", tipo="texto", texto="hola")
    for verbo in ("siguiente_paso", "resultado_final"):
        errores = _validar(tmp_path, _guion([texto, _p("inicio", verbo, objeto="der")])).errores
        assert any(h.codigo == "E3" and "derivacion" in h.mensaje for h in errores), errores
    quitada = [DER, _p("inicio", "quitar", objeto="der"), _p("inicio", "siguiente_paso", objeto="der")]
    assert "E4" in [h.codigo for h in _validar(tmp_path, _guion(quitada)).errores]


def test_transformar_ecuacion_en_derivacion_y_calculos(tmp_path):
    pasos = [
        _p("inicio", "mostrar", id="eq", tipo="ecuacion", tex="{cc.0.tokens}", tamano=72),
        _p("dos", "transformar", objeto="eq", a={"id": "der", "tipo": "derivacion", "pasos": "{cc}"}),
        _p("tres", "siguiente_paso", objeto="der"),
        _p("cuatro", "transformar", objeto="der.actual", copia=True,
           a={"id": "copia", "tipo": "ecuacion", "tex": "x^2 + 6x + 9 = 25"}),
    ]
    calculos = {"cc": {"motor": "completar_cuadrado", "a": 1, "b": 6, "c": -16}}
    reporte = _validar(tmp_path, _guion(pasos, calculos=calculos))
    assert reporte.ok, reporte.texto()


# --- humo: construyen escenas en dry_run con TTS offline -------------------------------------------------------

TRES_LINEAS = (
    "from toolkit.guion.runtime import escena_desde_yaml\n\n\n"
    "class {clase}(escena_desde_yaml(\"guion_tecnico.yaml\")):\n    pass\n"
)


def _importar(ruta: Path, nombre: str):
    spec = importlib.util.spec_from_file_location(nombre, ruta)
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[nombre] = modulo
    spec.loader.exec_module(modulo)
    return modulo


def _render(tmp_path: Path, datos: dict, nombre: str):
    """Renderiza (dry_run) el guion ``datos``; devuelve la escena con ``registro_plays`` [(t, animaciones)]."""
    from manim import tempconfig

    from toolkit.narracion import MotorNarracion

    clase = datos["meta"]["clase"]
    (tmp_path / "guion_tecnico.yaml").write_text(yaml.safe_dump(datos, allow_unicode=True), encoding="utf-8")
    ruta = tmp_path / "escena.py"
    ruta.write_text(TRES_LINEAS.format(clase=clase), encoding="utf-8")
    base = getattr(_importar(ruta, nombre), clase)

    class ConRegistro(base):
        def setup(self):
            super().setup()
            self._motor_narracion = MotorNarracion(dir_cache=tmp_path / "tts", permitir_red=False)
            self.registro_plays = []

        def play(self, *animaciones, **kwargs):
            self.registro_plays.append((self.renderer.time, animaciones))
            super().play(*animaciones, **kwargs)

    config = {"quality": "low_quality", "dry_run": True, "media_dir": str(tmp_path / "media"), "disable_caching": True}
    with tempconfig(config):
        escena = ConRegistro()
        escena.render()
    return escena


def _dentro_de_zona_segura(mob) -> bool:
    from toolkit.layout import ZONA_SEGURA

    return ZONA_SEGURA.contiene(mob)


def _animaciones(escena, clase) -> list:
    """Todas las animaciones de tipo ``clase`` reproducidas (recorre grupos y fases)."""
    from manim import AnimationGroup

    from toolkit.guion.catalogo.algebra import AnimacionEnFases

    encontradas = []

    def recorrer(a):
        if isinstance(a, clase):
            encontradas.append(a)
        if isinstance(a, AnimationGroup):
            for sub in a.animations:
                recorrer(sub)
        if isinstance(a, AnimacionEnFases):
            for grupo in a.grupos_construidos:
                recorrer(grupo)

    for _, anims in escena.registro_plays:
        for a in anims:
            recorrer(a)
    return encontradas


def _v02(modo: str, max_visibles: int, indicar: bool) -> dict:
    siguientes = [_p(pal, "siguiente_paso", objeto="der", indicar=indicar)
                  for pal in ("dos", "tres", "cuatro", "cinco", "seis")]
    return _guion(
        [_p("inicio", "mostrar", id="der", tipo="derivacion", resolver=RESOLVER_V02, modo=modo,
            max_visibles=max_visibles, mapa=MAPA_V02, mostrar_explicacion=False),
         *siguientes,
         _p("siete", "resultado_final", objeto="der", parte="0:3"),
         _p("ocho", "resaltar", objeto="der", parte="4:8", modo="rodear", color="gris")],
        narracion="Uno dos tres cuatro cinco seis siete ocho nueve diez.",
    )


@pytest.mark.render
def test_humo_derivacion_v02_completar_cuadrado_seis_pasos_acumular(tmp_path):
    from toolkit.algebra_visual import OPACIDAD_PASO_ANTERIOR, TransformarTokens

    datos = _v02("acumular", 2, indicar=False)
    datos["meta"]["clase"] = "V02Acumular"
    escena = _render(tmp_path, datos, "escena_alg_v02_acumular")
    der = escena.contexto_guion.objetos["der"]
    ctrl = der.derivacion_guion
    assert ctrl.dv.indice == 5 and not ctrl.dv.quedan_pasos
    assert [p.latex for p in ctrl.dv.pasos] == LATEX_V02
    assert ctrl.dv.actual.tokens == ("x", "=", "2", r"\quad", "x", "=", "-", "8")
    assert len(ctrl.dv.visibles) == 2 and ctrl.dv.caja is not None
    assert ctrl.dv.visibles[0].get_fill_opacity() == pytest.approx(OPACIDAD_PASO_ANTERIOR)
    # Los tokens vuelan: cada siguiente_paso reprodujo un TransformarTokens.
    assert len(_animaciones(escena, TransformarTokens)) == 5
    # En pantalla solo queda la derivación (filas visibles + caja), consolidada y dentro de la zona segura.
    familia = escena.get_mobject_family_members()
    assert der in escena.mobjects
    for fila in ctrl.dv.ecuaciones[:4]:
        assert fila not in familia
    assert set(der.submobjects) == {*ctrl.dv.visibles, ctrl.dv.caja}
    assert _dentro_de_zona_segura(der)


@pytest.mark.render
def test_humo_derivacion_reemplazar_con_indicar_y_explicacion(tmp_path):
    from manim import Indicate

    datos = _v02("reemplazar", 4, indicar=True)
    datos["segmentos"][0]["pasos"][0]["mostrar_explicacion"] = True
    datos["meta"]["clase"] = "V02Reemplazar"
    escena = _render(tmp_path, datos, "escena_alg_v02_reemplazar")
    ctrl = escena.contexto_guion.objetos["der"].derivacion_guion
    assert ctrl.dv.indice == 5 and len(ctrl.dv.visibles) == 1
    assert ctrl.dv.explicacion is not None and ctrl.dv.explicacion in escena.get_mobject_family_members()
    assert _animaciones(escena, Indicate)  # pasos con 'resaltar' del motor
    assert _dentro_de_zona_segura(escena.contexto_guion.objetos["der"])


@pytest.mark.render
def test_humo_ecuacion_transformar_tokens_copia_y_destino_token(tmp_path):
    from manim import ReplacementTransform

    from toolkit.algebra_visual import TransformarTokens

    pasos = [
        _p("inicio", "mostrar", id="eq", tipo="ecuacion", tex="x^2 + 6x = 16", mapa=MAPA_V02, tamano=72, zona="arriba"),
        _p("inicio", "mostrar", id="num", tipo="ecuacion", tex=["16"], zona="abajo", color="gris"),
        _p("dos", "resaltar", objeto="eq.16"),
        _p("tres", "transformar", objeto="eq", mapa={16: 25},
           a={"tipo": "ecuacion", "tex": "(x+3)^2 = 25", "mapa": MAPA_V02, "tamano": 72, "zona": "arriba"}),
        _p("cuatro", "transformar", objeto="eq.25", copia=True, arco=1.57,
           a={"id": "copia", "tipo": "ecuacion", "tex": ["25"], "zona": "medio"}),
        _p("cinco", "transformar", objeto="num", a="copia.25"),
        _p("seis", "resaltar", objeto="eq", parte="izquierda", modo="rodear"),
    ]
    zonas = {
        "arriba": {"de": "principal", "filas": [1, 1, 1], "fila": 0},
        "medio": {"de": "principal", "filas": [1, 1, 1], "fila": 1},
        "abajo": {"de": "principal", "filas": [1, 1, 1], "fila": 2},
    }
    datos = _guion(pasos, zonas=zonas)
    datos["meta"]["clase"] = "AlgEcuaciones"
    escena = _render(tmp_path, datos, "escena_alg_ecuaciones")
    ctx = escena.contexto_guion
    assert ctx.objetos["eq"].tokens == ("(x+3)^2", "=", "25")
    assert "num" not in ctx.objetos and "copia" in ctx.objetos
    assert len(_animaciones(escena, TransformarTokens)) == 1  # ecuación -> ecuación (con mapa 16 -> 25)
    # La copia del token 25 vuela a su igual en la ecuación nueva, y 'num' vuela al token 'copia.25'.
    vuelos = _animaciones(escena, ReplacementTransform)
    assert len(vuelos) == 2 and all(v.target_mobject.tex_string == "25" for v in vuelos)
    for id in ("eq", "copia"):
        assert _dentro_de_zona_segura(ctx.objetos[id])
    from toolkit.estilos import COLOR_SEMANTICO

    assert ctx.objetos["eq"].parte("25").get_color().to_hex().upper() == AMARILLO.upper()
    assert COLOR_SEMANTICO["x"] == AZUL


@pytest.mark.render
def test_humo_ecuacion_vuela_a_derivacion_y_derivacion_a_ecuacion(tmp_path):
    from toolkit.algebra_visual import TransformarTokens

    pasos = [
        _p("inicio", "mostrar", id="eq", tipo="ecuacion", tex="{cc.0.tokens}", tamano=80, zona="titulo"),
        _p("dos", "transformar", objeto="eq",
           a={"id": "der", "tipo": "derivacion", "pasos": "{cc}", "modo": "acumular", "max_visibles": 3}),
        _p("tres", "siguiente_paso", objeto="der"),
        _p("cuatro", "resaltar", objeto="der", parte="actual.9#2"),
        _p("cinco", "transformar", objeto="der", a={"id": "fin", "tipo": "ecuacion", "tex": "x = 2", "zona": "principal"}),
    ]
    calculos = {"cc": {"motor": "completar_cuadrado", "a": 1, "b": 6, "c": -16}}
    datos = _guion(pasos, calculos=calculos)
    datos["meta"]["clase"] = "AlgDesde"
    escena = _render(tmp_path, datos, "escena_alg_desde")
    ctx = escena.contexto_guion
    assert set(ctx.objetos) == {"fin"}
    assert len(_animaciones(escena, TransformarTokens)) == 3
    familia = escena.get_mobject_family_members()
    assert ctx.objetos["fin"] in familia
    assert _dentro_de_zona_segura(ctx.objetos["fin"])
