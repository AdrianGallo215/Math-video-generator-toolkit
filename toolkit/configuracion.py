"""Perfiles de calidad 9:16 que respetan los flags -ql/-qm/-qh de manim."""

import os
from dataclasses import dataclass

from manim import config

# --- CONSTANTES DE RENDERIZADO VERTICAL (SHORTS/REELS/TIKTOK) ---
# Mantenidas por compatibilidad: corresponden al perfil "alta".
RESOLUCION_ANCHO = 1080
RESOLUCION_ALTO = 1920

# Relación de aspecto matemática interna de Manim (9:16)
FRAME_WIDTH = 9.0
FRAME_HEIGHT = 16.0

FPS_ESTANDAR = 60
COLOR_FONDO_GLOBAL = "#0E0E10"


@dataclass(frozen=True)
class PerfilCalidad:
    """Perfil de renderizado vertical (resolución + fps) para una calidad dada."""

    nombre: str  # "borrador" | "media" | "alta"
    ancho_px: int
    alto_px: int
    fps: int


PERFILES: dict[str, PerfilCalidad] = {
    "borrador": PerfilCalidad("borrador", 540, 960, 30),
    "media": PerfilCalidad("media", 720, 1280, 30),
    "alta": PerfilCalidad("alta", 1080, 1920, 60),
}

MAPA_CALIDAD_MANIM = {
    "low_quality": "borrador",
    "medium_quality": "media",
    "high_quality": "alta",
    "production_quality": "alta",
    "fourk_quality": "alta",
}

VARIABLE_ENTORNO_CALIDAD = "SHORT_CALIDAD"

# Anchos de manim (854x480 para low_quality) no siguen la proporción 9:16 hasta que
# aplicamos nuestra propia configuración. Una vez aplicada una vez, pixel_height queda
# en 960/1280/1920 (9:16) y podemos detectar el perfil de forma idempotente.
_ALTOS_PERFIL_APLICADO = {perfil.alto_px: perfil for perfil in PERFILES.values()}
_ANCHOS_PERFIL_APLICADO = {perfil.ancho_px: perfil for perfil in PERFILES.values()}


def detectar_perfil() -> PerfilCalidad:
    """Determina el perfil de calidad vigente.

    Orden de prioridad:
    1. Variable de entorno ``SHORT_CALIDAD`` si contiene un nombre de perfil válido.
    2. El ``pixel_height`` actual de manim (fijado por los flags -ql/-qm/-qh antes de
       construir la escena), o, si ya aplicamos un perfil antes (idempotencia), el
       perfil cuyo ancho/alto coincide exactamente.
    """
    valor_entorno = os.environ.get(VARIABLE_ENTORNO_CALIDAD)
    if valor_entorno in PERFILES:
        return PERFILES[valor_entorno]

    alto_actual = config.pixel_height
    ancho_actual = config.pixel_width

    perfil_idempotente = _ALTOS_PERFIL_APLICADO.get(alto_actual)
    if (
        perfil_idempotente is not None
        and _ANCHOS_PERFIL_APLICADO.get(ancho_actual) is perfil_idempotente
    ):
        return perfil_idempotente

    if alto_actual <= 480:
        return PERFILES["borrador"]
    if alto_actual <= 720:
        return PERFILES["media"]
    return PERFILES["alta"]


def aplicar_configuracion_global(perfil: PerfilCalidad | None = None) -> PerfilCalidad:
    """Sobrescribe el objeto global ``config`` de manim con un perfil 9:16.

    Debe llamarse al inicio del método ``setup()`` (o ``__init__``) de la escena.
    Es idempotente: llamarla dos veces seguidas con el mismo perfil detectado no
    cambia el resultado.
    """
    if perfil is None:
        perfil = detectar_perfil()

    config.pixel_width = perfil.ancho_px
    config.pixel_height = perfil.alto_px
    config.frame_width = FRAME_WIDTH
    config.frame_height = FRAME_HEIGHT
    config.frame_rate = perfil.fps
    config.background_color = COLOR_FONDO_GLOBAL

    return perfil
