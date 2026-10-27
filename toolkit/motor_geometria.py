"""Motor geometrico puro (sin dependencias de manim salvo el compat final).

Todas las funciones de calculo trabajan con `numpy.ndarray` de 3 componentes
(z=0 para geometria plana) y no crean mobjects, salvo los alias de
compatibilidad marcados explicitamente, que devuelven `Polygon` de manim para
no romper escenas existentes.
"""

from __future__ import annotations

import logging

import numpy as np
from shapely.geometry import Polygon as PoligonoShapely
from shapely.geometry import LineString
from shapely.ops import split, unary_union
from shapely.affinity import scale

logger = logging.getLogger(__name__)

_TOLERANCIA = 1e-9


def a3d(p) -> np.ndarray:
    """Convierte un punto 2D o 3D (secuencia o ndarray) a un vector 3D float."""
    arreglo = np.asarray(p, dtype=float)
    if arreglo.shape[-1] == 2:
        return np.array([arreglo[0], arreglo[1], 0.0])
    return arreglo[:3].astype(float)


def punto_medio(a, b) -> np.ndarray:
    """Punto medio entre `a` y `b`."""
    return (a3d(a) + a3d(b)) / 2.0


def distancia(a, b) -> float:
    """Distancia euclidiana entre `a` y `b`."""
    return float(np.linalg.norm(a3d(a) - a3d(b)))


def pie_perpendicular(p, a, b) -> np.ndarray:
    """Pie de la perpendicular desde `p` hacia la recta que pasa por `a` y `b`.

    Si `a` y `b` coinciden, devuelve `a` (recta degenerada).
    """
    p3, a3, b3 = a3d(p), a3d(a), a3d(b)
    direccion = b3 - a3
    denominador = float(np.dot(direccion, direccion))
    if denominador < _TOLERANCIA:
        return a3.copy()
    t = float(np.dot(p3 - a3, direccion) / denominador)
    return a3 + t * direccion


def angulo_entre(v1, v2) -> float:
    """Angulo no orientado entre dos vectores, en radianes, dentro de [0, pi]."""
    vec1 = np.asarray(v1, dtype=float)
    vec2 = np.asarray(v2, dtype=float)
    norma1 = np.linalg.norm(vec1)
    norma2 = np.linalg.norm(vec2)
    if norma1 < _TOLERANCIA or norma2 < _TOLERANCIA:
        return 0.0
    coseno = float(np.dot(vec1, vec2) / (norma1 * norma2))
    coseno = max(-1.0, min(1.0, coseno))
    return float(np.arccos(coseno))


def angulo_orientado(a, vertice, b) -> float:
    """Angulo orientado (CCW positivo) de `vertice->a` a `vertice->b` en el plano XY.

    Rango: (-pi, pi].
    """
    va = a3d(a) - a3d(vertice)
    vb = a3d(b) - a3d(vertice)
    cruz = va[0] * vb[1] - va[1] * vb[0]
    punto = va[0] * vb[0] + va[1] * vb[1]
    return float(np.arctan2(cruz, punto))


def circuncentro(a, b, c) -> np.ndarray:
    """Circuncentro del triangulo `abc` (plano XY, z=0). Lanza si es colineal."""
    a3, b3, c3 = a3d(a), a3d(b), a3d(c)
    ax, ay = a3[0], a3[1]
    bx, by = b3[0], b3[1]
    cx, cy = c3[0], c3[1]
    d = 2.0 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < _TOLERANCIA:
        raise ValueError("puntos colineales: circuncentro indefinido")
    a2 = ax * ax + ay * ay
    b2 = bx * bx + by * by
    c2 = cx * cx + cy * cy
    ux = (a2 * (by - cy) + b2 * (cy - ay) + c2 * (ay - by)) / d
    uy = (a2 * (cx - bx) + b2 * (ax - cx) + c2 * (bx - ax)) / d
    return np.array([ux, uy, 0.0])


def incentro(a, b, c) -> np.ndarray:
    """Incentro del triangulo `abc` (promedio ponderado por longitud del lado opuesto)."""
    a3, b3, c3 = a3d(a), a3d(b), a3d(c)
    lado_a = distancia(b3, c3)
    lado_b = distancia(a3, c3)
    lado_c = distancia(a3, b3)
    perimetro = lado_a + lado_b + lado_c
    if perimetro < _TOLERANCIA:
        raise ValueError("triangulo degenerado: incentro indefinido")
    return (lado_a * a3 + lado_b * b3 + lado_c * c3) / perimetro


def baricentro(a, b, c) -> np.ndarray:
    """Baricentro (centroide) del triangulo `abc`."""
    return (a3d(a) + a3d(b) + a3d(c)) / 3.0


def ortocentro(a, b, c) -> np.ndarray:
    """Ortocentro del triangulo `abc`, via identidad vectorial H = A+B+C-2*O."""
    a3, b3, c3 = a3d(a), a3d(b), a3d(c)
    o = circuncentro(a3, b3, c3)
    return a3 + b3 + c3 - 2.0 * o


def interseccion_rectas(p1, p2, p3, p4) -> np.ndarray | None:
    """Interseccion algebraica (determinante) de la recta `p1p2` con `p3p4`.

    Devuelve `None` si son paralelas (determinante ~0, tolerancia 1e-9).
    No usa escalado artificial de las rectas.
    """
    a, b, c, d = a3d(p1), a3d(p2), a3d(p3), a3d(p4)
    x1, y1 = a[0], a[1]
    x2, y2 = b[0], b[1]
    x3, y3 = c[0], c[1]
    x4, y4 = d[0], d[1]
    denominador = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(denominador) < _TOLERANCIA:
        return None
    det12 = x1 * y2 - y1 * x2
    det34 = x3 * y4 - y3 * x4
    px = (det12 * (x3 - x4) - (x1 - x2) * det34) / denominador
    py = (det12 * (y3 - y4) - (y1 - y2) * det34) / denominador
    return np.array([px, py, 0.0])


def interseccion_recta_circulo(p1, p2, centro, radio) -> list[np.ndarray]:
    """Puntos de interseccion entre la recta `p1p2` y el circulo (`centro`, `radio`).

    Devuelve 0, 1 (tangente) o 2 puntos.
    """
    a, b, o = a3d(p1), a3d(p2), a3d(centro)
    direccion = (b - a)[:2]
    f = (a - o)[:2]
    coef_a = float(np.dot(direccion, direccion))
    if coef_a < _TOLERANCIA:
        raise ValueError("p1 y p2 coinciden: recta indefinida")
    coef_b = 2.0 * float(np.dot(f, direccion))
    coef_c = float(np.dot(f, f)) - float(radio) ** 2
    discriminante = coef_b**2 - 4.0 * coef_a * coef_c
    if discriminante < -_TOLERANCIA:
        return []
    discriminante = max(discriminante, 0.0)
    raiz = np.sqrt(discriminante)
    if raiz < 1e-7:
        t = -coef_b / (2.0 * coef_a)
        return [a + t * (b - a)]
    t1 = (-coef_b - raiz) / (2.0 * coef_a)
    t2 = (-coef_b + raiz) / (2.0 * coef_a)
    return [a + t1 * (b - a), a + t2 * (b - a)]


def regiones_de_cuerdas(radio, angulos, resolucion: int = 256) -> list[list[np.ndarray]]:
    """Vertices de cada region cerrada formada por las cuerdas entre `angulos`.

    Calcula con shapely las caras que resultan de trazar todas las cuerdas
    entre los puntos `(radio*cos(a), radio*sin(a))` dentro del circulo de
    radio `radio`. El orden de las regiones es determinista: se ordenan por
    el angulo (atan2) de su centroide.
    """
    t = np.linspace(0.0, 2.0 * np.pi, resolucion, endpoint=False)
    borde = [(radio * np.cos(a), radio * np.sin(a)) for a in t]
    circulo = PoligonoShapely(borde)

    conexiones = [(radio * np.cos(a), radio * np.sin(a)) for a in angulos]
    lineas = []
    n = len(conexiones)
    for i in range(n):
        for j in range(i + 1, n):
            cuerda = LineString([conexiones[i], conexiones[j]])
            # Factor 1.02: garantiza que la cuerda exceda el borde del
            # circulo y produzca cortes limpios (evita polígonos abiertos).
            lineas.append(scale(cuerda, xfact=1.02, yfact=1.02))

    if not lineas:
        coords = list(circulo.exterior.coords)[:-1]
        return [[np.array([x, y, 0.0]) for x, y in coords]]

    divisor = unary_union(lineas)
    regiones_shapely = split(circulo, divisor)

    con_angulo = []
    for poligono in regiones_shapely.geoms:
        coords = list(poligono.exterior.coords)[:-1]
        centroide = poligono.centroid
        angulo_centroide = np.arctan2(centroide.y, centroide.x) % (2.0 * np.pi)
        con_angulo.append((angulo_centroide, [np.array([x, y, 0.0]) for x, y in coords]))

    con_angulo.sort(key=lambda par: par[0])
    return [vertices for _, vertices in con_angulo]


def calcular_interseccion_rectas(p1, p2, p3, p4):
    """Alias de compatibilidad de `interseccion_rectas`."""
    return interseccion_rectas(p1, p2, p3, p4)


def extraer_regiones_intersecadas(radio, angulos):
    """Alias de compatibilidad: `regiones_de_cuerdas` como `Polygon` de manim."""
    from manim import Polygon

    regiones = regiones_de_cuerdas(radio, angulos)
    return [Polygon(*vertices) for vertices in regiones]
