"""Algoritmos y estructuras de datos visuales con estetica 3B1B.

Componentes:

- ``Celda``: caja redondeada con borde del color y relleno tenue + valor en CMU Serif.
- ``ArregloVisual``: fila (o filas) de celdas con indices; animaciones de colorear,
  atenuar rangos, comparar, resaltar e intercambiar (arcos suaves).
- ``Puntero``: flecha + nombre ("lo", "hi", "mid", "i") que se pega a una celda.
- ``CodigoResaltado``: bloque de codigo (``manim.Code``, estilo monokai) con una
  franja translucida que marca la linea activa.
- ``PilaVisual``: pila con push/pop animados (recursion).

Funciones puras (sin manim) para dirigir escenas: ``pasos_busqueda_binaria`` y
``pasos_burbuja``.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Iterable, Sequence

import numpy as np
from manim import (
    DOWN,
    LEFT,
    ORIGIN,
    PI,
    RIGHT,
    UP,
    Animation,
    AnimationGroup,
    Arrow,
    Code,
    FadeIn,
    FadeOut,
    Indicate,
    Line,
    Mobject,
    RoundedRectangle,
    SurroundingRectangle,
    Transform,
    VGroup,
    smooth,
    there_and_back,
)

from toolkit.estilos import (
    AMARILLO,
    AZUL,
    BLANCO,
    FONDO,
    FUENTE_ETIQUETA,
    FUENTE_MINIMA,
    GRIS,
    GRIS_OSCURO,
    GROSOR_LINEA_FINA,
    GROSOR_LINEA_GRUESA,
    GROSOR_LINEA_MEDIA,
    MORADO,
    OPACIDAD_ATENUADO,
    TIEMPO_ENFASIS,
    TURQUESA,
)
from toolkit.tipografia import Texto, registrar_fuentes

logger = logging.getLogger(__name__)

# Idempotente: garantiza CMU Serif al construir componentes fuera de una
# PlantillaShort (tests, prototipos); las medidas de celdas dependen de la fuente.
registrar_fuentes()

# --- Dimensiones internas de los componentes (unidades de escena) ---
LADO_CELDA = 0.62
RADIO_CELDA = 0.1
RELLENO_HORIZONTAL_CELDA = 0.06  # margen del valor dentro de la celda
OPACIDAD_RELLENO_CELDA = 0.15  # relleno tenue estilo 3B1B
SEPARACION_CELDAS = 0.08
SEPARACION_INDICE = 0.12
SEPARACION_FILAS = 0.3
ESCALA_ENFASIS = 1.15

LARGO_FLECHA_PUNTERO = 0.55
SEPARACION_PUNTERO = 0.1

OPACIDAD_RESALTADO_CODIGO = 0.22
FUENTE_CODIGO = "Consolas"  # la monoespaciada disponible mas angosta y legible (~0.25 u/caracter a 36)
INTERLETRADO_CODIGO = 0.9  # factor sobre el avance entre glifos (no deforma los glifos)
SEPARACION_NUMEROS_CODIGO = 0.2
MARGEN_FONDO_CODIGO = 0.2

ANCHO_MARCO_PILA = 2.6
ALTO_MARCO_PILA = 0.72
SEPARACION_MARCOS_PILA = 0.08


# ---------------------------------------------------------------------------
# Funciones puras
# ---------------------------------------------------------------------------


def pasos_busqueda_binaria(valores: Sequence[Any], objetivo: Any) -> list[dict]:
    """Pasos de la busqueda binaria clasica sobre ``valores`` (ordenados).

    Cada paso es ``{"lo", "hi", "mid", "comparacion"}`` donde ``comparacion``
    compara ``valores[mid]`` con ``objetivo``: ``"<"`` (el valor del medio es
    menor ⇒ ``lo = mid + 1``), ``">"`` (``hi = mid - 1``) o ``"=="`` (encontrado,
    ultimo paso). Si el objetivo no esta, se agrega un paso final con
    ``lo > hi``, ``mid=None`` y ``comparacion=None``.
    """
    lista = list(valores)
    if any(lista[k] > lista[k + 1] for k in range(len(lista) - 1)):
        raise ValueError("pasos_busqueda_binaria requiere valores ordenados de menor a mayor")

    pasos: list[dict] = []
    lo, hi = 0, len(lista) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        valor = lista[mid]
        if valor == objetivo:
            pasos.append({"lo": lo, "hi": hi, "mid": mid, "comparacion": "=="})
            return pasos
        comparacion = "<" if valor < objetivo else ">"
        pasos.append({"lo": lo, "hi": hi, "mid": mid, "comparacion": comparacion})
        if comparacion == "<":
            lo = mid + 1
        else:
            hi = mid - 1

    pasos.append({"lo": lo, "hi": hi, "mid": None, "comparacion": None})
    return pasos


def pasos_burbuja(valores: Sequence[Any]) -> list[tuple[str, int, int]]:
    """Pasos del ordenamiento burbuja (con corte temprano si una pasada no intercambia).

    Devuelve ``("comparar", j, j+1)`` y, si hace falta, ``("intercambiar", j, j+1)``
    inmediatamente despues. No modifica ``valores``.
    """
    lista = list(valores)
    pasos: list[tuple[str, int, int]] = []
    n = len(lista)
    for pasada in range(n - 1):
        hubo_intercambio = False
        for j in range(n - 1 - pasada):
            pasos.append(("comparar", j, j + 1))
            if lista[j] > lista[j + 1]:
                lista[j], lista[j + 1] = lista[j + 1], lista[j]
                pasos.append(("intercambiar", j, j + 1))
                hubo_intercambio = True
        if not hubo_intercambio:
            break
    return pasos


# ---------------------------------------------------------------------------
# Celda y arreglo
# ---------------------------------------------------------------------------


class Celda(VGroup):
    """Caja redondeada (lado ``LADO_CELDA``) con borde del color, relleno tenue y el valor centrado."""

    def __init__(
        self,
        valor: Any,
        color=AZUL,
        tamano: float = FUENTE_ETIQUETA,
        lado: float = LADO_CELDA,
        ancho: float | None = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.dato = valor
        self.color_base = color
        self.valor = Texto(str(valor), tamano=tamano, color=BLANCO)
        ancho = max(ancho or lado, self.valor.width + 2 * RELLENO_HORIZONTAL_CELDA)
        self.caja = RoundedRectangle(
            corner_radius=RADIO_CELDA,
            width=ancho,
            height=lado,
            stroke_color=color,
            stroke_width=GROSOR_LINEA_FINA,
            fill_color=color,
            fill_opacity=OPACIDAD_RELLENO_CELDA,
        )
        self.valor.move_to(self.caja)
        self.add(self.caja, self.valor)

    def pintar(self, color, opacidad: float = 0.8) -> "Celda":
        """Rellena la caja con ``color``; el valor pasa a oscuro si el relleno es intenso."""
        self.caja.set_stroke(color=color, width=GROSOR_LINEA_FINA, opacity=1.0)
        self.caja.set_fill(color=color, opacity=opacidad)
        self.valor.set_fill(color=FONDO if opacidad >= 0.5 else BLANCO, opacity=1.0)
        return self

    def atenuar(self, opacidad: float = OPACIDAD_ATENUADO, color=None) -> "Celda":
        """Baja la opacidad de la celda (y opcionalmente la tiñe de ``color``)."""
        color_caja = color if color is not None else self.caja.get_stroke_color()
        self.caja.set_stroke(color=color_caja, opacity=opacidad)
        self.caja.set_fill(color=color_caja, opacity=OPACIDAD_RELLENO_CELDA * opacidad)
        self.valor.set_fill(opacity=opacidad)
        return self

    def restaurar(self) -> "Celda":
        """Vuelve al aspecto base (color original, relleno tenue, valor blanco)."""
        self.caja.set_stroke(color=self.color_base, width=GROSOR_LINEA_FINA, opacity=1.0)
        self.caja.set_fill(color=self.color_base, opacity=OPACIDAD_RELLENO_CELDA)
        self.valor.set_fill(color=BLANCO, opacity=1.0)
        return self


class _ResaltarCelda(Animation):
    """Borde grueso persistente + pulso de escala (sube y vuelve)."""

    def __init__(self, celda: Celda, color, **kwargs):
        kwargs.setdefault("run_time", TIEMPO_ENFASIS)
        super().__init__(celda, rate_func=lambda t: t, **kwargs)
        self.objetivo = celda.copy()
        self.objetivo.caja.set_stroke(color=color, width=GROSOR_LINEA_GRUESA, opacity=1.0)

    def interpolate_mobject(self, alpha: float) -> None:
        # Mobject.interpolate no recorre la familia: se interpola cada miembro con puntos
        # (asi los puntos se reinician en cada fotograma y el pulso no se acumula).
        familias = zip(
            self.mobject.family_members_with_points(),
            self.starting_mobject.family_members_with_points(),
            self.objetivo.family_members_with_points(),
        )
        for miembro, inicio, fin in familias:
            miembro.interpolate(inicio, fin, smooth(alpha))
        self.mobject.scale(
            1 + (ESCALA_ENFASIS - 1) * there_and_back(alpha),
            about_point=self.starting_mobject.get_center(),
        )


def _trocear(n: int, filas: int) -> list[int]:
    """Reparte ``n`` elementos en ``filas`` filas balanceadas (las primeras, mas largas)."""
    base, resto = divmod(n, filas)
    return [base + (1 if k < resto else 0) for k in range(filas)]


def _ancho_fila(anchos: Sequence[float]) -> float:
    return sum(anchos) + SEPARACION_CELDAS * max(len(anchos) - 1, 0)


class ArregloVisual(VGroup):
    """Arreglo de celdas con indices debajo (en GRIS).

    Disposicion: con ``columnas_max`` las celdas van en filas de ese largo
    (fila 2 debajo de la 1, con espacio para los indices); con ``filas`` se
    reparten en ese numero de filas balanceadas; si ambos son ``None`` se usa
    el menor numero de filas balanceadas que quepa en ``ancho_max`` sin
    escalar. El orden logico 0..n-1 (``celda(i)``, rangos, intercambios) no
    depende de la disposicion. Si la fila mas larga no cabe se reduce el
    tamano del valor hasta ``FUENTE_MINIMA`` (``tamano_valor`` final queda en
    el atributo homonimo); si ni asi cabe lanza ``ValueError``.
    """

    def __init__(
        self,
        valores: Iterable,
        ancho_max: float = 6.0,
        con_indices: bool = True,
        color=AZUL,
        tamano_valor: float = FUENTE_ETIQUETA,
        filas: int | None = None,
        columnas_max: int | None = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.valores: list = list(valores)
        if not self.valores:
            raise ValueError("ArregloVisual necesita al menos un valor")
        self.color = color
        n = len(self.valores)

        def ancho_celda(tamano: float) -> float:
            return max(Celda(v, tamano=tamano).width for v in self.valores)

        if columnas_max is not None:
            if columnas_max < 1:
                raise ValueError("columnas_max debe ser >= 1")
            largos = [min(columnas_max, n - k) for k in range(0, n, columnas_max)]
        else:
            if filas is None:
                filas = self._filas_automaticas([ancho_celda(tamano_valor)] * n, ancho_max)
            largos = _trocear(n, max(1, min(int(filas), n)))
        self.filas = len(largos)

        # Si la fila mas larga no cabe se reduce el tamano del valor, nunca por
        # debajo de FUENTE_MINIMA (los indices ya estan en FUENTE_MINIMA).
        largo_max = max(largos)
        tamano = float(tamano_valor)
        ancho = ancho_celda(tamano)
        while _ancho_fila([ancho] * largo_max) > ancho_max + 1e-9 and tamano > FUENTE_MINIMA:
            tamano = max(float(FUENTE_MINIMA), tamano - 1)
            ancho = ancho_celda(tamano)
        if _ancho_fila([ancho] * largo_max) > ancho_max + 1e-9:
            raise ValueError(
                f"ArregloVisual de {n} elementos en {self.filas} fila(s) no cabe en ancho_max={ancho_max} "
                f"ni con el texto en FUENTE_MINIMA ({FUENTE_MINIMA}). "
                "Divide en mas filas (columnas_max / filas=None) o usa menos elementos."
            )
        self.tamano_valor = tamano

        # Ancho uniforme (el del valor mas ancho): columnas alineadas entre filas.
        self.celdas: list[Celda] = [
            Celda(v, color=color, tamano=tamano, ancho=ancho) for v in self.valores
        ]
        self.indices = VGroup()
        if con_indices:
            for k, celda in enumerate(self.celdas):
                indice = Texto(str(k), tamano=FUENTE_MINIMA, color=GRIS)
                indice.next_to(celda, DOWN, buff=SEPARACION_INDICE)
                self.indices.add(indice)

        # Cada "columna" = celda + su indice, para mantener el indice bajo la celda.
        columnas = [
            VGroup(celda, self.indices[k]) if con_indices else VGroup(celda)
            for k, celda in enumerate(self.celdas)
        ]
        grupos_fila = VGroup()
        inicio = 0
        for largo in largos:
            fila = VGroup(*columnas[inicio : inicio + largo])
            fila.arrange(RIGHT, buff=SEPARACION_CELDAS, aligned_edge=UP)
            grupos_fila.add(fila)
            inicio += largo
        # Filas alineadas a la izquierda: celda(k) y celda(k + columnas) comparten columna.
        grupos_fila.arrange(DOWN, buff=SEPARACION_FILAS, aligned_edge=LEFT)

        self.grupo_celdas = VGroup(*self.celdas)
        self.add(self.grupo_celdas, self.indices)
        self.move_to(ORIGIN)

    @staticmethod
    def _filas_automaticas(anchos: Sequence[float], ancho_max: float) -> int:
        n = len(anchos)
        for filas in range(1, n + 1):
            inicio = 0
            cabe = True
            for largo in _trocear(n, filas):
                if _ancho_fila(anchos[inicio : inicio + largo]) > ancho_max + 1e-9:
                    cabe = False
                    break
                inicio += largo
            if cabe:
                return filas
        return n

    def celda(self, i: int) -> Celda:
        """Celda que ocupa hoy la posicion ``i`` (cambia tras ``intercambiar``)."""
        return self.celdas[i]

    def _rango(self, i: int, j: int) -> range:
        a, b = sorted((i, j))
        return range(max(a, 0), min(b, len(self.celdas) - 1) + 1)

    def colorear(self, indices: int | Iterable[int], color, opacidad: float = 0.8) -> Animation:
        """Rellena las celdas ``indices`` con ``color`` (valor oscuro si el relleno es intenso)."""
        if isinstance(indices, int):
            indices = [indices]
        animaciones = [
            Transform(self.celdas[k], self.celdas[k].copy().pintar(color, opacidad)) for k in indices
        ]
        return AnimationGroup(*animaciones)

    def atenuar_rango(
        self, i: int, j: int, opacidad: float = OPACIDAD_ATENUADO, color=None
    ) -> Animation:
        """Atenua las celdas ``i..j`` (inclusive): mitades descartadas en busqueda binaria."""
        animaciones = [
            Transform(self.celdas[k], self.celdas[k].copy().atenuar(opacidad, color))
            for k in self._rango(i, j)
        ]
        return AnimationGroup(*animaciones)

    def restaurar(self, indices: Iterable[int] | None = None) -> Animation:
        """Devuelve las celdas (todas por defecto) a su aspecto base."""
        seleccion = range(len(self.celdas)) if indices is None else indices
        return AnimationGroup(
            *[Transform(self.celdas[k], self.celdas[k].copy().restaurar()) for k in seleccion]
        )

    def intercambiar(self, i: int, j: int, run_time: float = 0.8) -> Animation:
        """Intercambia las celdas ``i`` y ``j`` por arcos opuestos y actualiza las listas internas.

        Ambas celdas usan el mismo ``path_arc`` con extremos invertidos: una viaja
        por arriba y la otra por abajo (no chocan).
        """
        if i == j:
            return AnimationGroup(Animation(self.celdas[i]), run_time=run_time)
        celda_i, celda_j = self.celdas[i], self.celdas[j]
        centro_i, centro_j = celda_i.get_center(), celda_j.get_center()
        animacion = AnimationGroup(
            Transform(celda_i, celda_i.copy().move_to(centro_j), path_arc=PI / 2),
            Transform(celda_j, celda_j.copy().move_to(centro_i), path_arc=PI / 2),
            run_time=run_time,
        )
        self.celdas[i], self.celdas[j] = celda_j, celda_i
        self.valores[i], self.valores[j] = self.valores[j], self.valores[i]
        self.grupo_celdas.submobjects = list(self.celdas)
        return animacion

    def comparar(self, i: int, j: int, color=AMARILLO) -> Animation:
        """Indica simultaneamente las celdas ``i`` y ``j``."""
        return AnimationGroup(
            Indicate(self.celdas[i], color=color, scale_factor=ESCALA_ENFASIS),
            Indicate(self.celdas[j], color=color, scale_factor=ESCALA_ENFASIS),
        )

    def resaltar_celda(self, i: int, color=AMARILLO) -> Animation:
        """Borde grueso persistente de ``color`` + pulso de escala."""
        return _ResaltarCelda(self.celdas[i], color)


# ---------------------------------------------------------------------------
# Puntero
# ---------------------------------------------------------------------------


class Puntero(VGroup):
    """Flecha + nombre ("lo", "hi", "mid", "i").

    ``direccion`` es el lado de la celda donde se ubica el puntero: con ``UP``
    queda encima y la flecha apunta hacia abajo.
    """

    def __init__(self, etiqueta: str, color=TURQUESA, direccion=UP, **kwargs):
        super().__init__(**kwargs)
        self.direccion = np.array(direccion, dtype=float)
        self.flecha = Arrow(
            start=self.direccion * LARGO_FLECHA_PUNTERO,
            end=ORIGIN,
            buff=0,
            color=color,
            stroke_width=GROSOR_LINEA_MEDIA,
            max_stroke_width_to_length_ratio=12,
            max_tip_length_to_length_ratio=0.45,
        )
        self.etiqueta = Texto(etiqueta, tamano=FUENTE_ETIQUETA, color=color)
        self.etiqueta.next_to(self.flecha, self.direccion, buff=0.08)
        self.add(self.flecha, self.etiqueta)

    def _desplazamiento_hacia(self, celda: Mobject, buff: float) -> np.ndarray:
        punta = self.flecha.get_critical_point(-self.direccion)
        destino = celda.get_critical_point(self.direccion) + self.direccion * buff
        # Alineacion perpendicular: la flecha queda centrada sobre la celda.
        eje_perpendicular = np.array([abs(self.direccion[1]), abs(self.direccion[0]), 0.0])
        desplazamiento = (destino - punta) * np.abs(self.direccion)
        desplazamiento += (celda.get_center() - self.flecha.get_center()) * eje_perpendicular
        return desplazamiento

    def colocar_en(self, celda: Mobject, buff: float = SEPARACION_PUNTERO) -> "Puntero":
        """Pega el puntero (sin animar) a ``celda`` por el lado ``direccion``."""
        self.shift(self._desplazamiento_hacia(celda, buff))
        return self

    def apuntar_a(self, celda: Mobject, buff: float = SEPARACION_PUNTERO, **kwargs) -> Animation:
        """Anima el puntero hasta quedar pegado a ``celda``."""
        return Transform(self, self.copy().colocar_en(celda, buff), **kwargs)


# ---------------------------------------------------------------------------
# Codigo resaltado
# ---------------------------------------------------------------------------


class CodigoResaltado(VGroup):
    """Bloque de codigo (``manim.Code``, estilo monokai, fuente Consolas) con linea activa.

    ``tamano`` debe ser >= ``FUENTE_MINIMA``. A 36 cada caracter avanza
    ~0.225 u (Consolas con interletrado 0.9): caben lineas de hasta 24
    caracteres en 6.3 u de ancho (con numeros de linea de 1 cifra).
    """

    def __init__(self, codigo: str, lenguaje: str = "python", tamano: float = FUENTE_MINIMA, **kwargs):
        super().__init__(**kwargs)
        if tamano < FUENTE_MINIMA:
            raise ValueError(
                f"tamano ({tamano}) menor que FUENTE_MINIMA ({FUENTE_MINIMA}): codigo ilegible en movil"
            )
        self.codigo = Code(
            code_string=codigo.rstrip("\n"),
            language=lenguaje,
            formatter_style="monokai",
            add_line_numbers=True,
            background="rectangle",
            paragraph_config={"font": FUENTE_CODIGO, "font_size": tamano},
        )
        # Fondo de Code descartado: se rehace tras compactar el interletrado.
        self.codigo.remove(self.codigo.background)
        self._compactar_interletrado(INTERLETRADO_CODIGO)
        numeros = self.codigo.line_numbers
        numeros.shift(
            RIGHT
            * (self.codigo.code_lines.get_left()[0] - SEPARACION_NUMEROS_CODIGO - numeros.get_right()[0])
        )
        self.fondo = SurroundingRectangle(
            VGroup(numeros, self.codigo.code_lines),
            buff=MARGEN_FONDO_CODIGO,
            corner_radius=0.2,
            color=GRIS_OSCURO,
            stroke_width=GROSOR_LINEA_FINA,
            fill_color=GRIS_OSCURO,
            fill_opacity=0.35,
        )
        self.codigo.line_numbers.set_color(GRIS)
        self.n_lineas = len(self.codigo.code_lines)
        self.linea_activa: int | None = None

        if self.n_lineas >= 2:
            paso = abs(self.y_linea_de(0) - self.y_linea_de(1))
        else:
            paso = self.codigo.code_lines.height + 0.15
        self.resaltado = RoundedRectangle(
            corner_radius=0.08,
            width=self.fondo.width - 0.12,
            height=paso * 0.95,
            stroke_width=0,
            fill_color=AMARILLO,
            fill_opacity=0.0,
        )
        self.resaltado.move_to([self.fondo.get_x(), self.y_linea_de(0), 0.0])
        self.add(self.fondo, self.resaltado, self.codigo)

        from toolkit.layout import ZONA_SEGURA

        if self.width > ZONA_SEGURA.ancho:
            logger.warning(
                "CodigoResaltado mide %.2f u de ancho (> ZONA_SEGURA %.2f): acorta las lineas",
                self.width,
                ZONA_SEGURA.ancho,
            )

    def _compactar_interletrado(self, factor: float) -> None:
        """Acerca los glifos entre si (avance * ``factor``) sin deformarlos.

        Todas las lineas usan el mismo borde izquierdo de referencia, asi la
        indentacion se conserva.
        """
        referencia = self.codigo.code_lines.get_left()[0]
        for linea in self.codigo.code_lines:
            for glifo in linea:
                x = glifo.get_x()
                glifo.shift(RIGHT * ((referencia + (x - referencia) * factor) - x))

    def y_linea_de(self, indice: int) -> float:
        return float(self.codigo.line_numbers[indice].get_y())

    def y_linea(self, n: int) -> float:
        """Coordenada y del centro de la linea ``n`` (1-based)."""
        self._validar_linea(n)
        return self.y_linea_de(n - 1)

    def _validar_linea(self, n: int) -> None:
        if not 1 <= n <= self.n_lineas:
            raise ValueError(f"Linea {n} fuera de rango (1..{self.n_lineas})")

    def resaltar_linea(self, n: int, **kwargs) -> Animation:
        """Mueve (o hace aparecer) la franja AMARILLA translucida detras de la linea ``n`` (1-based)."""
        self._validar_linea(n)
        if self.linea_activa is None:
            self.resaltado.set_y(self.y_linea(n))
        objetivo = self.resaltado.copy().set_y(self.y_linea(n)).set_fill(opacity=OPACIDAD_RESALTADO_CODIGO)
        self.linea_activa = n
        return Transform(self.resaltado, objetivo, **kwargs)


# ---------------------------------------------------------------------------
# Pila
# ---------------------------------------------------------------------------


class PilaVisual(VGroup):
    """Pila vertical (crece hacia arriba) con push/pop animados, util para recursion."""

    def __init__(
        self,
        elementos: Iterable[str] = (),
        ancho: float = ANCHO_MARCO_PILA,
        color=MORADO,
        tamano: float = FUENTE_ETIQUETA,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.ancho = ancho
        self.color = color
        self.tamano_texto = tamano
        self.base = Line(LEFT * ancho * 0.6, RIGHT * ancho * 0.6, color=GRIS, stroke_width=GROSOR_LINEA_MEDIA)
        self.marcos = VGroup()
        self.elementos: list[str] = []
        self.add(self.base, self.marcos)
        for elemento in elementos:
            marco = self._crear_marco(elemento)
            marco.move_to(self._posicion_siguiente())
            self.marcos.add(marco)
            self.elementos.append(str(elemento))

    @property
    def tamano(self) -> int:
        return len(self.elementos)

    def _crear_marco(self, etiqueta: str) -> VGroup:
        caja = RoundedRectangle(
            corner_radius=RADIO_CELDA,
            width=self.ancho,
            height=ALTO_MARCO_PILA,
            stroke_color=self.color,
            stroke_width=GROSOR_LINEA_FINA,
            fill_color=self.color,
            fill_opacity=OPACIDAD_RELLENO_CELDA,
        )
        texto = Texto(str(etiqueta), tamano=self.tamano_texto, color=BLANCO)
        texto.move_to(caja)
        return VGroup(caja, texto)

    def _posicion_siguiente(self) -> np.ndarray:
        if len(self.marcos) == 0:
            return self.base.get_center() + UP * (ALTO_MARCO_PILA / 2 + SEPARACION_MARCOS_PILA)
        return self.marcos[-1].get_center() + UP * (ALTO_MARCO_PILA + SEPARACION_MARCOS_PILA)

    def push(self, etiqueta: str) -> Animation:
        """Apila un marco nuevo (cae desde arriba)."""
        marco = self._crear_marco(etiqueta)
        marco.move_to(self._posicion_siguiente())
        self.marcos.add(marco)
        self.elementos.append(str(etiqueta))
        return FadeIn(marco, shift=DOWN * 0.4)

    def pop(self) -> Animation:
        """Desapila el marco superior (sale hacia arriba)."""
        if not self.elementos:
            raise IndexError("pop de una PilaVisual vacia")
        marco = self.marcos[-1]
        self.marcos.remove(marco)
        self.elementos.pop()
        return FadeOut(marco, shift=UP * 0.4)


__all__ = [
    "Celda",
    "ArregloVisual",
    "Puntero",
    "CodigoResaltado",
    "PilaVisual",
    "pasos_busqueda_binaria",
    "pasos_burbuja",
]
