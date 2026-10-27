"""Zonas seguras del formato 9:16 como objetos de layout.

Sustituye las coordenadas magicas en escenas por zonas nombradas
(``Zona``) y funciones de posicionamiento relativo (``encajar``,
``colocar_en``, ``apilar``, ``dividir_vertical``, ``solapan``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np
from manim import DOWN, ORIGIN, Mobject, VGroup


@dataclass(frozen=True)
class Zona:
    """Rectangulo del sistema de coordenadas de manim (unidades de escena)."""

    nombre: str
    x_min: float
    x_max: float
    y_min: float
    y_max: float

    @property
    def ancho(self) -> float:
        return self.x_max - self.x_min

    @property
    def alto(self) -> float:
        return self.y_max - self.y_min

    @property
    def centro(self) -> np.ndarray:
        return np.array(
            [(self.x_min + self.x_max) / 2.0, (self.y_min + self.y_max) / 2.0, 0.0]
        )

    def contiene_punto(self, p) -> bool:
        """True si el punto ``p`` (2D o 3D) cae dentro de la zona."""
        x, y = p[0], p[1]
        return bool(self.x_min <= x <= self.x_max and self.y_min <= y <= self.y_max)

    def contiene(self, mob: Mobject, tolerancia: float = 0.01) -> bool:
        """True si el bounding box completo de ``mob`` cae dentro de la zona."""
        izquierda = mob.get_left()[0]
        derecha = mob.get_right()[0]
        abajo = mob.get_bottom()[1]
        arriba = mob.get_top()[1]
        return bool(
            izquierda >= self.x_min - tolerancia
            and derecha <= self.x_max + tolerancia
            and abajo >= self.y_min - tolerancia
            and arriba <= self.y_max + tolerancia
        )

    def borde(self, direccion) -> np.ndarray:
        """Punto medio del borde de la zona en la direccion dada (UP/DOWN/LEFT/RIGHT)."""
        centro = self.centro
        dx, dy = float(direccion[0]), float(direccion[1])
        x = self.x_max if dx > 0 else (self.x_min if dx < 0 else centro[0])
        y = self.y_max if dy > 0 else (self.y_min if dy < 0 else centro[1])
        return np.array([x, y, 0.0])


MARCO = Zona("marco", -4.5, 4.5, -8.0, 8.0)
ZONA_SEGURA = Zona("segura", -3.15, 3.15, -4.0, 5.6)
ZONA_TITULO = Zona("titulo", -3.15, 3.15, 4.2, 5.6)
ZONA_PRINCIPAL = Zona("principal", -3.15, 3.15, -2.2, 4.0)
ZONA_SUBTITULOS = Zona("subtitulos", -3.15, 3.15, -3.9, -2.4)

MARGEN_ENTRE_BLOQUES = 0.25


def _punto_zona(zona: Zona, direccion, margen: float) -> np.ndarray:
    """Punto ancla dentro de ``zona`` en ``direccion``, retraido por ``margen``."""
    centro = zona.centro
    dx, dy = float(direccion[0]), float(direccion[1])
    x = zona.x_max - margen if dx > 0 else (zona.x_min + margen if dx < 0 else centro[0])
    y = zona.y_max - margen if dy > 0 else (zona.y_min + margen if dy < 0 else centro[1])
    return np.array([x, y, 0.0])


def colocar_en(mob: Mobject, zona: Zona, direccion=ORIGIN, margen: float = 0.15) -> Mobject:
    """Posiciona ``mob`` dentro de ``zona`` sin escalarlo.

    ``direccion`` indica que borde de ``mob`` se pega al borde interior
    correspondiente de ``zona`` (retraido por ``margen``). ``ORIGIN``
    (por defecto) centra ``mob`` en la zona.
    """
    punto_zona = _punto_zona(zona, direccion, margen)
    punto_mob = mob.get_critical_point(direccion)
    mob.shift(punto_zona - punto_mob)
    return mob


def encajar(
    mob: Mobject,
    zona: Zona = ZONA_PRINCIPAL,
    margen: float = 0.15,
    escalar_arriba: bool = False,
    alineacion=ORIGIN,
) -> Mobject:
    """Escala ``mob`` (solo hacia abajo salvo ``escalar_arriba=True``) para que
    quepa dentro de ``zona`` (menos ``margen`` por lado) y lo posiciona.
    """
    ancho_disponible = zona.ancho - 2 * margen
    alto_disponible = zona.alto - 2 * margen
    if ancho_disponible <= 0 or alto_disponible <= 0:
        raise ValueError(f"Zona '{zona.nombre}' demasiado pequeña para margen={margen}")

    factor = min(ancho_disponible / mob.width, alto_disponible / mob.height)
    if escalar_arriba or factor < 1.0:
        mob.scale(factor)

    colocar_en(mob, zona, direccion=alineacion, margen=margen)
    return mob


def apilar(
    *mobs: Mobject,
    zona: Zona = ZONA_PRINCIPAL,
    espacio: float = MARGEN_ENTRE_BLOQUES,
) -> VGroup:
    """Apila ``mobs`` verticalmente y los encaja dentro de ``zona``."""
    grupo = VGroup(*mobs)
    grupo.arrange(DOWN, buff=espacio)
    encajar(grupo, zona=zona)
    return grupo


def dividir_vertical(zona: Zona, proporciones: Sequence[float]) -> list[Zona]:
    """Parte ``zona`` en franjas horizontales, de arriba a abajo, segun
    ``proporciones`` (se normalizan para sumar 1)."""
    total = sum(proporciones)
    if total <= 0:
        raise ValueError("La suma de proporciones debe ser positiva")

    zonas: list[Zona] = []
    y_actual = zona.y_max
    for indice, proporcion in enumerate(proporciones):
        alto = (proporcion / total) * zona.alto
        y_min = y_actual - alto
        zonas.append(Zona(f"{zona.nombre}_{indice}", zona.x_min, zona.x_max, y_min, y_actual))
        y_actual = y_min
    return zonas


def dividir_horizontal(zona: Zona, proporciones: Sequence[float], espacio: float = 0.0) -> list[Zona]:
    """Parte ``zona`` en columnas, de izquierda a derecha, segun ``proporciones``
    (se normalizan para sumar 1). ``espacio`` es el hueco entre columnas."""
    total = sum(proporciones)
    if total <= 0:
        raise ValueError("La suma de proporciones debe ser positiva")

    ancho_util = zona.ancho - espacio * (len(proporciones) - 1)
    zonas: list[Zona] = []
    x_actual = zona.x_min
    for indice, proporcion in enumerate(proporciones):
        ancho = (proporcion / total) * ancho_util
        zonas.append(Zona(f"{zona.nombre}_c{indice}", x_actual, x_actual + ancho, zona.y_min, zona.y_max))
        x_actual += ancho + espacio
    return zonas


def solapan(a: Mobject, b: Mobject, holgura: float = 0.0) -> bool:
    """True si los bounding boxes (x, y) de ``a`` y ``b`` se intersecan."""
    a_izquierda, a_derecha = a.get_left()[0], a.get_right()[0]
    a_abajo, a_arriba = a.get_bottom()[1], a.get_top()[1]
    b_izquierda, b_derecha = b.get_left()[0], b.get_right()[0]
    b_abajo, b_arriba = b.get_bottom()[1], b.get_top()[1]

    solapan_x = (a_izquierda - holgura) < b_derecha and (b_izquierda - holgura) < a_derecha
    solapan_y = (a_abajo - holgura) < b_arriba and (b_abajo - holgura) < a_arriba
    return bool(solapan_x and solapan_y)
