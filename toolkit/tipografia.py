"""
Tipografia: registro de fuentes serif (CMU Serif) y plantilla TeX en espanol.

Provee helpers `Texto` y `TextoTex` que envuelven `manim.Text` y `manim.Tex`
para usar consistentemente la fuente serif del sistema de diseno 3B1B y una
plantilla TeX capaz de compilar tildes, ene y signos de apertura en espanol.
"""

from __future__ import annotations

import logging
from pathlib import Path

import manimpango
from manim import NORMAL, Tex, Text, TexTemplate

from toolkit.estilos import BLANCO, FUENTE_CUERPO, FUENTE_MINIMA

logger = logging.getLogger(__name__)

FUENTE_SERIF = "CMU Serif"

_DIR_FUENTES = Path(__file__).resolve().parent.parent / "assets" / "fonts"
_EXTENSIONES_FUENTE = (".otf", ".ttf")

_plantilla_tex_es: TexTemplate | None = None
_serif_disponible: bool | None = None   # cache: manimpango.list_fonts() cuesta 0.5-4 s por llamada


def _serif_registrada() -> bool:
    global _serif_disponible
    if _serif_disponible is None:
        _serif_disponible = FUENTE_SERIF in manimpango.list_fonts()
    return _serif_disponible


def registrar_fuentes() -> bool:
    """Registra con manimpango cada fuente (.otf/.ttf) de assets/fonts.

    Idempotente: llamar varias veces no falla ni duplica registros.
    Devuelve True si "CMU Serif" queda disponible tras el registro.
    """
    if not _DIR_FUENTES.is_dir():
        logger.warning("No existe el directorio de fuentes: %s", _DIR_FUENTES)
        return _serif_registrada()

    global _serif_disponible
    if _serif_disponible:
        return True
    for ruta in sorted(_DIR_FUENTES.iterdir()):
        if ruta.suffix.lower() in _EXTENSIONES_FUENTE:
            try:
                manimpango.register_font(str(ruta))
            except Exception:
                logger.warning("No se pudo registrar la fuente %s", ruta, exc_info=True)

    _serif_disponible = None
    return _serif_registrada()


def fuente_por_defecto() -> str:
    """Devuelve "CMU Serif" si esta registrada; si no, "" (default de manim)."""
    if _serif_registrada():
        return FUENTE_SERIF
    return ""


def Texto(texto: str, tamano: float = FUENTE_CUERPO, color=BLANCO, peso: str = NORMAL, **kw) -> Text:
    """Crea un `Text` con la fuente serif por defecto (si esta registrada).

    Lanza ValueError si `tamano` es menor que FUENTE_MINIMA (legibilidad movil).
    """
    if tamano < FUENTE_MINIMA:
        raise ValueError(
            f"tamano ({tamano}) menor que FUENTE_MINIMA ({FUENTE_MINIMA}): texto ilegible en movil"
        )
    fuente = kw.pop("font", None) or fuente_por_defecto()
    return Text(texto, font_size=tamano, color=color, weight=peso, font=fuente, **kw)


def plantilla_tex_es() -> TexTemplate:
    """TexTemplate en espanol (utf8/T1, amsmath, amssymb). Singleton cacheado."""
    global _plantilla_tex_es
    if _plantilla_tex_es is not None:
        return _plantilla_tex_es

    # NOTA (desvio documentado): \usepackage[T1]{fontenc} produce SVGs sin
    # glifos (ancho 0) con la instalacion de MiKTeX del entorno: dvisvgm no
    # logra extraer los outlines de las fuentes EC/T1 disponibles. Se omite
    # fontenc; utf8 + amsmath/amssymb ya permiten compilar tildes, ñ y ¿ ¡.
    plantilla = TexTemplate()
    plantilla.preamble = (
        "\\usepackage[utf8]{inputenc}\n"
        "\\usepackage{amsmath}\n"
        "\\usepackage{amssymb}\n"
    )
    _plantilla_tex_es = plantilla
    return _plantilla_tex_es


def TextoTex(texto: str, tamano: float = FUENTE_CUERPO, color=BLANCO, **kw) -> Tex:
    """Crea un `Tex` con la plantilla en espanol (admite tildes, ene, ¿ ¡)."""
    return Tex(texto, font_size=tamano, color=color, tex_template=plantilla_tex_es(), **kw)
