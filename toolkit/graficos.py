"""Graficos: planos y funciones estilo 3B1B.

Planos y ejes cartesianos con la estetica de 3Blue1Brown (fondo con lineas
azuladas tenues, ejes blancos, numeros legibles en movil) y helpers para
curvas, puntos/tangentes animados, areas, vectores y trayectorias.

Separacion de responsabilidades: este modulo construye mobjects (manim);
no hace calculo simbolico (eso vive en ``toolkit/motor_*.py``).
"""

from __future__ import annotations

import logging
from typing import Callable, Iterable, Sequence

import numpy as np
from manim import (
    RIGHT,
    UP,
    Arrow,
    Axes,
    DashedLine,
    DecimalNumber,
    Dot,
    Line,
    MathTex,
    NumberPlane,
    ParametricFunction,
    Polygon,
    ValueTracker,
    VGroup,
    always_redraw,
)

from toolkit.estilos import (
    AMARILLO,
    AZUL,
    BLANCO,
    FUENTE_ETIQUETA,
    FUENTE_MINIMA,
    GROSOR_LINEA_FINA,
    GROSOR_LINEA_MEDIA,
    ROJO,
    TURQUESA,
    VERDE,
)

Rango = Sequence[float]

logger = logging.getLogger(__name__)

MUESTRAS_DOMINIO_VISIBLE = 400


def PlanoShort(
    x_rango: Rango = (-4, 4, 1),
    y_rango: Rango = (-4, 4, 1),
    ancho: float = 6.0,
    alto: float = 6.0,
    con_numeros: bool = True,
) -> NumberPlane:
    """Plano cartesiano estilo 3B1B: lineas de fondo azuladas tenues y ejes
    blancos gruesos, con numeros legibles en movil si ``con_numeros``."""
    plano = NumberPlane(
        x_range=x_rango,
        y_range=y_rango,
        x_length=ancho,
        y_length=alto,
        background_line_style={
            "stroke_color": AZUL,
            "stroke_width": 1.5,
            "stroke_opacity": 0.35,
        },
        faded_line_ratio=1,
        axis_config={
            "stroke_color": BLANCO,
            "stroke_width": 3,
            "include_tip": False,
            "font_size": FUENTE_MINIMA,
        },
    )
    if con_numeros:
        plano.add_coordinates()
    return plano


def EjesShort(
    x_rango: Rango = (-4, 4, 1),
    y_rango: Rango = (-4, 4, 1),
    ancho: float = 6.0,
    alto: float = 5.0,
    etiqueta_x: str = "x",
    etiqueta_y: str = "y",
    con_puntas: bool = True,
) -> Axes:
    """Ejes cartesianos (sin cuadricula) estilo 3B1B, con etiquetas de eje."""
    ejes = Axes(
        x_range=x_rango,
        y_range=y_rango,
        x_length=ancho,
        y_length=alto,
        tips=con_puntas,
        axis_config={
            "stroke_color": BLANCO,
            "stroke_width": 3,
            "font_size": FUENTE_MINIMA,
        },
    )
    etiquetas = ejes.get_axis_labels(x_label=etiqueta_x, y_label=etiqueta_y)
    ejes.etiquetas = etiquetas  # type: ignore[attr-defined]
    ejes.add(etiquetas)
    return ejes


def _tramos_visibles(
    f: Callable[[float], float],
    x_min: float,
    x_max: float,
    y_min: float,
    y_max: float,
    muestras: int = MUESTRAS_DOMINIO_VISIBLE,
) -> list[tuple[float, float]]:
    """Sub-intervalos de ``[x_min, x_max]`` donde ``f(x)`` cae dentro de
    ``[y_min, y_max]`` (muestreo denso; cada tramo tiene al menos 2 muestras)."""
    xs = np.linspace(x_min, x_max, muestras)
    tolerancia = 1e-6
    tramos: list[tuple[float, float]] = []
    inicio: float | None = None
    anterior: float | None = None
    for x in xs:
        try:
            y = f(x)
        except (ValueError, ZeroDivisionError, OverflowError):
            y = None
        visible = (
            y is not None
            and np.isfinite(y)
            and (y_min - tolerancia) <= y <= (y_max + tolerancia)
        )
        if visible and inicio is None:
            inicio = x
        elif not visible and inicio is not None:
            if anterior is not None and anterior > inicio:
                tramos.append((inicio, anterior))
            inicio = None
        anterior = x
    if inicio is not None and anterior is not None and anterior > inicio:
        tramos.append((inicio, anterior))
    return tramos


def curva(
    ejes: Axes,
    f: Callable[[float], float],
    rango_x: Rango | None = None,
    color=AZUL,
    grosor: float = GROSOR_LINEA_MEDIA,
    discontinuidades: Iterable[float] | None = None,
) -> ParametricFunction | VGroup:
    """Grafica ``f`` sobre ``ejes``.

    Si ``rango_x`` es ``None`` (por defecto), el dominio se restringe
    automaticamente a la region visible del rango de los ejes: se muestrea
    densamente ``f`` sobre ``ejes.x_range`` y se conservan solo los tramos
    donde ``ejes.y_range[0] <= f(x) <= ejes.y_range[1]`` (evita que la curva
    se dibuje fuera del rectangulo de los ejes, p. ej. una parabola que crece
    por encima de ``y_max``). Si ``rango_x`` se indica explicitamente, se usa
    tal cual (sin recortar) para no sorprender a quien pide un dominio propio.

    Devuelve un ``ParametricFunction`` si el dominio visible es un unico tramo
    continuo; si hay varios tramos (discontinuidades, asintotas, ramas
    separadas), devuelve un ``VGroup`` con un ``ParametricFunction`` por tramo.
    """
    if rango_x is not None:
        return ejes.plot(
            f,
            x_range=rango_x,
            color=color,
            stroke_width=grosor,
            discontinuities=discontinuidades,
        )

    x_min, x_max = float(ejes.x_range[0]), float(ejes.x_range[1])
    y_min, y_max = float(ejes.y_range[0]), float(ejes.y_range[1])
    tramos = _tramos_visibles(f, x_min, x_max, y_min, y_max)

    if not tramos:
        logger.warning(
            "curva: f no tiene valores dentro del rango visible de los ejes; "
            "se devuelve un VGroup vacio"
        )
        return VGroup()

    graficas = [
        ejes.plot(
            f,
            x_range=(a, b),
            color=color,
            stroke_width=grosor,
            discontinuities=discontinuidades,
        )
        for a, b in tramos
    ]
    if len(graficas) == 1:
        return graficas[0]
    return VGroup(*graficas)


def punto_sobre_curva(
    ejes: Axes,
    f: Callable[[float], float],
    tracker: ValueTracker,
    color=AMARILLO,
    radio: float = 0.09,
) -> Dot:
    """Punto que sigue a ``f`` en ``x = tracker.get_value()`` (always_redraw)."""
    return always_redraw(
        lambda: Dot(
            ejes.c2p(tracker.get_value(), f(tracker.get_value())),
            color=color,
            radius=radio,
        )
    )


def recta_tangente(
    ejes: Axes,
    f: Callable[[float], float],
    tracker: ValueTracker,
    longitud: float = 3.0,
    color=AMARILLO,
    dx: float = 1e-4,
) -> Line:
    """Recta tangente a ``f`` en ``x = tracker.get_value()`` (derivada numerica
    central), redibujada en cada frame (always_redraw)."""

    def _construir() -> Line:
        x0 = tracker.get_value()
        y0 = f(x0)
        pendiente = (f(x0 + dx) - f(x0 - dx)) / (2 * dx)
        direccion = np.array([1.0, pendiente, 0.0])
        direccion = direccion / np.linalg.norm(direccion)
        centro = ejes.c2p(x0, y0)
        escala_x = ejes.c2p(1, 0)[0] - ejes.c2p(0, 0)[0]
        escala_y = ejes.c2p(0, 1)[1] - ejes.c2p(0, 0)[1]
        direccion_pantalla = np.array(
            [direccion[0] * escala_x, direccion[1] * escala_y, 0.0]
        )
        direccion_pantalla = direccion_pantalla / np.linalg.norm(direccion_pantalla)
        mitad = direccion_pantalla * (longitud / 2)
        return Line(centro - mitad, centro + mitad, color=color, stroke_width=GROSOR_LINEA_MEDIA)

    return always_redraw(_construir)


def area_bajo_curva(
    ejes: Axes,
    f: Callable[[float], float],
    a: float,
    b: float,
    color=AZUL,
    opacidad: float = 0.4,
) -> Polygon:
    """Region bajo ``f`` entre ``a`` y ``b`` (usa ``Axes.get_area``)."""
    grafica = ejes.plot(f, x_range=(a, b))
    return ejes.get_area(grafica, x_range=(a, b), color=color, opacity=opacidad)


def etiqueta_valor(
    tracker: ValueTracker,
    prefijo: str = "",
    decimales: int = 2,
    tamano: float = FUENTE_ETIQUETA,
) -> VGroup:
    """Texto ``prefijo`` + numero que seguimiento en vivo el valor de ``tracker``."""
    texto = MathTex(prefijo, font_size=tamano, color=BLANCO) if prefijo else None
    numero = DecimalNumber(
        tracker.get_value(),
        num_decimal_places=decimales,
        font_size=tamano,
        color=BLANCO,
    )
    numero.add_updater(lambda m: m.set_value(tracker.get_value()))
    if texto is not None:
        grupo = VGroup(texto, numero).arrange(RIGHT, buff=0.1)
        numero.add_updater(lambda m: m.next_to(texto, RIGHT, buff=0.1))
        return grupo
    return VGroup(numero)


def trayectoria(
    ejes: Axes,
    x_de_t: Callable[[float], float],
    y_de_t: Callable[[float], float],
    t_max: float,
    color=TURQUESA,
) -> ParametricFunction:
    """Curva parametrica ``(x(t), y(t))`` para ``t`` en ``[0, t_max]`` (fisica)."""
    return ParametricFunction(
        lambda t: ejes.c2p(x_de_t(t), y_de_t(t)),
        t_range=(0, t_max),
        color=color,
        stroke_width=GROSOR_LINEA_MEDIA,
    )


def vector(
    inicio,
    fin,
    color=TURQUESA,
    etiqueta: str | None = None,
    grosor: float = GROSOR_LINEA_MEDIA,
) -> VGroup:
    """Flecha (Arrow) de ``inicio`` a ``fin`` con punta proporcional, mas
    etiqueta LaTeX opcional junto a la punta."""
    inicio = np.array(inicio, dtype=float)
    fin = np.array(fin, dtype=float)
    flecha = Arrow(
        inicio,
        fin,
        color=color,
        stroke_width=grosor,
        buff=0,
        max_tip_length_to_length_ratio=0.25,
        max_stroke_width_to_length_ratio=10,
    )
    grupo = VGroup(flecha)
    if etiqueta:
        texto = MathTex(etiqueta, color=color, font_size=FUENTE_ETIQUETA)
        texto.next_to(flecha.get_end(), UP, buff=0.1)
        grupo.add(texto)
    return grupo


def descomponer_vector(
    inicio,
    v,
    color_x=ROJO,
    color_y=VERDE,
) -> VGroup:
    """Componentes horizontal y vertical de ``v`` (desde ``inicio``), con lineas
    guia punteadas que completan el rectangulo cuya diagonal es ``v``."""
    inicio = np.array(inicio, dtype=float)
    v = np.array(v, dtype=float)
    fin = inicio + v
    fin_x = inicio + np.array([v[0], 0.0, 0.0])
    fin_y = inicio + np.array([0.0, v[1], 0.0])

    componente_x = Arrow(
        inicio,
        fin_x,
        color=color_x,
        buff=0,
        stroke_width=GROSOR_LINEA_MEDIA,
        max_tip_length_to_length_ratio=0.25,
    )
    componente_y = Arrow(
        inicio,
        fin_y,
        color=color_y,
        buff=0,
        stroke_width=GROSOR_LINEA_MEDIA,
        max_tip_length_to_length_ratio=0.25,
    )
    guia_vertical = DashedLine(
        fin_x, fin, color=color_y, stroke_width=GROSOR_LINEA_FINA, dashed_ratio=0.5
    )
    guia_horizontal = DashedLine(
        fin_y, fin, color=color_x, stroke_width=GROSOR_LINEA_FINA, dashed_ratio=0.5
    )

    return VGroup(componente_x, componente_y, guia_vertical, guia_horizontal)
