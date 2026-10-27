"""Vocabulario de animación estilo 3Blue1Brown.

Funciones que devuelven ``Animation``/``AnimationGroup`` listas para ``scene.play`` (no llaman a
``play`` salvo ``transicion_seccion``, marcada "(escena)"). Los tiempos por defecto salen de
``toolkit.estilos`` y las ``rate_functions`` son las suaves de 3B1B (``smooth``, ``there_and_back``,
``double_smooth``): el énfasis es sobrio y siempre vuelve al estado de reposo.
"""

from __future__ import annotations

import logging
from typing import Iterable, Sequence

import numpy as np
from manim import (
    DOWN,
    LEFT,
    RIGHT,
    UP,
    Animation,
    AnimationGroup,
    Arrow,
    Brace,
    ChangeDecimalToValue,
    Circumscribe,
    Create,
    CurvedArrow,
    DecimalNumber,
    DrawBorderThenFill,
    FadeIn,
    FadeOut,
    Flash,
    Group,
    GrowArrow,
    GrowFromCenter,
    Indicate,
    LaggedStart,
    Line,
    MarkupText,
    MathTex,
    Mobject,
    Paragraph,
    ScaleInPlace,
    SingleStringMathTex,
    Succession,
    SurroundingRectangle,
    Text,
    Transform,
    Underline,
    VGroup,
    VMobject,
    Write,
)
from manim.utils.rate_functions import smooth, there_and_back

from toolkit.estilos import (
    AMARILLO,
    FUENTE_ETIQUETA,
    FUENTE_MINIMA,
    FUENTE_SUBTITULO,
    GRIS,
    GROSOR_LINEA_FINA,
    GROSOR_LINEA_MEDIA,
    OPACIDAD_ATENUADO,
    TIEMPO_CREAR,
    TIEMPO_ENFASIS,
    TIEMPO_TRANSFORMAR,
    TIEMPO_TRANSICION,
)
from toolkit.layout import ZONA_TITULO, Zona, encajar
from toolkit.tipografia import Texto, plantilla_tex_es

logger = logging.getLogger(__name__)

__all__ = [
    "aparecer",
    "aparecer_escalonado",
    "desaparecer",
    "enfocar",
    "restaurar",
    "resaltar",
    "caja_resultado",
    "llave_con_etiqueta",
    "flecha_etiquetada",
    "contar",
    "pulso",
    "transicion_seccion",
    "titulo_seccion",
    "mover_a_zona",
]

RUN_TIME_MAX_WRITE = 1.5
DESPLAZAMIENTO_ENTRADA = 0.4
DESPLAZAMIENTO_TRANSICION = 0.3
ESCALA_INDICAR = 1.15
RADIO_ESQUINA_CAJA = 0.12
BUFF_ETIQUETA = 0.15
RADIO_MAX_DESTELLO = 1.5

_TIPOS_TEXTO = (Text, MarkupText, Paragraph, SingleStringMathTex, DecimalNumber)
_CANALES_OPACIDAD = ("fill_rgbas", "stroke_rgbas", "background_stroke_rgbas")
ATRIBUTO_OPACIDAD = "opacidad_original"


# --- utilidades internas ----------------------------------------------------------------


def _como_lista(mobs: Mobject | Iterable[Mobject]) -> list[Mobject]:
    """Acepta un mob suelto o un iterable de mobs y devuelve una lista plana."""
    if isinstance(mobs, Mobject):
        return [mobs]
    return list(mobs)


def _hojas(mob: Mobject) -> list[Mobject]:
    return [m for m in mob.get_family() if len(m.points) > 0]


def _es_texto(mob: Mobject) -> bool:
    if isinstance(mob, _TIPOS_TEXTO):
        return True
    return type(mob) in (VGroup, Group) and len(mob.submobjects) > 0 and all(
        _es_texto(s) for s in mob.submobjects
    )


def _tiene_relleno(m: Mobject) -> bool:
    rgbas = getattr(m, "fill_rgbas", None)
    return rgbas is not None and len(rgbas) > 0 and bool(np.any(rgbas[:, 3] > 0))


def _crear_etiqueta(texto: str, tamano: float, color) -> Mobject:
    """MathTex si ``texto`` empieza por "$" o contiene "\\"; si no, ``Texto`` serif."""
    if texto.startswith("$") or "\\" in texto:
        contenido = texto.strip()
        if contenido.startswith("$") and contenido.endswith("$") and len(contenido) >= 2:
            contenido = contenido[1:-1]
        return MathTex(contenido, font_size=tamano, color=color, tex_template=plantilla_tex_es())
    return Texto(texto, tamano=tamano, color=color)


def _normalizar(v: np.ndarray) -> np.ndarray:
    norma = np.linalg.norm(v)
    return v / norma if norma > 1e-9 else np.zeros(3)


def _punto_borde(objetivo: Mobject | np.ndarray, hacia: np.ndarray, buff: float) -> np.ndarray:
    """Punto de ``objetivo`` en dirección a ``hacia`` (borde del mob + ``buff``); los puntos pasan tal cual."""
    if not isinstance(objetivo, Mobject):
        return np.array(objetivo, dtype=float)
    direccion = _normalizar(np.asarray(hacia, dtype=float) - objetivo.get_center())
    if not np.any(direccion):
        return objetivo.get_center()
    return objetivo.get_boundary_point(direccion) + direccion * buff


def _centro(objetivo: Mobject | np.ndarray) -> np.ndarray:
    if isinstance(objetivo, Mobject):
        return objetivo.get_center()
    return np.array(objetivo, dtype=float)


# --- aparición / salida -----------------------------------------------------------------


def aparecer(mob: Mobject, direccion=None, run_time: float = TIEMPO_CREAR) -> Animation:
    """Entrada adecuada al tipo de ``mob``.

    - ``direccion`` ⇒ ``FadeIn`` desplazado ``direccion * 0.4``.
    - Texto/Tex/números ⇒ ``Write`` (``run_time`` ≤ 1.5 s).
    - ``VGroup`` mixto ⇒ ``AnimationGroup`` con la entrada adecuada de cada hijo.
    - Todo con relleno ⇒ ``DrawBorderThenFill``; solo trazo (o mixto) ⇒ ``Create``.
    """
    if direccion is not None:
        return FadeIn(mob, shift=np.asarray(direccion) * DESPLAZAMIENTO_ENTRADA, run_time=run_time)
    if _es_texto(mob):
        return Write(mob, run_time=min(run_time, RUN_TIME_MAX_WRITE))
    if type(mob) in (VGroup, Group) and len(mob.submobjects) > 0:
        return AnimationGroup(*[aparecer(s, run_time=run_time) for s in mob.submobjects])
    if not isinstance(mob, VMobject):
        return FadeIn(mob, run_time=run_time)
    hojas = _hojas(mob)
    if hojas and all(_tiene_relleno(h) for h in hojas):
        return DrawBorderThenFill(mob, run_time=run_time)
    return Create(mob, run_time=run_time)


def aparecer_escalonado(
    mobs: Sequence[Mobject] | VGroup, lag: float = 0.12, run_time: float | None = None
) -> Animation:
    """``LaggedStart`` de ``aparecer`` sobre cada mob; duración total ~0.6 + 0.12·n (máx. 2.5 s)."""
    lista = list(mobs.submobjects) if isinstance(mobs, Mobject) else list(mobs)
    if not lista:
        raise ValueError("aparecer_escalonado necesita al menos un mob")
    if run_time is None:
        run_time = min(0.6 + 0.12 * len(lista), 2.5)
    return LaggedStart(*[aparecer(m) for m in lista], lag_ratio=lag, run_time=run_time)


def desaparecer(*mobs: Mobject, direccion=None, run_time: float = TIEMPO_TRANSICION) -> Animation:
    """``FadeOut`` de ``mobs`` (con desplazamiento ``direccion * 0.4`` opcional)."""
    if not mobs:
        raise ValueError("desaparecer necesita al menos un mob")
    kwargs = {"run_time": run_time}
    if direccion is not None:
        kwargs["shift"] = np.asarray(direccion) * DESPLAZAMIENTO_ENTRADA
    return FadeOut(*mobs, **kwargs)


# --- foco: enfocar / restaurar ----------------------------------------------------------


def _leer_alfas(m: VMobject) -> dict[str, np.ndarray]:
    alfas = {}
    for canal in _CANALES_OPACIDAD:
        rgbas = getattr(m, canal, None)
        if rgbas is not None and len(rgbas) > 0:
            alfas[canal] = np.array(rgbas[:, 3], dtype=float)
    return alfas


def _escribir_alfas(m: VMobject, alfas: dict[str, np.ndarray]) -> None:
    for canal, valores in alfas.items():
        rgbas = getattr(m, canal, None)
        if rgbas is None or len(rgbas) == 0:
            continue
        nuevos = np.array(rgbas, dtype=float)
        if len(valores) == len(nuevos):
            nuevos[:, 3] = valores
        else:  # el número de colores cambió: se usa el primer valor para todos
            nuevos[:, 3] = valores[0]
        setattr(m, canal, nuevos)


class _AnimarOpacidad(Animation):
    """Interpola las opacidades (relleno, trazo, trazo de fondo) de cada miembro de la familia.

    ``modo``:
    - ``"atenuar"``: guarda la opacidad original (si no estaba guardada) y va a ``original * factor``.
      Un relleno 0 sigue en 0: nunca se añade relleno.
    - ``"enfocar"``/``"restaurar"``: vuelve a la opacidad original guardada (si la hay) y la olvida.
    """

    def __init__(self, mob: Mobject, modo: str, factor: float = 1.0, **kwargs) -> None:
        self.modo = modo
        self.factor = factor
        self._planes: list[tuple[VMobject, dict, dict]] = []
        kwargs.setdefault("rate_func", smooth)
        super().__init__(mob, **kwargs)

    def create_starting_mobject(self) -> Mobject:
        return self.mobject  # no se usa: se evita copiar el mob

    def begin(self) -> None:
        self._planes = []
        for m in self.mobject.get_family():
            if not isinstance(m, VMobject):
                continue
            actual = _leer_alfas(m)
            original = getattr(m, ATRIBUTO_OPACIDAD, None)
            if self.modo == "atenuar":
                if original is None:
                    original = {k: v.copy() for k, v in actual.items()}
                    setattr(m, ATRIBUTO_OPACIDAD, original)
                destino = {k: v * self.factor for k, v in original.items()}
            else:
                if original is None:
                    continue
                destino = original
            self._planes.append((m, actual, destino))
        super().begin()

    def interpolate_mobject(self, alpha: float) -> None:
        t = self.rate_func(alpha)
        for m, inicio, destino in self._planes:
            _escribir_alfas(
                m, {k: inicio[k] + (destino[k] - inicio[k]) * t for k in destino if k in inicio}
            )

    def finish(self) -> None:
        super().finish()
        if self.modo != "atenuar":
            for m, _, _ in self._planes:
                if hasattr(m, ATRIBUTO_OPACIDAD):
                    delattr(m, ATRIBUTO_OPACIDAD)


def enfocar(
    foco: Mobject,
    resto: Mobject | Iterable[Mobject],
    opacidad: float = OPACIDAD_ATENUADO,
    run_time: float = 0.5,
) -> Animation:
    """Atenúa ``resto`` (opacidad original × ``opacidad``, preservando la relación relleno/trazo)
    y devuelve ``foco`` a su opacidad plena (la original guardada, si estaba atenuado).

    La opacidad original de cada submob queda en ``submob.opacidad_original`` hasta ``restaurar``.
    ``resto`` puede contener a ``foco`` (p. ej. todo el grupo): el foco gana.
    """
    animaciones = [_AnimarOpacidad(m, "atenuar", factor=opacidad) for m in _como_lista(resto)]
    animaciones.append(_AnimarOpacidad(foco, "enfocar"))
    return AnimationGroup(*animaciones, run_time=run_time)


def restaurar(mobs: Mobject | Iterable[Mobject], run_time: float = 0.5) -> Animation:
    """Devuelve ``mobs`` a la opacidad guardada por ``enfocar`` (los no atenuados no cambian)."""
    return AnimationGroup(
        *[_AnimarOpacidad(m, "restaurar") for m in _como_lista(mobs)], run_time=run_time
    )


# --- énfasis ----------------------------------------------------------------------------


def resaltar(
    mob: Mobject, color=AMARILLO, modo: str = "indicar", run_time: float | None = None
) -> Animation:
    """Énfasis sobrio sobre ``mob``.

    Modos: ``"indicar"`` (Indicate, escala 1.15), ``"rodear"`` (Circumscribe), ``"destello"``
    (Flash desde el centro, radio según el tamaño) y ``"subrayar"`` (Underline: Create y FadeOut).
    """
    if modo == "indicar":
        return Indicate(
            mob, scale_factor=ESCALA_INDICAR, color=color, run_time=run_time or TIEMPO_ENFASIS
        )
    if modo == "rodear":
        return Circumscribe(
            mob,
            color=color,
            buff=0.15,
            stroke_width=GROSOR_LINEA_MEDIA,
            time_width=0.5,
            run_time=run_time or 1.2,
        )
    if modo == "destello":
        radio = min(max(mob.width, mob.height) / 2 + 0.15, RADIO_MAX_DESTELLO)
        return Flash(
            mob,
            color=color,
            flash_radius=radio,
            line_length=0.3,
            line_stroke_width=GROSOR_LINEA_FINA,
            run_time=run_time or TIEMPO_ENFASIS,
        )
    if modo == "subrayar":
        total = run_time or 1.2
        linea = Underline(mob, buff=0.1, color=color, stroke_width=GROSOR_LINEA_MEDIA)
        return Succession(
            Create(linea, run_time=total * 0.4),
            Animation(linea, run_time=total * 0.25),
            FadeOut(linea, run_time=total * 0.35),
        )
    raise ValueError(f"modo de resaltar desconocido: {modo!r}")


def caja_resultado(
    mob: Mobject, color=AMARILLO, buff: float = 0.25
) -> tuple[SurroundingRectangle, Animation]:
    """Rectángulo redondeado alrededor de ``mob`` y su ``Create`` de 0.6 s."""
    caja = SurroundingRectangle(
        mob,
        color=color,
        buff=buff,
        corner_radius=RADIO_ESQUINA_CAJA,
        stroke_width=GROSOR_LINEA_MEDIA,
    )
    return caja, Create(caja, run_time=0.6)


def llave_con_etiqueta(
    mob: Mobject,
    texto_o_tex: str,
    direccion=DOWN,
    color=GRIS,
    tamano: float = FUENTE_ETIQUETA,
) -> tuple[VGroup, Animation]:
    """``Brace`` en ``direccion`` + etiqueta en su punta (MathTex si empieza por "$" o lleva "\\").

    Devuelve ``(VGroup(llave, etiqueta), animación)``; la animación es GrowFromCenter + Write.
    """
    llave = Brace(mob, direction=direccion, color=color)
    etiqueta = _crear_etiqueta(texto_o_tex, tamano, color)
    llave.put_at_tip(etiqueta, buff=BUFF_ETIQUETA)
    animacion = AnimationGroup(
        GrowFromCenter(llave, run_time=0.8),
        Write(etiqueta, run_time=0.8),
        lag_ratio=0.4,
    )
    return VGroup(llave, etiqueta), animacion


def flecha_etiquetada(
    desde: Mobject | np.ndarray,
    hasta: Mobject | np.ndarray,
    texto: str,
    color=GRIS,
    curvatura: float = 0.0,
) -> tuple[VGroup, Animation]:
    """Flecha (``Arrow`` o ``CurvedArrow`` si ``curvatura`` ≠ 0, en radianes) con etiqueta en el
    punto medio, desplazada perpendicularmente (hacia el lado convexo si es curva).

    ``desde``/``hasta`` pueden ser puntos o mobs (la flecha nace y muere en su borde).
    """
    inicio = _punto_borde(desde, _centro(hasta), BUFF_ETIQUETA)
    fin = _punto_borde(hasta, _centro(desde), BUFF_ETIQUETA)
    if abs(curvatura) < 1e-9:
        flecha: VMobject = Arrow(
            inicio, fin, buff=0, color=color, stroke_width=GROSOR_LINEA_MEDIA
        )
        crecer: Animation = GrowArrow(flecha, run_time=0.8)
    else:
        flecha = CurvedArrow(inicio, fin, angle=curvatura, color=color, stroke_width=GROSOR_LINEA_MEDIA)
        crecer = Create(flecha, run_time=0.8)

    medio = flecha.point_from_proportion(0.5)
    cuerda = fin - inicio
    if abs(curvatura) < 1e-9:
        normal = _normalizar(np.array([-cuerda[1], cuerda[0], 0.0]))
    else:
        normal = _normalizar(medio - (inicio + fin) / 2)
    if not np.any(normal):
        normal = UP

    etiqueta = _crear_etiqueta(texto, FUENTE_ETIQUETA, color)
    etiqueta.next_to(medio, normal, buff=BUFF_ETIQUETA)
    animacion = AnimationGroup(
        crecer,
        FadeIn(etiqueta, shift=normal * 0.2, run_time=0.6),
        lag_ratio=0.5,
    )
    return VGroup(flecha, etiqueta), animacion


def contar(mob_numero: DecimalNumber, hasta: float, run_time: float = 1.5) -> Animation:
    """Cuenta suavemente desde el valor actual hasta ``hasta`` (``ChangeDecimalToValue``)."""
    if not isinstance(mob_numero, DecimalNumber):
        raise TypeError(f"contar necesita un DecimalNumber/Integer, no {type(mob_numero).__name__}")
    return ChangeDecimalToValue(mob_numero, hasta, run_time=run_time, rate_func=smooth)


def pulso(mob: Mobject, escala: float = 1.06, run_time: float = 0.6) -> Animation:
    """"Respiración": escala hasta ``escala`` y vuelve (``there_and_back``)."""
    return ScaleInPlace(mob, escala, rate_func=there_and_back, run_time=run_time)


# --- secciones y layout -----------------------------------------------------------------


def transicion_seccion(escena, salientes: list, run_time: float = TIEMPO_TRANSICION) -> None:
    """(escena) Fundido corto de ``salientes`` subiendo 0.3 u, con sfx "whoosh" si la escena lo tiene."""
    salientes = [m for m in salientes if m is not None]
    if not salientes:
        return
    sfx = getattr(escena, "sfx", None)
    if callable(sfx):
        try:
            sfx("whoosh")
        except Exception:  # el audio es opcional: nunca rompe la escena
            logger.warning("No se pudo reproducir el sfx 'whoosh'", exc_info=True)
    escena.play(
        FadeOut(*salientes, shift=UP * DESPLAZAMIENTO_TRANSICION, run_time=run_time, rate_func=smooth)
    )


def titulo_seccion(texto: str, zona: Zona = ZONA_TITULO) -> Mobject:
    """Título de sección: ``Texto`` gris (FUENTE_SUBTITULO) con subrayado fino, encajado en ``zona``."""
    etiqueta = Texto(texto, tamano=FUENTE_SUBTITULO, color=GRIS)
    linea = Line(LEFT, RIGHT, color=GRIS, stroke_width=GROSOR_LINEA_FINA, stroke_opacity=0.6)
    linea.match_width(etiqueta)
    linea.next_to(etiqueta, DOWN, buff=0.12)
    grupo = VGroup(etiqueta, linea)
    ancho_previo = grupo.width
    encajar(grupo, zona=zona)
    tamano_efectivo = FUENTE_SUBTITULO * grupo.width / ancho_previo
    if tamano_efectivo < FUENTE_MINIMA:
        logger.warning(
            "titulo_seccion(%r) queda a tamaño %.0f (< FUENTE_MINIMA): acórtalo", texto, tamano_efectivo
        )
    return grupo


def mover_a_zona(mob: Mobject, zona: Zona, run_time: float = TIEMPO_TRANSFORMAR) -> Animation:
    """``Transform`` de ``mob`` a una copia suya encajada (escalada y centrada) en ``zona``."""
    destino = mob.copy()
    encajar(destino, zona=zona)
    return Transform(mob, destino, run_time=run_time)
