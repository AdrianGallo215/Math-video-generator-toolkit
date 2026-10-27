"""Subtítulos karaoke sincronizados con la narración (``toolkit.narracion``).

Piezas puras (testeadas en ``tests/unit/test_subtitulos.py``):

- ``alinear_con_texto``: devuelve a las palabras temporizadas de edge-tts el texto ORIGINAL del guion
  (puntuación, ¿ ¡, mayúsculas); edge-tts las entrega sin signos y a veces con otra forma.
- ``agrupar_en_bloques``: parte la narración en bloques cortos y contiguos (tiempos absolutos de escena).
- ``indice_palabra_activa``, ``dividir_en_lineas``, ``color_base_de``.

``SubtitulosKaraoke`` es el mobject que las escenas base (``PlantillaShort``/``PlantillaShort3D``) crean y
fijan a la cámara. Un updater lee ``escena.renderer.time``: solo crea ``Text`` al cambiar de bloque; en cada
frame, a lo sumo recolorea la palabra activa o reposiciona el grupo si la cámara se movió.
"""

from __future__ import annotations

import bisect
import difflib
import logging
from dataclasses import dataclass, replace
from typing import Any, Callable, Sequence

import numpy as np
from manim import ORIGIN, Mobject, RoundedRectangle, VGroup

from .estilos import AMARILLO, BLANCO, FONDO, FUENTE_SUBTITULOS
from .layout import ZONA_SUBTITULOS, Zona
from .medios import normalizar_texto
from .narracion import PalabraTemporizada, SegmentoNarrado
from .tipografia import Texto, fuente_por_defecto

logger = logging.getLogger(__name__)

MAX_PALABRAS_BLOQUE = 4
MAX_CARACTERES_BLOQUE = 22
COLA_ULTIMO_BLOQUE = 0.2  # s que el último bloque sigue en pantalla tras su última palabra
COLA_PALABRA_ACTIVA = 0.25  # s que la última palabra del bloque sigue resaltada tras terminar
SIGNOS_DE_CORTE = ".,;:?!…"
CIERRES = "\"'»”’)]"

ESCALA_ACTIVA = 1.0  # solo color: escalar en su sitio estrechaba el espacio con las vecinas
OPACIDAD_FUTURA = 0.8
OPACIDAD_FONDO = 0.6
RADIO_FONDO = 0.18
RELLENO_FONDO = 0.18  # horizontal
RELLENO_VERTICAL = 0.1  # así caben 2 líneas a FUENTE_SUBTITULOS en ZONA_SUBTITULOS sin reducir el texto
ESPACIO_LINEAS = 0.08
MARGEN_ZONA = 0.05
Z_SUBTITULOS = 100  # igual que el HUD (base_scene.Z_INDEX_HUD); el texto va un nivel por encima del fondo

# Alineación: coste de unir varios tokens (o varias palabras temporizadas) en un mismo par.
_PENALIZACION_GRUPO = 0.35
_DESEMPATE_ANTERIOR = 0.001
_MAX_GRUPO = 6


# --- Alineación texto del guion ⇄ palabras temporizadas -------------------------------


def _clave(texto: str) -> str:
    """Forma comparable de un token: normalizada y sin espacios; si queda vacía, el token crudo."""
    return normalizar_texto(texto).replace(" ", "") or texto.strip()


def _coste_par(tokens: Sequence[str], palabras: Sequence[PalabraTemporizada]) -> float:
    a = "".join(_clave(t) for t in tokens)
    b = "".join(_clave(p.texto) for p in palabras)
    coste = 1.0 - difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()
    coste += _PENALIZACION_GRUPO * (len(tokens) - 1 + len(palabras) - 1)
    # Un token sin par se une preferentemente a la palabra ANTERIOR: penaliza apenas que el grupo
    # empiece por un token que no coincide con el inicio de la palabra.
    if len(tokens) > 1 and not b.startswith(_clave(tokens[0])):
        coste += _DESEMPATE_ANTERIOR
    return coste


def alinear_con_texto(palabras: list[PalabraTemporizada], texto: str) -> list[PalabraTemporizada]:
    """Asigna a las palabras temporizadas el texto original (con puntuación) de ``texto``.

    Alinea (programación dinámica monótona) los tokens de ``texto`` separados por espacios con
    ``palabras`` comparando ``normalizar_texto``. Cada par agrupa 1 token con k palabras o k tokens
    con 1 palabra; así se toleran números con otra forma ("100" ⇄ "cien"), palabras unidas por
    edge-tts ("1 a 100") o partidas ("x²", "+", "2x"). Un token sin par se une a la palabra anterior.
    Los tiempos se conservan: si un token cubre varias palabras, toma el inicio de la primera y el fin
    de la última. Devuelve una lista de longitud ≤ ``len(palabras)``, en orden.
    """
    tokens = texto.split()
    if not palabras:
        return []
    if not tokens:
        return list(palabras)
    n, m = len(tokens), len(palabras)
    maximo = _MAX_GRUPO if (n <= _MAX_GRUPO * m and m <= _MAX_GRUPO * n) else max(n, m)
    infinito = float("inf")
    coste = [[infinito] * (m + 1) for _ in range(n + 1)]
    previo: list[list[tuple[int, int] | None]] = [[None] * (m + 1) for _ in range(n + 1)]
    coste[0][0] = 0.0
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            opciones = [(1, 1)]
            opciones += [(a, 1) for a in range(2, min(maximo, i) + 1)]
            opciones += [(1, b) for b in range(2, min(maximo, j) + 1)]
            for a, b in opciones:
                base = coste[i - a][j - b]
                if base == infinito:
                    continue
                total = base + _coste_par(tokens[i - a : i], palabras[j - b : j])
                if total < coste[i][j]:
                    coste[i][j] = total
                    previo[i][j] = (a, b)
    pares: list[tuple[list[str], list[PalabraTemporizada]]] = []
    i, j = n, m
    while i > 0 and j > 0:
        paso = previo[i][j]
        assert paso is not None
        a, b = paso
        pares.append((tokens[i - a : i], palabras[j - b : j]))
        i, j = i - a, j - b
    pares.reverse()
    return [PalabraTemporizada(" ".join(ts), ps[0].inicio, ps[-1].fin) for ts, ps in pares]


# --- Bloques --------------------------------------------------------------------------


@dataclass(frozen=True)
class BloqueSubtitulo:
    """Grupo de palabras que se muestra a la vez. Todos los tiempos son ABSOLUTOS de escena."""

    palabras: tuple[PalabraTemporizada, ...]
    inicio: float
    fin: float


def _corta_tras(texto: str) -> bool:
    limpio = texto.rstrip(CIERRES)
    return bool(limpio) and limpio[-1] in SIGNOS_DE_CORTE


def agrupar_en_bloques(
    palabras: Sequence[PalabraTemporizada],
    inicio_segmento: float,
    max_palabras: int = MAX_PALABRAS_BLOQUE,
    max_caracteres: int = MAX_CARACTERES_BLOQUE,
) -> list[BloqueSubtitulo]:
    """Agrupa ``palabras`` (tiempos relativos al segmento) en bloques con tiempos absolutos.

    Primero corta tras palabras que terminan en ``. , ; : ? !`` (frases); cada frase se reparte en el
    MÍNIMO número de bloques con ≤ ``max_palabras`` palabras y ≤ ``max_caracteres`` caracteres
    (una palabra más larga va sola) y, entre esos repartos, el de bloques más parejos: se evitan
    palabras huérfanas ("dos," o "paso." solas). Los bloques son contiguos (fin = inicio del
    siguiente); el último termina ``COLA_ULTIMO_BLOQUE`` s tras su última palabra.
    """
    absolutas = [
        PalabraTemporizada(p.texto, inicio_segmento + p.inicio, inicio_segmento + p.fin) for p in palabras
    ]
    frases: list[list[PalabraTemporizada]] = []
    actual: list[PalabraTemporizada] = []
    for palabra in absolutas:
        actual.append(palabra)
        if _corta_tras(palabra.texto):
            frases.append(actual)
            actual = []
    if actual:
        frases.append(actual)
    grupos = [g for frase in frases for g in _repartir_frase(frase, max_palabras, max_caracteres)]
    bloques = []
    for k, grupo in enumerate(grupos):
        fin = grupos[k + 1][0].inicio if k + 1 < len(grupos) else grupo[-1].fin + COLA_ULTIMO_BLOQUE
        bloques.append(BloqueSubtitulo(tuple(grupo), grupo[0].inicio, fin))
    return bloques


def _repartir_frase(
    frase: list[PalabraTemporizada], max_palabras: int, max_caracteres: int
) -> list[list[PalabraTemporizada]]:
    """Partición de ``frase`` en el mínimo de trozos válidos, con el trozo más largo lo más corto posible."""
    n = len(frase)
    # mejor[i] = (n_trozos, caracteres_del_trozo_mas_largo) para las primeras i palabras.
    mejor: list[tuple[int, int] | None] = [None] * (n + 1)
    corte = [0] * (n + 1)
    mejor[0] = (0, 0)
    for i in range(1, n + 1):
        for j in range(i - 1, -1, -1):
            trozo = frase[j:i]
            largo = len(" ".join(p.texto for p in trozo))
            if len(trozo) > 1 and (len(trozo) > max_palabras or largo > max_caracteres):
                break  # alargar el trozo hacia atrás solo lo empeora
            previo = mejor[j]
            if previo is None:
                continue
            candidato = (previo[0] + 1, max(previo[1], largo))
            if mejor[i] is None or candidato < mejor[i]:
                mejor[i] = candidato
                corte[i] = j
    trozos = []
    i = n
    while i > 0:
        trozos.append(frase[corte[i] : i])
        i = corte[i]
    trozos.reverse()
    return trozos


def indice_palabra_activa(bloque: BloqueSubtitulo, t: float) -> int | None:
    """Índice de la palabra que se está diciendo en ``t`` (absoluto), o None.

    Una palabra sigue activa hasta que empieza la siguiente; la última, hasta ``COLA_PALABRA_ACTIVA`` s
    después de su fin.
    """
    inicios = [p.inicio for p in bloque.palabras]
    k = bisect.bisect_right(inicios, t) - 1
    if k < 0:
        return None
    if k == len(bloque.palabras) - 1 and t >= bloque.palabras[k].fin + COLA_PALABRA_ACTIVA:
        return None
    return k


def dividir_en_lineas(textos: Sequence[str]) -> list[list[str]]:
    """Parte las palabras en (a lo sumo) dos líneas de largo equilibrado (empate ⇒ primera más larga)."""
    textos = list(textos)
    if len(textos) < 2:
        return [textos]
    mejor_k, mejor = 1, None
    for k in range(1, len(textos)):
        a, b = len(" ".join(textos[:k])), len(" ".join(textos[k:]))
        clave = (max(a, b), abs(a - b), -k)
        if mejor is None or clave < mejor:
            mejor_k, mejor = k, clave
    return [textos[:mejor_k], textos[mejor_k:]]


def color_base_de(texto: str, colores_normalizados: dict[str, str], defecto: str) -> str:
    """Color de una palabra según ``colores`` (claves y palabra comparadas normalizadas)."""
    clave = normalizar_texto(texto)
    for k, color in colores_normalizados.items():
        if normalizar_texto(k) == clave:
            return color
    return defecto


# --- Mobject karaoke --------------------------------------------------------------------


def _vaciar(mob: Mobject) -> None:
    """Deja sin puntos a ``mob`` y su familia.

    Si el bloque cambia a mitad de un ``play``, manim sigue dibujando la lista de mobjects "en
    movimiento" calculada al empezar: los glifos del bloque anterior se verían encima del nuevo.
    """
    for m in mob.get_family():
        m.points = np.zeros((0, 3))


class SubtitulosKaraoke(VGroup):
    """Subtítulos por bloques con la palabra activa resaltada, sincronizados con ``renderer.time``.

    ``fuente``: familia para ``Texto`` (``None`` ⇒ ``fuente_por_defecto()``).
    ``escena``: de ella se toma el reloj (``renderer.time``); si tiene cámara móvil
    (``camera.frame`` y ``frame_referencia_ancho``) el contenido se mapea de pantalla a cámara; si es 3D,
    los mobjects nuevos se registran como fijos al cuadro. No se guarda la escena como atributo (las
    copias de mobjects no deben arrastrarla).
    """

    def __init__(
        self,
        escena: Any,
        zona: Zona = ZONA_SUBTITULOS,
        tamano: float = FUENTE_SUBTITULOS,
        color: str = BLANCO,
        color_activo: str = AMARILLO,
        colores_palabra: dict[str, str] | None = None,
        fuente: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.zona = zona
        self.tamano = tamano
        self.color_texto = color
        self.color_activo = color_activo
        self.colores_palabra = dict(colores_palabra or {})
        # ``None`` ⇒ fuente_por_defecto(), que consulta manimpango.list_fonts() (0.5-4 s por llamada):
        # las escenas base pasan la fuente ya resuelta al registrar las fuentes.
        self.fuente = fuente_por_defecto() if fuente is None else fuente
        self._metricas_fuente: tuple[float, float] | None = None
        self.bloques: list[BloqueSubtitulo] = []
        self.indice_activo: int | None = None
        self._bloque_mostrado: BloqueSubtitulo | None = None
        self._palabras_mob: list[VGroup] = []
        self._colores_base: list[str] = []
        self._escalada: int | None = None
        self._dichas_hasta: int = -1
        self._t: float | None = None  # entra en el hash de la caché de manim
        self._transformacion = (1.0, np.zeros(3))
        self._reloj, self._camara, self._registrar = _enlazar_escena(escena)
        self.add_updater(_actualizar_subtitulos)

    # --- API ----------------------------------------------------------------------------

    def programar(self, segmento: SegmentoNarrado, inicio: float) -> None:
        """Programa los bloques de ``segmento`` (que empieza en ``inicio``, tiempo de escena)."""
        palabras = alinear_con_texto(segmento.palabras, segmento.texto)
        nuevos = agrupar_en_bloques(palabras, inicio)
        if not nuevos:
            return
        # El último bloque cubre el silencio final del audio: entre narraciones seguidas (pausa_final
        # corta) no hay un parpadeo de pantalla vacía; la siguiente narración lo recorta.
        fin_audio = inicio + segmento.duracion + COLA_ULTIMO_BLOQUE
        if nuevos[-1].fin < fin_audio:
            nuevos[-1] = replace(nuevos[-1], fin=fin_audio)
        corte = nuevos[0].inicio
        previos = [b if b.fin <= corte else replace(b, fin=corte) for b in self.bloques if b.inicio < corte]
        self.bloques = previos + nuevos
        self.actualizar()

    def actualizar(self) -> None:
        """Sincroniza contenido, palabra activa y posición con el reloj y la cámara."""
        if self._reloj is None:
            return
        t = self._reloj()
        bloque = self._bloque_en(t)
        if _identidad(bloque) != _identidad(self._bloque_mostrado):
            self._reconstruir(bloque, t)
        else:
            self._bloque_mostrado = bloque  # mismo texto; quizá con otro ``fin`` (recortado): sin reconstruir
        if bloque is not None:
            activo = indice_palabra_activa(bloque, t)
            if activo is not None:
                dichas = activo
            else:
                dichas = len(bloque.palabras) if t >= bloque.palabras[0].inicio else -1
            if activo != self.indice_activo or dichas != self._dichas_hasta:
                self._aplicar_estilo(activo, dichas)
        self._sincronizar_camara()
        self._t = round(t, 4) if self._pendiente(t) else None

    def has_time_based_updater(self) -> bool:
        """True mientras quedan bloques por mostrar u ocultar: ``wait()`` no debe congelar el frame."""
        if super().has_time_based_updater():
            return True
        return self._reloj is not None and self._pendiente(self._reloj())

    # --- internos ---------------------------------------------------------------------

    def _pendiente(self, t: float) -> bool:
        return bool(self.submobjects) or any(b.fin > t for b in self.bloques)

    def _bloque_en(self, t: float) -> BloqueSubtitulo | None:
        inicios = [b.inicio for b in self.bloques]
        k = bisect.bisect_right(inicios, t) - 1
        if k >= 0 and t < self.bloques[k].fin:
            return self.bloques[k]
        return None

    def _reconstruir(self, bloque: BloqueSubtitulo | None, t: float) -> None:
        viejos = list(self.submobjects)
        self.remove(*viejos)
        for viejo in viejos:
            _vaciar(viejo)
        self._palabras_mob, self._colores_base = [], []
        self.indice_activo, self._escalada, self._dichas_hasta = None, None, -1
        self._bloque_mostrado = bloque
        self.bloques = [b for b in self.bloques if b.fin > t]  # poda: el hash no crece con la escena
        nuevos: list[Mobject] = []
        if bloque is not None:
            nuevos = self._construir(bloque)
            self.add(*nuevos)
        if self._registrar is not None:
            self._registrar(nuevos, viejos)

    def _construir(self, bloque: BloqueSubtitulo) -> list[Mobject]:
        """Fondo + líneas de texto del bloque, en coordenadas de pantalla y luego de cámara.

        Las líneas se colocan por su LÍNEA BASE con métricas fijas de la fuente (no por su caja): un
        bloque con tildes o descendentes no salta respecto al anterior y el fondo solo cambia de ancho.
        """
        textos = [p.texto for p in bloque.palabras]
        self._colores_base = [color_base_de(t, self.colores_palabra, self.color_texto) for t in textos]
        ancho_max = self.zona.ancho - 2 * (RELLENO_FONDO + MARGEN_ZONA)
        alto_max = self.zona.alto - 2 * RELLENO_VERTICAL
        lineas, palabras_mob, alto = self._crear_lineas([textos])
        if lineas.width > ancho_max and len(textos) > 1:
            lineas, palabras_mob, alto = self._crear_lineas(dividir_en_lineas(textos))
        # ``_crear_lineas`` deja el centro métrico del bloque en el origen.
        factor = min(1.0, ancho_max / lineas.width, alto_max / alto)
        if factor < 1.0:
            lineas.scale(factor, about_point=ORIGIN)
        lineas.shift(self.zona.centro)
        fondo = RoundedRectangle(
            width=lineas.width + 2 * RELLENO_FONDO,
            height=alto * factor + 2 * RELLENO_VERTICAL,
            corner_radius=RADIO_FONDO,
            stroke_width=0,
            fill_color=FONDO,
            fill_opacity=OPACIDAD_FONDO,
        ).move_to([lineas.get_center()[0], self.zona.centro[1], 0.0])
        fondo.set_z_index(Z_SUBTITULOS)
        lineas.set_z_index(Z_SUBTITULOS + 1)
        for i, mob in enumerate(palabras_mob):
            mob.set_fill(self._colores_base[i], opacity=1.0)
        self._palabras_mob = palabras_mob
        factor_cam, centro_cam = self._transformacion
        for mob in (fondo, lineas):
            mob.scale(factor_cam, about_point=ORIGIN)
            mob.shift(centro_cam)
        return [fondo, lineas]

    def _metricas(self) -> tuple[float, float]:
        """(ascendente, descendente) de la fuente al tamaño de los subtítulos, medidos una vez."""
        if self._metricas_fuente is None:
            referencia = Texto(
                "xhg", tamano=self.tamano, color=self.color_texto, font=self.fuente, disable_ligatures=True
            )
            base = referencia.submobjects[0].get_bottom()[1]
            self._metricas_fuente = (referencia.get_top()[1] - base, base - referencia.get_bottom()[1])
        return self._metricas_fuente

    def _crear_lineas(self, lineas_textos: list[list[str]]) -> tuple[VGroup, list[VGroup], float]:
        """Líneas centradas en x, con líneas base a paso fijo; devuelve (grupo, palabras, alto métrico)."""
        ascendente, descendente = self._metricas()
        paso = ascendente + descendente + ESPACIO_LINEAS
        alto = len(lineas_textos) * (ascendente + descendente) + (len(lineas_textos) - 1) * ESPACIO_LINEAS
        # Línea base de la primera línea, con el centro métrico del bloque en y = 0.
        base_0 = alto / 2 - ascendente
        lineas = VGroup()
        palabras_mob: list[VGroup] = []
        for k, textos in enumerate(lineas_textos):
            cadena = " ".join(textos)
            linea = Texto(
                cadena, tamano=self.tamano, color=self.color_texto, font=self.fuente, disable_ligatures=True
            )
            palabras_mob.extend(_trocear_en_palabras(linea, textos))
            linea.shift([-linea.get_center()[0], base_0 - k * paso - _linea_base(linea, cadena, descendente), 0.0])
            lineas.add(linea)
        return lineas, palabras_mob, alto

    def _aplicar_estilo(self, activo: int | None, dichas: int) -> None:
        if self._escalada is not None and self._escalada != activo:
            self._palabras_mob[self._escalada].scale(1.0 / ESCALA_ACTIVA)
            self._escalada = None
        for i, mob in enumerate(self._palabras_mob):
            if i == activo:
                mob.set_fill(self.color_activo, opacity=1.0)
            elif i < dichas:
                mob.set_fill(self._colores_base[i], opacity=1.0)
            else:
                mob.set_fill(self._colores_base[i], opacity=OPACIDAD_FUTURA)
        if activo is not None and self._escalada is None:
            self._palabras_mob[activo].scale(ESCALA_ACTIVA)
            self._escalada = activo
        self.indice_activo = activo
        self._dichas_hasta = dichas

    def _sincronizar_camara(self) -> None:
        if self._camara is None:
            return
        factor, centro = self._camara()
        factor_0, centro_0 = self._transformacion
        if np.isclose(factor, factor_0, rtol=1e-9, atol=0.0) and np.allclose(centro, centro_0, rtol=0.0, atol=1e-9):
            return
        if self.submobjects:
            self.shift(-centro_0)
            self.scale(factor / factor_0, about_point=ORIGIN)
            self.shift(centro)
        self._transformacion = (factor, np.array(centro, dtype=float))


def _identidad(bloque: BloqueSubtitulo | None) -> tuple | None:
    """Lo que se ve de un bloque (su ``fin`` puede recortarse sin que cambie el contenido)."""
    return None if bloque is None else (bloque.inicio, bloque.palabras)


def _actualizar_subtitulos(mob: Mobject) -> None:
    """Updater (no temporal) de ``SubtitulosKaraoke``; ``has_time_based_updater`` decide los ``wait``."""
    mob.actualizar()  # type: ignore[attr-defined]


_BASE_PLANA = set("hiklmnrvwxzEFHIKLMNPRTXZ147")
_BASE_REDONDA = set("abcdeostuABCDGOSU0235689")


def _linea_base(linea: Mobject, cadena: str, descendente: float) -> float:
    """y de la línea base de ``linea`` (un ``Text`` de ``cadena``) según un glifo sin descendente."""
    glifos = linea.submobjects
    if len(glifos) == len(cadena):
        for conjunto in (_BASE_PLANA, _BASE_REDONDA):
            for caracter, glifo in zip(cadena, glifos):
                if caracter in conjunto and glifo.has_points():
                    return float(glifo.get_bottom()[1])
    return float(linea.get_bottom()[1]) + descendente


def _trocear_en_palabras(linea: Mobject, textos: Sequence[str]) -> list[VGroup]:
    """Glifos de cada palabra de ``linea`` (un ``Text`` de ``" ".join(textos)``)."""
    glifos = list(linea.submobjects)
    cadena = " ".join(textos)
    con_espacios = len(glifos) == len(cadena)
    if not con_espacios and len(glifos) != len(cadena.replace(" ", "")):
        logger.debug("Glifos inesperados en %r: se resalta la línea completa", cadena)
        return [VGroup(*glifos) for _ in textos]
    grupos = []
    pos = 0
    for texto in textos:
        largo = len(texto)
        grupos.append(VGroup(*glifos[pos : pos + largo]))
        pos += largo + (1 if con_espacios else 0)
    return grupos


def _enlazar_escena(
    escena: Any,
) -> tuple[
    Callable[[], float] | None,
    Callable[[], tuple[float, np.ndarray]] | None,
    Callable[[list[Mobject], list[Mobject]], None] | None,
]:
    """Funciones (reloj, cámara 2D, registro 3D) que capturan la escena sin guardarla en el mobject."""
    if escena is None:
        return None, None, None

    def reloj() -> float:
        return float(escena.renderer.time)

    camara = None
    if hasattr(getattr(escena, "camera", None), "frame") and hasattr(escena, "frame_referencia_ancho"):

        def camara() -> tuple[float, np.ndarray]:
            frame = escena.camera.frame
            return frame.width / escena.frame_referencia_ancho, frame.get_center()

    registrar = None
    if hasattr(getattr(escena, "renderer", None), "camera") and hasattr(
        escena.renderer.camera, "add_fixed_in_frame_mobjects"
    ):

        def registrar(nuevos: list[Mobject], viejos: list[Mobject]) -> None:
            camara_3d = escena.renderer.camera
            if viejos:
                camara_3d.remove_fixed_in_frame_mobjects(*viejos)
            if nuevos:
                camara_3d.add_fixed_in_frame_mobjects(*nuevos)

    return reloj, camara, registrar
