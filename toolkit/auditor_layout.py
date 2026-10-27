"""Auditor automático de layout: detecta contenido fuera de la zona segura, textos solapados,
texto demasiado pequeño e invasión de la zona de subtítulos.

Se activa con la variable de entorno ``SHORT_AUDITAR=1``. ``toolkit.base_scene`` llama a
:func:`auditar_escena` tras cada ``play``/``wait`` de ``PlantillaShort``/``PlantillaShort3D``
(``wait`` delega en ``play``) y, al terminar la escena (``tear_down``), vuelca lo encontrado con
:func:`escribir_reporte`. La auditoría nunca debe romper el render: cualquier excepción se atrapa
y se registra como advertencia en ``toolkit.base_scene``.

Exclusiones deliberadas (no cuentan como "contenido"): la capa HUD (``escena.capa_hud``, que incluye
los subtítulos karaoke) y las guías de depuración (``escena.guias``). Los subtítulos viven en su
propia zona (``ZONA_SUBTITULOS``) y no deben generar ``solapamiento_texto`` con el contenido; en su
lugar, ``invade_subtitulos`` detecta cuando es el CONTENIDO el que invade esa zona mientras hay un
bloque de subtítulos visible.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import numpy as np
from manim import DecimalNumber, Integer, MarkupText, MathTex, Mobject, Tex, Text

from .configuracion import FRAME_HEIGHT, FRAME_WIDTH
from .layout import Zona, ZONA_SEGURA, ZONA_SUBTITULOS

logger = logging.getLogger(__name__)

VARIABLE_ENTORNO_AUDITAR = "SHORT_AUDITAR"

# Mobjects que cuentan como "texto" para fuera_de_zona / solapamiento_texto / texto_pequeno.
CLASES_TEXTO: tuple[type, ...] = (Text, MarkupText, MathTex, Tex, DecimalNumber, Integer)
# Solo estos tienen una altura de fuente directamente comparable en píxeles (MathTex/Tex se
# renderizan vía LaTeX con otra métrica: no se audita su tamaño, solo posición/solapamiento).
CLASES_TEXTO_CON_ALTURA_PX: tuple[type, ...] = (Text, MarkupText)

OPACIDAD_MINIMA = 0.05
TOLERANCIA_ZONA = 0.05
AREA_MINIMA_SOLAPAMIENTO = 0.02
# ≈ FUENTE_MINIMA (36pt) expresado como altura mínima en unidades de referencia (ancho de frame
# = FRAME_WIDTH), equivalente a "0.018 * alto del frame en píxeles" para cualquier perfil de calidad
# (el factor pixeles/unidad es el mismo en x e y una vez fijado el aspect ratio 9:16).
ALTURA_MINIMA_TEXTO = 0.018 * FRAME_HEIGHT
# Por debajo de esta área (unidades^2) una figura NO se considera "grande" a efectos de
# invade_subtitulos (evita que un trazo o icono pequeño dispare el hallazgo).
AREA_MINIMA_FIGURA_GRANDE = 1.0


@dataclass
class Hallazgo:
    """Un problema de layout detectado en un instante de la escena."""

    tiempo: float
    tipo: str  # "fuera_de_zona" | "solapamiento_texto" | "texto_pequeno" | "invade_subtitulos"
    descripcion: str
    objetos: list[str] = field(default_factory=list)


# --- Identificación e inventario de mobjects -------------------------------------------


def _identificar(mob: Mobject) -> str:
    """Etiqueta legible de ``mob`` para el reporte: clase y, si existe, el texto/tex que muestra.

    ``Text.text`` normaliza espacios (los quita); ``original_text`` conserva el texto tal cual se
    pasó al constructor y es más útil para identificar el mobject en el reporte.
    """
    texto = getattr(mob, "original_text", None) or getattr(mob, "text", None) or getattr(mob, "tex_string", None)
    nombre = type(mob).__name__
    if texto:
        recorte = texto if len(texto) <= 30 else texto[:27] + "..."
        return f"{nombre}({recorte!r})"
    return f"{nombre}#{id(mob):x}"


def _opacidad(mob: Mobject) -> float:
    try:
        return float(mob.get_fill_opacity())
    except Exception:
        return 1.0


def _tiene_extension(mob: Mobject) -> bool:
    """False para mobjects vacíos (sin puntos ni hijos): su bbox no es significativo."""
    try:
        return bool(mob.get_num_points()) or bool(mob.submobjects)
    except Exception:
        return False


def _capa_excluida(escena) -> set[int]:
    """ids de mobjects que viven en la capa HUD (incluye subtítulos) o en las guías: no son
    "contenido" a efectos de auditoría."""
    excluidos: set[int] = set()
    capa_hud = getattr(escena, "capa_hud", None)
    if capa_hud is not None:
        excluidos.update(id(m) for m in capa_hud.get_family())
    guias = getattr(escena, "guias", None)
    if guias is not None:
        excluidos.update(id(m) for m in guias.get_family())
    # `camera.frame.animate` mete el rectangulo de la camara en la escena: no es contenido.
    frame = getattr(getattr(escena, "camera", None), "frame", None)
    if frame is not None:
        excluidos.update(id(m) for m in frame.get_family())
    return excluidos


def _mobjects_de_contenido(escena) -> list[Mobject]:
    """Mobjects "del mundo" (fuera de la capa HUD/guías/subtítulos), aplanados (familia completa).

    En escenas 3D (``ThreeDScene``, sin ``camera.frame``) los mobjects del mundo viven en
    coordenadas 3D que no se proyectan de forma trivial a coordenadas de pantalla; auditar su bbox
    como si fuera 2D daría falsos positivos sistemáticos. Simplificación deliberada (ver plan T07):
    en ese caso solo se consideran los mobjects fijos al cuadro (``fixed_in_frame_mobjects``) que no
    formen parte de la capa HUD/guías/subtítulos — en la práctica, con el diseño actual de
    ``PlantillaShort3D`` (todo lo fijado a cámara entra en ``capa_hud``), esto deja el conjunto de
    "contenido 3D auditado" vacío; queda documentado como límite conocido, no como bug.
    """
    excluidos = _capa_excluida(escena)
    frame = getattr(escena.camera, "frame", None)
    if frame is None:
        camara = getattr(getattr(escena, "renderer", None), "camera", None)
        candidatos: list[Mobject] = list(getattr(camara, "fixed_in_frame_mobjects", None) or [])
    else:
        candidatos = list(escena.mobjects)

    vistos: set[int] = set()
    resultado: list[Mobject] = []
    for mob in candidatos:
        for sub in mob.get_family():
            if id(sub) in excluidos or id(sub) in vistos:
                continue
            vistos.add(id(sub))
            resultado.append(sub)
    return resultado


def textos_visibles(escena) -> list[Mobject]:
    """Textos del contenido (excluye capa HUD, guías y subtítulos) con opacidad > 0.05."""
    return [
        m
        for m in _mobjects_de_contenido(escena)
        if isinstance(m, CLASES_TEXTO) and _opacidad(m) > OPACIDAD_MINIMA and _tiene_extension(m)
    ]


# --- Geometría en coordenadas de referencia (cámara) -----------------------------------


def _transformacion_camara(escena) -> tuple[np.ndarray, float]:
    """(centro, factor) para llevar coordenadas de escena a unidades de referencia (ancho=FRAME_WIDTH).

    2D (``MovingCameraScene``): ``(p - frame.center) * (FRAME_WIDTH / frame.width)`` (ver plan T07);
    cancela el zoom/paneo de la cámara móvil. 3D: los mobjects fijos al cuadro ya viven en
    coordenadas de pantalla (sin transformar).
    """
    frame = getattr(escena.camera, "frame", None)
    if frame is not None:
        return frame.get_center(), FRAME_WIDTH / frame.width
    return np.zeros(3), 1.0


def _bbox_referencia(mob: Mobject, centro: np.ndarray, factor: float) -> tuple[float, float, float, float]:
    """(x_min, x_max, y_min, y_max) de ``mob`` en unidades de referencia."""
    izquierda = (mob.get_left()[0] - centro[0]) * factor
    derecha = (mob.get_right()[0] - centro[0]) * factor
    abajo = (mob.get_bottom()[1] - centro[1]) * factor
    arriba = (mob.get_top()[1] - centro[1]) * factor
    return izquierda, derecha, abajo, arriba


def _contiene(zona: Zona, bbox: tuple[float, float, float, float], tolerancia: float = TOLERANCIA_ZONA) -> bool:
    x_min, x_max, y_min, y_max = bbox
    return bool(
        x_min >= zona.x_min - tolerancia
        and x_max <= zona.x_max + tolerancia
        and y_min >= zona.y_min - tolerancia
        and y_max <= zona.y_max + tolerancia
    )


def _area_interseccion(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    a_x0, a_x1, a_y0, a_y1 = a
    b_x0, b_x1, b_y0, b_y1 = b
    ancho = min(a_x1, b_x1) - max(a_x0, b_x0)
    alto = min(a_y1, b_y1) - max(a_y0, b_y0)
    if ancho <= 0 or alto <= 0:
        return 0.0
    return ancho * alto


def _es_familiar(a: Mobject, b: Mobject) -> bool:
    """True si ``a`` es (o contiene a) un submobject del otro: no cuenta como solapamiento."""
    return a in b.get_family() or b in a.get_family()


def _subtitulos_activos(escena) -> bool:
    """True si hay un bloque de subtítulos visible AHORA (no solo programado)."""
    subtitulos = getattr(escena, "subtitulos", None)
    if subtitulos is None or getattr(escena, "_subtitulos_apagados", False):
        return False
    return getattr(subtitulos, "_bloque_mostrado", None) is not None


# --- Auditoría --------------------------------------------------------------------------


def auditar_escena(escena, zona: Zona = ZONA_SEGURA) -> list[Hallazgo]:
    """Audita el estado actual de ``escena`` (un instante, no un rango de tiempo).

    Detecta: contenido fuera de ``zona`` (tolerancia 0.05), pares de textos de contenido que se
    solapan (área > 0.02, ignorando pares padre/hijo), ``Text``/``MarkupText`` con altura estimada
    menor a ``FUENTE_MINIMA``, y contenido (texto o figura grande) que invade ``ZONA_SUBTITULOS``
    mientras hay un bloque de subtítulos visible.
    """
    tiempo = float(getattr(getattr(escena, "renderer", None), "time", 0.0))
    hallazgos: list[Hallazgo] = []

    centro, factor = _transformacion_camara(escena)
    mobs = _mobjects_de_contenido(escena)
    textos = [m for m in mobs if isinstance(m, CLASES_TEXTO) and _opacidad(m) > OPACIDAD_MINIMA and _tiene_extension(m)]
    bboxes = {id(m): _bbox_referencia(m, centro, factor) for m in textos}

    for m in textos:
        bbox = bboxes[id(m)]
        if not _contiene(zona, bbox):
            hallazgos.append(
                Hallazgo(tiempo, "fuera_de_zona", f"{_identificar(m)} fuera de '{zona.nombre}'", [_identificar(m)])
            )

    for i, a in enumerate(textos):
        for b in textos[i + 1 :]:
            if _es_familiar(a, b):
                continue
            area = _area_interseccion(bboxes[id(a)], bboxes[id(b)])
            if area > AREA_MINIMA_SOLAPAMIENTO:
                hallazgos.append(
                    Hallazgo(
                        tiempo,
                        "solapamiento_texto",
                        f"{_identificar(a)} se solapa con {_identificar(b)} (area={area:.3f})",
                        [_identificar(a), _identificar(b)],
                    )
                )

    for m in textos:
        if not isinstance(m, CLASES_TEXTO_CON_ALTURA_PX):
            continue
        _, _, abajo, arriba = bboxes[id(m)]
        altura = arriba - abajo
        if 0.0 < altura < ALTURA_MINIMA_TEXTO:
            hallazgos.append(
                Hallazgo(
                    tiempo,
                    "texto_pequeno",
                    f"{_identificar(m)} altura~{altura:.3f} < minimo {ALTURA_MINIMA_TEXTO:.3f}",
                    [_identificar(m)],
                )
            )

    if _subtitulos_activos(escena):
        zona_subs = (ZONA_SUBTITULOS.x_min, ZONA_SUBTITULOS.x_max, ZONA_SUBTITULOS.y_min, ZONA_SUBTITULOS.y_max)
        for m in mobs:
            if isinstance(m, CLASES_TEXTO):
                bbox = bboxes.get(id(m))
                if bbox is None:  # opacidad baja o sin extension: no cuenta como invasion
                    continue
            else:
                if not _tiene_extension(m):
                    continue
                bbox = _bbox_referencia(m, centro, factor)
                x0, x1, y0, y1 = bbox
                if (x1 - x0) * (y1 - y0) < AREA_MINIMA_FIGURA_GRANDE:
                    continue
            area = _area_interseccion(bbox, zona_subs)
            if area > AREA_MINIMA_SOLAPAMIENTO:
                hallazgos.append(
                    Hallazgo(
                        tiempo,
                        "invade_subtitulos",
                        f"{_identificar(m)} invade '{ZONA_SUBTITULOS.nombre}' (area={area:.3f})",
                        [_identificar(m)],
                    )
                )

    return hallazgos


def escribir_reporte(hallazgos: Iterable[Hallazgo], ruta: Path) -> None:
    """Escribe ``hallazgos`` como JSON en ``ruta``, deduplicados por ``(tipo, objetos)`` (se
    conserva el primer ``tiempo`` en que apareció cada uno)."""
    ruta = Path(ruta)
    vistos: dict[tuple[str, tuple[str, ...]], Hallazgo] = {}
    for h in hallazgos:
        clave = (h.tipo, tuple(h.objetos))
        previo = vistos.get(clave)
        if previo is None or h.tiempo < previo.tiempo:
            vistos[clave] = h

    lista_final = sorted(vistos.values(), key=lambda h: (h.tiempo, h.tipo, tuple(h.objetos)))
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", encoding="utf-8") as f:
        json.dump(
            [
                {"tiempo": h.tiempo, "tipo": h.tipo, "descripcion": h.descripcion, "objetos": h.objetos}
                for h in lista_final
            ],
            f,
            indent=2,
            ensure_ascii=False,
        )
