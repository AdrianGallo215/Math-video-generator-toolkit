"""Tests de algoritmos_visual: funciones puras de pasos y componentes visuales."""

import pytest

from toolkit.algoritmos_visual import pasos_burbuja, pasos_busqueda_binaria


# ---------------------------------------------------------------------------
# Funciones puras
# ---------------------------------------------------------------------------


def test_busqueda_binaria_encuentra_objetivo_en_pocos_pasos():
    valores = list(range(1, 17))
    pasos = pasos_busqueda_binaria(valores, 11)
    assert len(pasos) <= 5
    assert pasos[-1]["comparacion"] == "=="
    assert pasos[-1]["mid"] == valores.index(11)


def test_busqueda_binaria_pasos_coherentes():
    valores = [3, 8, 12, 17, 21, 25, 30, 34, 41, 47, 52, 58, 63, 70, 77, 85]
    pasos = pasos_busqueda_binaria(valores, 58)
    for paso in pasos:
        assert paso["lo"] <= paso["mid"] <= paso["hi"]
        assert paso["mid"] == (paso["lo"] + paso["hi"]) // 2
        valor_mid = valores[paso["mid"]]
        esperado = "<" if valor_mid < 58 else (">" if valor_mid > 58 else "==")
        assert paso["comparacion"] == esperado
    assert valores[pasos[-1]["mid"]] == 58


def test_busqueda_binaria_objetivo_ausente_termina_con_lo_mayor_que_hi():
    pasos = pasos_busqueda_binaria(list(range(1, 17)), 100)
    assert pasos[-1]["lo"] > pasos[-1]["hi"]
    assert pasos[-1]["mid"] is None
    assert all(p["comparacion"] != "==" for p in pasos)


def test_busqueda_binaria_ausente_intermedio():
    pasos = pasos_busqueda_binaria([2, 4, 6, 8], 5)
    assert pasos[-1]["lo"] > pasos[-1]["hi"]


def test_busqueda_binaria_arreglo_vacio():
    pasos = pasos_busqueda_binaria([], 3)
    assert len(pasos) == 1
    assert pasos[0]["lo"] > pasos[0]["hi"]


def test_busqueda_binaria_rechaza_desordenado():
    with pytest.raises(ValueError):
        pasos_busqueda_binaria([3, 1, 2], 2)


def _aplicar_pasos(valores, pasos):
    lista = list(valores)
    for accion, i, j in pasos:
        if accion == "intercambiar":
            lista[i], lista[j] = lista[j], lista[i]
    return lista


@pytest.mark.parametrize(
    "valores",
    [
        [5, 1, 4, 2, 8],
        [1, 3, 2, 4, 6, 5, 8, 7],
        [9, 8, 7, 6, 5, 4, 3, 2, 1],
        [1, 2, 3],
        [],
        [4],
        [2, 2, 1, 1],
    ],
)
def test_burbuja_aplicar_intercambios_ordena(valores):
    pasos = pasos_burbuja(valores)
    assert _aplicar_pasos(valores, pasos) == sorted(valores)


def test_burbuja_formato_y_comparar_antes_de_intercambiar():
    pasos = pasos_burbuja([3, 1, 2])
    assert pasos[0] == ("comparar", 0, 1)
    assert pasos[1] == ("intercambiar", 0, 1)
    for indice, (accion, i, j) in enumerate(pasos):
        assert accion in ("comparar", "intercambiar")
        assert j == i + 1
        if accion == "intercambiar":
            assert pasos[indice - 1] == ("comparar", i, j)


def test_burbuja_no_muta_entrada():
    valores = [3, 2, 1]
    pasos_burbuja(valores)
    assert valores == [3, 2, 1]


def test_burbuja_cuenta_tres_intercambios_en_demo():
    pasos = pasos_burbuja([1, 3, 2, 4, 6, 5, 8, 7])
    assert sum(1 for p in pasos if p[0] == "intercambiar") == 3


# ---------------------------------------------------------------------------
# Render (construyen mobjects / Scene en calidad borrador sin escribir MP4)
# ---------------------------------------------------------------------------


def _config_prueba():
    from toolkit.configuracion import FRAME_HEIGHT, FRAME_WIDTH

    return {
        "quality": "low_quality",
        "dry_run": True,
        "frame_width": FRAME_WIDTH,
        "frame_height": FRAME_HEIGHT,
        "pixel_width": 540,
        "pixel_height": 960,
    }


def _reproducir(*animaciones_o_fabricas):
    """Construye y 'renderiza' (dry_run) una Scene que reproduce las animaciones."""
    from manim import Animation, Scene, tempconfig

    class _EscenaPrueba(Scene):
        def construct(self):
            for fabrica in animaciones_o_fabricas:
                resultado = fabrica(self)
                if isinstance(resultado, Animation):
                    self.play(resultado)

    with tempconfig(_config_prueba()):
        escena = _EscenaPrueba()
        escena.render()
    return escena


@pytest.mark.render
def test_arreglo_de_16_cabe_en_zona_principal():
    from toolkit.algoritmos_visual import ArregloVisual
    from toolkit.layout import ZONA_PRINCIPAL

    arreglo = ArregloVisual(range(16))
    arreglo.move_to(ZONA_PRINCIPAL.centro)
    assert ZONA_PRINCIPAL.contiene(arreglo)
    assert len(arreglo.celdas) == 16
    assert arreglo.valores == list(range(16))


@pytest.mark.render
def test_arreglo_legibilidad_value_error_si_se_fuerza_una_fila():
    from toolkit.algoritmos_visual import ArregloVisual

    with pytest.raises(ValueError):
        ArregloVisual(range(16), filas=1)


@pytest.mark.render
def test_arreglo_de_8_en_una_fila():
    from toolkit.algoritmos_visual import ArregloVisual

    arreglo = ArregloVisual([5, 1, 4, 2, 8, 7, 3, 6])
    ys = {round(c.get_y(), 3) for c in arreglo.celdas}
    assert len(ys) == 1
    assert arreglo.width <= 6.0 + 1e-6


@pytest.mark.render
def test_intercambiar_intercambia_valores_internos_y_posiciones():
    from toolkit.algoritmos_visual import ArregloVisual

    arreglo = ArregloVisual([5, 1, 4, 2])
    celda_0, celda_3 = arreglo.celda(0), arreglo.celda(3)
    x0, x3 = celda_0.get_x(), celda_3.get_x()

    _reproducir(lambda escena: escena.add(arreglo), lambda escena: arreglo.intercambiar(0, 3))

    assert arreglo.valores == [2, 1, 4, 5]
    assert arreglo.celda(0) is celda_3
    assert arreglo.celda(3) is celda_0
    assert arreglo.celda(0).get_x() == pytest.approx(x0, abs=1e-6)
    assert arreglo.celda(3).get_x() == pytest.approx(x3, abs=1e-6)


@pytest.mark.render
def test_animaciones_del_arreglo_construyen_y_reproducen():
    from toolkit.algoritmos_visual import ArregloVisual
    from toolkit.estilos import VERDE

    arreglo = ArregloVisual([3, 8, 12, 17, 21, 25, 30, 34])
    ancho_celda_2 = arreglo.celda(2).width
    centro_celda_2 = arreglo.celda(2).get_center()
    _reproducir(
        lambda escena: escena.add(arreglo),
        lambda escena: arreglo.comparar(0, 1),
        lambda escena: arreglo.resaltar_celda(2),
        lambda escena: arreglo.colorear([4, 5], VERDE),
        lambda escena: arreglo.atenuar_rango(0, 3),
    )
    assert arreglo.celda(0).valor[0].get_fill_opacity() < 0.5
    assert arreglo.celda(0).caja.get_stroke_opacity() < 0.5
    # resaltar_celda: pulso sin acumular escala; queda el borde grueso.
    assert arreglo.celda(2).width == pytest.approx(ancho_celda_2, rel=0.05)
    assert arreglo.celda(2).get_center() == pytest.approx(centro_celda_2, abs=1e-3)
    assert arreglo.celda(2).caja.get_stroke_width() >= 8


@pytest.mark.render
def test_puntero_apuntar_a_queda_encima_de_la_celda():
    from manim import UP

    from toolkit.algoritmos_visual import ArregloVisual, Puntero

    arreglo = ArregloVisual([3, 8, 12, 17, 21, 25, 30, 34])
    puntero = Puntero("mid", direccion=UP).colocar_en(arreglo.celda(0))
    objetivo = arreglo.celda(5)

    _reproducir(
        lambda escena: escena.add(arreglo, puntero),
        lambda escena: puntero.apuntar_a(objetivo),
    )

    assert puntero.get_bottom()[1] >= objetivo.get_top()[1] - 1e-6
    assert puntero.get_bottom()[1] - objetivo.get_top()[1] < 0.5
    assert puntero.flecha.get_x() == pytest.approx(objetivo.get_x(), abs=1e-3)


@pytest.mark.render
def test_codigo_resaltado_construye_con_seis_lineas():
    from toolkit.algoritmos_visual import CodigoResaltado

    codigo = CodigoResaltado(
        "def buscar(a, x):\n"
        "    lo, hi = 0, len(a)-1\n"
        "    while lo <= hi:\n"
        "        m = (lo+hi)//2\n"
        "        ...\n"
        "    return -1\n"
    )
    assert codigo.n_lineas == 6
    assert codigo.width > 0

    _reproducir(
        lambda escena: escena.add(codigo),
        lambda escena: codigo.resaltar_linea(1),
        lambda escena: codigo.resaltar_linea(4),
    )
    assert codigo.linea_activa == 4
    assert codigo.resaltado.get_y() == pytest.approx(codigo.y_linea(4), abs=1e-3)


@pytest.mark.render
def test_codigo_resaltado_rechaza_linea_fuera_de_rango_y_fuente_chica():
    from toolkit.algoritmos_visual import CodigoResaltado
    from toolkit.estilos import FUENTE_MINIMA

    codigo = CodigoResaltado("a = 1\nb = 2\n")
    with pytest.raises(ValueError):
        codigo.resaltar_linea(3)
    with pytest.raises(ValueError):
        CodigoResaltado("a = 1", tamano=FUENTE_MINIMA - 1)


@pytest.mark.render
def test_pila_visual_push_pop():
    from toolkit.algoritmos_visual import PilaVisual

    pila = PilaVisual()
    _reproducir(
        lambda escena: escena.add(pila),
        lambda escena: pila.push("f(3)"),
        lambda escena: pila.push("f(2)"),
        lambda escena: pila.pop(),
    )
    assert pila.tamano == 1
    assert pila.elementos == ["f(3)"]


@pytest.mark.render
def test_arreglo_16_con_columnas_max_8_en_dos_filas():
    from toolkit.algoritmos_visual import ArregloVisual
    from toolkit.estilos import FUENTE_ETIQUETA, FUENTE_MINIMA
    from toolkit.layout import ZONA_PRINCIPAL
    from toolkit.tipografia import Texto

    arreglo = ArregloVisual(range(16), columnas_max=8)
    arreglo.move_to(ZONA_PRINCIPAL.centro)
    assert ZONA_PRINCIPAL.contiene(arreglo)
    assert arreglo.filas == 2
    # Sin escalado: el valor mide lo que un Texto de tamano_valor (>= FUENTE_MINIMA).
    assert FUENTE_MINIMA <= arreglo.tamano_valor <= FUENTE_ETIQUETA
    referencia = Texto("0", tamano=arreglo.tamano_valor)
    assert arreglo.celda(0).valor.height == pytest.approx(referencia.height, rel=1e-3)
    # Fila 2 debajo de la 1, con los indices de la fila 1 en medio.
    assert arreglo.celda(8).get_x() == pytest.approx(arreglo.celda(0).get_x(), abs=1e-6)
    assert arreglo.celda(8).get_top()[1] < arreglo.indices[0].get_bottom()[1]
    assert arreglo.celda(15).get_y() == pytest.approx(arreglo.celda(8).get_y(), abs=1e-6)


@pytest.mark.render
def test_arreglo_valores_v03_16_celdas_legibles():
    from toolkit.algoritmos_visual import ArregloVisual
    from toolkit.estilos import FUENTE_MINIMA
    from toolkit.layout import ZONA_PRINCIPAL

    valores = [3, 8, 12, 17, 21, 25, 30, 34, 41, 47, 52, 58, 63, 70, 77, 85]
    arreglo = ArregloVisual(valores, columnas_max=8)
    arreglo.move_to(ZONA_PRINCIPAL.centro)
    assert ZONA_PRINCIPAL.contiene(arreglo)
    assert arreglo.tamano_valor >= FUENTE_MINIMA
    anchos = {round(c.width, 6) for c in arreglo.celdas}
    assert len(anchos) == 1


@pytest.mark.render
def test_puntero_apunta_a_celda_de_la_segunda_fila():
    from manim import UP

    from toolkit.algoritmos_visual import ArregloVisual, Puntero

    arreglo = ArregloVisual(range(16), columnas_max=8)
    puntero = Puntero("mid", direccion=UP).colocar_en(arreglo.celda(3))
    objetivo = arreglo.celda(12)
    _reproducir(lambda escena: escena.add(arreglo, puntero), lambda escena: puntero.apuntar_a(objetivo))
    assert puntero.flecha.get_x() == pytest.approx(objetivo.get_x(), abs=1e-3)
    assert puntero.get_bottom()[1] >= objetivo.get_top()[1] - 1e-6


@pytest.mark.render
def test_codigo_resaltado_24_caracteres_cabe_en_ancho_seguro():
    from toolkit.algoritmos_visual import CodigoResaltado

    linea = "if a[mid] < x: lo = mid1"
    assert len(linea) == 24
    codigo = CodigoResaltado("\n".join([linea] * 8))
    assert codigo.n_lineas == 8
    assert codigo.width <= 6.3
