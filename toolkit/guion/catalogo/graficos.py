"""Familia gráficos del catálogo del guion: ejes, curvas, punto que recorre una curva, tangente, vectores y tiro
parabólico (envuelve ``toolkit.graficos`` y ``toolkit.motor_fisica``).

Piezas: tipos ``ejes``, ``curva``, ``punto_en_curva``, ``tangente``, ``vector``, ``trayectoria``; verbos
``descomponer_vector`` y ``mover_variable``.

Convenciones:

- Las piezas que dibujan SOBRE unos ejes los referencian con ``de`` (id de los ejes, de la curva o del punto).
  Las coordenadas que aparecen en el guion (``x``, ``componentes``, ``origen``) son coordenadas matemáticas de
  esos ejes, nunca de pantalla.
- ``curva.funcion`` es una expresión en ``x`` (``"x^2/2 - 1"``, ``"sin(x)"``) que se parsea de forma segura
  (:func:`parsear_funcion`): lista blanca de nombres, sin ``eval`` libre.
- Lo que se mueve (punto, tangente, trayectoria) sigue a un ``ValueTracker`` con updaters (no ``always_redraw``:
  la identidad del Mobject se conserva y ``resaltar``/``quitar`` funcionan). Los updaters se crean DESPUÉS de
  colocar los ejes y se aplican una vez al crearlos (primer fotograma correcto).
- ``variable``: un valor con nombre que varios objetos siguen (efecto persistente ``variable``; se mueve con
  ``mover_variable`` y se congela con ``detener``). Sin nombre, cada objeto móvil tiene su propio valor y
  ``mover_variable`` actúa con ``objeto: <id>``.
"""

from __future__ import annotations

import logging
import math
import re
from functools import partial
from typing import Any, Callable

import numpy as np
import sympy
from manim import (
    LEFT,
    RIGHT,
    UP,
    UR,
    AnimationGroup,
    Create,
    Dot,
    Line,
    MathTex,
    Mobject,
    TransformFromCopy,
    ValueTracker,
    VGroup,
)
from sympy.parsing.sympy_parser import (
    convert_xor,
    implicit_multiplication,
    parse_expr,
    standard_transformations,
)

from toolkit import motor_fisica
from toolkit.guion.catalogo.contadores import AnimacionDiferida
from toolkit.estilos import (
    BLANCO,
    FUENTE_ETIQUETA,
    FUENTE_MINIMA,
    GROSOR_LINEA_FINA,
    GROSOR_LINEA_MEDIA,
    TIEMPO_CREAR,
    TIEMPO_TRANSFORMAR,
)
from toolkit.graficos import EjesShort, PlanoShort, _tramos_visibles
from toolkit.graficos import curva as graficar_curva
from toolkit.graficos import descomponer_vector as componentes_de_vector
from toolkit.graficos import trayectoria as curva_parametrica
from toolkit.graficos import vector as flecha_vector
from toolkit.guion.contexto import (
    ALINEACIONES,
    ATRIBUTO_PARTES,
    MARGEN_ZONA,
    ZONA_CONTENIDO,
    ContextoGuion,
    _ajustar_dentro,
    _error,
)
from toolkit.guion.registro import Param, accion, objeto

logger = logging.getLogger(__name__)

# --- constantes de la familia -----------------------------------------------------------------------------

LONGITUD_MAX_EXPRESION = 200
RADIO_PUNTO = 0.11
RADIO_PROYECTIL = 0.12
LONGITUD_TANGENTE = 2.6
ITERACIONES_ENCAJE = 4
REDUCCION_ENCAJE = 0.98
MAX_MARCAS = 12
PROGRESO_MINIMO = 1e-3
LARGO_MINIMO_GUIA = 1e-3
TRAZOS_GUIA = 12
PROPORCION_TRAZO = 0.55  # parte de cada tramo de la guía que se pinta

# Atributos con que las piezas se reconocen entre sí (los pone la pieza que crea el objeto).
ATRIBUTO_EJES = "ejes_guion"
ATRIBUTO_FUNCION = "funcion_guion"
ATRIBUTO_TRACKER = "tracker_guion"
ATRIBUTO_VARIABLE = "variable_guion"
ATRIBUTO_VECTOR = "vector_guion"
TIPO_EFECTO_VARIABLE = "variable"

_PARAM_ZONA = Param("zona", "zona", defecto="principal",
                    descripcion="Zona donde se encajan los ejes (nombre) o {de: id, lado, espacio}.")
_PARAM_ALINEACION = Param("alineacion", "texto", defecto="centro", opciones=tuple(ALINEACIONES),
                          descripcion="Borde de la zona al que se pegan los ejes.")


# --- parseo seguro de expresiones ------------------------------------------------------------------------------


class ErrorExpresion(ValueError):
    """Expresión de ``curva.funcion`` inválida o no permitida (el mensaje dice qué corregir)."""


_X = sympy.Symbol("x", real=True)
_FUNCIONES_PERMITIDAS: dict[str, Any] = {
    "sin": sympy.sin, "cos": sympy.cos, "tan": sympy.tan,
    "asin": sympy.asin, "acos": sympy.acos, "atan": sympy.atan,
    "sinh": sympy.sinh, "cosh": sympy.cosh, "tanh": sympy.tanh,
    "exp": sympy.exp, "log": sympy.log, "ln": sympy.log, "sqrt": sympy.sqrt,
    "abs": sympy.Abs, "Abs": sympy.Abs, "floor": sympy.floor, "ceiling": sympy.ceiling,
}
_CONSTANTES_PERMITIDAS: dict[str, Any] = {"pi": sympy.pi, "E": sympy.E, "e": sympy.E}
NOMBRES_PERMITIDOS = frozenset({"x", *_FUNCIONES_PERMITIDAS, *_CONSTANTES_PERMITIDAS})
_CARACTERES_PERMITIDOS = re.compile(r"^[0-9A-Za-z_+\-*/^()., ]+$")
_NUMERO = re.compile(r"\d+\.?\d*(?:[eE][+-]?\d+)?|\.\d+(?:[eE][+-]?\d+)?")
_IDENTIFICADOR = re.compile(r"[A-Za-z_][A-Za-z_0-9]*")
_ACCESO_ATRIBUTO = re.compile(r"\.\s*[A-Za-z_(]")
_TRANSFORMACIONES = standard_transformations + (implicit_multiplication, convert_xor)
_GLOBALES_PARSEO = {
    "__builtins__": {},
    "Integer": sympy.Integer,
    "Float": sympy.Float,
    "Rational": sympy.Rational,
    "Symbol": sympy.Symbol,
}
_AYUDA_EXPRESION = ("usa una expresión en x con números, + - * / ^ ( ) y las funciones "
                    f"{', '.join(sorted(_FUNCIONES_PERMITIDAS))} o las constantes pi, E. Ej.: \"x^2/2 - 1\"")


class FuncionSegura:
    """Función real de una variable parseada de un texto: ``f(x)``, ``f.derivada(x)``, ``f.texto``, ``f.expr``.

    Fuera del dominio (``sqrt(-1)``, ``log(0)``, ``1/0``) lanza ``ValueError``/``ZeroDivisionError``/
    ``OverflowError`` (``toolkit.graficos`` los trata como "no visible").
    """

    def __init__(self, texto: str, expr: sympy.Expr) -> None:
        self.texto = texto
        self.expr = expr
        self._f = sympy.lambdify(_X, expr, modules="math")
        self._df = sympy.lambdify(_X, sympy.diff(expr, _X), modules="math")

    @staticmethod
    def _real(valor: Any) -> float:
        if isinstance(valor, complex):
            if abs(valor.imag) > 1e-12:
                raise ValueError("valor complejo fuera del dominio real")
            valor = valor.real
        resultado = float(valor)
        if not math.isfinite(resultado):
            raise ValueError("valor no finito")
        return resultado

    def __call__(self, x: float) -> float:
        return self._real(self._f(float(x)))

    def derivada(self, x: float) -> float:
        return self._real(self._df(float(x)))

    def __repr__(self) -> str:
        return f"FuncionSegura({self.texto!r})"


def parsear_funcion(texto: Any) -> FuncionSegura:
    """Parsea ``texto`` (expresión en ``x``) de forma segura; ``ErrorExpresion`` si no es válida o permitida.

    Seguridad: antes de llegar a sympy se exige un alfabeto mínimo (sin comillas, corchetes, ``;``, ``:``, ``=``),
    sin ``__`` ni acceso a atributos, y que TODOS los identificadores estén en :data:`NOMBRES_PERMITIDOS`;
    ``parse_expr`` corre con ``__builtins__`` vacío y un espacio de nombres restringido. El resultado debe ser una
    expresión sympy cuyo único símbolo libre sea ``x``.
    """
    if not isinstance(texto, str) or not texto.strip():
        raise ErrorExpresion(f"la función está vacía: {_AYUDA_EXPRESION}")
    limpio = texto.strip()
    if len(limpio) > LONGITUD_MAX_EXPRESION:
        raise ErrorExpresion(f"la función es demasiado larga (> {LONGITUD_MAX_EXPRESION} caracteres)")
    if not _CARACTERES_PERMITIDOS.match(limpio):
        raros = sorted({c for c in limpio if not _CARACTERES_PERMITIDOS.match(c)})
        raise ErrorExpresion(f"caracteres no permitidos {''.join(raros)!r} en {limpio!r}: {_AYUDA_EXPRESION}")
    if "__" in limpio or _ACCESO_ATRIBUTO.search(_NUMERO.sub("0", limpio)):
        raise ErrorExpresion(f"{limpio!r}: no se permite acceder a atributos: {_AYUDA_EXPRESION}")
    desconocidos = sorted(set(_IDENTIFICADOR.findall(_NUMERO.sub(" ", limpio))) - NOMBRES_PERMITIDOS)
    if desconocidos:
        raise ErrorExpresion(f"nombres no permitidos {desconocidos} en {limpio!r}: {_AYUDA_EXPRESION}")
    espacio = {"x": _X, **_FUNCIONES_PERMITIDAS, **_CONSTANTES_PERMITIDAS}
    try:
        expr = parse_expr(limpio, local_dict=espacio, global_dict=dict(_GLOBALES_PARSEO),
                          transformations=_TRANSFORMACIONES, evaluate=True)
    except Exception as error:  # SyntaxError, TokenError, TypeError... todo es "expresión mal formada"
        raise ErrorExpresion(f"no entiendo la función {limpio!r} ({type(error).__name__}): {_AYUDA_EXPRESION}") from error
    if not isinstance(expr, sympy.Expr):
        raise ErrorExpresion(f"{limpio!r} no es una expresión numérica: {_AYUDA_EXPRESION}")
    if expr.free_symbols - {_X}:
        raise ErrorExpresion(f"{limpio!r}: la única variable permitida es x")
    if expr.has(sympy.core.function.AppliedUndef):
        raise ErrorExpresion(f"{limpio!r}: usa solo funciones conocidas: {_AYUDA_EXPRESION}")
    try:
        return FuncionSegura(limpio, expr)
    except Exception as error:
        raise ErrorExpresion(f"no puedo evaluar {limpio!r}: {error}") from error


# --- utilidades comunes ------------------------------------------------------------------------------------


def _con_partes(grupo: Mobject, partes: dict[str, Mobject]) -> Mobject:
    setattr(grupo, ATRIBUTO_PARTES, partes)
    return grupo


def _exigir(ctx: ContextoGuion, ref: str, atributo: str, que: str) -> tuple[Mobject, Any]:
    """(mob, valor del atributo) del objeto ``ref``; E3 si no es del tipo esperado."""
    mob = ctx.obtener(ref)
    valor = getattr(mob, atributo, None)
    if valor is None:
        raise _error("E3", f"'{ref}' no es {que}", ctx.ubicacion)
    return mob, valor


def _ejes_de(ctx: ContextoGuion, ref: str):
    return _exigir(ctx, ref, ATRIBUTO_EJES, "unos ejes (ni una pieza dibujada sobre ejes): usa el id de un 'ejes'")[1]


def _funcion_en_guion(ctx: ContextoGuion, texto: str) -> FuncionSegura:
    try:
        return parsear_funcion(texto)
    except ErrorExpresion as error:
        raise _error("E3", str(error), ctx.ubicacion) from error


def _es_numero(valor: Any) -> bool:
    return isinstance(valor, (int, float)) and not isinstance(valor, bool)


def _lista_numeros(valor: Any, longitudes: tuple[int, ...]) -> bool:
    return isinstance(valor, list) and len(valor) in longitudes and all(_es_numero(v) for v in valor)


def _usar(estado, params: dict, *nombres: str) -> bool:
    """``estado.usar`` de cada parámetro-referencia (uno solo por parámetro) y de ``zona.de``; True si todo existe."""
    ok = True
    for nombre in nombres:
        valor = params.get(nombre)
        if valor is None:
            continue
        if isinstance(valor, list):
            estado.error("E3", f"'{nombre}' admite un solo id aquí, no una lista")
            ok = False
            continue
        ok = estado.usar(valor) and ok
    zona = params.get("zona")
    if isinstance(zona, dict) and isinstance(zona.get("de"), str):
        estado.usar(zona["de"], permitir_reservado=True)
    return ok


# --- variables (efecto persistente) ------------------------------------------------------------------------


def _tracker_de_variable(ctx: ContextoGuion, nombre: str | None, inicial: float) -> ValueTracker:
    """El ``ValueTracker`` de la variable ``nombre`` (lo crea como efecto si no existe) o uno privado."""
    if not nombre:
        return ValueTracker(float(inicial))
    efecto = ctx.efectos.get(nombre)
    if efecto is not None:
        if efecto.tipo != TIPO_EFECTO_VARIABLE:
            raise _error("E4", f"'{nombre}' es un efecto de tipo {efecto.tipo}, no una variable", ctx.ubicacion)
        return efecto.datos["tracker"]
    tracker = ValueTracker(float(inicial))
    seguidores: list[tuple[Mobject, Callable]] = []

    def congelar(_ctx: ContextoGuion) -> None:
        for mob, fn in seguidores:
            mob.remove_updater(fn)
        return None

    ctx.iniciar_efecto(nombre, TIPO_EFECTO_VARIABLE, congelar, tracker=tracker, seguidores=seguidores)
    return tracker


def _seguir(ctx: ContextoGuion, variable: str | None, mob: Mobject, fn: Callable[[Mobject], None]) -> None:
    """Hace que ``mob`` siga su valor: ``fn(mob)`` en cada fotograma, aplicado ya (primer fotograma correcto).

    El updater se cuelga de la primera HOJA con puntos de ``mob``: el renderer Cairo solo trata como "en
    movimiento" las hojas que tienen updaters (y las que van detrás); un updater en un VGroup padre deja a sus
    hojas pintadas en el fondo estático y no se ven moverse.
    """
    hojas = mob.family_members_with_points()
    portador = hojas[0] if hojas else mob

    def actualizar(_portador: Mobject) -> None:
        fn(mob)

    portador.add_updater(actualizar)
    fn(mob)
    if variable and variable in ctx.efectos:
        ctx.efectos[variable].datos["seguidores"].append((portador, actualizar))


def _ciclo_variable(params: dict, estado) -> None:
    variable = params.get("variable")
    if variable is None:
        return
    efecto = estado.efectos.get(variable)
    if efecto is None:
        estado.iniciar_efecto(variable, TIPO_EFECTO_VARIABLE)
    elif efecto[0] != TIPO_EFECTO_VARIABLE:
        estado.error("E4", f"'{variable}' ya es un efecto de tipo {efecto[0]}, no una variable")


# --- ejes ----------------------------------------------------------------------------------------------------


def _paso_automatico(minimo: float, maximo: float) -> float:
    """Paso "redondo" (1, 2, 5 × 10^k) que deja ≤ 8 marcas en el rango."""
    bruto = (maximo - minimo) / 8.0
    potencia = 10 ** math.floor(math.log10(bruto)) if bruto > 0 else 1.0
    for factor in (1, 2, 5, 10):
        if factor * potencia >= bruto:
            return float(factor * potencia)
    return float(10 * potencia)


def _rango(valor: list) -> tuple[float, float, float]:
    minimo, maximo = float(valor[0]), float(valor[1])
    paso = float(valor[2]) if len(valor) > 2 else _paso_automatico(minimo, maximo)
    return minimo, maximo, paso


def _marcas(minimo: float, maximo: float, paso: float) -> list[float]:
    marcas = []
    k = math.ceil(minimo / paso - 1e-9)
    while k * paso <= maximo + 1e-9 and len(marcas) < 4 * MAX_MARCAS:
        valor = round(k * paso, 10)
        if abs(valor) > 1e-9:
            marcas.append(valor)
        k += 1
    if len(marcas) > MAX_MARCAS:  # demasiado denso: una de cada dos
        marcas = marcas[1::2]
    return marcas


def _decimales(paso: float) -> int:
    return 0 if abs(paso - round(paso)) < 1e-9 else min(2, max(1, -math.floor(math.log10(paso))))


def _armar_ejes(xr, yr, ancho: float, alto: float, etiqueta_x: str, etiqueta_y: str, numeros: bool,
                cuadricula: bool) -> tuple[VGroup, Any, VGroup, VGroup]:
    if cuadricula:
        ejes = PlanoShort(x_rango=xr, y_rango=yr, ancho=ancho, alto=alto, con_numeros=False)
    else:
        ejes = EjesShort(x_rango=xr, y_rango=yr, ancho=ancho, alto=alto)
        ejes.remove(ejes.etiquetas)  # se rehacen abajo, al tamaño del guion y como parte direccionable
    marcas = VGroup()
    if numeros:
        for eje, (minimo, maximo, paso) in ((ejes.x_axis, xr), (ejes.y_axis, yr)):
            decimales = _decimales(paso)
            for valor in _marcas(minimo, maximo, paso):
                marcas.add(eje.get_number_mobject(valor, font_size=FUENTE_MINIMA, num_decimal_places=decimales))
    etiquetas = VGroup()
    if etiqueta_x or etiqueta_y:
        x_lab = MathTex(etiqueta_x or r"\,", font_size=FUENTE_ETIQUETA, color=BLANCO)
        y_lab = MathTex(etiqueta_y or r"\,", font_size=FUENTE_ETIQUETA, color=BLANCO)
        etiquetas = ejes.get_axis_labels(x_label=x_lab, y_label=y_lab)
        if not etiqueta_x:
            etiquetas.remove(etiquetas[0])
        if not etiqueta_y:
            etiquetas.remove(etiquetas[-1])
    miembros = [ejes] + [g for g in (marcas, etiquetas) if len(g.submobjects) > 0]
    grupo = VGroup(*miembros)
    return grupo, ejes, marcas, etiquetas


def _ciclo_ejes(params: dict, estado) -> None:
    _usar(estado, params)
    for clave in ("x", "y"):
        valor = params.get(clave)
        if not _lista_numeros(valor, (2, 3)):
            estado.error("E3", f"'{clave}' debe ser [mínimo, máximo] o [mínimo, máximo, paso], p. ej. [-3, 3, 1]")
            continue
        if valor[0] >= valor[1]:
            estado.error("E3", f"'{clave}': el mínimo ({valor[0]}) debe ser menor que el máximo ({valor[1]})")
        elif len(valor) == 3 and (valor[2] <= 0 or (valor[1] - valor[0]) / valor[2] > 50):
            estado.error("E3", f"'{clave}': el paso debe ser positivo y dejar ≤ 50 marcas")


@objeto(
    "ejes",
    "Ejes cartesianos estilo 3B1B encajados en una zona a su escala real: los números y las etiquetas "
    "conservan su tamaño legible (se ajusta el largo de los ejes, no la letra). Partes: x, y, numeros, etiquetas.",
    params=[
        Param("x", "lista", defecto=[-4, 4, 1], descripcion="Rango del eje x: [mínimo, máximo] o [mínimo, máximo, paso]."),
        Param("y", "lista", defecto=[-4, 4, 1], descripcion="Rango del eje y: [mínimo, máximo] o [mínimo, máximo, paso]."),
        _PARAM_ZONA,
        _PARAM_ALINEACION,
        Param("etiqueta_x", "texto", defecto="x", descripcion="Nombre del eje horizontal (LaTeX; vacío = sin etiqueta)."),
        Param("etiqueta_y", "texto", defecto="y", descripcion="Nombre del eje vertical (LaTeX; vacío = sin etiqueta)."),
        Param("numeros", "booleano", defecto=True, descripcion="Numera las marcas de ambos ejes (sin el 0)."),
        Param("cuadricula", "booleano", defecto=False, descripcion="Plano con cuadrícula de fondo azulada tenue."),
        Param("misma_escala", "booleano", defecto=False,
              descripcion="Misma unidad en x e y (círculos redondos, pendientes reales); si no, llena la zona."),
    ],
    ejemplo={"en": "inicio", "hacer": "mostrar", "id": "plano", "tipo": "ejes", "x": [-3, 3, 1], "y": [-1, 5, 1]},
    duracion=TIEMPO_CREAR,
    ciclo=_ciclo_ejes,
)
def crear_ejes(ctx: ContextoGuion, x, y, zona, alineacion, etiqueta_x, etiqueta_y, numeros, cuadricula,
               misma_escala) -> Mobject:
    xr, yr = _rango(x), _rango(y)
    referencia = ctx.zona_de_referencia(zona)
    disponible_x = referencia.ancho - 2 * MARGEN_ZONA
    disponible_y = referencia.alto - 2 * MARGEN_ZONA
    ancho, alto = disponible_x, disponible_y
    if misma_escala:
        unidad = min(disponible_x / (xr[1] - xr[0]), disponible_y / (yr[1] - yr[0]))
        ancho, alto = unidad * (xr[1] - xr[0]), unidad * (yr[1] - yr[0])
    for _ in range(ITERACIONES_ENCAJE):
        grupo, ejes, marcas, etiquetas = _armar_ejes(xr, yr, ancho, alto, str(etiqueta_x or ""),
                                                     str(etiqueta_y or ""), numeros, cuadricula)
        factor = min(disponible_x / grupo.width, disponible_y / grupo.height)
        if factor >= 1.0 - 1e-3:
            break
        ancho *= factor * REDUCCION_ENCAJE
        alto *= factor * REDUCCION_ENCAJE
    _con_partes(grupo, {"ejes": ejes, "x": ejes.x_axis, "y": ejes.y_axis, "numeros": marcas, "etiquetas": etiquetas})
    setattr(grupo, ATRIBUTO_EJES, ejes)
    ctx.colocar(grupo, zona, alineacion)
    return grupo


# --- curva -----------------------------------------------------------------------------------------------------


def _ciclo_curva(params: dict, estado) -> None:
    _usar(estado, params, "de")
    try:
        parsear_funcion(params.get("funcion"))
    except ErrorExpresion as error:
        estado.error("E3", f"funcion: {error}")
    desde, hasta = params.get("desde"), params.get("hasta")
    if _es_numero(desde) and _es_numero(hasta) and desde >= hasta:
        estado.error("E3", f"'desde' ({desde}) debe ser menor que 'hasta' ({hasta})")


@objeto(
    "curva",
    "Gráfica de una función de x sobre unos ejes, recortada a lo que se ve (asíntotas y ramas separadas sin "
    "trazos fuera del recuadro). La expresión se parsea de forma segura (solo x, números y funciones comunes).",
    params=[
        Param("de", "objeto", requerido=True, descripcion="Id de los ejes sobre los que se dibuja."),
        Param("funcion", "texto", requerido=True,
              descripcion="Expresión en x: \"x^2/2 - 1\", \"sin(x)\", \"2x + 1\", \"sqrt(x)\" (^ = potencia)."),
        Param("color", "color", defecto="azul", descripcion="Color de la curva."),
        Param("desde", "numero", descripcion="Inicio del dominio (defecto: el borde izquierdo de los ejes)."),
        Param("hasta", "numero", descripcion="Fin del dominio (defecto: el borde derecho de los ejes)."),
        Param("etiqueta", "texto", descripcion="Rótulo LaTeX junto al final de la curva, p. ej. \"f(x)=x^2\"."),
    ],
    ejemplo={"en": "inicio", "hacer": "mostrar", "id": "parabola", "tipo": "curva", "de": "plano",
             "funcion": "x^2/2", "color": "azul"},
    duracion=TIEMPO_CREAR,
    ciclo=_ciclo_curva,
)
def crear_curva(ctx: ContextoGuion, de, funcion, color, desde=None, hasta=None, etiqueta=None) -> Mobject:
    ejes = _ejes_de(ctx, de)
    f = _funcion_en_guion(ctx, funcion)
    hex_color = ctx.color(color)
    x_min, x_max = float(ejes.x_range[0]), float(ejes.x_range[1])
    y_min, y_max = float(ejes.y_range[0]), float(ejes.y_range[1])
    if desde is None and hasta is None:
        trazo = graficar_curva(ejes, f, color=hex_color, grosor=GROSOR_LINEA_MEDIA)
    else:
        a = max(x_min, float(desde)) if desde is not None else x_min
        b = min(x_max, float(hasta)) if hasta is not None else x_max
        tramos = _tramos_visibles(f, a, b, y_min, y_max) if a < b else []
        graficas = [ejes.plot(f, x_range=(t0, t1), color=hex_color, stroke_width=GROSOR_LINEA_MEDIA)
                    for t0, t1 in tramos]
        trazo = graficas[0] if len(graficas) == 1 else VGroup(*graficas)
    if trazo.get_num_points() == 0 and not trazo.submobjects:
        raise _error("E3", f"la función {funcion!r} no tiene ningún tramo visible en el rango de los ejes "
                           f"(x {x_min}..{x_max}, y {y_min}..{y_max})", ctx.ubicacion)
    resultado: Mobject = trazo
    if etiqueta:
        rotulo = MathTex(str(etiqueta), font_size=FUENTE_ETIQUETA, color=hex_color)
        ultimo = trazo.submobjects[-1] if isinstance(trazo, VGroup) and trazo.submobjects else trazo
        rotulo.next_to(ultimo.get_end(), UP + LEFT * 0.5, buff=0.15)
        _ajustar_dentro(rotulo, ZONA_CONTENIDO)
        resultado = _con_partes(VGroup(trazo, rotulo), {"curva": trazo, "etiqueta": rotulo})
    setattr(resultado, ATRIBUTO_EJES, ejes)
    setattr(resultado, ATRIBUTO_FUNCION, f)
    return resultado


# --- punto_en_curva ----------------------------------------------------------------------------------------------


def _ciclo_punto(params: dict, estado) -> None:
    _usar(estado, params, "de")
    _ciclo_variable(params, estado)


def _guia(color) -> VGroup:
    """Línea punteada de estructura fija (``TRAZOS_GUIA`` trazos) que :func:`_tender_guia` reubica cada fotograma.

    (``become`` con un ``DashedLine`` nuevo en cada fotograma anida submobjects sin fin: por eso trazos fijos.)
    """
    return VGroup(*[Line(LEFT * 0.5, RIGHT * 0.5, color=color, stroke_width=GROSOR_LINEA_FINA)
                    for _ in range(TRAZOS_GUIA)])


def _tender_guia(guia: VGroup, inicio: np.ndarray, fin: np.ndarray) -> None:
    delta = np.asarray(fin, dtype=float) - np.asarray(inicio, dtype=float)
    visible = float(np.linalg.norm(delta)) >= LARGO_MINIMO_GUIA
    n = len(guia.submobjects)
    for k, trazo in enumerate(guia.submobjects):
        if visible:
            trazo.put_start_and_end_on(inicio + delta * k / n, inicio + delta * (k + PROPORCION_TRAZO) / n)
        trazo.set_stroke(opacity=1.0 if visible else 0.0)


@objeto(
    "punto_en_curva",
    "Punto sobre una curva en x = valor de una variable: al moverla (mover_variable) el punto recorre la curva y lo "
    "siguen la tangente y las guías. Partes (si hay guías o etiqueta): punto, guias, etiqueta.",
    params=[
        Param("de", "objeto", requerido=True, descripcion="Id de la curva que recorre."),
        Param("x", "numero", defecto=0.0, descripcion="Valor inicial de x (si la variable ya existe, manda la variable)."),
        Param("variable", "texto",
              descripcion="Nombre de una variable compartida (efecto persistente; se congela con detener). "
                          "Sin nombre, se mueve con mover_variable objeto: <id del punto>."),
        Param("color", "color", defecto="amarillo", descripcion="Color del punto."),
        Param("guias", "booleano", defecto=False, descripcion="Líneas punteadas del punto a los ejes."),
        Param("etiqueta", "texto", descripcion="Rótulo LaTeX que acompaña al punto, p. ej. \"P\"."),
    ],
    ejemplo={"en": "inicio", "hacer": "mostrar", "id": "p", "tipo": "punto_en_curva", "de": "parabola", "x": -1.5},
    duracion=0.6,
    ciclo=_ciclo_punto,
)
def crear_punto_en_curva(ctx: ContextoGuion, de, x, color, guias, variable=None, etiqueta=None) -> Mobject:
    curva_mob, f = _exigir(ctx, de, ATRIBUTO_FUNCION, "una curva: usa el id de un 'curva'")
    ejes = getattr(curva_mob, ATRIBUTO_EJES)
    hex_color = ctx.color(color)
    tracker = _tracker_de_variable(ctx, variable, float(x))

    def posicion() -> np.ndarray | None:
        valor = tracker.get_value()
        try:
            return ejes.c2p(valor, f(valor))
        except (ValueError, ZeroDivisionError, OverflowError):
            return None  # fuera del dominio: el punto se queda donde estaba

    punto = Dot(radius=RADIO_PUNTO, color=hex_color)

    def seguir_punto(m: Mobject) -> None:
        p = posicion()
        if p is not None:
            m.move_to(p)

    _seguir(ctx, variable, punto, seguir_punto)
    extras: dict[str, Mobject] = {}
    if guias:
        vertical, horizontal = _guia(hex_color), _guia(hex_color)

        def seguir_vertical(m: Mobject) -> None:
            p = posicion()
            if p is not None:
                _tender_guia(m, ejes.x_axis.number_to_point(tracker.get_value()), p)

        def seguir_horizontal(m: Mobject) -> None:
            p = posicion()
            if p is not None:
                _tender_guia(m, ejes.y_axis.number_to_point(ejes.p2c(p)[1]), p)

        _seguir(ctx, variable, vertical, seguir_vertical)
        _seguir(ctx, variable, horizontal, seguir_horizontal)
        extras["guias"] = VGroup(vertical, horizontal)
    if etiqueta:
        rotulo = MathTex(str(etiqueta), font_size=FUENTE_ETIQUETA, color=hex_color)
        _seguir(ctx, variable, rotulo, lambda m: m.next_to(punto, UR, buff=0.08))
        extras["etiqueta"] = rotulo
    if extras:
        miembros = ([extras["guias"]] if "guias" in extras else []) + [punto] + (
            [extras["etiqueta"]] if "etiqueta" in extras else [])
        resultado = _con_partes(VGroup(*miembros), {"punto": punto, **extras})
    else:
        resultado = punto
    setattr(resultado, ATRIBUTO_EJES, ejes)
    setattr(resultado, ATRIBUTO_FUNCION, f)
    setattr(resultado, ATRIBUTO_TRACKER, tracker)
    setattr(resultado, ATRIBUTO_VARIABLE, variable)
    return resultado


# --- tangente ----------------------------------------------------------------------------------------------------


@objeto(
    "tangente",
    "Recta tangente a la curva en el punto (sigue al punto cuando su variable se mueve). Pendiente exacta (sympy).",
    params=[
        Param("de", "objeto", requerido=True, descripcion="Id del punto_en_curva donde es tangente."),
        Param("longitud", "numero", defecto=LONGITUD_TANGENTE, descripcion="Largo del segmento en unidades de escena."),
        Param("color", "color", defecto="amarillo", descripcion="Color de la recta."),
    ],
    ejemplo={"en": "inicio", "hacer": "mostrar", "id": "tg", "tipo": "tangente", "de": "p"},
    duracion=TIEMPO_CREAR,
)
def crear_tangente(ctx: ContextoGuion, de, longitud, color) -> Mobject:
    punto, tracker = _exigir(ctx, de, ATRIBUTO_TRACKER, "un punto_en_curva")
    f = getattr(punto, ATRIBUTO_FUNCION, None)
    ejes = getattr(punto, ATRIBUTO_EJES, None)
    if f is None or ejes is None:
        raise _error("E3", f"'{de}' no es un punto_en_curva (la tangente necesita una curva)", ctx.ubicacion)
    mitad = float(longitud) / 2.0
    linea = Line(LEFT * mitad, RIGHT * mitad, color=ctx.color(color), stroke_width=GROSOR_LINEA_MEDIA)

    def seguir(m: Mobject) -> None:
        x0 = tracker.get_value()
        try:
            y0, pendiente = f(x0), f.derivada(x0)
        except (ValueError, ZeroDivisionError, OverflowError):
            return
        centro = ejes.c2p(x0, y0)
        direccion = ejes.c2p(x0 + 1.0, y0 + pendiente) - centro
        norma = float(np.linalg.norm(direccion))
        if norma < 1e-9:
            return
        direccion = direccion / norma * mitad
        m.put_start_and_end_on(centro - direccion, centro + direccion)

    _seguir(ctx, getattr(punto, ATRIBUTO_VARIABLE, None), linea, seguir)
    setattr(linea, ATRIBUTO_TRACKER, tracker)
    return linea


# --- vector y descomponer_vector ------------------------------------------------------------------------------------


def _ciclo_vector(params: dict, estado) -> None:
    _usar(estado, params, "de")
    if not _lista_numeros(params.get("componentes"), (2,)):
        estado.error("E3", "'componentes' debe ser [vx, vy] (en unidades de los ejes)")
    if not _lista_numeros(params.get("origen"), (2,)):
        estado.error("E3", "'origen' debe ser [x, y] (en unidades de los ejes)")


@objeto(
    "vector",
    "Flecha de un vector sobre unos ejes (coordenadas de los ejes), con rótulo LaTeX opcional junto a la punta. "
    "Partes: flecha, etiqueta.",
    params=[
        Param("de", "objeto", requerido=True, descripcion="Id de los ejes."),
        Param("componentes", "lista", requerido=True, descripcion="[vx, vy] en unidades de los ejes."),
        Param("origen", "lista", defecto=[0, 0], descripcion="Punto de partida [x, y] en unidades de los ejes."),
        Param("color", "color", defecto="turquesa", descripcion="Color de la flecha."),
        Param("etiqueta", "texto", descripcion="Rótulo LaTeX, p. ej. \"\\\\vec{v}\"."),
    ],
    ejemplo={"en": "inicio", "hacer": "mostrar", "id": "v", "tipo": "vector", "de": "plano", "componentes": [2, 3],
             "etiqueta": "\\vec{v}"},
    duracion=TIEMPO_CREAR,
    ciclo=_ciclo_vector,
)
def crear_vector(ctx: ContextoGuion, de, componentes, origen, color, etiqueta=None) -> Mobject:
    ejes = _ejes_de(ctx, de)
    x0, y0 = float(origen[0]), float(origen[1])
    vx, vy = float(componentes[0]), float(componentes[1])
    grupo = flecha_vector(ejes.c2p(x0, y0), ejes.c2p(x0 + vx, y0 + vy), color=ctx.color(color),
                          etiqueta=str(etiqueta) if etiqueta else None)
    partes = {"flecha": grupo[0]}
    if len(grupo.submobjects) > 1:
        partes["etiqueta"] = grupo[1]
        _ajustar_dentro(grupo[1], ZONA_CONTENIDO)
    _con_partes(grupo, partes)
    setattr(grupo, ATRIBUTO_EJES, ejes)
    setattr(grupo, ATRIBUTO_VECTOR, ((x0, y0), (vx, vy)))
    return grupo


def _ciclo_descomponer(params: dict, estado) -> None:
    _usar(estado, params, "objeto")
    estado.crear(params.get("id"), "descomponer_vector")


@accion(
    "descomponer_vector",
    "Separa un vector en sus componentes horizontal y vertical (salen de la flecha) con guías punteadas; crea el "
    "objeto 'id' con partes x, y, guias.",
    params=[
        Param("objeto", "objeto", requerido=True, descripcion="Id del vector a descomponer."),
        Param("id", "texto", requerido=True, descripcion="Id nuevo para las componentes (para quitarlas o resaltarlas)."),
        Param("color_x", "color", defecto="rojo", descripcion="Color de la componente horizontal."),
        Param("color_y", "color", defecto="verde", descripcion="Color de la componente vertical."),
    ],
    ejemplo={"en": "inicio", "hacer": "descomponer_vector", "objeto": "v", "id": "comps"},
    duracion=TIEMPO_TRANSFORMAR,
    modificadores=("rate",),
    ciclo=_ciclo_descomponer,
)
def descomponer_vector(ctx: ContextoGuion, objeto, id, color_x, color_y):
    vec, ((x0, y0), (vx, vy)) = _exigir(ctx, objeto, ATRIBUTO_VECTOR, "un vector")
    ejes = getattr(vec, ATRIBUTO_EJES)
    inicio = ejes.c2p(x0, y0)
    delta = ejes.c2p(x0 + vx, y0 + vy) - inicio
    piezas = componentes_de_vector(inicio, delta, color_x=ctx.color(color_x), color_y=ctx.color(color_y))
    comp_x, comp_y, guia_v, guia_h = piezas.submobjects
    guias = VGroup(guia_v, guia_h)
    grupo = _con_partes(VGroup(comp_x, comp_y, guias), {"x": comp_x, "y": comp_y, "guias": guias})
    ctx.registrar(id, grupo)
    ctx.marcar_foco(id)
    ctx.despues(partial(ctx.consolidar, grupo))
    flecha = ctx.parte(vec, "flecha")
    return AnimationGroup(TransformFromCopy(flecha, comp_x), TransformFromCopy(flecha, comp_y), Create(guias),
                          lag_ratio=0.25)


# --- trayectoria ---------------------------------------------------------------------------------------------------


def _ciclo_trayectoria(params: dict, estado) -> None:
    _usar(estado, params, "de")
    reglas = [
        ("rapidez", lambda v: v > 0, "la rapidez debe ser positiva (m/s)"),
        ("angulo", lambda v: 0 < v < 180, "el ángulo va entre 0 y 180 grados (exclusivos)"),
        ("g", lambda v: v > 0, "la gravedad debe ser positiva"),
        ("rozamiento", lambda v: v >= 0, "el rozamiento debe ser ≥ 0"),
        ("progreso", lambda v: 0 <= v <= 1, "progreso va de 0 (sin lanzar) a 1 (vuelo completo)"),
    ]
    for clave, regla, mensaje in reglas:
        valor = params.get(clave)
        if _es_numero(valor) and not regla(valor):
            estado.error("E3", f"{clave} = {valor}: {mensaje}")


@objeto(
    "trayectoria",
    "Tiro parabólico (motor_fisica) sobre unos ejes en metros: camino + proyectil. 'progreso' es la fracción del "
    "vuelo dibujada; con progreso: 0 y luego mover_variable objeto: <id>, a: 1 el proyectil vuela trazando el camino. "
    "Partes: camino, proyectil.",
    params=[
        Param("de", "objeto", requerido=True, descripcion="Id de los ejes (x e y en metros)."),
        Param("rapidez", "numero", requerido=True, descripcion="Rapidez de lanzamiento (m/s)."),
        Param("angulo", "numero", requerido=True, descripcion="Ángulo de lanzamiento (grados)."),
        Param("g", "numero", defecto=motor_fisica.G_TIERRA, descripcion="Gravedad (m/s²)."),
        Param("rozamiento", "numero", defecto=0.0, descripcion="Coeficiente de rozamiento lineal k (1/s); 0 = sin aire."),
        Param("progreso", "numero", defecto=1.0, descripcion="Fracción del vuelo ya recorrida (0-1)."),
        Param("color", "color", defecto="turquesa", descripcion="Color del camino."),
        Param("proyectil", "booleano", defecto=True, descripcion="Dibuja la bolita en la punta del camino."),
    ],
    ejemplo={"en": "inicio", "hacer": "mostrar", "id": "tiro", "tipo": "trayectoria", "de": "plano", "rapidez": 8,
             "angulo": 60, "progreso": 0},
    duracion=TIEMPO_CREAR,
    ciclo=_ciclo_trayectoria,
)
def crear_trayectoria(ctx: ContextoGuion, de, rapidez, angulo, g, rozamiento, progreso, color, proyectil) -> Mobject:
    ejes = _ejes_de(ctx, de)
    v, grados, k, gravedad = float(rapidez), float(angulo), float(rozamiento), float(g)
    if k > 0:
        t_vuelo = motor_fisica.tiempo_vuelo_con_arrastre(v, grados, k, gravedad)

        def pos(t: float) -> tuple[float, float]:
            return motor_fisica.posicion_con_arrastre(v, grados, t, k, gravedad)
    else:
        t_vuelo = motor_fisica.tiempo_vuelo(v, grados, gravedad)

        def pos(t: float) -> tuple[float, float]:
            return motor_fisica.posicion(v, grados, t, gravedad)

    completa = curva_parametrica(ejes, lambda t: pos(t)[0], lambda t: pos(t)[1], t_vuelo, color=ctx.color(color))
    completa.set_stroke(opacity=0)  # referencia invisible (viaja con el grupo si se mueve)
    camino = completa.copy().set_stroke(ctx.color(color), width=GROSOR_LINEA_MEDIA, opacity=1)
    tracker = ValueTracker(float(progreso))

    def fraccion() -> float:
        return float(np.clip(tracker.get_value(), 0.0, 1.0))

    camino.add_updater(lambda m: m.pointwise_become_partial(completa, 0, max(fraccion(), PROGRESO_MINIMO)))
    camino.update()
    miembros: list[Mobject] = [completa, camino]
    partes: dict[str, Mobject] = {"camino": camino}
    if proyectil:
        bola = Dot(radius=RADIO_PROYECTIL, color=BLANCO)
        # El camino se actualiza antes (va antes en el grupo): la bola va en su punta.
        bola.add_updater(lambda m: m.move_to(camino.get_end()))
        bola.update()
        miembros.append(bola)
        partes["proyectil"] = bola
    grupo = _con_partes(VGroup(*miembros), partes)
    setattr(grupo, ATRIBUTO_EJES, ejes)
    setattr(grupo, ATRIBUTO_TRACKER, tracker)
    return grupo


class MoverValor(AnimacionDiferida):
    """Lleva un ``ValueTracker`` a ``hasta`` desde el valor que tenga al EMPEZAR (encadenable; final único)."""

    def __init__(self, tracker: ValueTracker, hasta: float, **kwargs: Any) -> None:
        self.hasta = float(hasta)
        self.inicio = 0.0
        super().__init__(tracker, **kwargs)

    def leer_inicio(self) -> None:
        self.inicio = float(self.mobject.get_value())

    def aplicar(self, alfa: float) -> None:
        self.mobject.set_value(self.inicio + (self.hasta - self.inicio) * alfa)


# --- mover_variable ------------------------------------------------------------------------------------------------


def _ciclo_mover_variable(params: dict, estado) -> None:
    objeto_ref, variable = params.get("objeto"), params.get("variable")
    if (objeto_ref is None) == (variable is None):
        estado.error("E3", "indica 'objeto' (un punto_en_curva, tangente o trayectoria) o 'variable' (su nombre), "
                           "uno de los dos")
        return
    if objeto_ref is not None:
        _usar(estado, params, "objeto")
        return
    efecto = estado.efectos.get(variable)
    if efecto is None:
        estado.error("E4", f"la variable '{variable}' no existe o ya se detuvo (se crea con "
                           f"{{tipo: punto_en_curva, variable: {variable}, ...}})")
    elif efecto[0] != TIPO_EFECTO_VARIABLE:
        estado.error("E4", f"'{variable}' es un efecto de tipo {efecto[0]}, no una variable")


@accion(
    "mover_variable",
    "Anima el valor que siguen los objetos móviles: el punto recorre la curva (y su tangente lo acompaña) o el "
    "proyectil vuela. Con 'objeto' mueve el valor propio de ese objeto; con 'variable', la variable compartida.",
    params=[
        Param("objeto", "objeto", descripcion="Id de un punto_en_curva, tangente o trayectoria."),
        Param("variable", "texto", descripcion="Nombre de una variable compartida (alternativa a 'objeto')."),
        Param("a", "numero", requerido=True,
              descripcion="Valor final (x del punto; en una trayectoria, fracción del vuelo 0-1)."),
    ],
    ejemplo={"en": "inicio", "hacer": "mover_variable", "objeto": "p", "a": 1.5, "dur": 2.0},
    duracion=2.0,
    modificadores=("rate",),
    ciclo=_ciclo_mover_variable,
)
def mover_variable(ctx: ContextoGuion, a, objeto=None, variable=None):
    if objeto is not None:
        _, tracker = _exigir(ctx, objeto, ATRIBUTO_TRACKER, "un objeto móvil (punto_en_curva, tangente o trayectoria)")
        ctx.marcar_foco(str(objeto).split(".", 1)[0])
    else:
        efecto = ctx.efectos.get(variable)
        if efecto is None or efecto.tipo != TIPO_EFECTO_VARIABLE:
            raise _error("E4", f"no hay una variable activa '{variable}'", ctx.ubicacion)
        tracker = efecto.datos["tracker"]
    if ctx.escena is not None:
        # manim añade el tracker (sus "puntos" guardan el valor) a la escena al animarlo: fuera tras el play.
        ctx.despues(partial(ctx.escena.remove, tracker))
    return MoverValor(tracker, float(a))


__all__ = [
    "ErrorExpresion",
    "FuncionSegura",
    "NOMBRES_PERMITIDOS",
    "parsear_funcion",
    "crear_ejes",
    "crear_curva",
    "crear_punto_en_curva",
    "crear_tangente",
    "crear_vector",
    "crear_trayectoria",
    "descomponer_vector",
    "mover_variable",
    "MoverValor",
]
