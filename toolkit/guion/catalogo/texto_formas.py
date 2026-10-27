"""Piezas de texto y formas básicas (tipos ``texto`` y ``forma``).

G02 amplía esta familia (llave, flecha, títulos...). Cada pieza se coloca sola en su ``zona`` (nombre o
``{de: id, lado, espacio}``), usa colores por nombre y nunca baja de ``FUENTE_MINIMA``.
"""

from __future__ import annotations

import logging
import math

from manim import (
    BOLD,
    DOWN,
    LEFT,
    NORMAL,
    RIGHT,
    Circle,
    Dot,
    Line,
    Mobject,
    Rectangle,
    RegularPolygon,
    Square,
    VGroup,
)

from toolkit.estilos import FUENTE_CUERPO, FUENTE_MINIMA, GROSOR_LINEA_MEDIA, OPACIDAD_RELLENO
from toolkit.guion.contexto import ALINEACIONES, ATRIBUTO_PARTES, MARGEN_ZONA, ContextoGuion
from toolkit.guion.registro import Param, objeto
from toolkit.tipografia import Texto

logger = logging.getLogger(__name__)

MAX_LINEAS_AUTO = 4
ESPACIO_LINEAS = 0.25  # hueco entre líneas a FUENTE_CUERPO (escala con el tamaño)
RADIO_PUNTO = 0.12
ESPACIO_CELDAS = 0.08
MAX_CELDAS_LADO = 12
FIGURAS = ("rect", "circulo", "linea", "punto", "poligono", "cuadricula")
_PARAM_ZONA = Param("zona", "zona", defecto="principal",
                    descripcion="Zona donde se encaja (nombre) o {de: id, lado: abajo|arriba|izq|der, espacio: 0.3}.")
_PARAM_ALINEACION = Param("alineacion", "texto", defecto="centro", opciones=tuple(ALINEACIONES),
                          descripcion="Borde de la zona al que se pega.")


# --- texto ------------------------------------------------------------------------------------------


def _partir_en_lineas(texto: str, n: int) -> list[str]:
    """Reparte las palabras de ``texto`` en ``n`` líneas de longitud parecida (orden conservado)."""
    palabras = texto.split()
    if n <= 1 or len(palabras) <= 1:
        return [texto]
    objetivo = len(texto) / n
    lineas: list[str] = []
    actual: list[str] = []
    for palabra in palabras:
        candidata = " ".join(actual + [palabra])
        if actual and len(candidata) > objetivo and len(lineas) < n - 1:
            lineas.append(" ".join(actual))
            actual = [palabra]
        else:
            actual.append(palabra)
    lineas.append(" ".join(actual))
    return lineas


def _bloque(lineas: list[str], tamano: float, color: str, peso: str, alineacion: str) -> Mobject:
    textos = [Texto(linea, tamano=tamano, color=color, peso=peso) for linea in lineas]
    if len(textos) == 1:
        return textos[0]
    borde = {"izquierda": LEFT, "derecha": RIGHT}.get(alineacion)
    grupo = VGroup(*textos)
    if borde is not None:
        grupo.arrange(DOWN, buff=ESPACIO_LINEAS * tamano / FUENTE_CUERPO, aligned_edge=borde)
    else:
        grupo.arrange(DOWN, buff=ESPACIO_LINEAS * tamano / FUENTE_CUERPO)
    setattr(grupo, ATRIBUTO_PARTES, {str(i): t for i, t in enumerate(textos)})
    return grupo


def _factor_encaje(mob: Mobject, ancho: float, alto: float) -> float:
    return min(1.0, ancho / max(mob.width, 1e-6), alto / max(mob.height, 1e-6))


@objeto(
    "texto",
    "Texto legible (fuente serif) encajado en una zona; si no cabe a su tamaño se parte en líneas.",
    params=[
        Param("texto", "texto", requerido=True, descripcion="Texto visible, con tildes (\\n fuerza un salto de línea)."),
        _PARAM_ZONA,
        Param("tamano", "numero", defecto=FUENTE_CUERPO, descripcion=f"Tamaño en puntos (mínimo {FUENTE_MINIMA})."),
        Param("color", "color", defecto="blanco", descripcion="Nombre de color de la paleta."),
        _PARAM_ALINEACION,
        Param("peso", "texto", defecto="normal", opciones=("normal", "negrita"), descripcion="Grosor de la letra."),
        Param("lineas", "entero", defecto=0, descripcion="Nº de líneas (0 = automático: las mínimas para caber)."),
    ],
    ejemplo={"en": "inicio", "hacer": "mostrar", "id": "titulo", "tipo": "texto", "texto": "¿Por qué funciona?",
             "zona": "titulo", "color": "amarillo"},
)
def crear_texto(ctx: ContextoGuion, texto, zona, tamano, color, alineacion, peso, lineas) -> Mobject:
    peso_manim = BOLD if peso == "negrita" else NORMAL
    hex_color = ctx.color(color)
    referencia = ctx.zona_de_referencia(zona)
    ancho, alto = referencia.ancho - 2 * MARGEN_ZONA, referencia.alto - 2 * MARGEN_ZONA
    if "\n" in texto:
        candidatos = [[linea.strip() for linea in texto.split("\n")]]
    elif lineas and lineas > 0:
        candidatos = [_partir_en_lineas(texto, lineas)]
    else:
        maximo = min(MAX_LINEAS_AUTO, max(1, len(texto.split())))
        candidatos = [_partir_en_lineas(texto, n) for n in range(1, maximo + 1)]
    mejor, mejor_factor = None, -1.0
    for partes in candidatos:
        mob = _bloque(partes, tamano, hex_color, peso_manim, alineacion)
        factor = _factor_encaje(mob, ancho, alto)
        if factor > mejor_factor + 1e-9:
            mejor, mejor_factor = mob, factor
        if factor >= 1.0:
            break
    ctx.colocar(mejor, zona, alineacion)
    efectivo = tamano * mejor_factor
    if efectivo < FUENTE_MINIMA:
        logger.warning("texto %r queda a tamaño %.0f (< %d): acórtalo o dale una zona más grande",
                       texto[:40], efectivo, FUENTE_MINIMA)
    return mejor


# --- forma --------------------------------------------------------------------------------------------


def _ciclo_forma(params: dict, estado) -> None:
    proporcion = params.get("proporcion", 0.5)
    if isinstance(proporcion, (int, float)) and not 0 < proporcion <= 1:
        estado.error("E3", f"proporcion {proporcion}: debe estar entre 0 (exclusivo) y 1 (fracción de la zona)")
    lados = params.get("lados", 6)
    if isinstance(lados, int) and lados < 3:
        estado.error("E3", "lados: un polígono necesita al menos 3")
    for clave in ("filas", "columnas"):
        valor = params.get(clave, 3)
        if isinstance(valor, int) and not 1 <= valor <= MAX_CELDAS_LADO:
            estado.error("E3", f"{clave}: entre 1 y {MAX_CELDAS_LADO}")
    aspecto = params.get("aspecto", 1.0)
    if isinstance(aspecto, (int, float)) and aspecto <= 0:
        estado.error("E3", "aspecto: debe ser positivo (ancho/alto)")


def _cuadricula(filas: int, columnas: int) -> VGroup:
    celdas = [Square(side_length=1.0) for _ in range(filas * columnas)]
    grupo = VGroup(*celdas).arrange_in_grid(rows=filas, cols=columnas, buff=ESPACIO_CELDAS)
    partes = {}
    for k, celda in enumerate(celdas):
        partes[str(k)] = celda
        partes[f"{k // columnas},{k % columnas}"] = celda
    setattr(grupo, ATRIBUTO_PARTES, partes)
    return grupo


@objeto(
    "forma",
    "Figura geométrica (rect, círculo, línea, punto, polígono regular o cuadrícula de celdas) a escala de su zona.",
    params=[
        Param("figura", "texto", requerido=True, opciones=FIGURAS, descripcion="Qué figura dibujar."),
        _PARAM_ZONA,
        Param("color", "color", defecto="azul", descripcion="Color del borde (y del relleno)."),
        Param("relleno", "booleano", defecto=True, descripcion="Relleno semitransparente del mismo color."),
        Param("proporcion", "numero", defecto=0.5, descripcion="Tamaño como fracción (0-1] de la zona."),
        Param("aspecto", "numero", defecto=1.0, descripcion="Ancho/alto del rectángulo."),
        Param("lados", "entero", defecto=6, descripcion="Lados del polígono regular."),
        Param("filas", "entero", defecto=3, descripcion="Filas de la cuadrícula (celdas 'id.k' o 'id.f,c')."),
        Param("columnas", "entero", defecto=3, descripcion="Columnas de la cuadrícula."),
        _PARAM_ALINEACION,
    ],
    ejemplo={"en": "inicio", "hacer": "mostrar", "id": "caja", "tipo": "forma", "figura": "rect", "aspecto": 1.6,
             "color": "verde"},
    ciclo=_ciclo_forma,
)
def crear_forma(ctx: ContextoGuion, figura, zona, color, relleno, proporcion, aspecto, lados, filas, columnas,
                alineacion) -> Mobject:
    hex_color = ctx.color(color)
    if figura == "punto":
        mob: Mobject = Dot(radius=RADIO_PUNTO, color=hex_color)
    else:
        mob = {
            "rect": lambda: Rectangle(width=float(aspecto), height=1.0),
            "circulo": lambda: Circle(radius=0.5),
            "linea": lambda: Line(LEFT * 0.5, RIGHT * 0.5),
            "poligono": lambda: RegularPolygon(n=int(lados)),
            "cuadricula": lambda: _cuadricula(int(filas), int(columnas)),
        }[figura]()
        mob.set_stroke(hex_color, width=GROSOR_LINEA_MEDIA)
        if relleno and figura != "linea":
            mob.set_fill(hex_color, opacity=OPACIDAD_RELLENO)
        referencia = ctx.zona_de_referencia(zona)
        ancho = (referencia.ancho - 2 * MARGEN_ZONA) * proporcion
        alto = (referencia.alto - 2 * MARGEN_ZONA) * proporcion
        factores = [ancho / mob.width] if mob.width > 1e-6 else []
        if mob.height > 1e-6:
            factores.append(alto / mob.height)
        mob.scale(min(factores) if factores else 1.0)
    ctx.colocar(mob, zona, alineacion)
    if not math.isfinite(mob.width):
        raise ValueError("forma degenerada")
    return mob
