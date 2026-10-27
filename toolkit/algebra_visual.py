"""Algebra visual: ecuaciones tokenizadas con color semantico robusto y derivaciones animadas.

- ``Ecuacion``: ``MathTex`` donde cada token es un submobject (``tex_string`` = token normalizado),
  asi ``TransformMatchingTex`` empareja tokens iguales entre pasos (vuelan en vez de fundirse).
- Color: tokens exactos del ``mapa`` (variables con exponente/subindice incluidos, y numeros
  como "3", "25" si el mapa los trae). Dentro de tokens compuestos ("(x+3)^2", "\\frac{x}{2}")
  las variables/numeros del mapa se aislan con ``patron_seguro``: nunca dentro de un comando
  (``\\sqrt`` no se parte en ``\\sqr``+``t``), ni pegados a letras/digitos, ni tras ``^``/``_``,
  ni dentro de ``\\text{..}``.
- ``TransformarTokens``: ``TransformMatchingTex`` con ``key_map`` que usa ``FadeTransform`` (en manim
  0.21 ``FadeTransformPieces`` falla con ``MathTexPart``: ver ``fade_transform_mismatches``).
- ``DerivacionVisual``: dirige una lista de ``Paso`` en modo "reemplazar" o "acumular".
"""

from __future__ import annotations

import logging
import re
from typing import Mapping, Sequence

import numpy as np
from manim import (
    DOWN,
    UP,
    AnimationGroup,
    FadeIn,
    FadeOut,
    FadeTransform,
    Flash,
    Indicate,
    MathTex,
    Mobject,
    ReplacementTransform,
    Transform,
    TransformMatchingTex,
    VGroup,
    Write,
)
from manim.mobject.types.vectorized_mobject import VMobject

from .estilos import (
    AMARILLO,
    COLOR_SEMANTICO,
    FUENTE_ETIQUETA,
    FUENTE_MATEMATICA,
    GRIS,
    MAPA_COLORES_MATEMATICOS,  # noqa: F401  (compat de importacion)
    TIEMPO_ENFASIS,
    TIEMPO_TRANSFORMAR,
)
from .layout import MARGEN_ENTRE_BLOQUES, ZONA_PRINCIPAL, Zona
from .motor_algebra import RELACIONES, Paso, emparejar_tokens, normalizar_token, tokenizar_latex

logger = logging.getLogger(__name__)

__all__ = [
    "color_de_token",
    "patron_seguro",
    "Ecuacion",
    "EcuacionColoreada",
    "TransformarTokens",
    "DerivacionVisual",
    "animar_paso_algebraico",
    "OPACIDAD_PASO_ANTERIOR",
]

# Opacidad de los pasos anteriores en modo "acumular" (legibles pero secundarios).
OPACIDAD_PASO_ANTERIOR = 0.5
# Modo "acumular": fraccion del run_time de ``siguiente`` para subir/atenuar las filas previas
# (fase 1); el resto es la transformacion de la copia en la fila nueva (fase 2).
FRACCION_FASE_SUBIR = 0.35
# Margen interior respecto a la zona.
MARGEN_ZONA = 0.15

_ADJUNTOS = r"(?:[\^_](?:\{[^{}]*\}|\\[A-Za-z]+|[A-Za-z0-9]))*"
_RE_NUMERO = re.compile(r"\d+(?:\.\d+)?$")
_RE_COMANDO = re.compile(r"\\[A-Za-z]+$")
_RE_TEXTO = re.compile(r"\\(?:text|textrm|textbf|textit|mbox|mathrm|operatorname)\s*\{")


# ============================================================ color


def _es_simbolo(clave: str) -> bool:
    return (len(clave) == 1 and clave.isalpha()) or bool(_RE_COMANDO.match(clave))


def patron_seguro(clave: str) -> re.Pattern:
    """Regex que encuentra ``clave`` solo donde aislarla es seguro para LaTeX.

    Letra/comando: no precedida de ``\\``, letra, ``^`` o ``_``; incluye su exponente/subindice
    y no puede ir seguida de letra, ``^`` ni ``_``. Numero: igual, sin digitos ni punto alrededor.
    Otras claves: literal.
    """
    esc = re.escape(clave)
    if _es_simbolo(clave):
        return re.compile(rf"(?<![\\A-Za-z^_]){esc}{_ADJUNTOS}(?![A-Za-z^_])")
    if _RE_NUMERO.match(clave):
        return re.compile(rf"(?<![\\A-Za-z0-9.^_]){esc}{_ADJUNTOS}(?![0-9.^_])")
    return re.compile(esc)


def _base(token: str) -> str:
    m = re.match(rf"^(\\[A-Za-z]+|[A-Za-z]|\d+(?:\.\d+)?){_ADJUNTOS}$", token)
    return m.group(1) if m else token


def color_de_token(token: str, mapa: Mapping[str, str] = COLOR_SEMANTICO) -> str | None:
    """Color de un token: clave exacta del mapa, o variable/numero del mapa con exponente/subindice."""
    token = normalizar_token(token)
    if token in mapa:
        return mapa[token]
    base = _base(token)
    if base != token and base in mapa:
        return mapa[base]
    return None


class _Coincidencia:
    """Imita la interfaz de ``re.Match`` que usa ``MathTex._handle_match`` (grupos 1..3)."""

    def __init__(self, antes: str, coincidencia: str, despues: str) -> None:
        self._grupos = (antes + coincidencia + despues, antes, coincidencia, despues)

    def group(self, i: int = 0) -> str:
        return self._grupos[i]


def _rangos_texto(s: str) -> list[tuple[int, int]]:
    rangos = []
    for m in _RE_TEXTO.finditer(s):
        profundidad, j = 0, m.end() - 1
        while j < len(s):
            if s[j] == "{":
                profundidad += 1
            elif s[j] == "}":
                profundidad -= 1
                if profundidad == 0:
                    break
            j += 1
        rangos.append((m.start(), j + 1))
    return rangos


# ============================================================ Ecuacion


class Ecuacion(MathTex):
    """``MathTex`` con un submobject por token y color semantico robusto."""

    def __init__(
        self,
        *tokens: str,
        tamano: float = FUENTE_MATEMATICA,
        colorear: bool = True,
        mapa: Mapping[str, str] | None = None,
        **kw,
    ) -> None:
        tokens = tuple(normalizar_token(str(t)) for t in tokens)
        tokens = tuple(t for t in tokens if t)
        if not tokens:
            raise ValueError("Ecuacion necesita al menos un token no vacio")
        self.tokens = tokens
        self.mapa = dict(COLOR_SEMANTICO if mapa is None else mapa)
        self.colorear = colorear
        aislar = list(kw.pop("substrings_to_isolate", None) or [])
        self._patrones: dict[str, re.Pattern] = {}
        if colorear:
            for clave in self.mapa:
                if _es_simbolo(clave) or _RE_NUMERO.match(clave):
                    self._patrones[clave] = patron_seguro(clave)
                    aislar.append(clave)
        kw.setdefault("font_size", tamano)
        super().__init__(*tokens, substrings_to_isolate=aislar, **kw)
        if colorear:
            self._aplicar_colores()

    # MathTex llama a este metodo para localizar las subcadenas a aislar.
    def _locate_first_match(self, substrings_to_isolate, unprocessed_string):  # noqa: D401
        patrones = getattr(self, "_patrones", {})
        prohibidos = _rangos_texto(unprocessed_string)
        mejor = None
        for sub in substrings_to_isolate:
            patron = patrones.get(sub) or re.compile(re.escape(sub))
            for m in patron.finditer(unprocessed_string):
                if m.end() == m.start() or any(a <= m.start() < b for a, b in prohibidos):
                    continue
                clave = (m.start(), -(m.end() - m.start()))
                if mejor is None or clave < mejor[0]:
                    mejor = (clave, m)
                break
        if mejor is None:
            return None
        m = mejor[1]
        s = unprocessed_string
        return _Coincidencia(s[: m.start()], m.group(0), s[m.end() :])

    def _aplicar_colores(self) -> None:
        for parte in self.submobjects:
            color = color_de_token(parte.tex_string, self.mapa)
            if color is not None:
                parte.set_color(color)
        for texto, ident in self._substring_matches:
            color = color_de_token(texto, self.mapa)
            if color is not None and ident in self.id_to_vgroup_dict:
                self.id_to_vgroup_dict[ident].set_color(color)

    @classmethod
    def desde_paso(cls, paso: Paso, **kw) -> "Ecuacion":
        return cls(*paso.tokens, **kw)

    # ---------------------------------------------------------- acceso a tokens
    def tiene(self, token: str) -> bool:
        token = normalizar_token(token)
        return any(p.tex_string == token for p in self.submobjects)

    def partes(self, token: str) -> VGroup:
        """Todos los submobjects cuyo token es ``token``."""
        token = normalizar_token(token)
        return VGroup(*[p for p in self.submobjects if p.tex_string == token])

    def parte(self, token: str, ocurrencia: int = 0) -> VMobject:
        """El submobject de la ``ocurrencia``-esima aparicion de ``token``."""
        encontradas = self.partes(token)
        if ocurrencia >= len(encontradas):
            raise KeyError(f"token {token!r} (ocurrencia {ocurrencia}) no esta en {self.tokens}")
        return encontradas[ocurrencia]

    def indice_relacion(self) -> int | None:
        for i, t in enumerate(self.tokens):
            if t in RELACIONES:
                return i
        return None


class EcuacionColoreada(Ecuacion):
    """Compat: acepta uno o varios strings LaTeX enteros y los tokeniza."""

    def __init__(self, *tex_strings: str, **kw) -> None:
        mapa = kw.get("mapa") or COLOR_SEMANTICO
        variables = {"x", "y", "n"} | {k for k in mapa if len(k) == 1 and k.isalpha()}
        latex = " ".join(str(s) for s in tex_strings)
        super().__init__(*tokenizar_latex(latex, variables=variables), **kw)


# ============================================================ transicion


class TransformarTokens(TransformMatchingTex):
    """``TransformMatchingTex`` robusto para manim 0.21.

    Tokens con igual ``tex_string`` => ``Transform`` (vuelan). ``key_map`` (por defecto el
    automatico de ``emparejar_tokens``) => ``FadeTransform`` (uno se funde en el otro mientras viaja). Resto:
    ``FadeOut`` hacia los nuevos y ``FadeIn`` desde los viejos. Orden determinista.
    """

    def __init__(self, mobject, target_mobject, key_map: dict | None = None, **kwargs) -> None:
        kwargs.pop("fade_transform_mismatches", None)
        kwargs.pop("transform_mismatches", None)
        kwargs.setdefault("path_arc", 0)
        origen = self.get_shape_map(mobject)
        destino = self.get_shape_map(target_mobject)
        if key_map is None:
            key_map = emparejar_tokens(list(origen), list(destino))

        comunes = [k for k in origen if k in destino]
        anims = []
        if comunes:
            anims.append(
                Transform(VGroup(*[origen[k] for k in comunes]), VGroup(*[destino[k] for k in comunes]), **kwargs)
            )
        for k1, k2 in key_map.items():
            if k1 in origen and k2 in destino and k1 not in destino and k2 not in origen:
                anims.append(FadeTransform(origen.pop(k1), destino.pop(k2), **kwargs))

        sobran = VGroup(*[origen[k] for k in origen if k not in destino])
        faltan = VGroup(*[destino[k] for k in destino if k not in origen])
        faltan_copia = faltan.copy()
        extra = {k: v for k, v in kwargs.items() if k != "path_arc"}
        if len(sobran):
            anims.append(FadeOut(sobran, target_position=faltan if len(faltan) else sobran, **extra))
        if len(faltan):
            anims.append(FadeIn(faltan_copia, target_position=sobran if len(sobran) else faltan, **extra))
        AnimationGroup.__init__(self, *anims)
        self.to_remove = [mobject, faltan_copia]
        self.to_add = target_mobject


def animar_paso_algebraico(escena, eq_origen, eq_destino, run_time: float = 1.5) -> None:
    """Compat: transicion que empareja tokens (sin path_arc)."""
    escena.play(TransformarTokens(eq_origen, eq_destino, path_arc=0), run_time=run_time)


# ============================================================ derivacion


def _texto_envuelto(texto: str, ancho: float, tamano: float = FUENTE_ETIQUETA, color=GRIS) -> VGroup:
    """Texto gris partido por palabras en lineas de ancho <= ``ancho`` (centradas)."""
    from .tipografia import Texto

    lineas: list[str] = []
    actual = ""
    for palabra in texto.split():
        candidata = f"{actual} {palabra}".strip()
        if actual and Texto(candidata, tamano=tamano).width > ancho:
            lineas.append(actual)
            actual = palabra
        else:
            actual = candidata
    if actual:
        lineas.append(actual)
    if len(lineas) > 2:
        logger.warning("explicacion larga (%d lineas): %r", len(lineas), texto)
    grupo = VGroup(*[Texto(l, tamano=tamano, color=color) for l in lineas])
    return grupo.arrange(DOWN, buff=0.12)



class DerivacionVisual:
    """Dirige una secuencia de ``Paso`` en pantalla con transiciones que emparejan tokens.

    modo "reemplazar": una ecuacion a la vez, con el "=" fijo. modo "acumular": pila de
    pasos alineados por "=" (como mucho ``max_visibles``, y menos si no caben en la zona);
    los anteriores se atenuan (``OPACIDAD_PASO_ANTERIOR``) y suben, el mas viejo sale.
    """

    def __init__(
        self,
        escena,
        pasos: Sequence[Paso],
        zona: Zona = ZONA_PRINCIPAL,
        tamano: float = FUENTE_MATEMATICA,
        mostrar_explicacion: bool = True,
        modo: str = "reemplazar",
        max_visibles: int = 4,
        mapa: Mapping[str, str] | None = None,
        espacio: float = MARGEN_ENTRE_BLOQUES,
    ) -> None:
        if not pasos:
            raise ValueError("DerivacionVisual necesita al menos un paso")
        if modo not in ("reemplazar", "acumular"):
            raise ValueError(f"modo desconocido: {modo!r}")
        if max_visibles < 1:
            raise ValueError("max_visibles debe ser >= 1")
        self.escena = escena
        self.pasos = list(pasos)
        self.zona = zona
        self.modo = modo
        self.max_visibles = max_visibles
        self.espacio = espacio
        self.mostrar_explicacion = mostrar_explicacion
        self.indice = -1
        self.visibles: list[Ecuacion] = []
        self.explicacion = None
        self.caja = None

        self._zona_explicacion, self._zona_ecuaciones = self._partir_zona()
        ancho_util = self._zona_ecuaciones.ancho - 2 * MARGEN_ZONA
        self.ecuaciones: list[Ecuacion] = []
        for i, paso in enumerate(self.pasos):
            eq = Ecuacion.desde_paso(paso, tamano=tamano, mapa=mapa)
            if eq.width > ancho_util:
                logger.warning("paso %d mide %.2f > %.2f de ancho util: se reduce", i, eq.width, ancho_util)
                eq.scale_to_fit_width(ancho_util)
            self.ecuaciones.append(eq)
        self._x_relacion = self._calcular_eje(self.ecuaciones)

    # ---------------------------------------------------------- layout
    def _partir_zona(self) -> tuple[Zona | None, Zona]:
        """Reserva arriba una franja para la explicacion, del alto de la mas alta (1-2 lineas)."""
        self._textos_explicacion: dict[int, VGroup] = {}
        if not self.mostrar_explicacion or not any(p.explicacion for p in self.pasos):
            return None, self.zona
        ancho = self.zona.ancho - 2 * MARGEN_ZONA
        for i, paso in enumerate(self.pasos):
            if paso.explicacion:
                self._textos_explicacion[i] = _texto_envuelto(paso.explicacion, ancho)
        alto = max(t.height for t in self._textos_explicacion.values()) + 2 * MARGEN_ZONA
        z = self.zona
        return (
            Zona(f"{z.nombre}_explicacion", z.x_min, z.x_max, z.y_max - alto, z.y_max),
            Zona(f"{z.nombre}_ecuaciones", z.x_min, z.x_max, z.y_min, z.y_max - alto),
        )

    @staticmethod
    def _extremos(eq: Ecuacion) -> tuple[float, float] | None:
        """(ancho a la izquierda, ancho a la derecha) del centro del primer token de relacion."""
        i = eq.indice_relacion()
        if i is None:
            return None
        x = eq[i].get_center()[0]
        return x - eq.get_left()[0], eq.get_right()[0] - x

    def _calcular_eje(self, ecuaciones: Sequence[Ecuacion]) -> float | None:
        """x del "=" comun que centra el conjunto; None si no cabe o no hay relaciones."""
        extremos = [e for e in (self._extremos(eq) for eq in ecuaciones) if e is not None]
        if not extremos:
            return None
        izq = max(e[0] for e in extremos)
        der = max(e[1] for e in extremos)
        if izq + der > self._zona_ecuaciones.ancho - 2 * MARGEN_ZONA:
            return None
        return float(self._zona_ecuaciones.centro[0] - (der - izq) / 2)

    def _x_de(self, eq: Ecuacion, eje: float | None) -> np.ndarray:
        """Desplazamiento horizontal que pone el "=" de ``eq`` en ``eje`` (o la centra)."""
        i = eq.indice_relacion()
        if eje is None or i is None:
            return np.array([self._zona_ecuaciones.centro[0] - eq.get_center()[0], 0, 0])
        return np.array([eje - eq[i].get_center()[0], 0, 0])

    def _cuantas_caben(self, lista: Sequence[Ecuacion]) -> int:
        alto_util = self._zona_ecuaciones.alto - 2 * MARGEN_ZONA
        k = 0
        total = 0.0
        for eq in reversed(lista[-self.max_visibles :]):
            nuevo = total + eq.height + (self.espacio if k else 0.0)
            if k and nuevo > alto_util:
                break
            total, k = nuevo, k + 1
        return max(k, 1)

    def _destinos(self, lista: Sequence[Ecuacion]) -> list[np.ndarray]:
        """Desplazamiento de cada ecuacion de ``lista`` a su lugar en la zona."""
        z = self._zona_ecuaciones
        eje = self._x_relacion
        if eje is None:  # el conjunto completo no cabe alineado: se intenta con los visibles
            eje = self._calcular_eje(lista)
        if self.modo == "reemplazar":
            eq = lista[-1]
            dy = z.centro[1] - eq.get_center()[1]
            return [self._x_de(eq, eje) + np.array([0, dy, 0])]
        desplazamientos = []
        tope = z.y_max - MARGEN_ZONA
        for eq in lista:
            dy = tope - eq.get_top()[1]
            desplazamientos.append(self._x_de(eq, eje) + np.array([0, dy, 0]))
            tope -= eq.height + self.espacio
        return desplazamientos

    # ---------------------------------------------------------- explicacion
    def _texto_explicacion(self, indice: int):
        texto = self._textos_explicacion.get(indice)
        if self._zona_explicacion is None or texto is None:
            return None
        from .layout import encajar

        return encajar(texto, self._zona_explicacion, margen=MARGEN_ZONA)

    def _animaciones_explicacion(self, indice: int) -> list:
        anims = []
        nuevo = self._texto_explicacion(indice)
        if self.explicacion is not None:
            anims.append(FadeOut(self.explicacion, shift=UP * 0.2))
        if nuevo is not None:
            anims.append(FadeIn(nuevo, shift=UP * 0.2))
        self.explicacion = nuevo
        return anims

    # ---------------------------------------------------------- API
    @property
    def actual(self) -> Ecuacion:
        if self.indice < 0:
            raise RuntimeError("todavia no se ha mostrado ningun paso (llama a mostrar_inicial)")
        return self.ecuaciones[self.indice]

    @property
    def quedan_pasos(self) -> bool:
        return self.indice + 1 < len(self.pasos)

    @property
    def grupo(self) -> VGroup:
        """Todo lo que la derivacion tiene en pantalla (ecuaciones visibles, explicacion, caja)."""
        mobs = list(self.visibles)
        mobs += [m for m in (self.explicacion, self.caja) if m is not None]
        return VGroup(*mobs)

    def mostrar_inicial(
        self,
        run_time: float = 1.2,
        animaciones_extra: Sequence = (),
        desde: Mobject | None = None,
    ) -> None:
        """Write del paso 0 (+ su explicacion) en el mismo ``play`` que ``animaciones_extra``.

        ``desde``: un mob ya en pantalla (p. ej. la misma ecuacion en grande en el gancho) que
        vuela y se convierte en la fila 0 (``ReplacementTransform``) en vez de escribirla.
        """
        if self.indice >= 0:
            raise RuntimeError("mostrar_inicial ya se llamo")
        self.indice = 0
        eq = self.ecuaciones[0]
        eq.shift(self._destinos([eq])[0])
        self.visibles = [eq]
        if desde is not None:
            anims = [ReplacementTransform(desde, eq, run_time=run_time)]
        else:
            anims = [Write(eq, run_time=run_time)]
        anims += [a for a in self._animaciones_explicacion(0)]
        for a in anims[1:]:
            a.run_time = min(run_time, 0.6)
        self.escena.play(*anims, *animaciones_extra)

    def siguiente(
        self,
        run_time: float = TIEMPO_TRANSFORMAR,
        animaciones_extra: Sequence = (),
        indicar: bool = True,
    ) -> None:
        """Transicion al siguiente paso emparejando tokens; ``animaciones_extra`` van en el mismo play.

        Despues, si ``indicar``, ``Indicate`` de los tokens de ``Paso.resaltar``.
        """
        if self.indice < 0:
            self.mostrar_inicial()
            return
        if not self.quedan_pasos:
            raise IndexError("no quedan pasos en la derivacion")
        previa = self.actual
        self.indice += 1
        nueva = self.ecuaciones[self.indice]
        paso = self.pasos[self.indice]
        anims = []
        if self.modo == "reemplazar":
            nueva.shift(self._destinos([nueva])[0])
            anims.append(TransformarTokens(previa, nueva, run_time=run_time))
            self.visibles = [nueva]
            for a in self._animaciones_explicacion(self.indice):
                a.run_time = min(run_time, 0.6)
                anims.append(a)
            self.escena.play(*anims, *animaciones_extra)
        else:
            # Dos fases para que nunca se superpongan tres capas de texto: primero las filas
            # previas suben/se atenuan (y sale la mas vieja); despues la copia de la anterior
            # (ya en su sitio nuevo) se transforma en la fila nueva, junto a animaciones_extra.
            t_subir = run_time * FRACCION_FASE_SUBIR
            t_transformar = run_time - t_subir
            candidatas = self.visibles + [nueva]
            k = self._cuantas_caben(candidatas)
            quedan, salen = candidatas[-k:], candidatas[:-k]
            desplazamientos = self._destinos(quedan)
            nueva.shift(desplazamientos[-1])
            for eq, d in zip(quedan[:-1], desplazamientos[:-1]):
                anims.append(eq.animate(run_time=t_subir).shift(d).set_opacity(OPACIDAD_PASO_ANTERIOR))
            for eq in salen:
                anims.append(FadeOut(eq, shift=UP * 0.3, run_time=t_subir))
            for a in self._animaciones_explicacion(self.indice):
                a.run_time = min(t_subir, 0.6)
                anims.append(a)
            if anims:
                self.escena.play(*anims)
            origen = previa.copy().set_opacity(1)
            self.visibles = quedan
            self.escena.play(TransformarTokens(origen, nueva, run_time=t_transformar), *animaciones_extra)
        if indicar and paso.resaltar:
            tokens = VGroup(*[nueva[i] for i in paso.resaltar])
            self.escena.play(Indicate(tokens, color=AMARILLO, scale_factor=1.15, run_time=TIEMPO_ENFASIS))

    def todos(self, pausa: float = 0.5) -> None:
        """Muestra (si hace falta) y recorre todos los pasos con ``pausa`` entre ellos."""
        if self.indice < 0:
            self.mostrar_inicial()
            self.escena.wait(pausa)
        while self.quedan_pasos:
            self.siguiente()
            self.escena.wait(pausa)

    def resultado_final(self, color=AMARILLO):
        """Caja de resultado + Flash sobre la ecuacion actual. Devuelve la caja."""
        eq = self.actual
        try:
            from .animaciones import caja_resultado

            caja, anim_caja = caja_resultado(eq, color=color)
        except ImportError:  # animaciones.py aun no disponible
            from manim import Create, SurroundingRectangle

            caja = SurroundingRectangle(eq, color=color, buff=0.25, corner_radius=0.1)
            anim_caja = Create(caja, run_time=0.6)
        flash = Flash(
            eq.get_center(),
            color=color,
            flash_radius=max(caja.width, caja.height) / 2 + 0.1,
            line_length=0.25,
            num_lines=16,
            run_time=0.8,
        )
        self.escena.play(anim_caja, flash)
        self.caja = caja
        return caja
