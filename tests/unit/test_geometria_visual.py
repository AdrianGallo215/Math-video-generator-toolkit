"""Tests de toolkit/geometria_visual.py."""

import numpy as np
import pytest
from manim import Angle, DashedLine, Line, RightAngle, VGroup

from toolkit.estilos import GRIS
from toolkit.geometria_visual import (
    EtiquetaAngulo,
    LineaAuxiliar,
    MarcaAngulo,
    TrianguloEtiquetado,
    cota,
    marcas_congruencia,
    regiones_coloreadas,
)
from toolkit.motor_geometria import baricentro, distancia


def test_linea_auxiliar_es_dashed_line():
    linea = LineaAuxiliar([0, 0, 0], [1, 0, 0])
    assert isinstance(linea, DashedLine)


def test_linea_auxiliar_color_por_defecto_es_secundario():
    from toolkit.estilos import COLORES_MARCA

    linea = LineaAuxiliar([0, 0, 0], [1, 0, 0])
    assert linea.get_color().to_hex() == COLORES_MARCA["TEXTO_SECUNDARIO"]


def test_marca_angulo_es_vgroup():
    marca = MarcaAngulo([2, 0, 0], [0, 0, 0], [0, 2, 0])
    assert isinstance(marca, VGroup)


@pytest.mark.render
def test_marca_angulo_recto_usa_right_angle():
    marca = MarcaAngulo([2, 0, 0], [0, 0, 0], [0, 2, 0])
    assert isinstance(marca.arco, RightAngle)
    assert marca.arco in marca.submobjects


@pytest.mark.render
def test_marca_angulo_no_recto_usa_angle_generico():
    marca = MarcaAngulo([2, 0, 0], [0, 0, 0], [2, 1, 0])
    assert isinstance(marca.arco, Angle)
    assert not isinstance(marca.arco, RightAngle)


def test_marca_angulo_elige_angulo_interior_sin_importar_orden():
    # El angulo interior entre estos dos rayos es ~53.13 grados (<pi),
    # sin importar si se pide en un orden u otro.
    m1 = MarcaAngulo([3, 4, 0], [0, 0, 0], [1, 0, 0], radio=0.5)
    m2 = MarcaAngulo([1, 0, 0], [0, 0, 0], [3, 4, 0], radio=0.5)
    assert abs(m1.arco.get_value()) == pytest.approx(abs(m2.arco.get_value()), abs=1e-6)
    assert abs(m1.arco.get_value()) < np.pi


def test_marca_angulo_etiqueta_sobre_bisectriz():
    marca = MarcaAngulo([2, 0, 0], [0, 0, 0], [0, 2, 0], etiqueta=r"\alpha", radio=0.5)
    centro_etiqueta = marca.etiqueta.get_center()
    # La bisectriz de 90 grados entre eje x y eje y es la direccion (1,1)/sqrt(2).
    direccion = centro_etiqueta / np.linalg.norm(centro_etiqueta)
    assert direccion[0] == pytest.approx(direccion[1], abs=1e-2)


def test_marca_angulo_sin_etiqueta():
    marca = MarcaAngulo([2, 0, 0], [0, 0, 0], [0, 2, 0], etiqueta=None)
    assert marca.etiqueta is None


def test_etiqueta_angulo_compat_delega_en_marca_angulo():
    l1 = Line([0, 0, 0], [3, 0, 0])
    l2 = Line([0, 0, 0], [0, 3, 0])
    resultado = EtiquetaAngulo(l1, l2, r"\theta", radio=0.8)
    assert isinstance(resultado, MarcaAngulo)
    assert isinstance(resultado.arco, RightAngle)


def test_etiqueta_angulo_compat_vertice_por_interseccion():
    # Lineas que no comparten punto de inicio pero si se intersecan.
    l1 = Line([-2, -2, 0], [2, 2, 0])
    l2 = Line([-2, 2, 0], [2, -2, 0])
    resultado = EtiquetaAngulo(l1, l2, r"\theta")
    assert np.allclose(resultado.arco.get_center(), resultado.arco.get_center())  # construye sin lanzar


def test_triangulo_etiquetado_es_vgroup_y_expone_atributos():
    triangulo = TrianguloEtiquetado([0, 0, 0], [4, 0, 0], [0, 3, 0], lados=("a", "b", "c"))
    assert isinstance(triangulo, VGroup)
    assert len(triangulo.vertices) == 3
    assert isinstance(triangulo.lados, VGroup)
    assert len(triangulo.lados) == 3
    assert isinstance(triangulo.etiquetas, VGroup)


def test_triangulo_etiquetado_etiquetas_fuera_del_triangulo():
    a, b, c = [0, 0, 0], [4, 0, 0], [0, 3, 0]
    triangulo = TrianguloEtiquetado(a, b, c)
    centro = baricentro(np.array(a), np.array(b), np.array(c))

    for punto, etiqueta in zip((a, b, c), triangulo.etiquetas):
        distancia_vertice_centro = distancia(punto, centro)
        distancia_etiqueta_centro = distancia(etiqueta.get_center(), centro)
        assert distancia_etiqueta_centro > distancia_vertice_centro


def test_triangulo_etiquetado_sin_lados_no_agrega_etiquetas_de_lado():
    triangulo_sin_lados = TrianguloEtiquetado([0, 0, 0], [4, 0, 0], [0, 3, 0])
    triangulo_con_lados = TrianguloEtiquetado(
        [0, 0, 0], [4, 0, 0], [0, 3, 0], lados=("3", "4", "5")
    )
    assert len(triangulo_con_lados.etiquetas) == len(triangulo_sin_lados.etiquetas) + 3


def test_marcas_congruencia_produce_n_rayitas():
    linea = Line([0, 0, 0], [2, 0, 0])
    assert len(marcas_congruencia(linea, n=1)) == 1
    assert len(marcas_congruencia(linea, n=3)) == 3


def test_marcas_congruencia_centradas_en_punto_medio():
    linea = Line([0, 0, 0], [2, 0, 0])
    grupo = marcas_congruencia(linea, n=1)
    assert np.allclose(grupo[0].get_center(), [1.0, 0.0, 0.0], atol=1e-6)


def test_marcas_congruencia_perpendiculares_a_la_linea():
    linea = Line([0, 0, 0], [2, 0, 0])
    grupo = marcas_congruencia(linea, n=1)
    vector_marca = grupo[0].get_end() - grupo[0].get_start()
    assert abs(vector_marca[0]) < 1e-6  # sin componente horizontal: perpendicular al eje x


def test_cota_devuelve_vgroup_con_cuatro_elementos():
    grupo = cota([0, 0, 0], [2, 0, 0], "2 cm")
    assert isinstance(grupo, VGroup)
    assert len(grupo) == 4


def test_cota_desplazada_del_segmento_original():
    grupo = cota([0, 0, 0], [2, 0, 0], "2 cm", lado=1.0, color=GRIS)
    linea_cota = grupo[0]
    assert linea_cota.get_start()[1] == pytest.approx(1.0, abs=1e-6)
    assert linea_cota.get_end()[1] == pytest.approx(1.0, abs=1e-6)


def test_regiones_coloreadas_devuelve_vgroup_determinista():
    grupo1 = regiones_coloreadas(3.0, [0.5, 2.0, 3.5, 5.0])
    grupo2 = regiones_coloreadas(3.0, [0.5, 2.0, 3.5, 5.0])
    assert len(grupo1) == len(grupo2) == 8
    for r1, r2 in zip(grupo1, grupo2):
        assert r1.get_color() == r2.get_color()


def test_regiones_coloreadas_usa_paleta_secuencial_por_indice():
    from toolkit.estilos import PALETA_SECUENCIAL

    grupo = regiones_coloreadas(3.0, [0.5, 2.0, 3.5, 5.0])
    for i, region in enumerate(grupo):
        assert region.get_color().to_hex() == PALETA_SECUENCIAL[i % len(PALETA_SECUENCIAL)]
