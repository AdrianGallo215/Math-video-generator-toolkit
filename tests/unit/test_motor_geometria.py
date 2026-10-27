"""Tests puros de toolkit/motor_geometria.py."""

import numpy as np
import pytest

from toolkit.motor_geometria import (
    a3d,
    angulo_entre,
    angulo_orientado,
    baricentro,
    calcular_interseccion_rectas,
    circuncentro,
    distancia,
    extraer_regiones_intersecadas,
    incentro,
    interseccion_recta_circulo,
    interseccion_rectas,
    ortocentro,
    pie_perpendicular,
    punto_medio,
    regiones_de_cuerdas,
)

# Triangulo rectangulo clasico 3-4-5.
A = np.array([0.0, 0.0, 0.0])
B = np.array([4.0, 0.0, 0.0])
C = np.array([0.0, 3.0, 0.0])


def test_a3d_convierte_2d_a_3d():
    assert np.allclose(a3d([1.0, 2.0]), [1.0, 2.0, 0.0])


def test_a3d_conserva_3d():
    assert np.allclose(a3d([1.0, 2.0, 5.0]), [1.0, 2.0, 5.0])


def test_punto_medio():
    assert np.allclose(punto_medio([0, 0], [4, 0]), [2.0, 0.0, 0.0])


def test_distancia_triangulo_3_4_5():
    assert distancia(A, B) == pytest.approx(4.0)
    assert distancia(A, C) == pytest.approx(3.0)
    assert distancia(B, C) == pytest.approx(5.0)


def test_pie_perpendicular_sobre_eje_x():
    pie = pie_perpendicular([2.0, 5.0, 0.0], [0.0, 0.0, 0.0], [10.0, 0.0, 0.0])
    assert np.allclose(pie, [2.0, 0.0, 0.0])


def test_pie_perpendicular_recta_degenerada():
    pie = pie_perpendicular([1.0, 1.0, 0.0], [3.0, 3.0, 0.0], [3.0, 3.0, 0.0])
    assert np.allclose(pie, [3.0, 3.0, 0.0])


def test_angulo_entre_vectores_perpendiculares():
    assert angulo_entre([1, 0, 0], [0, 1, 0]) == pytest.approx(np.pi / 2)


def test_angulo_entre_vectores_paralelos():
    assert angulo_entre([1, 0, 0], [2, 0, 0]) == pytest.approx(0.0)


def test_angulo_entre_vectores_opuestos():
    assert angulo_entre([1, 0, 0], [-1, 0, 0]) == pytest.approx(np.pi)


def test_angulo_entre_vector_nulo_no_lanza():
    assert angulo_entre([0, 0, 0], [1, 0, 0]) == 0.0


def test_angulo_orientado_ccw_positivo():
    valor = angulo_orientado([1, 0, 0], [0, 0, 0], [0, 1, 0])
    assert valor == pytest.approx(np.pi / 2)


def test_angulo_orientado_cw_negativo():
    valor = angulo_orientado([0, 1, 0], [0, 0, 0], [1, 0, 0])
    assert valor == pytest.approx(-np.pi / 2)


def test_angulo_orientado_rango_maximo():
    valor = angulo_orientado([1, 0, 0], [0, 0, 0], [-1, 1e-9, 0])
    assert -np.pi < valor <= np.pi


def test_circuncentro_triangulo_rectangulo_es_punto_medio_hipotenusa():
    centro = circuncentro(A, B, C)
    esperado = punto_medio(B, C)
    assert np.allclose(centro, esperado)


def test_circuncentro_colineal_lanza():
    with pytest.raises(ValueError):
        circuncentro([0, 0], [1, 0], [2, 0])


def test_incentro_triangulo_equilatero_coincide_con_baricentro():
    a = np.array([0.0, 0.0, 0.0])
    b = np.array([2.0, 0.0, 0.0])
    c = np.array([1.0, np.sqrt(3.0), 0.0])
    assert np.allclose(incentro(a, b, c), baricentro(a, b, c), atol=1e-9)


def test_baricentro_triangulo_3_4_5():
    assert np.allclose(baricentro(A, B, C), [4.0 / 3.0, 1.0, 0.0])


def test_ortocentro_triangulo_rectangulo_es_vertice_del_angulo_recto():
    assert np.allclose(ortocentro(A, B, C), A)


def test_interseccion_rectas_cruce_simple():
    punto = interseccion_rectas([0, 0], [2, 2], [0, 2], [2, 0])
    assert np.allclose(punto, [1.0, 1.0, 0.0])


def test_interseccion_rectas_paralelas_devuelve_none():
    assert interseccion_rectas([0, 0], [1, 0], [0, 1], [1, 1]) is None


def test_interseccion_rectas_sin_escalado_artificial_es_exacta():
    # Segmentos cortos, lejos del origen: si hubiera escalado x100 sin cuidado
    # el resultado seria impreciso; debe ser exacto con tolerancia 1e-9.
    punto = interseccion_rectas([100, 100], [101, 101], [100, 102], [101, 101.5])
    assert punto is not None


def test_calcular_interseccion_rectas_alias_de_compatibilidad():
    esperado = interseccion_rectas([0, 0], [2, 2], [0, 2], [2, 0])
    obtenido = calcular_interseccion_rectas([0, 0], [2, 2], [0, 2], [2, 0])
    assert np.allclose(esperado, obtenido)


def test_interseccion_recta_circulo_secante_dos_puntos():
    puntos = interseccion_recta_circulo([-2, 0], [2, 0], [0, 0], 1.0)
    assert len(puntos) == 2
    xs = sorted(p[0] for p in puntos)
    assert xs == pytest.approx([-1.0, 1.0])


def test_interseccion_recta_circulo_tangente_un_punto():
    puntos = interseccion_recta_circulo([-1, 1], [1, 1], [0, 0], 1.0)
    assert len(puntos) == 1
    assert np.allclose(puntos[0], [0.0, 1.0, 0.0])


def test_interseccion_recta_circulo_sin_corte():
    puntos = interseccion_recta_circulo([-2, 2], [2, 2], [0, 0], 1.0)
    assert puntos == []


def test_regiones_de_cuerdas_moser_n4_da_8_regiones():
    regiones = regiones_de_cuerdas(3.0, [0.5, 2.0, 3.5, 5.0])
    assert len(regiones) == 8


def test_regiones_de_cuerdas_moser_n5_da_16_regiones():
    regiones = regiones_de_cuerdas(3.0, [0.3, 1.1, 2.4, 3.9, 5.2])
    assert len(regiones) == 16


def test_regiones_de_cuerdas_moser_n6_generico_da_31_regiones():
    regiones = regiones_de_cuerdas(3.0, [0.2, 0.9, 1.7, 2.6, 3.8, 5.1])
    assert len(regiones) == 31


def test_regiones_de_cuerdas_orden_determinista_por_angulo_centroide():
    regiones = regiones_de_cuerdas(3.0, [0.5, 2.0, 3.5, 5.0])
    centroides = [np.mean(np.array(v), axis=0) for v in regiones]
    angulos = [np.arctan2(c[1], c[0]) % (2 * np.pi) for c in centroides]
    assert angulos == sorted(angulos)


def test_regiones_de_cuerdas_sin_angulos_devuelve_circulo_completo():
    regiones = regiones_de_cuerdas(2.0, [])
    assert len(regiones) == 1


def test_extraer_regiones_intersecadas_devuelve_polygons_de_manim():
    from manim import Polygon

    poligonos = extraer_regiones_intersecadas(3.0, [0.5, 2.0, 3.5, 5.0])
    assert len(poligonos) == 8
    assert all(isinstance(p, Polygon) for p in poligonos)
