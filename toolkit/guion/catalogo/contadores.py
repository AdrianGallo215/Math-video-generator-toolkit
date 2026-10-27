"""Familia contadores del catálogo del guion: odómetro, barras de progreso y tabla de barras en una misma escala.

Piezas: tipos ``odometro``, ``barra``, ``tabla``; verbos ``contar``, ``llenar``, ``partir``.

Estado visual (riesgos R-estado y R-contar del análisis de cobertura):

- ``odometro`` usa :class:`NumeroOdometro`: ``set_value`` conserva el color/opacidad VISIBLES (manim reaplica el
  color de construcción), el separador de miles es configurable (espacio fino "100 000", coma "100,000" o
  ninguno) y el número queda anclado (a la izquierda junto a su rótulo, o centrado) aunque crezca.
- ``contar`` y ``llenar`` leen su valor inicial al EJECUTARSE (``begin`` de la animación), no al construirse:
  dentro de un grupo construido de antemano, con ``retraso`` o en cadena, cada paso arranca donde terminó el
  anterior, sin parpadeo a 0. ``pasos: k`` hace un escalón exacto (solo valores del escalón).
- ``partir`` corta la barra por la mitad (línea discontinua), la mitad descartada se tiñe y sale; la que queda
  vuelve a ocupar el largo completo (``reescalar``) o se queda a la mitad. Su id no cambia.
- ``tabla``: filas rótulo/barra/valor en UNA escala común; una fila con valor > escala desborda la zona a
  propósito (el «¡ajá!» de Big-O). Cada fila es ``id.<nombre>`` (o ``id.<k>``) con partes rotulo, barra, valor.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any

import numpy as np
from manim import (
    DOWN,
    LEFT,
    ORIGIN,
    RIGHT,
    UP,
    Animation,
    AnimationGroup,
    DecimalNumber,
    FadeIn,
    LaggedStart,
    Line,
    MathTex,
    Mobject,
    Rectangle,
    Succession,
    VectorizedPoint,
    VGroup,
    Wait,
)
from manim.utils.rate_functions import linear

from toolkit.estilos import (
    BLANCO,
    FONDO,
    FUENTE_CUERPO,
    FUENTE_MINIMA,
    GRIS,
    GROSOR_LINEA_FINA,
    GROSOR_LINEA_GRUESA,
    TIEMPO_CREAR,
)
from toolkit.guion.contexto import (
    ALINEACIONES,
    ATRIBUTO_PARTES,
    COLORES,
    MARGEN_ZONA,
    ContextoGuion,
    _error,
    separar_ref,
)
from toolkit.guion.registro import Param, accion, objeto
from toolkit.tipografia import Texto

logger = logging.getLogger(__name__)

# --- constantes de la familia ------------------------------------------------------------------------------------

SEPARADORES = ("espacio", "coma", "ninguno")
LADOS_ROTULO = ("izquierda", "arriba")
LADOS_PARTIR = ("izquierda", "derecha")
TAMANO_ODOMETRO = 72
FACTOR_ROTULO = 0.6  # rótulo del odómetro respecto al número (nunca por debajo de FUENTE_MINIMA)
ESPACIO_ROTULO = 0.3
MAX_DECIMALES = 6
ALTO_BARRA = 0.5
ALTO_BARRA_TABLA = 0.42
OPACIDAD_BARRA = 0.9
ANCHO_MINIMO = 1e-3  # ancho del relleno "vacío" (un rectángulo de ancho 0 no se puede estirar)
MAX_SEGMENTOS = 64
MAX_VECES_PARTIR = 8
SOBRANTE_CORTE = 0.3  # la línea de corte asoma por arriba y por abajo de la barra
TRAZOS_CORTE = 7
PROPORCION_TRAZO_CORTE = 0.6
SEPARACION_MITADES = 0.12
DESPLAZAMIENTO_DESCARTE = 0.35  # sale sin cruzar el borde de la zona segura (se desvanece a la vez)
TIEMPOS_FASE = (0.25, 0.35, 0.4)  # corte · separación · salida (proporciones de cada corte)
ESPACIO_TABLA = 0.3
ESPACIO_FILAS = 0.35
LARGO_MINIMO_TABLA = 1.0
CLAVES_FILA = ("rotulo", "tex", "valor", "texto", "color", "nombre")
FACTOR_VALOR_TABLA = 0.85  # tamaño del texto de valor respecto al rótulo

ATRIBUTO_BARRA = "barra_guion"

_PARAM_ZONA = Param("zona", "zona", defecto="principal",
                    descripcion="Zona donde se encaja (nombre) o {de: id, lado: abajo|arriba|izq|der, espacio: 0.3}.")
_PARAM_ALINEACION = Param("alineacion", "texto", defecto="centro", opciones=tuple(ALINEACIONES),
                          descripcion="Borde de la zona al que se pega.")


# --- funciones puras -----------------------------------------------------------------------------------------------


def valor_contado(inicio: float, fin: float, alfa: float, pasos: int = 0) -> float:
    """Valor de un conteo ``inicio → fin`` en ``alfa`` ∈ [0, 1].

    ``pasos = 0``: interpolación continua. ``pasos = k``: escalón exacto de ``k`` saltos iguales; el primer salto
    ocurre apenas empieza (``alfa > 0``) y el último en el tramo final, así que solo aparecen valores del escalón
    y cada salto coincide con el inicio de su k-ésimo del tiempo.
    """
    a = min(1.0, max(0.0, float(alfa)))
    if pasos and pasos > 0:
        n = max(0, min(int(pasos), math.ceil(a * pasos - 1e-9)))
        return inicio + (fin - inicio) * n / pasos
    return inicio + (fin - inicio) * a


def mitades_de_barra(ancho: float, veces: int, reescalar: bool = True) -> list[float]:
    """Ancho del relleno tras cada uno de ``veces`` cortes (con ``reescalar`` la mitad que queda vuelve al largo)."""
    anchos = []
    for _ in range(max(0, int(veces))):
        ancho = ancho if reescalar else ancho / 2.0
        anchos.append(ancho)
    return anchos


def _es_numero(valor: Any) -> bool:
    return isinstance(valor, (int, float)) and not isinstance(valor, bool)


def _con_partes(grupo: Mobject, partes: dict[str, Mobject]) -> Mobject:
    setattr(grupo, ATRIBUTO_PARTES, partes)
    return grupo


def reconsolidar_despues(ctx: ContextoGuion, ref: str) -> None:
    """Tras el ``play`` del grupo, deja el objeto registrado de ``ref`` entero y encima en la escena.

    ManimCE, al reproducir un ``AnimationGroup``/``Succession`` cuyas animaciones mueven PARTES de un VGroup
    (el relleno de una barra, el número de un odómetro), reestructura la escena: saca esas partes del VGroup y
    las vuelve a añadir sueltas al final (se pintan encima de sus hermanas: p. ej. el relleno tapa las divisiones
    de la barra). Esta tarea lo recompone. No hace nada si el objeto ya se quitó (``quitar`` en el mismo grupo).
    """
    if ctx.escena is None:
        return
    id_raiz = separar_ref(ref)[0]
    raiz = ctx.objetos.get(id_raiz)
    if raiz is None:
        return

    def recomponer() -> None:
        if ctx.objetos.get(id_raiz) is raiz:
            ctx.consolidar(raiz)

    ctx.despues(recomponer)


def _usar(estado, params: dict, *nombres: str) -> bool:
    ok = True
    for nombre in nombres:
        valor = params.get(nombre)
        if valor is None:
            continue
        if isinstance(valor, list):
            estado.error("E3", f"'{nombre}' admite un solo id aquí, no una lista")
            ok = False
            continue
        ok = estado.usar(valor) and ok
    zona = params.get("zona")
    if isinstance(zona, dict) and isinstance(zona.get("de"), str):
        estado.usar(zona["de"], permitir_reservado=True)
    return ok


# --- odómetro ------------------------------------------------------------------------------------------------------


class NumeroOdometro(DecimalNumber):
    """``DecimalNumber`` con separador de miles configurable, anclaje fijo y color estable.

    - ``separador``: ``"espacio"`` (100 000, coma decimal), ``"coma"`` (100,000) o ``"ninguno"``.
    - ``ancla``: borde que no se mueve cuando el número cambia de ancho (``LEFT``, ``ORIGIN`` o ``UP``).
    - ``set_value`` reaplica el color y la opacidad que el número TENÍA (no el de construcción).
    """

    def __init__(self, valor: float = 0, separador: str = "espacio", decimales: int = 0,
                 tamano: float = TAMANO_ODOMETRO, color=BLANCO, ancla=LEFT) -> None:
        self.separador = separador
        super().__init__(
            valor,
            num_decimal_places=int(decimales),
            group_with_commas=separador != "ninguno",
            font_size=tamano,
            color=color,
            edge_to_fix=ancla,
        )

    def _string_to_mob(self, string: str, mob_class=None, **kwargs: Any):
        if string == "." and getattr(self, "separador", "") == "espacio":
            string = "{,}"  # coma decimal (convención LatAm con espacio de miles)
        return super()._string_to_mob(string, mob_class, **kwargs)

    def _set_submobjects_from_number(self, number: float) -> None:
        super()._set_submobjects_from_number(number)
        if getattr(self, "separador", "") != "espacio":
            return
        cadena = self._get_num_string(number)
        for i, caracter in enumerate(cadena):
            if caracter == "," and i < len(self.submobjects):
                # La coma deja su hueco (espacio fino) y desaparece.
                self.submobjects[i] = VectorizedPoint(self.submobjects[i].get_center())
        self.initial_height = self.height

    def _estilo_visible(self) -> tuple[Any, float] | None:
        for sub in self.submobjects:
            if isinstance(sub, VectorizedPoint):
                continue
            hojas = sub.family_members_with_points()
            if hojas:
                return hojas[0].get_fill_color(), float(hojas[0].get_fill_opacity())
        return None

    def set_value(self, number: float):
        estilo = self._estilo_visible()
        super().set_value(number)
        if estilo is not None:
            self.set_fill(estilo[0], opacity=estilo[1])
        return self

    def fijar_tamano(self, tamano: float) -> None:
        """Cambia el tamaño (puntos) sin mover su borde de anclaje."""
        punto = self.get_critical_point(self.edge_to_fix)
        self.font_size = float(tamano)
        self.move_to(punto, aligned_edge=self.edge_to_fix)


def _ciclo_odometro(params: dict, estado) -> None:
    _usar(estado, params)
    decimales = params.get("decimales", 0)
    if isinstance(decimales, int) and not 0 <= decimales <= MAX_DECIMALES:
        estado.error("E3", f"decimales: entre 0 y {MAX_DECIMALES}")


@objeto(
    "odometro",
    "Número grande que cuenta (con 'contar'), con rótulo opcional y separador de miles; conserva su color y queda "
    "anclado aunque crezca. Partes: rotulo, numero.",
    params=[
        Param("valor", "numero", defecto=0, descripcion="Valor inicial."),
        Param("rotulo", "texto", descripcion="Texto que acompaña al número (p. ej. \"Datos\")."),
        Param("lado_rotulo", "texto", defecto="izquierda", opciones=LADOS_ROTULO,
              descripcion="Dónde va el rótulo: a la izquierda (el número crece a la derecha) o arriba (centrado)."),
        Param("separador", "texto", defecto="espacio", opciones=SEPARADORES,
              descripcion="Separador de miles: espacio fino (100 000, coma decimal), coma (100,000) o ninguno."),
        Param("decimales", "entero", defecto=0, descripcion="Cifras decimales."),
        Param("maximo", "numero", descripcion="Valor más ancho que mostrará (reserva su lugar para no salirse de la zona)."),
        Param("tamano", "numero", defecto=TAMANO_ODOMETRO, descripcion=f"Tamaño del número en puntos (mínimo {FUENTE_MINIMA})."),
        Param("color", "color", defecto="blanco", descripcion="Color del número."),
        Param("color_rotulo", "color", defecto="gris", descripcion="Color del rótulo."),
        _PARAM_ZONA,
        _PARAM_ALINEACION,
    ],
    ejemplo={"en": "inicio", "hacer": "mostrar", "id": "odo", "tipo": "odometro", "valor": 0, "rotulo": "Datos",
             "maximo": 1000000},
    duracion=TIEMPO_CREAR,
    ciclo=_ciclo_odometro,
)
def crear_odometro(ctx: ContextoGuion, valor, lado_rotulo, separador, decimales, tamano, color, color_rotulo,
                   zona, alineacion, rotulo=None, maximo=None) -> Mobject:
    hex_color = ctx.color(color)
    if rotulo:
        ancla = LEFT if lado_rotulo == "izquierda" else UP
    else:
        ancla = ORIGIN
    reserva = max(abs(float(valor)), abs(float(maximo))) if maximo is not None else float(valor)
    if maximo is not None and float(valor) < 0:
        reserva = -reserva
    numero = NumeroOdometro(reserva, separador=separador, decimales=decimales, tamano=float(tamano),
                            color=hex_color, ancla=ancla)
    partes: dict[str, Mobject] = {"numero": numero}
    if rotulo:
        texto = Texto(str(rotulo), tamano=max(FUENTE_MINIMA, float(tamano) * FACTOR_ROTULO),
                      color=ctx.color(color_rotulo))
        grupo = VGroup(texto, numero)
        grupo.arrange(RIGHT if lado_rotulo == "izquierda" else DOWN, buff=ESPACIO_ROTULO)
        partes["rotulo"] = texto
    else:
        grupo = VGroup(numero)
    _con_partes(grupo, partes)
    ctx.colocar(grupo, zona, alineacion)
    numero.set_value(float(valor))
    if numero.font_size < FUENTE_MINIMA - 0.5:
        logger.warning("odometro queda a tamaño %.0f (< %d): dale una zona más grande o un 'maximo' menor",
                       numero.font_size, FUENTE_MINIMA)
    return grupo


def _numero_de(ctx: ContextoGuion, ref: str) -> NumeroOdometro | DecimalNumber:
    mob = ctx.obtener(ref)
    if isinstance(mob, DecimalNumber):
        return mob
    partes = getattr(mob, ATRIBUTO_PARTES, None) or {}
    numero = partes.get("numero")
    if isinstance(numero, DecimalNumber):
        return numero
    raise _error("E3", f"'{ref}' no es un odometro (contar necesita un número)", ctx.ubicacion)


class AnimacionDiferida(Animation):
    """Base de las animaciones de valor del guion (contar, llenar, mover_variable).

    - Leen su estado inicial en ``begin`` (al EMPEZAR a reproducirse), no al construirse.
    - Escriben su valor final UNA sola vez: ``AnimationGroup.finish`` vuelve a llamar a ``finish`` de todas sus
      animaciones al terminar el grupo; sin esta guarda, en una cadena dentro del mismo grupo (con ``retraso``) el
      primer paso reescribiría su valor final encima del último (el contador "salta atrás").
    """

    def __init__(self, mobject: Mobject, **kwargs: Any) -> None:
        self._completada = False
        super().__init__(mobject, **kwargs)

    def leer_inicio(self) -> None:  # pragma: no cover - abstracto
        raise NotImplementedError

    def aplicar(self, alfa: float) -> None:  # pragma: no cover - abstracto
        raise NotImplementedError

    def begin(self) -> None:
        self._completada = False
        self.leer_inicio()
        super().begin()

    def interpolate_mobject(self, alpha: float) -> None:
        if self._completada:
            return
        self.aplicar(self.rate_func(alpha))
        if alpha >= 1.0:
            self._completada = True

    def finish(self) -> None:
        if self._completada:
            if self.suspend_mobject_updating and self.mobject is not None:
                self.mobject.resume_updating()
            return
        super().finish()


class ContarDiferido(AnimacionDiferida):
    """Cuenta hasta ``hasta`` leyendo el valor inicial al EMPEZAR (no al construirse): encadenable sin parpadeo."""

    def __init__(self, numero: DecimalNumber, hasta: float, desde: float | None = None, pasos: int = 0,
                 tamano: float | None = None, **kwargs: Any) -> None:
        self.hasta = float(hasta)
        self.desde = None if desde is None else float(desde)
        self.pasos = int(pasos or 0)
        self.tamano_final = None if tamano is None else float(tamano)
        self.inicio = 0.0
        self.tamano_inicial = 0.0
        super().__init__(numero, **kwargs)

    def leer_inicio(self) -> None:
        self.inicio = self.desde if self.desde is not None else float(self.mobject.get_value())
        self.tamano_inicial = float(self.mobject.font_size)

    def aplicar(self, alfa: float) -> None:
        numero = self.mobject
        numero.set_value(round(valor_contado(self.inicio, self.hasta, alfa, self.pasos), numero.num_decimal_places))
        if self.tamano_final is not None:
            tamano = self.tamano_inicial + (self.tamano_final - self.tamano_inicial) * alfa
            if isinstance(numero, NumeroOdometro):
                numero.fijar_tamano(tamano)
            else:
                numero.font_size = tamano


def _ciclo_contar(params: dict, estado) -> None:
    _usar(estado, params, "objeto")
    pasos = params.get("pasos", 0)
    if isinstance(pasos, int) and pasos < 0:
        estado.error("E3", "pasos: 0 (continuo) o el número de saltos del escalón (≥ 1)")


@accion(
    "contar",
    "El odómetro cuenta hasta 'a' desde donde esté al empezar (o desde 'desde'); 'pasos: k' da k saltos exactos "
    "(p. ej. 1, 2, 3). Encadenable: cada contar arranca donde terminó el anterior. No lo combines con la entrada "
    "del mismo odómetro en el mismo instante.",
    params=[
        Param("objeto", "objeto", requerido=True, descripcion="Id del odometro (o 'id.numero')."),
        Param("a", "numero", requerido=True, descripcion="Valor final."),
        Param("desde", "numero", descripcion="Valor inicial explícito (defecto: el que muestre al empezar)."),
        Param("pasos", "entero", defecto=0, descripcion="0 = continuo; k = k saltos iguales (ritmo lineal)."),
        Param("tamano", "numero", descripcion=f"Tamaño final del número en puntos (anima el tamaño; mínimo {FUENTE_MINIMA})."),
    ],
    ejemplo={"en": "inicio", "hacer": "contar", "objeto": "odo", "a": 1000000, "dur": 2.0},
    duracion=1.5,
    modificadores=("rate",),
    ciclo=_ciclo_contar,
)
def contar(ctx: ContextoGuion, objeto, a, pasos=0, desde=None, tamano=None):
    numero = _numero_de(ctx, objeto)
    ctx.marcar_foco(separar_ref(objeto)[0])
    reconsolidar_despues(ctx, objeto)
    extra = {"rate_func": linear} if pasos else {}
    return ContarDiferido(numero, a, desde=desde, pasos=pasos, tamano=tamano, **extra)


# --- barra ----------------------------------------------------------------------------------------------------------


@dataclass
class EstadoBarra:
    """Referencias internas de una barra (el VGroup de la barra lleva esto en ``barra_guion``)."""

    relleno: Rectangle
    ancla: VectorizedPoint  # centro del borde izquierdo (origen de la escala)
    tope: VectorizedPoint  # donde termina la escala completa (valor = maximo)
    maximo: float
    objetivo: float | None = None  # valor al que llenar si 'llenar' no dice 'a' (filas de tabla)
    texto_pendiente: Mobject | None = None  # texto de valor que aparece al llenarse (tabla vacía)
    fila: Mobject | None = None
    raiz: Mobject | None = None  # objeto registrado que contiene la barra (para reconsolidar)

    @property
    def largo(self) -> float:
        return float(self.tope.get_center()[0] - self.ancla.get_center()[0])

    def fraccion(self) -> float:
        largo = self.largo
        ancho = float(self.relleno.width)
        return 0.0 if largo <= 0 or ancho <= 2 * ANCHO_MINIMO else ancho / largo

    def fijar_fraccion(self, fraccion: float) -> None:
        ancho = max(float(fraccion) * self.largo, ANCHO_MINIMO)
        self.relleno.stretch_to_fit_width(ancho)
        self.relleno.move_to(self.ancla.get_center(), aligned_edge=LEFT)


def _armar_barra(largo: float, alto: float, color, maximo: float, valor: float, marco: bool,
                 segmentos: int) -> VGroup:
    ancla = VectorizedPoint(ORIGIN)
    tope = VectorizedPoint(RIGHT * largo)
    relleno = Rectangle(width=largo, height=alto, stroke_width=0, fill_color=color, fill_opacity=OPACIDAD_BARRA)
    relleno.move_to(ORIGIN, aligned_edge=LEFT)
    miembros: list[Mobject] = [ancla, tope]
    partes: dict[str, Mobject] = {"relleno": relleno}
    if marco:
        caja = Rectangle(width=largo, height=alto, stroke_color=GRIS, stroke_width=GROSOR_LINEA_FINA, fill_opacity=0)
        caja.move_to(ORIGIN, aligned_edge=LEFT)
        miembros.append(caja)
        partes["marco"] = caja
    miembros.append(relleno)
    if segmentos > 1:
        divisiones = VGroup(*[
            Line(RIGHT * largo * k / segmentos + UP * alto / 2, RIGHT * largo * k / segmentos + DOWN * alto / 2,
                 stroke_color=FONDO, stroke_width=GROSOR_LINEA_FINA)
            for k in range(1, segmentos)
        ])
        miembros.append(divisiones)
        partes["divisiones"] = divisiones
    barra = _con_partes(VGroup(*miembros), partes)
    estado = EstadoBarra(relleno=relleno, ancla=ancla, tope=tope, maximo=float(maximo))
    setattr(barra, ATRIBUTO_BARRA, estado)
    estado.fijar_fraccion(float(valor) / float(maximo))
    return barra


def _ciclo_barra(params: dict, estado) -> None:
    _usar(estado, params)
    maximo = params.get("maximo")
    if _es_numero(maximo) and maximo <= 0:
        estado.error("E3", "maximo: debe ser positivo (el valor que llena la barra)")
    valor = params.get("valor")
    if _es_numero(valor) and valor < 0:
        estado.error("E3", "valor: no puede ser negativo")
    largo = params.get("largo")
    if _es_numero(largo) and not 0 < largo <= 1:
        estado.error("E3", "largo: fracción (0-1] del ancho de la zona")
    alto = params.get("alto")
    if _es_numero(alto) and alto <= 0:
        estado.error("E3", "alto: debe ser positivo")
    segmentos = params.get("segmentos")
    if isinstance(segmentos, int) and not 0 <= segmentos <= MAX_SEGMENTOS:
        estado.error("E3", f"segmentos: entre 0 y {MAX_SEGMENTOS}")


@objeto(
    "barra",
    "Barra de progreso horizontal anclada a la izquierda: 'valor' de 'maximo' lleno; se llena con 'llenar' y se "
    "parte a la mitad con 'partir'. 'segmentos' la divide en celdas. Partes: relleno, marco, divisiones.",
    params=[
        Param("valor", "numero", defecto=1.0, descripcion="Cuánto está llena (en las unidades de 'maximo')."),
        Param("maximo", "numero", defecto=1.0, descripcion="Valor que corresponde a la barra llena."),
        Param("color", "color", defecto="azul", descripcion="Color del relleno."),
        Param("marco", "booleano", defecto=True, descripcion="Contorno gris del largo completo (la pista)."),
        Param("segmentos", "entero", defecto=0, descripcion="Nº de celdas (0 = continua; 16 = un arreglo de 16)."),
        Param("largo", "numero", defecto=0.9, descripcion="Largo como fracción (0-1] del ancho de la zona."),
        Param("alto", "numero", defecto=ALTO_BARRA, descripcion="Grosor de la barra (unidades de escena)."),
        _PARAM_ZONA,
        _PARAM_ALINEACION,
    ],
    ejemplo={"en": "inicio", "hacer": "mostrar", "id": "barra", "tipo": "barra", "valor": 1, "segmentos": 16},
    duracion=TIEMPO_CREAR,
    ciclo=_ciclo_barra,
)
def crear_barra(ctx: ContextoGuion, valor, maximo, color, marco, segmentos, largo, alto, zona, alineacion) -> Mobject:
    referencia = ctx.zona_de_referencia(zona)
    largo_real = (referencia.ancho - 2 * MARGEN_ZONA) * float(largo)
    barra = _armar_barra(largo_real, float(alto), ctx.color(color), float(maximo), 0.0, marco, int(segmentos))
    ctx.colocar(barra, zona, alineacion)
    estado: EstadoBarra = getattr(barra, ATRIBUTO_BARRA)
    estado.fijar_fraccion(float(valor) / float(maximo))
    if float(valor) > float(maximo):
        logger.info("barra con valor %s > maximo %s: desborda su zona a propósito", valor, maximo)
    return barra


def _barra_de(ctx: ContextoGuion, ref: str) -> tuple[Mobject, EstadoBarra]:
    mob = ctx.obtener(ref)
    estado = getattr(mob, ATRIBUTO_BARRA, None)
    if estado is None:
        partes = getattr(mob, ATRIBUTO_PARTES, None) or {}
        interna = partes.get("barra")
        estado = getattr(interna, ATRIBUTO_BARRA, None) if interna is not None else None
        mob = interna if estado is not None else mob
    if estado is None:
        raise _error("E3", f"'{ref}' no es una barra ni una fila de tabla", ctx.ubicacion)
    return mob, estado


class LlenarDiferido(AnimacionDiferida):
    """Lleva la barra a la fracción ``hasta`` desde la que tenga al EMPEZAR (o ``desde``)."""

    def __init__(self, barra: Mobject, hasta: float, desde: float | None = None, **kwargs: Any) -> None:
        self.estado_barra: EstadoBarra = getattr(barra, ATRIBUTO_BARRA)
        self.hasta = float(hasta)
        self.desde = None if desde is None else float(desde)
        self.inicio = 0.0
        super().__init__(barra, **kwargs)

    def leer_inicio(self) -> None:
        self.inicio = self.desde if self.desde is not None else self.estado_barra.fraccion()

    def aplicar(self, alfa: float) -> None:
        self.estado_barra.fijar_fraccion(self.inicio + (self.hasta - self.inicio) * alfa)


def _animacion_llenar(ctx: ContextoGuion, barra: Mobject, estado: EstadoBarra, a, desde) -> Animation:
    destino = estado.objetivo if a is None else float(a)
    if destino is None:
        raise _error("E3", "falta 'a' (valor al que llenar la barra)", ctx.ubicacion)
    llenado = LlenarDiferido(barra, destino / estado.maximo,
                             desde=None if desde is None else float(desde) / estado.maximo)
    texto = estado.texto_pendiente
    if texto is None:
        return llenado
    estado.texto_pendiente = None
    fila, raiz = estado.fila, estado.raiz

    def adoptar() -> None:
        if fila is not None:
            fila.add(texto)
        if raiz is not None:
            ctx.consolidar(raiz)

    ctx.despues(adoptar)
    return AnimationGroup(llenado, Succession(Wait(run_time=0.5), FadeIn(texto, run_time=0.5)))


def _ciclo_llenar(params: dict, estado) -> None:
    _usar(estado, params, "objeto")
    for clave in ("a", "desde"):
        valor = params.get(clave)
        if _es_numero(valor) and valor < 0:
            estado.error("E3", f"{clave}: no puede ser negativo")


@accion(
    "llenar",
    "Llena (o vacía) una barra hasta 'a' desde donde esté al empezar. Sobre una tabla o una fila sin 'a', llena "
    "hasta el valor de cada fila (y hace aparecer su texto). Un valor mayor que la escala desborda la zona.",
    params=[
        Param("objeto", "objeto", requerido=True, descripcion="Id de una barra, de una tabla o de una fila ('tabla.fila')."),
        Param("a", "numero", descripcion="Valor final (unidades de 'maximo'/'escala'); omitir en tablas = el de la fila."),
        Param("desde", "numero", descripcion="Valor inicial explícito (defecto: el actual al empezar)."),
    ],
    ejemplo={"en": "inicio", "hacer": "llenar", "objeto": "barra", "a": 0.5},
    duracion=TIEMPO_CREAR,
    modificadores=("rate", "escalonado"),
    ciclo=_ciclo_llenar,
)
def llenar(ctx: ContextoGuion, objeto, a=None, desde=None, escalonado=0.0):
    ctx.marcar_foco(separar_ref(objeto)[0])
    reconsolidar_despues(ctx, objeto)
    mob = ctx.obtener(objeto)
    filas = getattr(mob, "filas_guion", None)
    if filas is not None:  # la tabla entera: cada fila hasta su valor (o todas hasta 'a')
        anims = []
        for fila in filas:
            barra = ctx.parte(fila, "barra")
            anims.append(_animacion_llenar(ctx, barra, getattr(barra, ATRIBUTO_BARRA), a, desde))
        return LaggedStart(*anims, lag_ratio=escalonado) if escalonado > 0 else AnimationGroup(*anims)
    barra, estado = _barra_de(ctx, objeto)
    return _animacion_llenar(ctx, barra, estado, a, desde)


# --- partir ---------------------------------------------------------------------------------------------------------


def _ciclo_partir(params: dict, estado) -> None:
    _usar(estado, params, "objeto")
    veces = params.get("veces", 1)
    if isinstance(veces, int) and not 1 <= veces <= MAX_VECES_PARTIR:
        estado.error("E3", f"veces: entre 1 y {MAX_VECES_PARTIR} (da un dur de ~1 s por corte)")


def _suave(x: float) -> float:
    x = min(1.0, max(0.0, x))
    return x * x * (3.0 - 2.0 * x)


def geometria_corte(ancho: float, ancho_final: float, lado: str, t: float) -> dict:
    """Estado de UN corte en su instante local ``t`` ∈ [0, 1] (x relativas al origen izquierdo de la barra).

    Fases (``TIEMPOS_FASE``): la línea de corte crece; la mitad que sale se tiñe y se separa; sale (se desplaza
    y se desvanece) mientras la que queda pasa a ocupar ``[0, ancho_final]``. Devuelve ``relleno`` (izq, der),
    ``descarte`` (izq, der), ``opacidad_descarte`` (0-1), ``corte`` (fracción 0-1 de su largo) y
    ``opacidad_corte``.
    """
    t1, t2, _ = TIEMPOS_FASE
    mitad = ancho / 2.0
    signo = 1.0 if lado == "izquierda" else -1.0  # hacia dónde sale el descarte
    queda, sale = ((0.0, mitad), (mitad, ancho)) if lado == "izquierda" else ((mitad, ancho), (0.0, mitad))
    t = min(1.0, max(0.0, float(t)))
    estado = {"relleno": (0.0, ancho), "descarte": sale, "opacidad_descarte": 0.0,
              "corte": _suave(t / t1), "opacidad_corte": 1.0}
    if t <= t1:
        return estado
    u = _suave((t - t1) / t2)
    separacion = signo * SEPARACION_MITADES / 2.0
    separado = (queda[0] - separacion, queda[1] - separacion)
    if t <= t1 + t2:
        estado["relleno"] = tuple(a + (b - a) * u for a, b in zip((0.0, ancho), separado))
        estado["descarte"] = (sale[0] + separacion * u, sale[1] + separacion * u)
        estado["opacidad_descarte"] = u
        return estado
    v = _suave((t - t1 - t2) / (1.0 - t1 - t2))
    estado["relleno"] = tuple(a + (b - a) * v for a, b in zip(separado, (0.0, ancho_final)))
    salida = separacion + signo * DESPLAZAMIENTO_DESCARTE * v
    estado["descarte"] = (sale[0] + salida, sale[1] + salida)
    estado["opacidad_descarte"] = 1.0 - v
    estado["opacidad_corte"] = 1.0 - v
    return estado


def _trazos(n: int, color, grosor: float) -> VGroup:
    return VGroup(*[Line(LEFT * 0.5, RIGHT * 0.5, color=color, stroke_width=grosor) for _ in range(n)])


def _tender_trazos(trazos: VGroup, inicio, fin, opacidad: float) -> None:
    """Reparte los trazos (línea discontinua de estructura fija) entre ``inicio`` y ``fin``."""
    delta = fin - inicio
    visible = float(np.linalg.norm(delta)) > ANCHO_MINIMO and opacidad > 0
    n = len(trazos.submobjects)
    for k, trazo in enumerate(trazos.submobjects):
        if visible:
            trazo.put_start_and_end_on(inicio + delta * k / n, inicio + delta * (k + PROPORCION_TRAZO_CORTE) / n)
        trazo.set_stroke(opacity=opacidad if visible else 0.0)


def _fijar_tramo(rect: Mobject, x0: float, y: float, izq: float, der: float) -> None:
    rect.stretch_to_fit_width(max(der - izq, ANCHO_MINIMO))
    rect.move_to(np.array([x0 + (izq + der) / 2.0, y, 0.0]))


class PartirBarra(Animation):
    """Uno o varios cortes seguidos como UNA sola animación sobre la barra entera.

    La línea de corte y la mitad descartada viven como hijas temporales de la barra (encima del relleno) mientras
    dura la animación y se retiran al terminar. Sin ``AnimationGroup`` interno no hay reestructuración de la
    escena: las divisiones de una barra segmentada siguen pintándose encima del relleno también durante el corte.
    """

    def __init__(self, barra: Mobject, estado: EstadoBarra, veces: int, lado: str, reescalar: bool,
                 color_descarte, color_corte, **kwargs: Any) -> None:
        self.estado_barra = estado
        self.lado = lado
        relleno = estado.relleno
        self.x0 = float(estado.ancla.get_center()[0])
        self.y = float(relleno.get_center()[1])
        self.alto = float(relleno.height)
        ancho = float(relleno.width)
        self.fases: list[tuple[float, float]] = []
        for ancho_final in mitades_de_barra(ancho, veces, reescalar):
            self.fases.append((ancho, ancho_final))
            ancho = ancho_final
        self.descarte = Rectangle(width=1.0, height=self.alto, stroke_width=0, fill_color=color_descarte,
                                  fill_opacity=0.0)
        _fijar_tramo(self.descarte, self.x0, self.y, 0.0, ANCHO_MINIMO)
        self.corte = _trazos(TRAZOS_CORTE, color_corte, GROSOR_LINEA_GRUESA)
        centro = np.array([self.x0, self.y, 0.0])
        _tender_trazos(self.corte, centro, centro, 0.0)
        # El descarte va justo encima del relleno (debajo de las divisiones); el corte, encima de todo.
        barra.submobjects.insert(barra.submobjects.index(relleno) + 1, self.descarte)
        barra.add(self.corte)
        kwargs.setdefault("rate_func", linear)  # cada corte ya lleva su propia suavidad
        super().__init__(barra, **kwargs)

    def interpolate_mobject(self, alpha: float) -> None:
        a = min(1.0, max(0.0, self.rate_func(alpha)))
        n = len(self.fases)
        k = min(n - 1, int(a * n))
        local = 1.0 if a >= 1.0 else a * n - k
        ancho, ancho_final = self.fases[k]
        g = geometria_corte(ancho, ancho_final, self.lado, local)
        _fijar_tramo(self.estado_barra.relleno, self.x0, self.y, *g["relleno"])
        _fijar_tramo(self.descarte, self.x0, self.y, *g["descarte"])
        self.descarte.set_fill(opacity=OPACIDAD_BARRA * g["opacidad_descarte"])
        x_corte = self.x0 + ancho / 2.0
        medio = (self.alto / 2.0 + SOBRANTE_CORTE) * g["corte"]
        _tender_trazos(self.corte, np.array([x_corte, self.y + medio, 0.0]),
                       np.array([x_corte, self.y - medio, 0.0]), g["opacidad_corte"])

    def clean_up_from_scene(self, scene) -> None:
        super().clean_up_from_scene(scene)
        self.mobject.remove(self.descarte, self.corte)


@accion(
    "partir",
    "Parte la barra por la mitad: aparece una línea de corte discontinua, la mitad descartada se tiñe y sale, y la "
    "que queda vuelve a ocupar el largo completo ('reescalar') o se queda a la mitad. 'veces' repite el corte "
    "dentro de dur (dale ~1 s por corte). La barra conserva su id.",
    params=[
        Param("objeto", "objeto", requerido=True, descripcion="Id de la barra (o 'tabla.fila')."),
        Param("veces", "entero", defecto=1, descripcion="Cuántos cortes seguidos."),
        Param("lado", "texto", defecto="izquierda", opciones=LADOS_PARTIR, descripcion="Mitad que se queda."),
        Param("reescalar", "booleano", defecto=True,
              descripcion="true: la mitad que queda se estira al largo completo (zoom a lo que queda)."),
        Param("color", "color", defecto="rojo", descripcion="Color de la mitad descartada."),
        Param("color_corte", "color", defecto="amarillo", descripcion="Color de la línea de corte."),
    ],
    ejemplo={"en": "inicio", "hacer": "partir", "objeto": "barra", "veces": 3, "dur": 3.0},
    duracion=1.2,
    ciclo=_ciclo_partir,
)
def partir(ctx: ContextoGuion, objeto, veces, lado, reescalar, color, color_corte):
    barra, estado = _barra_de(ctx, objeto)
    ctx.marcar_foco(separar_ref(objeto)[0])
    reconsolidar_despues(ctx, objeto)
    return PartirBarra(barra, estado, int(veces), lado, bool(reescalar), ctx.color(color), ctx.color(color_corte))


# --- tabla ----------------------------------------------------------------------------------------------------------


def _ciclo_tabla(params: dict, estado) -> None:
    _usar(estado, params)
    filas = params.get("filas")
    if not isinstance(filas, list) or not filas:
        estado.error("E3", "'filas' debe ser una lista de filas {rotulo|tex, valor, texto?, color?, nombre?}")
        return
    nombres: set[str] = set()
    for i, fila in enumerate(filas):
        donde = f"fila {i}"
        if not isinstance(fila, dict):
            estado.error("E3", f"{donde}: cada fila es un mapa {{rotulo: ..., valor: ...}}")
            continue
        sobrantes = set(fila) - set(CLAVES_FILA)
        if sobrantes:
            estado.error("E1", f"{donde}: claves desconocidas {sorted(sobrantes)} (usa {', '.join(CLAVES_FILA)})")
        if not isinstance(fila.get("rotulo"), str) and not isinstance(fila.get("tex"), str):
            estado.error("E3", f"{donde}: falta 'rotulo' (texto) o 'tex' (LaTeX)")
        valor = fila.get("valor")
        if not _es_numero(valor) or valor < 0:
            estado.error("E3", f"{donde}: 'valor' debe ser un número ≥ 0")
        color = fila.get("color", "blanco")
        if color not in COLORES:
            estado.error("E6", f"{donde}: el color '{color}' no existe. Colores: {', '.join(COLORES)}")
        nombre = fila.get("nombre")
        if nombre is not None:
            if not isinstance(nombre, str) or not nombre.isidentifier() or nombre[0].isdigit() or not nombre.islower():
                estado.error("E3", f"{donde}: 'nombre' en minúsculas sin espacios (p. ej. lineal)")
            elif nombre in nombres:
                estado.error("E3", f"{donde}: nombre '{nombre}' repetido")
            nombres.add(nombre)
    escala = params.get("escala")
    if _es_numero(escala) and escala <= 0:
        estado.error("E3", "escala: debe ser positiva (el valor que ocupa el largo completo)")


def _rotulo_fila(fila: dict, tamano: float, color) -> Mobject:
    if isinstance(fila.get("tex"), str):
        return MathTex(fila["tex"], font_size=tamano, color=color)
    return Texto(str(fila["rotulo"]), tamano=tamano, color=color)


@objeto(
    "tabla",
    "Filas rótulo | barra | valor en UNA misma escala (compara tiempos o tamaños). Con 'vacia' las barras empiezan "
    "en 0 y se llenan con 'llenar' (tabla entera o 'id.fila'); una fila con valor > escala se sale de la zona a "
    "propósito (el ¡ajá! de Big-O). Partes: eje, y cada fila (nombre o índice) con rotulo, barra, valor.",
    params=[
        Param("filas", "lista", requerido=True,
              descripcion="Lista de {rotulo | tex, valor, texto?, color?, nombre?}; texto = cifra que se muestra."),
        Param("escala", "numero", descripcion="Valor que ocupa el largo completo (defecto: el mayor de las filas)."),
        Param("vacia", "booleano", defecto=False, descripcion="Barras en 0 y textos ocultos hasta 'llenar'."),
        Param("tamano", "numero", defecto=FUENTE_CUERPO, descripcion=f"Tamaño de los rótulos en puntos (mínimo {FUENTE_MINIMA})."),
        _PARAM_ZONA,
        _PARAM_ALINEACION,
    ],
    ejemplo={"en": "inicio", "hacer": "mostrar", "id": "tiempos", "tipo": "tabla", "vacia": True, "escala": 0.02,
             "filas": [{"rotulo": "n", "valor": 0.001, "texto": "0,001 s", "color": "verde", "nombre": "lineal"},
                       {"tex": "n^2", "valor": 100, "texto": "100 s", "color": "rojo", "nombre": "cuadratica"}]},
    duracion=TIEMPO_CREAR,
    ciclo=_ciclo_tabla,
)
def crear_tabla(ctx: ContextoGuion, filas, vacia, tamano, zona, alineacion, escala=None) -> Mobject:
    referencia = ctx.zona_de_referencia(zona)
    ancho_util = referencia.ancho - 2 * MARGEN_ZONA
    colores = [ctx.color(f.get("color", "blanco")) for f in filas]
    rotulos = [_rotulo_fila(f, float(tamano), c) for f, c in zip(filas, colores)]
    tamano_valor = max(FUENTE_MINIMA, float(tamano) * FACTOR_VALOR_TABLA)
    textos = [Texto(str(f["texto"]), tamano=tamano_valor, color=c) if f.get("texto") else None
              for f, c in zip(filas, colores)]
    ancho_rotulos = max(r.width for r in rotulos)
    ancho_textos = max((t.width for t in textos if t is not None), default=0.0)
    largo = ancho_util - ancho_rotulos - ancho_textos - 2 * ESPACIO_TABLA
    if largo < LARGO_MINIMO_TABLA:
        logger.warning("tabla: rótulos/textos muy anchos para la zona; las barras quedan cortas")
        largo = LARGO_MINIMO_TABLA
    valores = [float(f["valor"]) for f in filas]
    escala_real = float(escala) if escala else (max(valores) or 1.0)
    borde_derecho = largo + ESPACIO_TABLA + ancho_textos  # x local donde acaba el área de textos

    filas_mob: list[VGroup] = []
    ocultos: list[Mobject] = []
    y_actual = 0.0
    for fila, rotulo, texto, valor, color in zip(filas, rotulos, textos, valores, colores):
        barra = _armar_barra(largo, ALTO_BARRA_TABLA, color, escala_real, 0.0, marco=False, segmentos=0)
        rotulo.next_to(ORIGIN, LEFT, buff=ESPACIO_TABLA)
        miembros: list[Mobject] = [rotulo, barra]
        partes: dict[str, Mobject] = {"rotulo": rotulo, "barra": barra}
        if texto is not None:
            fraccion = valor / escala_real
            if fraccion <= 1.0:
                texto.next_to(RIGHT * largo * fraccion, RIGHT, buff=ESPACIO_TABLA)
            else:  # la barra se saldrá: su cifra queda dentro, pegada al borde derecho y sobre la barra
                texto.move_to(RIGHT * (borde_derecho - texto.width / 2) + UP * (ALTO_BARRA_TABLA / 2 + 0.08 + texto.height / 2))
            partes["valor"] = texto
            if vacia:
                ocultos.append(texto)
            else:
                miembros.append(texto)
        fila_mob = _con_partes(VGroup(*miembros), partes)
        # La fila (con su texto, aunque esté oculto) se apila bajo la anterior.
        completa = VGroup(fila_mob, texto) if (vacia and texto is not None) else fila_mob
        completa.shift(UP * (y_actual - completa.get_top()[1]))
        y_actual = completa.get_bottom()[1] - ESPACIO_FILAS
        estado: EstadoBarra = getattr(barra, ATRIBUTO_BARRA)
        estado.objetivo = valor
        estado.fila = fila_mob
        estado.texto_pendiente = texto if (vacia and texto is not None) else None
        filas_mob.append(fila_mob)
    primera, ultima = filas_mob[0], filas_mob[-1]
    arriba = ctx.parte(primera, "barra").get_top() + UP * ALTO_BARRA_TABLA * 0.3
    abajo = ctx.parte(ultima, "barra").get_bottom() + DOWN * ALTO_BARRA_TABLA * 0.3
    eje = Line([0, arriba[1], 0], [0, abajo[1], 0], color=GRIS, stroke_width=GROSOR_LINEA_FINA)
    tabla = VGroup(eje, *filas_mob)
    partes_tabla: dict[str, Mobject] = {"eje": eje}
    for k, (fila, fila_mob) in enumerate(zip(filas, filas_mob)):
        partes_tabla[str(k)] = fila_mob
        if fila.get("nombre"):
            partes_tabla[str(fila["nombre"])] = fila_mob
    _con_partes(tabla, partes_tabla)
    tabla.filas_guion = filas_mob  # type: ignore[attr-defined]
    # Se coloca con los textos ocultos incluidos (reservan su lugar) y con las barras sin desbordar.
    ctx.colocar(VGroup(tabla, *ocultos), zona, alineacion)
    for fila_mob, valor in zip(filas_mob, valores):
        estado = getattr(ctx.parte(fila_mob, "barra"), ATRIBUTO_BARRA)
        estado.raiz = tabla
        if not vacia:
            estado.fijar_fraccion(valor / escala_real)
    return tabla


__all__ = [
    "AnimacionDiferida",
    "NumeroOdometro",
    "ContarDiferido",
    "LlenarDiferido",
    "EstadoBarra",
    "valor_contado",
    "reconsolidar_despues",
    "mitades_de_barra",
    "geometria_corte",
    "PartirBarra",
    "crear_odometro",
    "crear_barra",
    "crear_tabla",
    "contar",
    "llenar",
    "partir",
]
