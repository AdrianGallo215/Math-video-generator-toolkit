"""Motor de física (puro, sin manim): tiro parabólico con y sin rozamiento lineal.

Convenciones: ángulos en GRADOS (como se narran), SI (m, s, m/s, m/s²), lanzamiento desde el
origen y aterrizaje a la misma altura. Sin aire: ``x = v cosθ t``, ``y = v sinθ t − g t²/2``.
Con aire (rozamiento lineal ``a = −k·v``): solución analítica exacta.
"""

from __future__ import annotations

import math

__all__ = [
    "G_TIERRA",
    "componentes_velocidad",
    "posicion",
    "velocidad",
    "tiempo_cima",
    "tiempo_vuelo",
    "altura_maxima",
    "alcance",
    "angulo_alcance_maximo",
    "posicion_con_arrastre",
    "tiempo_vuelo_con_arrastre",
]

G_TIERRA = 9.8
_ITERACIONES_BISECCION = 80


def _validar(v: float, g: float) -> None:
    if v < 0:
        raise ValueError(f"la rapidez debe ser >= 0 (v={v})")
    if g <= 0:
        raise ValueError(f"la gravedad debe ser > 0 (g={g})")


def componentes_velocidad(v: float, grados: float) -> tuple[float, float]:
    """``(vx, vy) = (v cosθ, v sinθ)``."""
    rad = math.radians(grados)
    return v * math.cos(rad), v * math.sin(rad)


def posicion(v: float, grados: float, t: float, g: float = G_TIERRA) -> tuple[float, float]:
    """Posición ``(x, y)`` en el instante ``t`` (sin aire)."""
    _validar(v, g)
    vx, vy = componentes_velocidad(v, grados)
    return vx * t, vy * t - g * t * t / 2.0


def velocidad(v: float, grados: float, t: float, g: float = G_TIERRA) -> tuple[float, float]:
    """Velocidad ``(vx, vy(t))``: ``vx`` constante, ``vy = v sinθ − g t``."""
    _validar(v, g)
    vx, vy = componentes_velocidad(v, grados)
    return vx, vy - g * t


def tiempo_cima(v: float, grados: float, g: float = G_TIERRA) -> float:
    """Instante en que ``vy = 0`` (vértice de la parábola)."""
    _validar(v, g)
    return componentes_velocidad(v, grados)[1] / g


def tiempo_vuelo(v: float, grados: float, g: float = G_TIERRA) -> float:
    """Tiempo en el aire: ``2 v sinθ / g``."""
    return 2.0 * tiempo_cima(v, grados, g)


def altura_maxima(v: float, grados: float, g: float = G_TIERRA) -> float:
    """``(v sinθ)² / (2g)``."""
    _validar(v, g)
    vy = componentes_velocidad(v, grados)[1]
    return vy * vy / (2.0 * g)


def alcance(v: float, grados: float, g: float = G_TIERRA) -> float:
    """``R = v² sin(2θ) / g`` (= vx · tiempo de vuelo)."""
    _validar(v, g)
    return v * v * math.sin(math.radians(2.0 * grados)) / g


def angulo_alcance_maximo() -> float:
    """Ángulo (grados) de alcance máximo sin aire y a igual altura: 45."""
    return 45.0


def posicion_con_arrastre(
    v: float, grados: float, t: float, k: float, g: float = G_TIERRA
) -> tuple[float, float]:
    """Posición con rozamiento lineal ``a = −k v`` (k en 1/s). ``k = 0`` ⇒ caso sin aire."""
    _validar(v, g)
    if k < 0:
        raise ValueError(f"el coeficiente de rozamiento debe ser >= 0 (k={k})")
    if k == 0:
        return posicion(v, grados, t, g)
    vx, vy = componentes_velocidad(v, grados)
    factor = (1.0 - math.exp(-k * t)) / k
    return vx * factor, (vy + g / k) * factor - g * t / k


def tiempo_vuelo_con_arrastre(v: float, grados: float, k: float, g: float = G_TIERRA) -> float:
    """Tiempo hasta volver a ``y = 0`` con rozamiento lineal (bisección determinista)."""
    if k == 0:
        return tiempo_vuelo(v, grados, g)
    t_sin_aire = tiempo_vuelo(v, grados, g)
    if t_sin_aire == 0:
        return 0.0
    bajo, alto = t_sin_aire * 1e-6, t_sin_aire
    while posicion_con_arrastre(v, grados, alto, k, g)[1] > 0:
        alto *= 2.0
    for _ in range(_ITERACIONES_BISECCION):
        medio = (bajo + alto) / 2.0
        if posicion_con_arrastre(v, grados, medio, k, g)[1] > 0:
            bajo = medio
        else:
            alto = medio
    return (bajo + alto) / 2.0
