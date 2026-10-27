"""Implementación de los modificadores comunes (``entrada``, ``salida``, ``escalonado``) para las piezas.

Las especificaciones (``Param``) viven en ``toolkit.guion.registro.MODIFICADORES``; aquí está el comportamiento
que comparten los verbos. ``rate`` lo aplica el runtime; ``escala``, ``caja`` y ``tachar`` los interpreta cada
pieza que los declare.
"""

from __future__ import annotations

import re
from typing import Callable

import numpy as np
from manim import (
    DL,
    DOWN,
    LEFT,
    RIGHT,
    UP,
    UR,
    Animation,
    Create,
    FadeIn,
    FadeOut,
    GrowFromCenter,
    GrowFromEdge,
    LaggedStart,
    Line,
    Mobject,
    Succession,
    VGroup,
    Write,
)

from toolkit.animaciones import aparecer, caja_resultado
from toolkit.estilos import GROSOR_LINEA_MEDIA

DESPLAZAMIENTO = 0.4  # unidades que se desplaza una entrada/salida direccional
ESCALA_ENCOGER = 0.3
DIRECCIONES_ENTRADA = {"desde_arriba": DOWN, "desde_abajo": UP, "desde_izquierda": RIGHT, "desde_derecha": LEFT}
DIRECCIONES_SALIDA = {"arriba": UP, "abajo": DOWN, "izquierda": LEFT, "derecha": RIGHT}


def _entrada_simple(entrada: str) -> Callable[[Mobject], Animation]:
    if entrada in DIRECCIONES_ENTRADA:
        direccion = np.asarray(DIRECCIONES_ENTRADA[entrada])
        return lambda m: FadeIn(m, shift=direccion * DESPLAZAMIENTO)
    return {
        "auto": aparecer,
        "desvanecer": FadeIn,
        "escribir": Write,
        "crear": Create,
        "crecer": GrowFromCenter,
        "crecer_izq": lambda m: GrowFromEdge(m, LEFT),
    }[entrada]


def es_conjunto(mob: Mobject) -> bool:
    """True para agrupaciones "de verdad" (VGroup de varias piezas), no para un Text (sus letras)."""
    return type(mob) is VGroup and len(mob.submobjects) > 1


def animacion_entrada(mob: Mobject, entrada: str = "auto", escalonado: float = 0.0) -> Animation:
    """Entrada de ``mob`` según ``entrada``; con ``escalonado`` > 0 y un conjunto, un ``LaggedStart`` por miembro."""
    crear = _entrada_simple(entrada)
    if escalonado > 0 and es_conjunto(mob):
        return LaggedStart(*[crear(m) for m in mob.submobjects], lag_ratio=escalonado)
    return crear(mob)


def animacion_salida(mobs: list[Mobject], salida: str = "desvanecer", escalonado: float = 0.0) -> Animation:
    """Salida de ``mobs`` según ``salida``; con ``escalonado`` > 0, uno tras otro."""

    def crear(m: Mobject) -> Animation:
        if salida in DIRECCIONES_SALIDA:
            return FadeOut(m, shift=np.asarray(DIRECCIONES_SALIDA[salida]) * DESPLAZAMIENTO)
        if salida == "encoger":
            return FadeOut(m, scale=ESCALA_ENCOGER)
        return FadeOut(m)

    if escalonado > 0 and len(mobs) > 1:
        return LaggedStart(*[crear(m) for m in mobs], lag_ratio=escalonado)
    if len(mobs) == 1:
        return crear(mobs[0])
    return LaggedStart(*[crear(m) for m in mobs], lag_ratio=0.0)


def escalonar(animaciones: list[Animation], escalonado: float) -> Animation | list[Animation]:
    """``LaggedStart`` si ``escalonado`` > 0 y hay varias animaciones; si no, la lista tal cual."""
    if escalonado > 0 and len(animaciones) > 1:
        return LaggedStart(*animaciones, lag_ratio=escalonado)
    return animaciones


# --- Marcas persistentes: ``caja`` y ``tachar`` ---------------------------------------------------------------
#
# Una pieza que declara ``modificadores=("caja", "tachar")`` las cablea con tres llamadas: ``ciclo_marcas`` en su
# gancho de ciclo (declara los ids nuevos) y ``con_marcas`` al construir (agrega la marca DESPUÉS de su animación).
# La marca es un objeto más (``<id>_caja``, ``<id>_tachado``): se quita con ``quitar`` como cualquier otro.

SUFIJOS_MARCAS = {"caja": "caja", "tachar": "tachado"}
DURACION_TACHADO = 0.4


def id_derivado(id_base: str, parte: str | None, sufijo: str) -> str:
    """Id de la marca de ``id_base`` (o de una de sus partes): ``eq0_caja``, ``eq0_16_tachado``."""
    if parte:
        limpia = re.sub(r"[^a-z0-9_]", "_", str(parte).lower())
        return f"{id_base}_{limpia}_{sufijo}"
    return f"{id_base}_{sufijo}"


def es_marca_de(id: str, id_base: str) -> bool:
    """True si ``id`` es un id de caja/tachado derivado de ``id_base`` (con o sin parte)."""
    return re.fullmatch(rf"{re.escape(id_base)}(_[a-z0-9_]+)?_(caja|tachado)", id) is not None


def ciclo_marcas(params: dict, estado, id_base: str, parte: str | None = None) -> None:
    """Gancho de validación: declara los ids ``<id>_caja`` / ``<id>_tachado`` que crean ``caja`` y ``tachar``."""
    for modificador, sufijo in SUFIJOS_MARCAS.items():
        if params.get(modificador):
            nuevo = id_derivado(id_base, parte, sufijo)
            if estado.crear(nuevo, sufijo):
                estado.usos[nuevo] = 1  # es un adorno: no debe avisar A4 si no se usa después


def con_marcas(ctx, animacion: Animation | None, id_base: str, parte: str | None, mob: Mobject,
               caja: bool = False, tachar: bool = False) -> Animation | None:
    """``animacion`` seguida de la caja de resultado y/o el tachado sobre ``mob`` (los registra como objetos).

    La duración total la escala el runtime (``dur``); sin marcas devuelve ``animacion`` intacta.
    """
    extras: list[Animation] = []
    if caja:
        rect, crear = caja_resultado(mob, color=ctx.color("amarillo"))
        ctx.registrar(id_derivado(id_base, parte, "caja"), rect)
        extras.append(crear)
    if tachar:
        linea = Line(mob.get_corner(DL), mob.get_corner(UR), color=ctx.color("rojo"), stroke_width=GROSOR_LINEA_MEDIA)
        ctx.registrar(id_derivado(id_base, parte, "tachado"), linea)
        extras.append(Create(linea, run_time=DURACION_TACHADO))
    if not extras:
        return animacion
    return Succession(*([animacion] if animacion is not None else []), *extras)


def miembros_de_ola(ctx, mob: Mobject) -> list[Mobject]:
    """Las partes sobre las que corre una ``ola``: partes nombradas de la pieza, o sus submobjects."""
    from toolkit.guion.contexto import ATRIBUTO_PARTES

    partes = getattr(mob, ATRIBUTO_PARTES, None)
    if isinstance(partes, dict) and partes:
        unicas: list[Mobject] = []
        for m in partes.values():
            if m is not mob and not any(m is u for u in unicas):
                unicas.append(m)
        if len(unicas) > 1:
            return unicas
    return list(mob.submobjects) if len(mob.submobjects) > 1 else [mob]
