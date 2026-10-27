"""Tests de toolkit/layout.py: zonas seguras y funciones de posicionamiento."""

import numpy as np
import pytest
from manim import DOWN, LEFT, RIGHT, UP, ORIGIN, Rectangle

from toolkit.layout import (
    MARCO,
    ZONA_PRINCIPAL,
    ZONA_SEGURA,
    ZONA_SUBTITULOS,
    ZONA_TITULO,
    Zona,
    colocar_en,
    dividir_vertical,
    encajar,
    solapan,
)


def test_zona_principal_dentro_de_zona_segura():
    assert ZONA_SEGURA.contiene(Rectangle(width=ZONA_PRINCIPAL.ancho, height=ZONA_PRINCIPAL.alto).move_to(ZONA_PRINCIPAL.centro))
    assert ZONA_PRINCIPAL.x_min >= ZONA_SEGURA.x_min
    assert ZONA_PRINCIPAL.x_max <= ZONA_SEGURA.x_max
    assert ZONA_PRINCIPAL.y_min >= ZONA_SEGURA.y_min
    assert ZONA_PRINCIPAL.y_max <= ZONA_SEGURA.y_max


def test_zona_titulo_dentro_de_zona_segura():
    assert ZONA_TITULO.x_min >= ZONA_SEGURA.x_min
    assert ZONA_TITULO.x_max <= ZONA_SEGURA.x_max
    assert ZONA_TITULO.y_min >= ZONA_SEGURA.y_min
    assert ZONA_TITULO.y_max <= ZONA_SEGURA.y_max


def test_zona_propiedades_basicas():
    zona = Zona("prueba", -1.0, 1.0, -2.0, 2.0)
    assert zona.ancho == pytest.approx(2.0)
    assert zona.alto == pytest.approx(4.0)
    assert np.allclose(zona.centro, np.array([0.0, 0.0, 0.0]))


def test_zona_contiene_punto():
    zona = Zona("prueba", -1.0, 1.0, -2.0, 2.0)
    assert zona.contiene_punto([0.0, 0.0, 0.0])
    assert not zona.contiene_punto([5.0, 0.0, 0.0])


def test_zona_borde_direcciones():
    zona = Zona("prueba", -1.0, 1.0, -2.0, 2.0)
    assert np.allclose(zona.borde(UP), [0.0, 2.0, 0.0])
    assert np.allclose(zona.borde(DOWN), [0.0, -2.0, 0.0])
    assert np.allclose(zona.borde(LEFT), [-1.0, 0.0, 0.0])
    assert np.allclose(zona.borde(RIGHT), [1.0, 0.0, 0.0])


def test_encajar_escala_hacia_abajo_y_conserva_proporcion():
    rect = Rectangle(width=20, height=2)
    proporcion_original = rect.width / rect.height

    resultado = encajar(rect, zona=ZONA_PRINCIPAL)

    assert resultado is rect
    assert ZONA_PRINCIPAL.contiene(rect)
    assert rect.width / rect.height == pytest.approx(proporcion_original)


def test_encajar_no_agranda_si_escalar_arriba_es_falso():
    zona = Zona("grande", -10.0, 10.0, -10.0, 10.0)
    rect = Rectangle(width=1, height=1)
    ancho_original = rect.width

    encajar(rect, zona=zona, escalar_arriba=False)

    assert rect.width == pytest.approx(ancho_original)


def test_encajar_agranda_si_escalar_arriba_es_verdadero():
    zona = Zona("grande", -10.0, 10.0, -10.0, 10.0)
    rect = Rectangle(width=1, height=1)
    ancho_original = rect.width

    encajar(rect, zona=zona, escalar_arriba=True)

    assert rect.width > ancho_original


def test_dividir_vertical_da_zonas_contiguas_que_cubren_la_zona():
    zona = Zona("z", -3.0, 3.0, -2.0, 2.0)

    superior, inferior = dividir_vertical(zona, [1, 1])

    assert superior.y_max == pytest.approx(zona.y_max)
    assert inferior.y_min == pytest.approx(zona.y_min)
    assert superior.y_min == pytest.approx(inferior.y_max)
    assert superior.alto == pytest.approx(inferior.alto)
    assert superior.x_min == pytest.approx(zona.x_min)
    assert superior.x_max == pytest.approx(zona.x_max)
    assert inferior.x_min == pytest.approx(zona.x_min)
    assert inferior.x_max == pytest.approx(zona.x_max)


def test_dividir_vertical_normaliza_proporciones():
    zona = Zona("z", -3.0, 3.0, -3.0, 9.0)

    primera, segunda, tercera = dividir_vertical(zona, [1, 2, 1])

    assert primera.alto == pytest.approx(zona.alto * 0.25)
    assert segunda.alto == pytest.approx(zona.alto * 0.5)
    assert tercera.alto == pytest.approx(zona.alto * 0.25)


def test_solapan_casos_positivo_y_negativo():
    a = Rectangle(width=2, height=2).move_to([0, 0, 0])
    b = Rectangle(width=2, height=2).move_to([1, 0, 0])
    c = Rectangle(width=2, height=2).move_to([10, 0, 0])

    assert solapan(a, b) is True
    assert solapan(a, c) is False


def test_solapan_con_holgura():
    a = Rectangle(width=2, height=2).move_to([0, 0, 0])
    b = Rectangle(width=2, height=2).move_to([2.5, 0, 0])

    assert solapan(a, b, holgura=0.0) is False
    assert solapan(a, b, holgura=1.0) is True


def test_colocar_en_pega_el_top_al_borde_superior_interior():
    margen = 0.15
    rect = Rectangle(width=1, height=1)

    colocar_en(rect, ZONA_TITULO, direccion=UP, margen=margen)

    assert rect.get_top()[1] == pytest.approx(ZONA_TITULO.y_max - margen)


def test_colocar_en_sin_direccion_centra_en_la_zona():
    rect = Rectangle(width=1, height=1)

    colocar_en(rect, ZONA_PRINCIPAL, direccion=ORIGIN)

    assert np.allclose(rect.get_center(), ZONA_PRINCIPAL.centro)


def test_marco_y_zona_segura_son_consistentes_con_el_cuadro():
    assert MARCO.ancho == pytest.approx(9.0)
    assert MARCO.alto == pytest.approx(16.0)
    assert ZONA_SEGURA.ancho < MARCO.ancho
    assert ZONA_SEGURA.alto < MARCO.alto
    assert ZONA_SUBTITULOS.y_max <= ZONA_SEGURA.y_max


def test_dividir_horizontal_columnas_contiguas_con_espacio():
    from toolkit.layout import dividir_horizontal, ZONA_PRINCIPAL
    izq, der = dividir_horizontal(ZONA_PRINCIPAL, [1, 1], espacio=0.3)
    assert izq.x_min == ZONA_PRINCIPAL.x_min
    assert abs(der.x_max - ZONA_PRINCIPAL.x_max) < 1e-9
    assert abs((der.x_min - izq.x_max) - 0.3) < 1e-9
    assert abs(izq.ancho - der.ancho) < 1e-9
    assert izq.y_min == ZONA_PRINCIPAL.y_min and izq.y_max == ZONA_PRINCIPAL.y_max
