"""Tests de toolkit/utils_grafos.py: red neuronal, pulsos y recorridos BFS/DFS."""

import numpy as np
import pytest

from toolkit.layout import ZONA_PRINCIPAL
from toolkit.utils_grafos import (
    animar_recorrido,
    crear_grafo,
    crear_red_neuronal,
    ids_por_capa,
    propagacion_hacia_adelante,
    pulso_de_activacion,
    recorrido_bfs,
    recorrido_dfs,
)


def test_ids_por_capa():
    assert ids_por_capa((2, 3)) == [[0, 1], [2, 3, 4]]
    assert ids_por_capa((3, 5, 5, 2)) == [
        [0, 1, 2],
        [3, 4, 5, 6, 7],
        [8, 9, 10, 11, 12],
        [13, 14],
    ]


def test_ids_por_capa_arquitectura_vacia_capa():
    assert ids_por_capa((1,)) == [[0]]


def _aristas_grafo_conocido():
    # 0 - 1 - 3
    # |       |
    # 2 ------+
    return [(0, 1), (0, 2), (1, 3), (2, 3)]


def test_recorrido_bfs_grafo_conocido():
    assert recorrido_bfs(_aristas_grafo_conocido(), 0) == [0, 1, 2, 3]


def test_recorrido_dfs_grafo_conocido():
    assert recorrido_dfs(_aristas_grafo_conocido(), 0) == [0, 1, 3, 2]


def test_recorrido_bfs_determinista_con_orden_de_aristas_distinto():
    aristas_reordenadas = [(2, 3), (1, 3), (0, 2), (0, 1)]
    assert recorrido_bfs(aristas_reordenadas, 0) == [0, 1, 2, 3]


def test_crear_red_neuronal_orientacion_vertical_no_rota():
    red = crear_red_neuronal(arquitectura=(2, 2), espaciado_capas=2.0, espaciado_nodos=1.0)
    # Capa 0 (ids 0,1) por encima de la capa 1 (ids 2,3): mismo y por nodo.
    y_capa_0 = red.vertices[0].get_center()[1]
    y_capa_1 = red.vertices[2].get_center()[1]
    assert y_capa_0 > y_capa_1
    assert np.isclose(red.vertices[0].get_center()[1], red.vertices[1].get_center()[1])


def test_crear_red_neuronal_firma_compatible_con_llamadas_legado():
    # Llamada tal como aparece en ejemplos/legado/test_hito5.py
    red = crear_red_neuronal(arquitectura=[3, 6, 6, 2], espaciado_capas=2.5)
    assert len(red.vertices) == 3 + 6 + 6 + 2
    animacion = pulso_de_activacion(red, 0, 3, tiempo=0.8)
    assert animacion is not None


def test_crear_red_neuronal_encaja_en_zona_principal_red_grande():
    red = crear_red_neuronal(arquitectura=(4, 8, 8, 4), encajar_en=ZONA_PRINCIPAL)
    assert ZONA_PRINCIPAL.contiene(red)


def test_pulso_de_activacion_arista_directa_termina_en_hasta():
    red = crear_red_neuronal(arquitectura=(2, 2))
    posicion_destino = red.vertices[2].get_center()
    pulso = pulso_de_activacion(red, 0, 2)
    linea = pulso.mobject
    assert np.allclose(linea.get_end(), posicion_destino, atol=1e-6)


def test_pulso_de_activacion_arista_invertida_termina_en_hasta():
    red = crear_red_neuronal(arquitectura=(2, 2))
    # La arista se almacena como (0, 2); pedimos el pulso en sentido opuesto.
    posicion_destino = red.vertices[0].get_center()
    pulso = pulso_de_activacion(red, 2, 0)
    linea = pulso.mobject
    assert np.allclose(linea.get_end(), posicion_destino, atol=1e-6)


def test_pulso_de_activacion_arista_inexistente_lanza_keyerror():
    red = crear_red_neuronal(arquitectura=(2, 2))
    with pytest.raises(KeyError):
        pulso_de_activacion(red, 0, 1)


def test_propagacion_hacia_adelante_construye_animacion():
    red = crear_red_neuronal(arquitectura=(2, 2))
    animacion = propagacion_hacia_adelante(red, (2, 2))
    assert animacion is not None


def test_crear_grafo_layout_dict_explicito():
    posiciones = {0: [0.0, 0.0, 0.0], 1: [1.0, 0.0, 0.0]}
    grafo = crear_grafo([0, 1], [(0, 1)], layout=posiciones)
    assert np.allclose(grafo.vertices[1].get_center(), [1.0, 0.0, 0.0])


def test_crear_grafo_layout_spring_determinista_con_semilla():
    vertices = [0, 1, 2, 3]
    aristas = [(0, 1), (1, 2), (2, 3), (3, 0)]
    grafo_a = crear_grafo(vertices, aristas, layout="spring", semilla=7)
    grafo_b = crear_grafo(vertices, aristas, layout="spring", semilla=7)
    for v in vertices:
        assert np.allclose(
            grafo_a.vertices[v].get_center(), grafo_b.vertices[v].get_center()
        )


def test_animar_recorrido_construye_animacion():
    red = crear_red_neuronal(arquitectura=(2, 2))
    orden = recorrido_bfs([(0, 2), (0, 3), (1, 2), (1, 3)], 0)
    animacion = animar_recorrido(red, orden)
    assert animacion is not None
