"""Grafos: redes neuronales estilizadas y utilidades de recorrido (BFS/DFS).

Construccion visual (colores, radios, grosores) vive aqui; el calculo puro de
topologia (ids_por_capa, recorrido_bfs, recorrido_dfs) no depende de manim.
"""

from __future__ import annotations

from collections import deque
from typing import Hashable, Sequence

from manim import (
    Animation,
    AnimationGroup,
    Graph,
    Indicate,
    LaggedStart,
    Line,
    ShowPassingFlash,
)

from .estilos import AMARILLO, AZUL, BLANCO, COLORES_MARCA
from .layout import Zona, encajar as encajar_en_zona

ArquitecturaRed = Sequence[int]
Arista = tuple[Hashable, Hashable]


def ids_por_capa(arquitectura: ArquitecturaRed) -> list[list[int]]:
    """Ids consecutivos de cada capa (puro, orden determinista por id)."""
    capas: list[list[int]] = []
    id_actual = 0
    for num_neuronas in arquitectura:
        capas.append(list(range(id_actual, id_actual + num_neuronas)))
        id_actual += num_neuronas
    return capas


def crear_red_neuronal(
    arquitectura: ArquitecturaRed = (3, 5, 5, 2),
    espaciado_capas: float = 2.0,
    espaciado_nodos: float = 1.0,
    orientacion: str = "vertical",
    encajar_en: Zona | None = None,
) -> Graph:
    """Construye una red neuronal densa (fully connected) como ``Graph``.

    ``orientacion="vertical"`` (por defecto) ordena las capas de arriba a
    abajo calculando las posiciones directamente (sin rotar). ``"horizontal"``
    conserva el comportamiento legado (capas de izquierda a derecha).
    Si ``encajar_en`` recibe una ``Zona``, el grafo se escala automaticamente
    (solo hacia abajo) para caber en ella.
    """
    capas = ids_por_capa(arquitectura)
    num_capas = len(arquitectura)
    posiciones: dict[int, list[float]] = {}

    if orientacion == "vertical":
        offset_y = ((num_capas - 1) * espaciado_capas) / 2
        for indice_capa, ids_capa in enumerate(capas):
            y = offset_y - indice_capa * espaciado_capas
            offset_x = ((len(ids_capa) - 1) * espaciado_nodos) / 2
            for indice_nodo, id_nodo in enumerate(ids_capa):
                posiciones[id_nodo] = [-offset_x + indice_nodo * espaciado_nodos, y, 0.0]
    else:
        offset_x = -((num_capas - 1) * espaciado_capas) / 2
        for indice_capa, ids_capa in enumerate(capas):
            offset_y = ((len(ids_capa) - 1) * espaciado_nodos) / 2
            for indice_nodo, id_nodo in enumerate(ids_capa):
                posiciones[id_nodo] = [
                    offset_x + indice_capa * espaciado_capas,
                    offset_y - indice_nodo * espaciado_nodos,
                    0.0,
                ]

    vertices = [id_nodo for ids_capa in capas for id_nodo in ids_capa]
    aristas: list[Arista] = [
        (origen, destino)
        for ids_capa_actual, ids_capa_siguiente in zip(capas, capas[1:])
        for origen in ids_capa_actual
        for destino in ids_capa_siguiente
    ]

    grafo = Graph(
        vertices,
        aristas,
        layout=posiciones,
        vertex_config={"radius": 0.18, "color": AZUL, "fill_opacity": 0.8},
        edge_config={"stroke_color": BLANCO, "stroke_opacity": 0.25, "stroke_width": 1.5},
    )

    if encajar_en is not None:
        encajar_en_zona(grafo, zona=encajar_en)

    return grafo


def pulso_de_activacion(
    grafo: Graph,
    desde_nodo: Hashable,
    hasta_nodo: Hashable,
    color_pulso: str = COLORES_MARCA["RESALTE"],
    tiempo: float = 1.0,
) -> Animation:
    """Destello que viaja por la arista de ``desde_nodo`` a ``hasta_nodo``.

    Si la arista esta almacenada en el grafo con el orden invertido, se
    intercambian los extremos de la linea para que el pulso siga viajando
    de ``desde_nodo`` hacia ``hasta_nodo``. Lanza ``KeyError`` si la arista
    no existe en ninguno de los dos ordenes.
    """
    if (desde_nodo, hasta_nodo) in grafo.edges:
        arista = grafo.edges[(desde_nodo, hasta_nodo)]
        inicio, fin = arista.get_start(), arista.get_end()
    elif (hasta_nodo, desde_nodo) in grafo.edges:
        arista = grafo.edges[(hasta_nodo, desde_nodo)]
        inicio, fin = arista.get_end(), arista.get_start()
    else:
        raise KeyError(
            f"No existe arista entre {desde_nodo!r} y {hasta_nodo!r} en el grafo."
        )

    pulso = Line(inicio, fin, color=color_pulso, stroke_width=4)
    return ShowPassingFlash(pulso, time_width=0.5, run_time=tiempo)


def propagacion_hacia_adelante(
    grafo: Graph, arquitectura: ArquitecturaRed, color: str = COLORES_MARCA["RESALTE"]
) -> Animation:
    """Propagacion completa: LaggedStart por capas de pulsos en todas las
    aristas de cada capa (lag 0.3)."""
    capas = ids_por_capa(arquitectura)
    grupos_por_capa = [
        AnimationGroup(
            *[
                pulso_de_activacion(grafo, origen, destino, color_pulso=color)
                for origen in ids_capa_actual
                for destino in ids_capa_siguiente
            ]
        )
        for ids_capa_actual, ids_capa_siguiente in zip(capas, capas[1:])
    ]
    return LaggedStart(*grupos_por_capa, lag_ratio=0.3)


def crear_grafo(
    vertices: Sequence[Hashable],
    aristas: Sequence[Arista],
    layout: str | dict = "spring",
    semilla: int = 1,
) -> Graph:
    """Construye un ``Graph`` generico con el estilo visual del toolkit.

    ``layout`` acepta ``"spring"``, ``"circular"`` (nombres reconocidos por
    manim) o un diccionario explicito de posiciones. ``semilla`` fija el
    layout ``"spring"`` (no determinista por defecto en networkx).
    """
    layout_config = {"seed": semilla} if layout == "spring" else None
    return Graph(
        vertices,
        aristas,
        layout=layout,
        layout_config=layout_config,
        vertex_config={"radius": 0.18, "color": AZUL, "fill_opacity": 0.8},
        edge_config={"stroke_color": BLANCO, "stroke_opacity": 0.25, "stroke_width": 1.5},
    )


def _construir_adyacencia(aristas: Sequence[Arista]) -> dict[Hashable, list[Hashable]]:
    adyacencia: dict[Hashable, list[Hashable]] = {}
    for origen, destino in aristas:
        adyacencia.setdefault(origen, []).append(destino)
        adyacencia.setdefault(destino, []).append(origen)
    for nodo, vecinos in adyacencia.items():
        adyacencia[nodo] = sorted(set(vecinos))
    return adyacencia


def recorrido_bfs(aristas: Sequence[Arista], inicio: Hashable) -> list[Hashable]:
    """Orden de visita BFS (puro, determinista: vecinos ordenados por id)."""
    adyacencia = _construir_adyacencia(aristas)
    visitados = {inicio}
    orden = [inicio]
    cola: deque[Hashable] = deque([inicio])
    while cola:
        actual = cola.popleft()
        for vecino in adyacencia.get(actual, []):
            if vecino not in visitados:
                visitados.add(vecino)
                orden.append(vecino)
                cola.append(vecino)
    return orden


def recorrido_dfs(aristas: Sequence[Arista], inicio: Hashable) -> list[Hashable]:
    """Orden de visita DFS (puro, determinista: vecinos ordenados por id)."""
    adyacencia = _construir_adyacencia(aristas)
    visitados: set[Hashable] = set()
    orden: list[Hashable] = []

    def _visitar(nodo: Hashable) -> None:
        visitados.add(nodo)
        orden.append(nodo)
        for vecino in adyacencia.get(nodo, []):
            if vecino not in visitados:
                _visitar(vecino)

    _visitar(inicio)
    return orden


def animar_recorrido(grafo: Graph, orden: Sequence[Hashable], color: str = AMARILLO) -> Animation:
    """Resalta los vertices de ``orden`` en secuencia; anima tambien la
    arista entre nodos consecutivos cuando existe en ``grafo``."""
    animaciones: list[Animation] = []
    for indice, nodo in enumerate(orden):
        animaciones.append(Indicate(grafo.vertices[nodo], color=color))
        if indice + 1 < len(orden):
            actual, siguiente = nodo, orden[indice + 1]
            if (actual, siguiente) in grafo.edges or (siguiente, actual) in grafo.edges:
                animaciones.append(
                    pulso_de_activacion(grafo, actual, siguiente, color_pulso=color, tiempo=0.5)
                )
    return LaggedStart(*animaciones, lag_ratio=0.3)
