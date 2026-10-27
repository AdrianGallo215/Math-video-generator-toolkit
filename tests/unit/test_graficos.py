"""Tests de toolkit/graficos.py: planos, curvas y helpers estilo 3B1B."""

import numpy as np
import pytest
from manim import (
    Axes,
    Dot,
    Line,
    MathTex,
    NumberPlane,
    ParametricFunction,
    Polygon,
    VGroup,
    ValueTracker,
)

from toolkit.estilos import AMARILLO, AZUL, BLANCO, FUENTE_ETIQUETA
from toolkit.graficos import (
    EjesShort,
    PlanoShort,
    area_bajo_curva,
    curva,
    descomponer_vector,
    etiqueta_valor,
    punto_sobre_curva,
    recta_tangente,
    trayectoria,
    vector,
)


def test_plano_short_devuelve_number_plane():
    plano = PlanoShort()
    assert isinstance(plano, NumberPlane)


def test_plano_short_lineas_de_fondo_azules_y_tenues():
    plano = PlanoShort()
    estilo = plano.background_line_style
    assert estilo["stroke_color"] == AZUL
    assert estilo["stroke_opacity"] == pytest.approx(0.35)
    assert estilo["stroke_width"] == pytest.approx(1.5)


def test_plano_short_ejes_blancos_grosor_3():
    plano = PlanoShort()
    for eje in (plano.get_x_axis(), plano.get_y_axis()):
        assert eje.get_stroke_width() == pytest.approx(3)


def test_plano_short_con_numeros_agrega_etiquetas():
    plano_con_numeros = PlanoShort(con_numeros=True)
    plano_sin_numeros = PlanoShort(con_numeros=False)
    assert len(plano_con_numeros.get_x_axis().submobjects) > len(
        plano_sin_numeros.get_x_axis().submobjects
    )


def test_ejes_short_devuelve_axes_con_etiquetas():
    ejes = EjesShort(etiqueta_x="x", etiqueta_y="y")
    assert isinstance(ejes, Axes)
    assert ejes.etiquetas is not None


def test_curva_construye_parametric_function():
    ejes = EjesShort()
    grafica = curva(ejes, lambda x: x**2)
    assert isinstance(grafica, ParametricFunction)


def _puntos_de_grafica(grafica):
    """Devuelve todos los puntos (coordenadas de escena) de una curva que puede
    ser un unico ParametricFunction o un VGroup de varios tramos."""
    piezas = grafica.submobjects if isinstance(grafica, VGroup) else [grafica]
    puntos = []
    for pieza in piezas:
        puntos.extend(pieza.get_all_points())
    return puntos


def test_curva_recorta_al_rango_visible_por_defecto():
    """f(x) = x^2 crece por encima de y_max=5 fuera de [-sqrt(5), sqrt(5)];
    con rango_x=None (por defecto) ningun punto de la curva debe caer fuera
    del rectangulo de los ejes (x_range, y_range), con tolerancia 0.05."""
    ejes = EjesShort(x_rango=(-3, 3, 1), y_rango=(-1, 5, 1), ancho=6.0, alto=5.0)
    grafica = curva(ejes, lambda x: x**2)

    x_min, x_max = float(ejes.x_range[0]), float(ejes.x_range[1])
    y_min, y_max = float(ejes.y_range[0]), float(ejes.y_range[1])
    tolerancia = 0.05

    puntos = _puntos_de_grafica(grafica)
    assert puntos, "la curva no genero ningun punto"
    for punto in puntos:
        x, y = ejes.p2c(punto)[0], ejes.p2c(punto)[1]
        assert x_min - tolerancia <= x <= x_max + tolerancia
        assert y_min - tolerancia <= y <= y_max + tolerancia


def test_curva_con_rango_x_explicito_no_recorta():
    """Si se pide un rango_x explicito, se respeta tal cual (no se recorta al
    rango visible): es responsabilidad de quien llama."""
    ejes = EjesShort(x_rango=(-3, 3, 1), y_rango=(-1, 5, 1), ancho=6.0, alto=5.0)
    grafica = curva(ejes, lambda x: x**2, rango_x=(-3, 3))
    assert isinstance(grafica, ParametricFunction)


def test_recta_tangente_a_x_cuadrado_en_x_1_tiene_pendiente_2():
    """La derivada de f(x) = x^2 en x=1 es 2: la tangente numerica (dx pequeno)
    debe reproducir esa pendiente en las COORDENADAS de los ejes (no de pantalla)."""
    ejes = EjesShort(x_rango=(-4, 4, 1), y_rango=(-4, 4, 1), ancho=6.0, alto=5.0)
    tracker = ValueTracker(1.0)
    tangente = recta_tangente(ejes, lambda x: x**2, tracker)
    linea = tangente.copy()  # always_redraw ya construyo la Line inicial

    inicio_datos = ejes.p2c(linea.get_start())
    fin_datos = ejes.p2c(linea.get_end())
    pendiente = (fin_datos[1] - inicio_datos[1]) / (fin_datos[0] - inicio_datos[0])
    assert pendiente == pytest.approx(2.0, abs=1e-2)


def test_punto_sobre_curva_sigue_al_tracker():
    ejes = EjesShort()
    tracker = ValueTracker(0.0)
    punto = punto_sobre_curva(ejes, lambda x: x**2, tracker)
    assert isinstance(punto, Dot)
    esperado = ejes.c2p(0.0, 0.0)
    assert np.allclose(punto.get_center(), esperado, atol=1e-6)

    tracker.set_value(2.0)
    punto.update()
    esperado2 = ejes.c2p(2.0, 4.0)
    assert np.allclose(punto.get_center(), esperado2, atol=1e-6)


def test_area_bajo_curva_es_polygon_con_area_positiva():
    ejes = EjesShort()
    region = area_bajo_curva(ejes, lambda x: x**2, 0, 2)
    assert isinstance(region, Polygon)
    assert region.width > 0
    assert region.height > 0


def test_etiqueta_valor_actualiza_con_tracker():
    tracker = ValueTracker(1.5)
    grupo = etiqueta_valor(tracker, prefijo="t=", decimales=1)
    assert isinstance(grupo, VGroup)
    numero = grupo[-1]
    assert numero.get_value() == pytest.approx(1.5)
    tracker.set_value(3.25)
    numero.update()
    assert numero.get_value() == pytest.approx(3.25, abs=0.05)


def test_etiqueta_valor_decimal_number_usa_el_tamano_pedido():
    """El DecimalNumber de etiqueta_valor debe medir (altura) lo mismo que un
    MathTex('0', font_size=tamano) de referencia (font_size SI se propaga),
    con una tolerancia del 15% (distintos glifos, distinta altura exacta)."""
    tracker = ValueTracker(-2.0)
    grupo = etiqueta_valor(tracker, prefijo="x=", decimales=2, tamano=FUENTE_ETIQUETA)
    numero = grupo[-1]
    referencia = MathTex("0", font_size=FUENTE_ETIQUETA)
    assert numero.height == pytest.approx(referencia.height, rel=0.15)


def test_trayectoria_construye_parametric_function():
    ejes = EjesShort()
    curva_t = trayectoria(ejes, lambda t: t, lambda t: -t**2, t_max=2.0)
    assert isinstance(curva_t, ParametricFunction)


def test_vector_construye_flecha_entre_puntos():
    grupo = vector((0, 0, 0), (2, 1, 0))
    assert isinstance(grupo, VGroup)
    flecha = grupo[0]
    assert np.allclose(flecha.get_start(), np.array([0.0, 0.0, 0.0]), atol=1e-6)
    assert np.allclose(flecha.get_end(), np.array([2.0, 1.0, 0.0]), atol=1e-6)


def test_vector_con_etiqueta_agrega_texto():
    grupo = vector((0, 0, 0), (1, 1, 0), etiqueta="v")
    assert len(grupo) == 2


def test_descomponer_vector_devuelve_cuatro_piezas():
    grupo = descomponer_vector((0, 0, 0), (3, 2, 0))
    assert isinstance(grupo, VGroup)
    assert len(grupo) == 4
    componente_x, componente_y = grupo[0], grupo[1]
    assert np.allclose(componente_x.get_end(), np.array([3.0, 0.0, 0.0]), atol=1e-6)
    assert np.allclose(componente_y.get_end(), np.array([0.0, 2.0, 0.0]), atol=1e-6)


@pytest.mark.render
def test_todas_las_funciones_construyen_en_render_borrador():
    """Humo: cada funcion del modulo construye sin lanzar, en calidad borrador."""
    from manim import tempconfig

    with tempconfig({"quality": "low_quality", "dry_run": True}):
        plano = PlanoShort()
        ejes = EjesShort()
        tracker = ValueTracker(1.0)
        grafica = curva(ejes, lambda x: x**2)
        punto = punto_sobre_curva(ejes, lambda x: x**2, tracker)
        tangente = recta_tangente(ejes, lambda x: x**2, tracker)
        area = area_bajo_curva(ejes, lambda x: x**2, 0, 2)
        etiqueta = etiqueta_valor(tracker)
        curva_t = trayectoria(ejes, lambda t: t, lambda t: t, 1.0)
        vec = vector((0, 0, 0), (1, 1, 0), etiqueta="v")
        descomp = descomponer_vector((0, 0, 0), (2, 1, 0))

        assert plano is not None and ejes is not None
        assert grafica is not None and punto is not None and tangente is not None
        assert area is not None and etiqueta is not None
        assert curva_t is not None and vec is not None and descomp is not None
