"""Tests puros de toolkit/motor_fisica.py (tiro parabólico)."""

import math

import pytest

from toolkit.motor_fisica import (
    G_TIERRA,
    alcance,
    altura_maxima,
    angulo_alcance_maximo,
    componentes_velocidad,
    posicion,
    posicion_con_arrastre,
    tiempo_cima,
    tiempo_vuelo,
    tiempo_vuelo_con_arrastre,
    velocidad,
)

V, G = 10.0, 9.8


def test_g_tierra():
    assert G_TIERRA == pytest.approx(9.8)


def test_componentes_velocidad_45():
    vx, vy = componentes_velocidad(V, 45)
    assert vx == pytest.approx(7.0711, abs=1e-4)
    assert vy == pytest.approx(vx)


def test_componentes_velocidad_30_60_intercambiadas():
    vx30, vy30 = componentes_velocidad(V, 30)
    vx60, vy60 = componentes_velocidad(V, 60)
    assert (vx30, vy30) == pytest.approx((vy60, vx60))
    assert (vx30, vy30) == pytest.approx((8.6603, 5.0), abs=1e-4)


@pytest.mark.parametrize(
    "grados,t_vuelo,h_max,r",
    [(15, 0.528, 0.342, 5.102), (30, 1.020, 1.276, 8.837), (45, 1.443, 2.551, 10.204),
     (60, 1.767, 3.827, 8.837), (75, 1.971, 4.760, 5.102)],
)
def test_tabla_del_guion(grados, t_vuelo, h_max, r):
    assert tiempo_vuelo(V, grados, G) == pytest.approx(t_vuelo, abs=1e-3)
    assert altura_maxima(V, grados, G) == pytest.approx(h_max, abs=1e-3)
    assert alcance(V, grados, G) == pytest.approx(r, abs=1e-3)


def test_alcance_es_vx_por_tiempo_de_vuelo():
    for grados in (10, 25, 45, 70):
        vx, _ = componentes_velocidad(V, grados)
        assert alcance(V, grados, G) == pytest.approx(vx * tiempo_vuelo(V, grados, G))


def test_posicion_inicial_cima_y_aterrizaje():
    assert posicion(V, 60, 0.0, G) == pytest.approx((0.0, 0.0))
    x, y = posicion(V, 60, tiempo_cima(V, 60, G), G)
    assert y == pytest.approx(altura_maxima(V, 60, G))
    x, y = posicion(V, 60, tiempo_vuelo(V, 60, G), G)
    assert (x, y) == pytest.approx((alcance(V, 60, G), 0.0), abs=1e-9)


def test_tiempo_cima_es_mitad_del_vuelo():
    assert tiempo_cima(V, 45, G) == pytest.approx(0.7215, abs=1e-4)
    assert tiempo_cima(V, 45, G) * 2 == pytest.approx(tiempo_vuelo(V, 45, G))


def test_velocidad_vx_constante_vy_lineal():
    vx0, vy0 = componentes_velocidad(V, 60)
    assert velocidad(V, 60, 0.0, G) == pytest.approx((vx0, vy0))
    vx, vy = velocidad(V, 60, tiempo_cima(V, 60, G), G)
    assert vx == pytest.approx(vx0)
    assert vy == pytest.approx(0.0, abs=1e-12)
    vx, vy = velocidad(V, 60, tiempo_vuelo(V, 60, G), G)
    assert (vx, vy) == pytest.approx((vx0, -vy0))


def test_angulo_alcance_maximo():
    assert angulo_alcance_maximo() == pytest.approx(45.0)
    assert alcance(V, 45, G) == pytest.approx(V**2 / G)
    assert all(alcance(V, d, G) < alcance(V, 45, G) for d in (44, 46, 30, 60))


def test_arrastre_cero_coincide_con_vacio():
    t = 0.8
    assert posicion_con_arrastre(V, 45, t, 0.0, G) == pytest.approx(posicion(V, 45, t, G))
    assert tiempo_vuelo_con_arrastre(V, 45, 0.0, G) == pytest.approx(tiempo_vuelo(V, 45, G))


def test_arrastre_acorta_y_aterriza_en_cero():
    k = 0.4
    t_v = tiempo_vuelo_con_arrastre(V, 45, k, G)
    x, y = posicion_con_arrastre(V, 45, t_v, k, G)
    assert y == pytest.approx(0.0, abs=1e-6)
    assert 0 < x < alcance(V, 45, G)
    assert t_v < tiempo_vuelo(V, 45, G)


def test_valida_parametros():
    with pytest.raises(ValueError):
        alcance(-1.0, 45, G)
    with pytest.raises(ValueError):
        tiempo_vuelo(V, 45, 0.0)
    with pytest.raises(ValueError):
        posicion_con_arrastre(V, 45, 1.0, -0.1, G)
    assert math.isfinite(alcance(0.0, 45, G))
