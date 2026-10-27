"""Familia ``algebra`` del catálogo del guion técnico: tipos ``ecuacion`` y ``derivacion``, verbos
``siguiente_paso`` y ``resultado_final``, y la transición algebraica que usa ``transformar``.

Envuelve ``toolkit.algebra_visual`` (``Ecuacion``, ``DerivacionVisual``, ``TransformarTokens``) y
``toolkit.motor_algebra`` sin duplicar su lógica. Lo aprendido en V02 que esta familia resuelve sola:

- Los tokens iguales entre pasos **vuelan** (``TransformarTokens``, nunca FadeOut + FadeIn); ``mapa`` (key_map)
  empareja tokens distintos. ``fade_transform_mismatches`` y el ``key_map`` nativo de manim 0.21 fallan: por eso
  siempre se usa ``TransformarTokens``.
- Modo ``acumular`` en **dos fases** (primero suben/se atenúan las filas previas, luego la copia de la anterior se
  transforma en la nueva): una sola animación :class:`AnimacionEnFases` que construye cada fase al empezarla (la
  copia nace donde quedó la fila anterior tras la fase 1).
- ``transformar`` de una ecuación a una ``derivacion`` nueva = ``DerivacionVisual.mostrar_inicial(desde=)``: la
  ecuación vuela a la fila 0.
- Cada token debe ser LaTeX completo (``\\frac{1}{2}`` entero, nunca ``\\frac{1`` + ``}{2}``): se valida.
- Partes direccionables: ``eq.16`` (primer token ``16``), ``eq.9#2`` (segunda aparición), ``eq.0:3`` (tokens 0-2),
  ``eq.izquierda`` / ``eq.derecha`` (lados de la relación). Una derivación expone ``actual``, ``anterior``,
  ``explicacion``, ``caja``, ``pasoN`` y, sin prefijo, los tokens de la ecuación actual (``der.25``, ``der.actual.9#2``).
"""

from __future__ import annotations

import logging
import re
import weakref
from dataclasses import dataclass
from functools import partial
from typing import Any, Callable, Iterator, Sequence

from manim import (
    UP,
    Animation,
    AnimationGroup,
    FadeIn,
    FadeOut,
    Flash,
    Group,
    Indicate,
    Mobject,
    ReplacementTransform,
    VGroup,
    Wait,
    config,
)
from manim.constants import RendererType
from manim.mobject.text.tex_mobject import MathTexPart
from manim.utils.rate_functions import linear, smooth, squish_rate_func

from toolkit.algebra_visual import (
    FRACCION_FASE_SUBIR,
    OPACIDAD_PASO_ANTERIOR,
    DerivacionVisual,
    Ecuacion,
    TransformarTokens,
)
from toolkit.estilos import COLOR_SEMANTICO, FUENTE_MATEMATICA, FUENTE_MINIMA, TIEMPO_ENFASIS, TIEMPO_TRANSFORMAR
from toolkit.guion.contexto import ALINEACIONES, ATRIBUTO_PARTES, COLORES, ContextoGuion, _error, separar_ref
from toolkit.guion.registro import Param, accion, objeto
from toolkit.motor_algebra import (
    Paso,
    completar_cuadrado,
    normalizar_token,
    resolver_cuadratica_formula,
    resolver_lineal,
    tokenizar_latex,
)

logger = logging.getLogger(__name__)

ATRIBUTO_DERIVACION = "derivacion_guion"  # controlador de la derivación en su contenedor
ATRIBUTO_FIJO_EN_ZONA = "fijo_en_zona"  # transformar no debe recolocar el destino junto al origen
MOTORES_DERIVACION: dict[str, Callable[..., list[Paso]]] = {
    "completar_cuadrado": completar_cuadrado,
    "cuadratica": resolver_cuadratica_formula,
    "lineal": resolver_lineal,
}
MODOS_DERIVACION = ("reemplazar", "acumular")
VARIABLES_BASE = ("x", "y", "n")
ESCALA_INDICAR = 1.15
PESO_INDICAR = 0.5  # fracción de la duración que ocupa el énfasis final de siguiente_paso (relativa a la transición)
PESO_EXPLICACION = 0.6  # la explicación entra/sale en el 60 % inicial de su fase
BUFF_CAJA = 0.15
LINEAS_DESTELLO = 16
LARGO_DESTELLO = 0.25
_RANGO = re.compile(r"^(\d*):(\d*)$")
_OCURRENCIA = re.compile(r"^(.+)#(\d+)$")


# ============================================================ funciones puras (datos -> tokens/pasos)


def _balanceadas(token: str) -> bool:
    profundidad = 0
    for i, c in enumerate(token):
        if c in "{}" and i > 0 and token[i - 1] == "\\":
            continue  # \{ y \} son llaves literales
        if c == "{":
            profundidad += 1
        elif c == "}":
            profundidad -= 1
            if profundidad < 0:
                return False
    return profundidad == 0


def tokens_de_tex(tex: Any, variables: Sequence[str] = VARIABLES_BASE) -> tuple[str, ...]:
    """Tokens normalizados de ``tex`` (lista de tokens o string LaTeX que se tokeniza con ``tokenizar_latex``).

    ``ValueError`` si está vacío, no es texto/lista o algún token tiene llaves desbalanceadas.
    """
    if isinstance(tex, str):
        crudos = list(tokenizar_latex(tex, variables=set(variables)))
    elif isinstance(tex, (list, tuple)):
        crudos = []
        for t in tex:
            if isinstance(t, bool) or not isinstance(t, (str, int, float)):
                raise ValueError(f"token {t!r}: cada token es un texto LaTeX o un número")
            crudos.append(str(t))
    else:
        raise ValueError(f"'tex' debe ser una lista de tokens o un texto LaTeX, no {tex!r}")
    tokens = tuple(t for t in (normalizar_token(c) for c in crudos) if t)
    if not tokens:
        raise ValueError("'tex' está vacío: escribe al menos un token, p. ej. ['x', '=', '2'] o \"x = 2\"")
    for t in tokens:
        if not _balanceadas(t):
            raise ValueError(f"el token '{t}' tiene llaves desbalanceadas: cada token debe ser LaTeX completo "
                             "(p. ej. '\\frac{1}{2}' entero, no partido en dos tokens)")
    return tokens


def variables_de_mapa(mapa: dict | None) -> tuple[str, ...]:
    """Variables para tokenizar: las base + las claves de una letra del mapa de colores."""
    extra = [str(k) for k in (mapa or {}) if len(str(k)) == 1 and str(k).isalpha()]
    return tuple(dict.fromkeys([*VARIABLES_BASE, *extra]))


def mapa_de_colores(mapa: dict | None) -> dict[str, str]:
    """``COLOR_SEMANTICO`` + ``mapa`` (token -> nombre de color del guion, claves numéricas incluidas) en hex."""
    resultado = dict(COLOR_SEMANTICO)
    for clave, nombre in (mapa or {}).items():
        if nombre not in COLORES:
            raise ValueError(f"el color '{nombre}' del mapa (token {clave!r}) no existe. Colores: {', '.join(COLORES)}")
        resultado[normalizar_token(str(clave))] = COLORES[nombre]
    return resultado


def mapa_de_tokens(mapa: dict | None) -> dict[str, str]:
    """``mapa`` de ``transformar`` (token origen -> token destino) con claves y valores como tokens de texto."""
    return {normalizar_token(str(k)): normalizar_token(str(v)) for k, v in (mapa or {}).items()}


def _paso_manual(dato: Any, i: int) -> Paso:
    try:
        if isinstance(dato, dict):
            desconocidas = set(dato) - {"tex", "tokens", "latex", "explicacion", "resaltar"}
            if desconocidas:
                raise ValueError(f"claves desconocidas {sorted(desconocidas)} (usa tex, explicacion, resaltar)")
            fuente = dato.get("tex", dato.get("tokens", dato.get("latex")))
            resaltar = dato.get("resaltar") or []
            if not isinstance(resaltar, list) or not all(isinstance(r, int) and not isinstance(r, bool) for r in resaltar):
                raise ValueError("'resaltar' es una lista de índices de tokens")
            return Paso(tokens_de_tex(fuente), str(dato.get("explicacion") or ""), tuple(resaltar))
        return Paso(tokens_de_tex(dato), "")
    except ValueError as error:
        raise ValueError(f"paso {i}: {error}") from error


def pasos_de_derivacion(
    resolver: dict | None = None,
    pasos: list | None = None,
    tomar: list | None = None,
    explicaciones: list | None = None,
) -> list[Paso]:
    """Pasos de una derivación: de un motor (``resolver: {motor, coefs, variable?}``) o manuales (``pasos``).

    ``pasos`` admite por paso: una lista de tokens, un texto LaTeX o ``{tex, explicacion?, resaltar?}`` (también la
    salida del bloque ``calculos:``, con ``tokens``/``latex``). ``tomar``: índices que se usan (en ese orden).
    ``explicaciones``: una por paso final; ``null`` conserva la del motor, ``""`` la quita. ``ValueError`` si algo falla.
    """
    if (resolver is None) == (pasos is None):
        raise ValueError("indica exactamente uno de 'resolver' (un motor) o 'pasos' (lista manual)")
    if resolver is not None:
        if not isinstance(resolver, dict):
            raise ValueError("'resolver' es {motor: completar_cuadrado|cuadratica|lineal, coefs: [a, b, c]}")
        desconocidas = set(resolver) - {"motor", "coefs", "variable"}
        if desconocidas:
            raise ValueError(f"'resolver' no admite {sorted(desconocidas)} (usa motor, coefs, variable)")
        motor = MOTORES_DERIVACION.get(resolver.get("motor"))
        if motor is None:
            raise ValueError(f"motor '{resolver.get('motor')}' inexistente. Motores: {', '.join(MOTORES_DERIVACION)}")
        coefs = resolver.get("coefs")
        if (not isinstance(coefs, list) or len(coefs) != 3
                or not all(isinstance(c, (int, float)) and not isinstance(c, bool) for c in coefs)):
            raise ValueError("'coefs' debe ser una lista de 3 números [a, b, c]")
        try:
            lista = list(motor(*coefs, variable=str(resolver.get("variable", "x"))))
        except (ValueError, ArithmeticError) as error:
            raise ValueError(f"el motor '{resolver['motor']}' falló con coefs {coefs}: {error}") from error
    else:
        if not isinstance(pasos, list) or not pasos:
            raise ValueError("'pasos' debe ser una lista con al menos un paso")
        lista = [_paso_manual(dato, i) for i, dato in enumerate(pasos)]
    if tomar:
        if not all(isinstance(i, int) and not isinstance(i, bool) and 0 <= i < len(lista) for i in tomar):
            raise ValueError(f"'tomar' usa índices de 0 a {len(lista) - 1} (hay {len(lista)} pasos)")
        lista = [lista[i] for i in tomar]
    if explicaciones:
        if len(explicaciones) > len(lista):
            raise ValueError(f"'explicaciones' tiene {len(explicaciones)} textos y la derivación {len(lista)} pasos")
        lista = [Paso(p.tokens, p.explicacion if e is None else str(e), p.resaltar) if i < len(explicaciones) else p
                 for i, (p, e) in enumerate(zip(lista, [*explicaciones, *[None] * len(lista)]))]
    return lista


# ============================================================ partes direccionables


def _rango(clave: str, n: int) -> tuple[int, int] | None:
    m = _RANGO.match(clave)
    if m is None:
        return None
    a = int(m.group(1)) if m.group(1) else 0
    b = int(m.group(2)) if m.group(2) else n
    return (a, b) if 0 <= a < b <= n else None


class PartesEcuacion(dict):
    """``partes_guion`` de una ``Ecuacion``: tokens (primera aparición), ``izquierda``/``derecha`` y, al pedirlas,
    ocurrencias ``token#k`` (1 = primera) y rangos ``a:b`` de índices de tokens."""

    def __init__(self, eq: Ecuacion) -> None:
        super().__init__()
        self.eq = eq
        for sub in eq.submobjects:
            self.setdefault(sub.tex_string, sub)
        rel = eq.indice_relacion()
        if rel is not None:
            self["izquierda"] = VGroup(*eq.submobjects[:rel])
            self["derecha"] = VGroup(*eq.submobjects[rel + 1:])

    def _dinamica(self, clave: Any) -> Mobject | None:
        clave = str(clave)
        rango = _rango(clave, len(self.eq.submobjects))
        if rango is not None:
            return VGroup(*self.eq.submobjects[rango[0]:rango[1]])
        m = _OCURRENCIA.match(clave)
        if m is not None and int(m.group(2)) >= 1:
            iguales = [s for s in self.eq.submobjects if s.tex_string == normalizar_token(m.group(1))]
            k = int(m.group(2))
            return iguales[k - 1] if k <= len(iguales) else None
        return None

    def __contains__(self, clave: object) -> bool:
        return dict.__contains__(self, clave) or self._dinamica(clave) is not None

    def __getitem__(self, clave: Any) -> Mobject:
        if dict.__contains__(self, clave):
            return dict.__getitem__(self, clave)
        parte = self._dinamica(clave)
        if parte is None:
            raise KeyError(clave)
        return parte


def anotar_partes(eq: Ecuacion) -> Ecuacion:
    """Da a ``eq`` sus partes direccionables desde el guion (``eq.16``, ``eq.9#2``, ``eq.0:3``...)."""
    setattr(eq, ATRIBUTO_PARTES, PartesEcuacion(eq))
    return eq


class PartesDerivacion(dict):
    """``partes_guion`` (dinámicas) del contenedor de una derivación: ``actual``, ``anterior``, ``explicacion``,
    ``caja``, ``pasoN`` (si está visible) y cualquier parte de la ecuación actual (``der.25``)."""

    def __init__(self, control: "ControlDerivacion") -> None:
        super().__init__()
        self.control = control

    def _nombradas(self) -> dict[str, Mobject]:
        dv = self.control.dv
        nombradas: dict[str, Mobject] = {}
        if dv.indice >= 0:
            nombradas["actual"] = dv.actual
        if len(dv.visibles) >= 2:
            nombradas["anterior"] = dv.visibles[-2]
        if dv.explicacion is not None:
            nombradas["explicacion"] = dv.explicacion
        if dv.caja is not None:
            nombradas["caja"] = dv.caja
        for eq in dv.visibles:
            nombradas[f"paso{dv.ecuaciones.index(eq)}"] = eq
        return nombradas

    def _de_actual(self) -> PartesEcuacion | dict:
        dv = self.control.dv
        return getattr(dv.actual, ATRIBUTO_PARTES, {}) if dv.indice >= 0 else {}

    def __contains__(self, clave: object) -> bool:
        return clave in self._nombradas() or clave in self._de_actual()

    def __getitem__(self, clave: Any) -> Mobject:
        nombradas = self._nombradas()
        if clave in nombradas:
            return nombradas[clave]
        return self._de_actual()[clave]

    def __iter__(self) -> Iterator[str]:
        return iter([*self._nombradas(), *(k for k in self._de_actual() if k not in ("izquierda", "derecha"))])

    def __len__(self) -> int:
        return len(list(iter(self)))

    def __deepcopy__(self, memo: dict) -> "PartesDerivacion":
        return self  # vista dinámica del controlador (que tampoco se copia)


# ============================================================ animación en fases


@dataclass
class Fase:
    """Una fase de :class:`AnimacionEnFases`: ``peso`` relativo y ``construir`` (se llama al empezar la fase)."""

    peso: float
    construir: Callable[[], list]


class AnimacionEnFases(Animation):
    """Animaciones que se reproducen una tras otra dentro de UN ``play``, cada fase construida al empezar.

    Sirve cuando una fase depende del estado que deja la anterior (la copia de la fila anterior nace donde quedó
    tras subir). Al cambiar de fase limpia la anterior (``clean_up_from_scene``), añade a la escena lo que la nueva
    anima y recalcula qué se redibuja cada fotograma (renderer Cairo), como hace ``Scene.begin_animations``.
    ``run_time`` se reparte entre las fases según su ``peso``; la curva de cada animación interna se conserva.
    """

    def __init__(self, fases: Sequence[Fase], **kwargs: Any) -> None:
        if not fases:
            raise ValueError("AnimacionEnFases necesita al menos una fase")
        self.fases = list(fases)
        total = sum(max(f.peso, 0.0) for f in self.fases) or 1.0
        limites, acumulado = [], 0.0
        for f in self.fases:
            inicio = acumulado / total
            acumulado += max(f.peso, 0.0)
            limites.append((inicio, acumulado / total))
        self.limites = limites
        self.grupos_construidos: list[AnimationGroup] = []
        self.escena_fases = None
        kwargs.setdefault("run_time", total)
        kwargs.setdefault("rate_func", linear)
        super().__init__(Group(), **kwargs)
        self.starting_mobject = self.mobject

    # --- ciclo de vida de manim ---------------------------------------------------------------------------
    def _setup_scene(self, scene) -> None:
        self.escena_fases = scene

    def begin(self) -> None:
        if not self.grupos_construidos:
            self._entrar()
        self.interpolate(0)

    def interpolate(self, alpha: float) -> None:
        t = min(max(self.rate_func(alpha), 0.0), 1.0)
        k = next((i for i, (_, fin) in enumerate(self.limites) if t < fin), len(self.fases) - 1)
        while len(self.grupos_construidos) - 1 < k:
            self._salir()
            self._entrar()
        inicio, fin = self.limites[k]
        sub = 1.0 if fin <= inicio else (t - inicio) / (fin - inicio)
        self.grupos_construidos[k].interpolate(min(max(sub, 0.0), 1.0))

    def update_mobjects(self, dt: float) -> None:
        if self.grupos_construidos:
            self.grupos_construidos[-1].update_mobjects(dt)

    def finish(self) -> None:
        self.interpolate(1.0)
        self.grupos_construidos[-1].finish()

    def clean_up_from_scene(self, scene) -> None:
        if self.grupos_construidos:
            self.grupos_construidos[-1].clean_up_from_scene(scene)
        scene.remove(self.mobject)
        self.mobject.submobjects = []

    # --- fases --------------------------------------------------------------------------------------------
    def _entrar(self) -> None:
        indice = len(self.grupos_construidos)
        anims = [a for a in self.fases[indice].construir() if a is not None] or [Wait(run_time=1.0)]
        grupo = AnimationGroup(*anims)
        self.grupos_construidos.append(grupo)
        self.mobject.submobjects = [grupo.mobject]
        escena = self.escena_fases
        if escena is not None:
            escena.add_mobjects_from_animations([grupo])
            grupo._setup_scene(escena)
        grupo.begin()
        if escena is not None and indice > 0:
            self._refrescar(escena)

    def _salir(self) -> None:
        grupo = self.grupos_construidos[-1]
        grupo.interpolate(1.0)
        grupo.finish()
        if self.escena_fases is not None:
            grupo.clean_up_from_scene(self.escena_fases)

    @staticmethod
    def _refrescar(escena) -> None:
        """Recalcula los mobjects en movimiento y la imagen estática (lo mismo que ``Scene.begin_animations``)."""
        if config.renderer != RendererType.CAIRO or not getattr(escena, "animations", None):
            return
        escena.moving_mobjects, escena.static_mobjects = escena.get_moving_and_static_mobjects(escena.animations)
        escena.renderer.save_static_frame_data(escena, escena.static_mobjects)


# ============================================================ controlador de una derivación


class ControlDerivacion:
    """Estado de una derivación del guion: su ``DerivacionVisual`` (layout) y el contenedor que ve el guion."""

    def __init__(self, dv: DerivacionVisual, contenedor: VGroup) -> None:
        self.dv = dv
        self.contenedor = contenedor

    def __deepcopy__(self, memo: dict) -> "ControlDerivacion":
        return self  # las copias del contenedor (Indicate, enfocar...) comparten el controlador

    # --- estado ---------------------------------------------------------------------------------------------
    def en_pantalla(self) -> list[Mobject]:
        dv = self.dv
        return [*dv.visibles, *(m for m in (dv.explicacion, dv.caja) if m is not None)]

    def asentar(self, ctx: ContextoGuion) -> None:
        """Tras la animación: el contenedor pasa a ser lo que se ve y queda como una sola entrada de la escena."""
        self.contenedor.remove(*self.contenedor.submobjects)
        self.contenedor.add(*self.en_pantalla())
        if ctx.escena is not None and not ctx.oculto(self._id(ctx)):
            ctx.consolidar(self.contenedor)

    def _id(self, ctx: ContextoGuion) -> str:
        return next((i for i, m in ctx.objetos.items() if m is self.contenedor), "")

    def _animaciones_explicacion(self, indice: int) -> list[Animation]:
        """Relevo de la explicación sin solape: la vieja sale en la primera mitad y la nueva entra en la segunda."""
        anims = self.dv._animaciones_explicacion(indice)
        relevo = len(anims) == 2
        for a in anims:
            a.run_time = PESO_EXPLICACION
            if relevo:
                a.rate_func = squish_rate_func(smooth, *((0.0, 0.5) if isinstance(a, FadeOut) else (0.5, 1.0)))
        return anims

    def _salida_caja(self) -> list[Animation]:
        if self.dv.caja is None:
            return []
        caja, self.dv.caja = self.dv.caja, None
        return [FadeOut(caja, run_time=PESO_EXPLICACION)]

    # --- verbos ---------------------------------------------------------------------------------------------
    def siguiente(self, indicar: bool, color: str) -> Animation | list[Animation]:
        dv = self.dv
        previa = dv.actual
        dv.indice += 1
        nueva = dv.ecuaciones[dv.indice]
        paso = dv.pasos[dv.indice]
        fases: list[Fase] = []
        if dv.modo == "reemplazar":
            nueva.shift(dv._destinos([nueva])[0])
            dv.visibles = [nueva]
            anims = [TransformarTokens(previa, nueva, run_time=1.0), *self._salida_caja(),
                     *self._animaciones_explicacion(dv.indice)]
            fases.append(Fase(1.0, lambda anims=anims: anims))
        else:
            candidatas = [*dv.visibles, nueva]
            k = dv._cuantas_caben(candidatas)
            quedan, salen = candidatas[-k:], candidatas[:-k]
            desplazamientos = dv._destinos(quedan)
            nueva.shift(desplazamientos[-1])
            subir = [eq.animate.shift(d).set_opacity(OPACIDAD_PASO_ANTERIOR)
                     for eq, d in zip(quedan[:-1], desplazamientos[:-1])]
            subir += [FadeOut(eq, shift=UP * 0.3) for eq in salen]
            subir += [*self._salida_caja(), *self._animaciones_explicacion(dv.indice)]
            dv.visibles = quedan

            def transformar_copia(previa=previa, nueva=nueva) -> list[Animation]:
                # La copia nace donde quedó la fila anterior (ya subida y atenuada) y a opacidad plena.
                return [TransformarTokens(previa.copy().set_opacity(1), nueva, run_time=1.0)]

            fases.append(Fase(FRACCION_FASE_SUBIR, lambda subir=subir: subir))
            fases.append(Fase(1.0 - FRACCION_FASE_SUBIR, transformar_copia))
        if indicar and paso.resaltar:
            # Un Indicate por token: escalar el grupo entero separaría tokens lejanos (los dos '9' de "+9 = 16+9").
            tokens = [nueva[i] for i in paso.resaltar]
            fases.append(Fase(PESO_INDICAR, lambda: [Indicate(t, color=color, scale_factor=ESCALA_INDICAR)
                                                     for t in tokens]))
        if len(fases) == 1:
            return fases[0].construir()
        return AnimacionEnFases(fases)

    def resultado_final(self, objetivo: Mobject, color: str, destello: bool) -> list[Animation]:
        from toolkit.animaciones import caja_resultado

        anims = self._salida_caja()
        caja, crear = caja_resultado(objetivo, color=color, buff=BUFF_CAJA)
        self.dv.caja = caja
        anims.append(crear)
        if destello:
            anims.append(Flash(objetivo.get_center(), color=color, flash_radius=max(caja.width, caja.height) / 2 + 0.1,
                               line_length=LARGO_DESTELLO, num_lines=LINEAS_DESTELLO))
        return anims


def control_de(mob: Mobject) -> ControlDerivacion | None:
    return getattr(mob, ATRIBUTO_DERIVACION, None)


def es_ecuacion(mob: Mobject) -> bool:
    return isinstance(mob, Ecuacion)


# ============================================================ validación (ganchos ``ciclo``)

# Por validación: id de derivación -> [nº de pasos, nº de siguiente_paso ya usados]
_DERIVACIONES: "weakref.WeakKeyDictionary[Any, dict[str, list[int]]]" = weakref.WeakKeyDictionary()


def _derivaciones(estado) -> dict[str, list[int]]:
    if estado not in _DERIVACIONES:
        _DERIVACIONES[estado] = {}
    return _DERIVACIONES[estado]


def _ciclo_colores(params: dict, estado) -> None:
    mapa = params.get("mapa") or {}
    for clave, nombre in mapa.items():
        if nombre not in COLORES:
            estado.error("E6", f"el color '{nombre}' del mapa (token {clave!r}) no existe. Colores: {', '.join(COLORES)}")


def _ciclo_ecuacion(params: dict, estado) -> None:
    _ciclo_colores(params, estado)
    try:
        tokens_de_tex(params.get("tex"), variables_de_mapa(params.get("mapa")))
    except ValueError as error:
        estado.error("E3", str(error))


def _ciclo_derivacion(params: dict, estado) -> None:
    _ciclo_colores(params, estado)
    if not isinstance(params.get("zona"), str):
        estado.error("E3", "la zona de una derivación es el nombre de una zona (ocupa la zona entera; no admite "
                           "{de: id, lado: ...})")
    if isinstance(params.get("max_visibles"), int) and params["max_visibles"] < 1:
        estado.error("E3", "'max_visibles' debe ser ≥ 1")
    try:
        pasos = pasos_de_derivacion(params.get("resolver"), params.get("pasos"), params.get("tomar"),
                                    params.get("explicaciones"))
    except ValueError as error:
        estado.error("E3", str(error))
        return
    if estado.creando is not None:
        _derivaciones(estado)[estado.creando] = [len(pasos), 0]


def _usar_derivacion(params: dict, estado, verbo: str) -> str | None:
    ref = params.get("objeto")
    if not isinstance(ref, str):
        estado.error("E3", f"{verbo} actúa sobre UNA derivación: 'objeto' es su id")
        return None
    id, parte = separar_ref(ref)
    if parte is not None:
        estado.error("E3", f"{verbo}: usa el id de la derivación ('{id}'), no '{ref}'")
        return None
    if not estado.usar(id):
        return None
    tipo = estado.tipos.get(id)
    if tipo != "derivacion":
        estado.error("E3", f"{verbo} actúa sobre un objeto de tipo derivacion y '{id}' es de tipo '{tipo}'")
        return None
    return id


def _ciclo_siguiente_paso(params: dict, estado) -> None:
    id = _usar_derivacion(params, estado, "siguiente_paso")
    if id is None:
        return
    cuenta = _derivaciones(estado).get(id)
    if cuenta is None:
        return
    cuenta[1] += 1
    if cuenta[1] > cuenta[0] - 1:
        estado.error("E3", f"la derivación '{id}' tiene {cuenta[0]} pasos: ya se mostraron todos (sobra este "
                           f"siguiente_paso; usa resultado_final o quítalo)")


def _ciclo_resultado_final(params: dict, estado) -> None:
    _usar_derivacion(params, estado, "resultado_final")


# ============================================================ piezas

_PARAM_ZONA = Param("zona", "zona", defecto="principal",
                    descripcion="Zona donde se encaja (nombre) o {de: id, lado: abajo|arriba|izq|der, espacio: 0.3}.")
_PARAM_MAPA = Param("mapa", "mapa", defecto={},
                    descripcion="Colores extra por token (token -> nombre de color), p. ej. {3: naranja, 25: amarillo}; "
                                "se suman al color semántico (x azul, y verde...).")


@objeto(
    "ecuacion",
    "Ecuación LaTeX partida en tokens con color semántico; los tokens son partes direccionables ('eq.16', 'eq.9#2', "
    "'eq.0:3', 'eq.izquierda') y vuelan al transformarla en otra ecuación.",
    params=[
        Param("tex", "cualquiera", requerido=True,
              descripcion="Lista de tokens ['x^2', '+', '6', 'x', '=', '16'] (recomendado) o texto LaTeX que se "
                          "tokeniza ('x^2 + 6x = 16'). Cada token es LaTeX completo."),
        _PARAM_ZONA,
        Param("tamano", "numero", defecto=FUENTE_MATEMATICA, descripcion=f"Tamaño en puntos (mínimo {FUENTE_MINIMA})."),
        _PARAM_MAPA,
        Param("color", "color", descripcion="Color base de toda la ecuación (antes del color por token)."),
        Param("colorear", "booleano", defecto=True, descripcion="false: sin color por token (todo en el color base)."),
        Param("alineacion", "texto", defecto="centro", opciones=tuple(ALINEACIONES),
              descripcion="Borde de la zona al que se pega."),
    ],
    ejemplo={"en": "inicio", "hacer": "mostrar", "id": "eq0", "tipo": "ecuacion",
             "tex": ["x^2", "+", "6", "x", "=", "16"], "mapa": {6: "naranja"}, "zona": "principal"},
    duracion=1.2,
    ciclo=_ciclo_ecuacion,
)
def crear_ecuacion(ctx: ContextoGuion, tex, zona, tamano, mapa, color, colorear, alineacion) -> Mobject:
    try:
        tokens = tokens_de_tex(tex, variables_de_mapa(mapa))
        colores = mapa_de_colores(mapa)
    except ValueError as error:
        raise _error("E3", str(error), ctx.ubicacion) from error
    eq = Ecuacion(*tokens, tamano=tamano, colorear=colorear, mapa=colores)
    if color is not None:
        eq.set_color(ctx.color(color))
        if colorear:
            eq._aplicar_colores()
    anotar_partes(eq)
    ancho = eq.width
    ctx.colocar(eq, zona, alineacion)
    escala = eq.width / max(ancho, 1e-6)
    if tamano * escala < FUENTE_MINIMA - 1e-6:
        logger.warning("%s: la ecuación se redujo a ~%.0f pt para caber en su zona (< %s): parte la ecuación o usa "
                       "una zona más ancha", ctx.ubicacion, tamano * escala, FUENTE_MINIMA)
    return eq


@objeto(
    "derivacion",
    "Derivación algebraica paso a paso (motor de álgebra o pasos manuales) alineada por el '='; avanza con "
    "siguiente_paso (los tokens vuelan) y cierra con resultado_final. Partes: 'der.actual', 'der.anterior', "
    "'der.explicacion', 'der.caja', 'der.pasoN' y tokens de la ecuación actual ('der.25').",
    params=[
        Param("resolver", "mapa",
              descripcion="Pasos de un motor: {motor: completar_cuadrado|cuadratica|lineal, coefs: [a, b, c], "
                          "variable: x} (ax²+bx+c=0; lineal: ax+b=c)."),
        Param("pasos", "lista",
              descripcion="Pasos manuales (en vez de resolver): cada uno lista de tokens, texto LaTeX o {tex, "
                          "explicacion, resaltar}; admite la salida de un cálculo ('{cc}')."),
        Param("tomar", "lista", defecto=[], descripcion="Índices de los pasos que se usan, en orden (vacío = todos)."),
        Param("explicaciones", "lista", defecto=[],
              descripcion="Texto por paso para la franja de explicación (null = el del motor, \"\" = ninguno)."),
        Param("modo", "texto", defecto="reemplazar", opciones=MODOS_DERIVACION,
              descripcion="reemplazar: una ecuación a la vez; acumular: pila (las anteriores suben y se atenúan)."),
        Param("max_visibles", "entero", defecto=4, descripcion="Filas visibles como máximo en modo acumular (≥ 1)."),
        Param("mostrar_explicacion", "booleano", defecto=True,
              descripcion="Franja gris arriba con la explicación de cada paso."),
        _PARAM_MAPA,
        Param("zona", "zona", defecto="principal", descripcion="Nombre de la zona que ocupa la derivación entera."),
        Param("tamano", "numero", defecto=FUENTE_MATEMATICA, descripcion=f"Tamaño en puntos (mínimo {FUENTE_MINIMA})."),
    ],
    ejemplo={"en": "inicio", "hacer": "mostrar", "id": "der", "tipo": "derivacion",
             "resolver": {"motor": "completar_cuadrado", "coefs": [1, 6, -16]}, "modo": "acumular", "max_visibles": 2},
    duracion=1.2,
    ciclo=_ciclo_derivacion,
)
def crear_derivacion(ctx: ContextoGuion, resolver, pasos, tomar, explicaciones, modo, max_visibles,
                     mostrar_explicacion, mapa, zona, tamano) -> Mobject:
    try:
        lista = pasos_de_derivacion(resolver, pasos, tomar, explicaciones)
        colores = mapa_de_colores(mapa)
    except ValueError as error:
        raise _error("E3", str(error), ctx.ubicacion) from error
    if not isinstance(zona, str):
        raise _error("E3", "la zona de una derivación es el nombre de una zona", ctx.ubicacion)
    dv = DerivacionVisual(None, lista, zona=ctx.zona(zona), tamano=tamano, mostrar_explicacion=mostrar_explicacion,
                          modo=modo, max_visibles=max_visibles, mapa=colores)
    for eq in dv.ecuaciones:
        anotar_partes(eq)
    # Estado de "mostrar_inicial" sin reproducir nada: la fila 0 en su sitio y su explicación.
    dv.indice = 0
    eq0 = dv.ecuaciones[0]
    eq0.shift(dv._destinos([eq0])[0])
    dv.visibles = [eq0]
    dv.explicacion = dv._texto_explicacion(0)
    contenedor = VGroup()
    control = ControlDerivacion(dv, contenedor)
    contenedor.add(*control.en_pantalla())
    setattr(contenedor, ATRIBUTO_DERIVACION, control)
    setattr(contenedor, ATRIBUTO_PARTES, PartesDerivacion(control))
    setattr(contenedor, ATRIBUTO_FIJO_EN_ZONA, True)
    return contenedor


def _control(ctx: ContextoGuion, objeto: str) -> ControlDerivacion:
    control = control_de(ctx.obtener(objeto))
    if control is None:
        raise _error("E3", f"'{objeto}' no es una derivación (tipo derivacion)", ctx.ubicacion)
    return control


@accion(
    "siguiente_paso",
    "Avanza una derivación a su siguiente paso: los tokens iguales vuelan a su sitio (en acumular, primero suben y se "
    "atenúan las filas previas y después la copia de la anterior se convierte en la nueva). Otros pasos con el mismo "
    "'en' se reproducen a la vez (animaciones extra); en acumular la transformación ocupa el último 65 % de dur, así "
    "que un extra con retraso ≈ 0.35·dur va sincronizado con ella.",
    params=[
        Param("objeto", "objeto", requerido=True, descripcion="Id de la derivación."),
        Param("indicar", "booleano", defecto=False,
              descripcion="true: al final, énfasis sobre los tokens nuevos del paso (los que marca el motor)."),
        Param("color", "color", defecto="amarillo", descripcion="Color del énfasis de 'indicar'."),
    ],
    ejemplo={"en": "inicio", "hacer": "siguiente_paso", "objeto": "der"},
    duracion=TIEMPO_TRANSFORMAR,
    modificadores=("rate",),
    ciclo=_ciclo_siguiente_paso,
)
def siguiente_paso(ctx: ContextoGuion, objeto, indicar=False, color="amarillo"):
    control = _control(ctx, objeto)
    if not control.dv.quedan_pasos:
        raise _error("E3", f"la derivación '{objeto}' ya mostró sus {len(control.dv.pasos)} pasos", ctx.ubicacion)
    ctx.marcar_foco(separar_ref(objeto)[0])
    animacion = control.siguiente(bool(indicar), ctx.color(color))
    ctx.despues(partial(control.asentar, ctx))
    return animacion


siguiente_paso.previos_ejemplo = [
    {"en": "inicio", "hacer": "mostrar", "id": "der", "tipo": "derivacion",
     "resolver": {"motor": "completar_cuadrado", "coefs": [1, 6, -16]}, "modo": "acumular", "max_visibles": 2},
]


@accion(
    "resultado_final",
    "Cierra una derivación: caja de resultado (y destello) alrededor de la ecuación actual o de una parte suya "
    "('0:3' = los tres primeros tokens, 'izquierda', un token).",
    params=[
        Param("objeto", "objeto", requerido=True, descripcion="Id de la derivación."),
        Param("parte", "texto", descripcion="Parte de la ecuación actual a encajonar (defecto: toda)."),
        Param("color", "color", defecto="amarillo", descripcion="Color de la caja y del destello."),
        Param("destello", "booleano", defecto=True, descripcion="Destello radial al aparecer la caja."),
    ],
    ejemplo={"en": "inicio", "hacer": "resultado_final", "objeto": "der", "color": "verde"},
    duracion=0.8,
    modificadores=("rate",),
    ciclo=_ciclo_resultado_final,
)
def resultado_final(ctx: ContextoGuion, objeto, parte=None, color="amarillo", destello=True):
    control = _control(ctx, objeto)
    actual = control.dv.actual
    objetivo = ctx.parte(actual, parte) if parte else actual
    ctx.marcar_foco(separar_ref(objeto)[0])
    anims = control.resultado_final(objetivo, ctx.color(color), bool(destello))
    ctx.despues(partial(control.asentar, ctx))
    return anims


resultado_final.previos_ejemplo = [
    {"en": "inicio", "hacer": "mostrar", "id": "der", "tipo": "derivacion",
     "resolver": {"motor": "lineal", "coefs": [2, 3, 11]}},
]


# ============================================================ transformar (lo usa nucleo.transformar)


def transicion_algebraica(ctx: ContextoGuion, origen: Mobject, destino: Mobject, *, mapa: dict | None,
                          copia: bool, arco: float) -> Animation | list[Animation] | None:
    """Animación de ``transformar`` cuando origen o destino son algebraicos; ``None`` si no aplica.

    - ecuación -> derivación nueva: la ecuación vuela a la fila 0 (``mostrar_inicial(desde=)``).
    - derivación -> ecuación: la ecuación actual vuela al destino y el resto de la derivación se desvanece.
    - ecuación -> ecuación (también ``der.actual``): ``TransformarTokens`` con ``mapa`` como key_map.
    """
    llaves = mapa_de_tokens(mapa) or None
    control_destino = control_de(destino)
    if control_destino is not None:
        eq0 = control_destino.dv.actual
        fuente = origen.copy() if copia else origen
        if es_ecuacion(origen):
            anims: list[Animation] = [TransformarTokens(fuente, eq0, key_map=llaves, path_arc=arco)]
        else:
            anims = [ReplacementTransform(fuente, eq0, path_arc=arco)]
        if control_destino.dv.explicacion is not None:
            anims.append(FadeIn(control_destino.dv.explicacion, shift=UP * 0.2, run_time=PESO_EXPLICACION))
        ctx.despues(partial(control_destino.asentar, ctx))
        return anims
    control_origen = control_de(origen)
    if control_origen is not None and es_ecuacion(destino):
        actual = control_origen.dv.actual
        if copia:
            return TransformarTokens(actual.copy(), destino, key_map=llaves, path_arc=arco)
        resto = [m for m in control_origen.en_pantalla() if m is not actual]
        return [TransformarTokens(actual, destino, key_map=llaves, path_arc=arco),
                *[FadeOut(m, run_time=PESO_EXPLICACION) for m in resto]]
    if es_ecuacion(origen) and es_ecuacion(destino):
        fuente = origen.copy() if copia else origen
        return TransformarTokens(fuente, destino, key_map=llaves, path_arc=arco)
    if isinstance(origen, MathTexPart) and es_ecuacion(destino):
        # Un token (p. ej. 'eq.25' con copia) vuela a su igual en la ecuación nueva; el resto de ella aparece.
        buscado = (llaves or {}).get(origen.tex_string, origen.tex_string)
        iguales = [s for s in destino.submobjects if s.tex_string == buscado]
        if iguales:
            fuente = origen.copy() if copia else origen
            resto = [s for s in destino.submobjects if s is not iguales[0]]
            anims = [ReplacementTransform(fuente, iguales[0], path_arc=arco)]
            if resto:
                anims.append(FadeIn(VGroup(*resto), run_time=PESO_EXPLICACION))
            ctx.despues(partial(ctx.consolidar, destino))
            return anims
    return None


__all__ = [
    "AnimacionEnFases",
    "ControlDerivacion",
    "Fase",
    "PartesDerivacion",
    "PartesEcuacion",
    "anotar_partes",
    "mapa_de_colores",
    "mapa_de_tokens",
    "pasos_de_derivacion",
    "tokens_de_tex",
    "transicion_algebraica",
]
