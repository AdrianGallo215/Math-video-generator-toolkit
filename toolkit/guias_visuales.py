"""Guias visuales de depuracion: franjas prohibidas y contornos de zonas.

Calculadas a partir de las zonas de ``toolkit.layout`` (``MARCO``,
``ZONA_SEGURA``, ``ZONA_TITULO``, ``ZONA_PRINCIPAL``, ``ZONA_SUBTITULOS``)
en vez de porcentajes fijos del cuadro.
"""

from manim import DashedVMobject, Rectangle, VGroup

from .estilos import COLORES_MARCA
from .layout import MARCO, ZONA_PRINCIPAL, ZONA_SEGURA, ZONA_SUBTITULOS, ZONA_TITULO


def _rectangulo_rango(x_min, x_max, y_min, y_max, color, opacidad) -> Rectangle:
    """Rectangulo de guia definido por un rango ``[x_min,x_max] x [y_min,y_max]``."""
    rect = Rectangle(
        width=x_max - x_min,
        height=y_max - y_min,
        color=color,
        fill_opacity=opacidad,
        stroke_width=0,
    )
    rect.move_to([(x_min + x_max) / 2.0, (y_min + y_max) / 2.0, 0.0])
    return rect


def generar_guia_superior() -> Rectangle:
    """Bloquea la franja superior fuera de la zona segura (camara, titulo de Shorts)."""
    return _rectangulo_rango(
        MARCO.x_min, MARCO.x_max, ZONA_SEGURA.y_max, MARCO.y_max,
        COLORES_MARCA["GUIA_ERROR"], 0.3,
    )


def generar_guia_inferior() -> Rectangle:
    """Bloquea la franja inferior fuera de la zona segura (descripcion, barra de audio)."""
    return _rectangulo_rango(
        MARCO.x_min, MARCO.x_max, MARCO.y_min, ZONA_SEGURA.y_min,
        COLORES_MARCA["GUIA_ERROR"], 0.3,
    )


def generar_guia_lateral_izquierda() -> Rectangle:
    """Bloquea la franja izquierda fuera de la zona segura."""
    return _rectangulo_rango(
        MARCO.x_min, ZONA_SEGURA.x_min, MARCO.y_min, MARCO.y_max,
        COLORES_MARCA["GUIA_ERROR"], 0.2,
    )


def generar_guia_lateral_derecha() -> Rectangle:
    """Bloquea la franja derecha fuera de la zona segura (botones de Like, Dislike, Share)."""
    return _rectangulo_rango(
        ZONA_SEGURA.x_max, MARCO.x_max, MARCO.y_min, MARCO.y_max,
        COLORES_MARCA["GUIA_ERROR"], 0.35,
    )


def generar_contornos_zonas() -> VGroup:
    """Borde punteado de las zonas TITULO/PRINCIPAL/SUBTITULOS."""
    contornos = VGroup()
    for zona in (ZONA_TITULO, ZONA_PRINCIPAL, ZONA_SUBTITULOS):
        rect = Rectangle(
            width=zona.ancho,
            height=zona.alto,
            color=COLORES_MARCA["PRIMARIO"],
            fill_opacity=0.0,
            stroke_width=2,
        )
        rect.move_to(zona.centro)
        contornos.add(DashedVMobject(rect))
    return contornos


def obtener_todas_las_guias() -> VGroup:
    """Devuelve un grupo con las franjas prohibidas y los contornos de zonas."""
    guias_prohibidas = VGroup(
        generar_guia_superior(),
        generar_guia_inferior(),
        generar_guia_lateral_izquierda(),
        generar_guia_lateral_derecha(),
    )
    return VGroup(guias_prohibidas, generar_contornos_zonas())
