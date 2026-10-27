"""Componentes visuales de geometria (VGroup/manim) construidos sobre
`toolkit.motor_geometria`. Todo el calculo numerico vive en el motor; este
modulo solo dirige mobjects.
"""

from __future__ import annotations

import numpy as np
from manim import (
    Angle,
    DashedLine,
    DoubleArrow,
    Line,
    MathTex,
    Polygon,
    RightAngle,
    VGroup,
    WHITE,
)

from .estilos import (
    AMARILLO,
    AZUL,
    BLANCO,
    COLORES_MARCA,
    FUENTE_ETIQUETA,
    GRIS,
    GROSOR_LINEA_FINA,
    GROSOR_LINEA_MEDIA,
    PALETA_SECUENCIAL,
)
from .motor_geometria import a3d, baricentro, interseccion_rectas, punto_medio
from .tipografia import Texto

_TOLERANCIA_RECTO = 1e-2  # ~0.57 grados: margen para detectar angulo recto


class LineaAuxiliar(DashedLine):
    """Trazo punteado estandarizado para demostraciones de geometria.

    Obliga a usar el color secundario de la marca para mantener consistencia.
    """

    def __init__(self, start, end, **kwargs):
        color_default = kwargs.pop("color", COLORES_MARCA["TEXTO_SECUNDARIO"])
        stroke_width = kwargs.pop("stroke_width", GROSOR_LINEA_FINA)
        dashed_ratio = kwargs.pop("dashed_ratio", 0.5)

        super().__init__(
            start,
            end,
            color=color_default,
            stroke_width=stroke_width,
            dashed_ratio=dashed_ratio,
            **kwargs,
        )


def _bisectriz_unitaria(vertice: np.ndarray, pa: np.ndarray, pb: np.ndarray) -> np.ndarray:
    """Direccion unitaria de la bisectriz del angulo `pa-vertice-pb` (plano XY)."""
    u1 = pa - vertice
    n1 = np.linalg.norm(u1)
    u1 = u1 / n1 if n1 > 1e-9 else np.array([1.0, 0.0, 0.0])

    u2 = pb - vertice
    n2 = np.linalg.norm(u2)
    u2 = u2 / n2 if n2 > 1e-9 else np.array([1.0, 0.0, 0.0])

    bisectriz = u1 + u2
    norma = np.linalg.norm(bisectriz)
    if norma < 1e-9:
        # a y b son opuestos: no hay bisectriz unica; usar perpendicular a u1.
        return np.array([-u1[1], u1[0], 0.0])
    return bisectriz / norma


class MarcaAngulo(VGroup):
    """Arco de angulo con etiqueta, construido desde 3 puntos (a, vertice, b).

    Elige automaticamente el angulo interior (< pi) entre los rayos
    `vertice->a` y `vertice->b`; si es recto (dentro de una tolerancia
    angular pequena), dibuja `RightAngle` en vez de `Angle`. La etiqueta se
    posiciona sobre la bisectriz del angulo.
    """

    def __init__(
        self,
        a,
        vertice,
        b,
        etiqueta: str | None = r"\alpha",
        radio: float = 0.5,
        color=AMARILLO,
        **kwargs,
    ):
        super().__init__(**kwargs)

        pa, pv, pb = a3d(a), a3d(vertice), a3d(b)
        linea1 = Line(pv, pa)
        linea2 = Line(pv, pb)

        arco = Angle(linea1, linea2, radius=radio, color=color)
        if abs(arco.get_value()) > np.pi + 1e-9:
            arco = Angle(linea1, linea2, radius=radio, other_angle=True, color=color)

        valor = abs(arco.get_value())
        es_recto = abs(valor - np.pi / 2) < _TOLERANCIA_RECTO
        if es_recto:
            arco = RightAngle(linea1, linea2, length=radio, color=color)

        self.arco = arco
        self.add(self.arco)

        self.etiqueta = None
        if etiqueta:
            direccion = _bisectriz_unitaria(pv, pa, pb)
            self.etiqueta = MathTex(etiqueta, color=color, font_size=FUENTE_ETIQUETA)
            self.etiqueta.move_to(pv + direccion * (radio + 0.35))
            self.add(self.etiqueta)


def EtiquetaAngulo(
    linea1: Line,
    linea2: Line,
    texto_latex: str,
    radio: float = 0.5,
    color_arco=WHITE,
    color_texto=None,
    **kwargs,
) -> MarcaAngulo:
    """Compat: recibe dos `Line`, calcula el vertice comun y delega en `MarcaAngulo`."""
    color_texto = color_texto if color_texto is not None else COLORES_MARCA["RESALTE"]

    p1s, p1e = linea1.get_start(), linea1.get_end()
    p2s, p2e = linea2.get_start(), linea2.get_end()

    vertice = interseccion_rectas(p1s, p1e, p2s, p2e)
    if vertice is None:
        # Rectas paralelas: usar el punto de linea1 mas cercano a linea2 como vertice.
        vertice = p1s if np.linalg.norm(p1s - p2s) < np.linalg.norm(p1e - p2s) else p1e

    a = p1e if np.linalg.norm(p1s - vertice) < np.linalg.norm(p1e - vertice) else p1s
    b = p2e if np.linalg.norm(p2s - vertice) < np.linalg.norm(p2e - vertice) else p2s

    resultado = MarcaAngulo(a, vertice, b, etiqueta=texto_latex, radio=radio, color=color_arco, **kwargs)
    if resultado.etiqueta is not None:
        resultado.etiqueta.set_color(color_texto)
    return resultado


class TrianguloEtiquetado(VGroup):
    """Triangulo relleno con vertices y (opcionalmente) lados etiquetados.

    Expone `.vertices` (lista de 3 puntos 3D), `.lados` (`VGroup` de 3
    `Line`) y `.etiquetas` (`VGroup` con las etiquetas de vertice y de lado).
    """

    def __init__(
        self,
        a,
        b,
        c,
        nombres=("A", "B", "C"),
        lados=None,
        color=AZUL,
        relleno: float = 0.25,
        **kwargs,
    ):
        super().__init__(**kwargs)

        pa, pb, pc = a3d(a), a3d(b), a3d(c)
        self.vertices = [pa, pb, pc]
        centro = baricentro(pa, pb, pc)

        relleno_poligono = Polygon(
            pa, pb, pc, color=color, fill_color=color, fill_opacity=relleno, stroke_width=0
        )
        lado_ab = Line(pa, pb, color=color, stroke_width=GROSOR_LINEA_MEDIA)
        lado_bc = Line(pb, pc, color=color, stroke_width=GROSOR_LINEA_MEDIA)
        lado_ca = Line(pc, pa, color=color, stroke_width=GROSOR_LINEA_MEDIA)
        self.lados = VGroup(lado_ab, lado_bc, lado_ca)

        self.etiquetas = VGroup()
        for punto, nombre in zip((pa, pb, pc), nombres):
            direccion = punto - centro
            norma = np.linalg.norm(direccion)
            direccion = direccion / norma if norma > 1e-9 else np.array([0.0, 1.0, 0.0])
            etiqueta = Texto(nombre, tamano=FUENTE_ETIQUETA, color=color)
            etiqueta.move_to(punto + direccion * 0.4)
            self.etiquetas.add(etiqueta)

        if lados is not None:
            pares = ((pa, pb), (pb, pc), (pc, pa))
            for (p1, p2), texto in zip(pares, lados):
                if not texto:
                    continue
                medio = punto_medio(p1, p2)
                direccion = medio - centro
                norma = np.linalg.norm(direccion)
                direccion = direccion / norma if norma > 1e-9 else np.array([0.0, 1.0, 0.0])
                etiqueta_lado = Texto(texto, tamano=FUENTE_ETIQUETA, color=color)
                etiqueta_lado.move_to(medio + direccion * 0.35)
                self.etiquetas.add(etiqueta_lado)

        self.add(relleno_poligono, self.lados, self.etiquetas)


def marcas_congruencia(linea: Line, n: int = 1, color=BLANCO) -> VGroup:
    """`n` rayitas perpendiculares centradas en el punto medio de `linea`."""
    inicio, fin = linea.get_start(), linea.get_end()
    medio = punto_medio(inicio, fin)

    direccion = fin - inicio
    norma = np.linalg.norm(direccion)
    unitario = direccion / norma if norma > 1e-9 else np.array([1.0, 0.0, 0.0])
    perpendicular = np.array([-unitario[1], unitario[0], 0.0])

    largo = 0.15
    separacion = 0.08
    grupo = VGroup()
    for i in range(n):
        desplazamiento = (i - (n - 1) / 2.0) * separacion
        centro_marca = medio + unitario * desplazamiento
        p1 = centro_marca + perpendicular * (largo / 2.0)
        p2 = centro_marca - perpendicular * (largo / 2.0)
        grupo.add(Line(p1, p2, color=color, stroke_width=GROSOR_LINEA_MEDIA))
    return grupo


def cota(a, b, texto: str, lado: float = 1.0, color=GRIS) -> VGroup:
    """Linea de cota paralela a `ab`, desplazada `lado`, con flechas y etiqueta."""
    pa, pb = a3d(a), a3d(b)
    direccion = pb - pa
    norma = np.linalg.norm(direccion)
    unitario = direccion / norma if norma > 1e-9 else np.array([1.0, 0.0, 0.0])
    perpendicular = np.array([-unitario[1], unitario[0], 0.0])
    desplazamiento = perpendicular * lado

    p1 = pa + desplazamiento
    p2 = pb + desplazamiento

    linea_cota = DoubleArrow(
        p1, p2, color=color, stroke_width=GROSOR_LINEA_FINA, buff=0, tip_length=0.15
    )
    guia1 = DashedLine(pa, p1, color=color, stroke_width=GROSOR_LINEA_FINA)
    guia2 = DashedLine(pb, p2, color=color, stroke_width=GROSOR_LINEA_FINA)

    etiqueta = Texto(texto, tamano=FUENTE_ETIQUETA, color=color)
    etiqueta.move_to(punto_medio(p1, p2) + perpendicular * 0.35)

    return VGroup(linea_cota, guia1, guia2, etiqueta)


def regiones_coloreadas(radio, angulos, paleta=None, opacidad: float = 0.6) -> VGroup:
    """Regiones de las cuerdas entre `angulos`, coloreadas deterministicamente
    (indice de region mod `len(paleta)`)."""
    from .motor_geometria import regiones_de_cuerdas

    if paleta is None:
        paleta = PALETA_SECUENCIAL

    grupo = VGroup()
    for i, vertices in enumerate(regiones_de_cuerdas(radio, angulos)):
        color = paleta[i % len(paleta)]
        poligono = Polygon(
            *vertices, color=color, fill_color=color, fill_opacity=opacidad, stroke_width=GROSOR_LINEA_FINA
        )
        grupo.add(poligono)
    return grupo
