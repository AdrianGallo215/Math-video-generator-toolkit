"""Familia algoritmos del catálogo del guion técnico (G02): arreglos, punteros, código, cuadrículas y pilas.

Envuelve ``toolkit.algoritmos_visual`` (``ArregloVisual``, ``Puntero``, ``CodigoResaltado``, ``PilaVisual``) sin
duplicar su lógica; solo agrega ``CuadriculaVisual`` (la cuadrícula n×n con cabeceras, cursores y ``expandir`` que
V04 armaba a mano en la escena).

Tipos: ``arreglo``, ``puntero``, ``codigo``, ``cuadricula``, ``pila``.
Verbos: ``apuntar``, ``colorear``, ``atenuar_rango``, ``restablecer_celdas``, ``intercambiar``, ``comparar``,
``resaltar_linea``, ``expandir``, ``cursor``, ``apilar``, ``desapilar`` y los que consumen la traza de un motor
(``paso_busqueda``, ``paso_burbuja``; la traza sale de ``calculos:`` con ``{traza}`` o ``{traza.N.mid}``).

Direccionamiento de partes (``objeto: arr.celda3``, ``objeto: cuad.fila:2``):
- arreglo: ``celdaK`` (o solo ``K``), la celda que ocupa hoy la posición K (sigue a los intercambios).
- cuadrícula: ``celda:r,c``, ``fila:r``, ``columna:c``, ``cuadrante:si|sd|ii|id``, ``cabecera_sup:i``,
  ``cabecera_izq:i`` (todo 0-based; los cuadrantes son mitades de la cuadrícula actual, así que tras ``expandir``
  ``cuadrante:si`` es la cuadrícula original).
"""

from __future__ import annotations

import re
import weakref
from typing import Any, Callable

from manim import (
    DOWN,
    LEFT,
    RIGHT,
    UP,
    UL,
    Animation,
    AnimationGroup,
    Create,
    FadeIn,
    LaggedStart,
    Mobject,
    Rectangle,
    Square,
    SurroundingRectangle,
    Transform,
    VGroup,
)

from toolkit.algoritmos_visual import ArregloVisual, CodigoResaltado, PilaVisual, Puntero
from toolkit.estilos import (
    FUENTE_MINIMA,
    GRIS,
    GROSOR_LINEA_FINA,
    GROSOR_LINEA_MEDIA,
    OPACIDAD_ATENUADO,
    ROJO,
    TIEMPO_ENFASIS,
    VERDE,
    AMARILLO,
)
from toolkit.guion.contexto import ALINEACIONES, ATRIBUTO_PARTES, MARGEN_ZONA, ContextoGuion, _error, separar_ref
from toolkit.guion.esquema import sugerencia
from toolkit.guion.registro import Param, accion, objeto

MAX_VALORES = 32  # más celdas no caben legibles en una zona principal
MAX_LADO_CUADRICULA = 16
MAX_LINEA_CODIGO = 24  # caracteres por línea (CodigoResaltado a FUENTE_MINIMA)
MAX_LINEAS_CODIGO = 12
MAX_MARCOS_PILA = 6
LADO_CUADRO = 0.38  # celda de la cuadrícula antes de escalar (V04)
SEPARACION_CUADROS = 0.04
SEPARACION_CABECERA = 0.12
OPACIDAD_CABECERA = 0.55
LADOS_PILA_DIRECCION = {"arriba": UP, "abajo": DOWN}
CUADRANTES = {"si": (0, 0), "sd": (0, 1), "ii": (1, 0), "id": (1, 1)}
_PARAM_ZONA = Param("zona", "zona", defecto="principal",
                    descripcion="Zona donde se encaja (nombre) o {de: id, lado: abajo|arriba|izq|der, espacio: 0.3}.")
_PARAM_ALINEACION = Param("alineacion", "texto", defecto="centro", opciones=tuple(ALINEACIONES),
                          descripcion="Borde de la zona al que se pega.")


def _como_lista(valor: Any) -> list:
    return list(valor) if isinstance(valor, (list, tuple)) else [valor]


# --- Función pura: partes de una cuadrícula ---------------------------------------------------------


def celdas_de_parte(parte: str | None, n: int) -> list[tuple[int, int]]:
    """Celdas ``(fila, columna)`` de una parte de una cuadrícula n×n (``ValueError`` con qué corregir).

    ``None``/``""``/``"todo"``: todas · ``fila:r`` · ``columna:c`` · ``celda:r,c`` · ``cuadrante:si|sd|ii|id``.
    """
    if parte in (None, "", "todo"):
        return [(r, c) for r in range(n) for c in range(n)]
    tipo, _, valor = str(parte).partition(":")

    def entero(texto: str, nombre: str) -> int:
        try:
            k = int(texto)
        except ValueError:
            raise ValueError(f"'{parte}': {nombre} debe ser un número entero, no '{texto}'") from None
        if not 0 <= k < n:
            raise ValueError(f"'{parte}': {nombre} {k} fuera de la cuadrícula (0-{n - 1})")
        return k

    if tipo == "fila":
        r = entero(valor, "la fila")
        return [(r, c) for c in range(n)]
    if tipo == "columna":
        c = entero(valor, "la columna")
        return [(r, c) for r in range(n)]
    if tipo == "celda":
        partes = valor.split(",")
        if len(partes) != 2:
            raise ValueError(f"'{parte}': escribe celda:fila,columna (p. ej. celda:2,3)")
        return [(entero(partes[0], "la fila"), entero(partes[1], "la columna"))]
    if tipo == "cuadrante":
        if valor not in CUADRANTES:
            raise ValueError(f"'{parte}': cuadrante inválido.{sugerencia(valor, CUADRANTES)} "
                             f"Cuadrantes: {', '.join(CUADRANTES)} (si=sup. izquierdo, sd=sup. derecho, ...)")
        if n % 2:
            raise ValueError(f"'{parte}': la cuadrícula de {n}×{n} no se parte en cuadrantes (n debe ser par)")
        mitad = n // 2
        f0, c0 = CUADRANTES[valor]
        return [(r, c) for r in range(f0 * mitad, (f0 + 1) * mitad) for c in range(c0 * mitad, (c0 + 1) * mitad)]
    raise ValueError(f"parte '{parte}' desconocida: usa celda:r,c · fila:r · columna:c · cuadrante:si|sd|ii|id · "
                     "cabecera_sup:i · cabecera_izq:i")


# --- Partes perezosas (siguen a los intercambios / expansiones) -----------------------------------------


class _Partes(dict):
    """Diccionario de partes que se resuelve al consultar (no se congela al construir)."""

    def __init__(self, dueno: Mobject | None = None, ejemplos: Callable[[Any], list[str]] | None = None) -> None:
        super().__init__()
        self._dueno = weakref.ref(dueno) if dueno is not None else None
        self._ejemplos = ejemplos

    def _resolver(self, clave: str) -> Mobject:
        dueno = self._dueno() if self._dueno else None
        if dueno is None:
            raise KeyError(clave)
        try:
            return dueno.parte(clave)
        except ValueError as error:
            raise KeyError(clave) from error

    def __contains__(self, clave: object) -> bool:
        try:
            self._resolver(str(clave))
        except (KeyError, IndexError):
            return False
        return True

    def __getitem__(self, clave: str) -> Mobject:
        return self._resolver(str(clave))

    def get(self, clave, defecto=None):
        return self[clave] if clave in self else defecto

    def __iter__(self):
        dueno = self._dueno() if self._dueno else None
        return iter(self._ejemplos(dueno) if dueno is not None and self._ejemplos else [])

    def __len__(self) -> int:
        return len(list(iter(self)))


def _partes_arreglo(arreglo: ArregloVisual) -> list[str]:
    return [f"celda{k}" for k in range(len(arreglo.celdas))]


def _celda_de_arreglo(arreglo: ArregloVisual, parte: str) -> Mobject:
    m = re.fullmatch(r"(?:celda)?(\d+)", parte)
    if m is None or int(m.group(1)) >= len(arreglo.celdas):
        raise ValueError(parte)
    return arreglo.celda(int(m.group(1)))


class ArregloDireccionable(ArregloVisual):
    """``ArregloVisual`` que responde a ``parte('celda3')`` (la celda que hoy ocupa la posición 3)."""

    def parte(self, nombre: str) -> Mobject:
        return _celda_de_arreglo(self, nombre)


# --- CuadriculaVisual --------------------------------------------------------------------------------------


class CuadriculaVisual(VGroup):
    """Cuadrícula n×n de celdas (borde gris, relleno rojo a 0) con cabeceras verdes opcionales y dos cursores.

    Los cursores (``cursor_fila``, ``cursor_col``) nacen invisibles dentro del grupo (así salen con él).
    ``expandir()`` duplica n manteniendo el contorno exterior (V04 seg. 10: 8×8 → 16×16).
    """

    def __init__(self, n: int, cabeceras: bool = False, color_borde=GRIS, lado: float = LADO_CUADRO,
                 separacion: float = SEPARACION_CUADROS, separacion_cabecera: float = SEPARACION_CABECERA,
                 **kwargs):
        super().__init__(**kwargs)
        if n < 1:
            raise ValueError("n debe ser >= 1")
        self.n = n
        self.color_borde = color_borde
        self.lado = lado
        self.separacion = separacion
        self.separacion_cabecera = separacion_cabecera
        self.celdas: list[Mobject] = [
            Square(lado, stroke_color=color_borde, stroke_width=GROSOR_LINEA_FINA, fill_color=ROJO, fill_opacity=0.0)
            for _ in range(n * n)
        ]
        self.grupo_celdas = VGroup(*self.celdas).arrange_in_grid(n, n, buff=separacion)
        self.cab_sup: list[Mobject] = []
        self.cab_izq: list[Mobject] = []
        self.grupo_cab_sup = VGroup()
        self.grupo_cab_izq = VGroup()
        if cabeceras:
            self.cab_sup = [self._cabecera() for _ in range(n)]
            self.cab_izq = [self._cabecera() for _ in range(n)]
            self.grupo_cab_sup = VGroup(*self.cab_sup).arrange(direction=RIGHT, buff=separacion)
            self.grupo_cab_izq = VGroup(*self.cab_izq).arrange(direction=DOWN, buff=separacion)
            self.grupo_cab_sup.next_to(self.grupo_celdas, UP, buff=separacion_cabecera).align_to(
                self.grupo_celdas, LEFT)
            self.grupo_cab_izq.next_to(self.grupo_celdas, LEFT, buff=separacion_cabecera).align_to(
                self.grupo_celdas, UP)
        self.cursor_fila = self._cursor_nuevo()
        self.cursor_col = self._cursor_nuevo()
        self.add(self.grupo_celdas, self.grupo_cab_sup, self.grupo_cab_izq, self.cursor_fila, self.cursor_col)
        setattr(self, ATRIBUTO_PARTES, _Partes(self, _ejemplos_cuadricula))

    # --- construcción ----------------------------------------------------------------------------

    def _cabecera(self) -> Square:
        return Square(self.lado, stroke_color=VERDE, stroke_width=GROSOR_LINEA_FINA, fill_color=VERDE,
                      fill_opacity=OPACIDAD_CABECERA)

    def _cursor_nuevo(self) -> Rectangle:
        cursor = Rectangle(width=self.lado, height=self.lado, stroke_color=AMARILLO, stroke_width=GROSOR_LINEA_MEDIA,
                           fill_opacity=0.0)
        cursor.move_to(self.grupo_celdas.get_center())
        return cursor.set_stroke(opacity=0.0)

    @property
    def con_cabeceras(self) -> bool:
        return bool(self.cab_sup)

    def celda(self, fila: int, columna: int) -> Mobject:
        return self.celdas[fila * self.n + columna]

    def celdas_de(self, parte: str | None) -> list[Mobject]:
        return [self.celda(r, c) for r, c in celdas_de_parte(parte, self.n)]

    def parte(self, nombre: str) -> Mobject:
        """Sub-elemento direccionable (``ValueError`` si no existe)."""
        tipo, _, valor = str(nombre).partition(":")
        if tipo in ("cabecera_sup", "cabecera_izq"):
            lista = self.cab_sup if tipo == "cabecera_sup" else self.cab_izq
            if not lista:
                raise ValueError(f"'{nombre}': la cuadrícula no tiene cabeceras (cabeceras: true)")
            if not valor.isdigit() or int(valor) >= len(lista):
                raise ValueError(f"'{nombre}': índice inválido (0-{len(lista) - 1})")
            return lista[int(valor)]
        celdas = self.celdas_de(nombre)
        return celdas[0] if len(celdas) == 1 else VGroup(*celdas)

    def objetivo_cursor(self, fila: int | None, columna: int | None) -> tuple[Mobject, Mobject]:
        """Mobjects que rodean los cursores de fila y de columna (la cabecera, o la primera celda sin cabeceras)."""
        for k, nombre in ((fila, "fila"), (columna, "columna")):
            if k is not None and not 0 <= k < self.n:
                raise ValueError(f"{nombre} {k} fuera de la cuadrícula (0-{self.n - 1})")
        de_fila = None if fila is None else (self.cab_izq[fila] if self.con_cabeceras else self.celda(fila, 0))
        de_col = None if columna is None else (self.cab_sup[columna] if self.con_cabeceras else self.celda(0, columna))
        return de_fila, de_col

    # --- animaciones -----------------------------------------------------------------------------

    @staticmethod
    def _visible(cursor: Mobject) -> bool:
        return cursor.get_stroke_opacity() > 0.01

    def _mover(self, cursor: Rectangle, destino: Mobject, color) -> Animation:
        objetivo = SurroundingRectangle(destino, color=color, buff=self.separacion * 0.75,
                                        stroke_width=GROSOR_LINEA_MEDIA)
        if not self._visible(cursor):
            cursor.become(objetivo.copy().set_stroke(opacity=0.0))
        return Transform(cursor, objetivo)

    def mover_cursor(self, fila: int | None = None, columna: int | None = None, color=AMARILLO) -> list[Animation]:
        """Lleva (creándolo si hace falta) el cursor de fila y/o de columna."""
        de_fila, de_col = self.objetivo_cursor(fila, columna)
        animaciones = []
        if de_fila is not None:
            animaciones.append(self._mover(self.cursor_fila, de_fila, color))
        if de_col is not None:
            animaciones.append(self._mover(self.cursor_col, de_col, color))
        return animaciones

    def quitar_cursores(self) -> list[Animation]:
        return [Transform(c, c.copy().set_stroke(opacity=0.0)) for c in (self.cursor_fila, self.cursor_col)
                if self._visible(c)]

    def expandir(self) -> tuple[Animation, Callable[[], None]]:
        """Animación que duplica n conservando el contorno y la función que consolida los grupos (llamar tras el play).

        Las celdas y cabeceras actuales se reducen a la esquina superior izquierda (conservan su relleno) y
        aparecen las nuevas. El estado (``n``, ``celdas``, cabeceras) ya queda actualizado al devolver.
        """
        n, nuevo_n = self.n, self.n * 2
        contorno = n * self.lado + (n - 1) * self.separacion
        lado = self.lado / 2
        separacion = (contorno - nuevo_n * lado) / (nuevo_n - 1)
        grande = CuadriculaVisual(nuevo_n, self.con_cabeceras, self.color_borde, lado, separacion,
                                  self.separacion_cabecera)
        grande.shift(self.grupo_celdas.get_corner(UL) - grande.grupo_celdas.get_corner(UL))

        animaciones: list[Animation] = list(self.quitar_cursores())
        lista_nueva: list[Mobject] = [None] * (nuevo_n * nuevo_n)  # type: ignore[list-item]
        for r in range(n):
            for c in range(n):
                vieja = self.celdas[r * n + c]
                destino = grande.celdas[r * nuevo_n + c].copy().set_fill(
                    vieja.get_fill_color(), vieja.get_fill_opacity())
                animaciones.append(Transform(vieja, destino))
                lista_nueva[r * nuevo_n + c] = vieja
        creadas: list[Mobject] = []
        for r in range(nuevo_n):
            for c in range(nuevo_n):
                if lista_nueva[r * nuevo_n + c] is None:
                    nueva = grande.celdas[r * nuevo_n + c]
                    lista_nueva[r * nuevo_n + c] = nueva
                    creadas.append(nueva)
        extras_sup = extras_izq = []
        if self.con_cabeceras:
            for k in range(n):
                animaciones.append(Transform(self.cab_sup[k], grande.cab_sup[k].copy()))
                animaciones.append(Transform(self.cab_izq[k], grande.cab_izq[k].copy()))
            extras_sup, extras_izq = grande.cab_sup[n:], grande.cab_izq[n:]
        animacion = AnimationGroup(
            *animaciones,
            LaggedStart(*[Create(c) for c in creadas], lag_ratio=0.004),
            *([FadeIn(*extras_sup, *extras_izq)] if extras_sup else []),
        )
        self.n, self.lado, self.separacion = nuevo_n, lado, separacion
        self.celdas = lista_nueva
        self.cab_sup = self.cab_sup + list(extras_sup)
        self.cab_izq = self.cab_izq + list(extras_izq)

        def consolidar() -> None:
            self.grupo_celdas.add(*creadas)
            self.grupo_cab_sup.add(*extras_sup)
            self.grupo_cab_izq.add(*extras_izq)

        return animacion, consolidar


def _ejemplos_cuadricula(cuad: CuadriculaVisual) -> list[str]:
    n = cuad.n
    partes = [f"fila:{r}" for r in range(n)] + [f"columna:{c}" for c in range(n)] + ["celda:r,c"]
    if n % 2 == 0:
        partes += [f"cuadrante:{q}" for q in CUADRANTES]
    if cuad.con_cabeceras:
        partes += ["cabecera_sup:i", "cabecera_izq:i"]
    return partes


# --- Ayudas de validación (ganchos ``ciclo``) ------------------------------------------------------------


def _info(estado) -> dict:
    """Datos por id que las piezas de esta familia recuerdan durante la validación (tamaño, arreglo del puntero...)."""
    return estado.__dict__.setdefault("info_alg", {})


def _base(estado, ref: Any, tipos: tuple[str, ...], admite_parte: bool = False):
    """Usa ``ref`` y comprueba su tipo; devuelve ``(id, parte, info)`` o ``None`` (ya reportó el error)."""
    if not isinstance(ref, str):
        return None
    id, parte = separar_ref(ref)
    if parte is not None and not admite_parte:
        estado.error("E3", f"este verbo actúa sobre el objeto completo: usa '{id}', no '{ref}'")
        return None
    if not estado.usar(ref):
        return None
    tipo = estado.tipos.get(id)
    if tipo not in tipos:
        estado.error("E3", f"'{id}' es de tipo '{tipo}'; este verbo actúa sobre: {', '.join(tipos)}")
        return None
    return id, parte, _info(estado).get(id, {})


def _en_rango(estado, valor: Any, n: int | None, nombre: str, minimo: int = 0) -> bool:
    if not isinstance(valor, int) or isinstance(valor, bool) or n is None:
        return True
    if not minimo <= valor < n + minimo:
        estado.error("E3", f"{nombre}={valor} fuera de rango: hay {n} elementos ({minimo}-{n + minimo - 1})")
        return False
    return True


def _rango_pedido(estado, params: dict, n: int | None) -> None:
    for clave in ("desde", "hasta"):
        _en_rango(estado, params.get(clave), n, clave)
    desde, hasta = params.get("desde"), params.get("hasta")
    if isinstance(desde, int) and isinstance(hasta, int) and desde > hasta:
        estado.error("E3", f"desde ({desde}) no puede ser mayor que hasta ({hasta})")


def _traza_valida(estado, traza: Any, n: int | None, claves: tuple[str, ...]) -> list[dict] | None:
    if not isinstance(traza, list) or not traza:
        estado.error("E3", "traza debe ser la lista de pasos de un cálculo: usa traza: \"{nombre_del_calculo}\"")
        return None
    for k, paso in enumerate(traza):
        if not isinstance(paso, dict) or any(c not in paso for c in claves):
            estado.error("E3", f"traza[{k}] no tiene {', '.join(claves)}: ¿es la traza del motor correcto?")
            return None
    return traza


# --- arreglo --------------------------------------------------------------------------------------------------


def _ciclo_arreglo(params: dict, estado) -> None:
    valores = params.get("valores")
    if not isinstance(valores, list):
        return
    if not 1 <= len(valores) <= MAX_VALORES:
        estado.error("E3", f"valores: entre 1 y {MAX_VALORES} elementos (hay {len(valores)}); más celdas no se leen en un móvil")
    if any(isinstance(v, (list, dict)) for v in valores):
        estado.error("E3", "valores: cada elemento es un número o un texto corto")
    columnas = params.get("columnas_max")
    if isinstance(columnas, int) and columnas < 0:
        estado.error("E3", "columnas_max: 0 (automático) o un entero positivo")
    espacio = params.get("espacio_filas")
    if isinstance(espacio, (int, float)) and espacio < 0:
        estado.error("E3", "espacio_filas: debe ser ≥ 0")
    if estado.creando:
        _info(estado)[estado.creando] = {"tipo": "arreglo", "n": len(valores)}


@objeto(
    "arreglo",
    "Arreglo de celdas con valor (y índices opcionales), en una o varias filas; las celdas se direccionan como "
    "'id.celda3'. Punteros, colores, descartes e intercambios actúan sobre él.",
    params=[
        Param("valores", "lista", requerido=True, descripcion=f"Valores de las celdas (1-{MAX_VALORES}); p. ej. [3, 8, 12]."),
        Param("columnas_max", "entero", defecto=0,
              descripcion="Celdas por fila (0 = automático: las filas mínimas que quepan). 8 con 16 valores = 2 filas."),
        Param("indices", "booleano", defecto=True, descripcion="Muestra el índice (0, 1, 2...) bajo cada celda."),
        Param("color", "color", defecto="azul", descripcion="Color de las celdas."),
        Param("espacio_filas", "numero", defecto=None,
              descripcion="Hueco entre filas en unidades (defecto: el compacto; ~1.3 deja sitio a punteros entre filas)."),
        _PARAM_ZONA,
        _PARAM_ALINEACION,
    ],
    ejemplo={"en": "inicio", "hacer": "mostrar", "id": "arr", "tipo": "arreglo",
             "valores": [3, 8, 12, 17, 21, 25, 30, 34], "columnas_max": 4, "zona": "principal"},
    duracion=1.0,
    ciclo=_ciclo_arreglo,
)
def crear_arreglo(ctx: ContextoGuion, valores, columnas_max, indices, color, espacio_filas, zona, alineacion) -> Mobject:
    referencia = ctx.zona_de_referencia(zona)
    arreglo = ArregloDireccionable(
        valores,
        ancho_max=referencia.ancho - 2 * MARGEN_ZONA,
        con_indices=bool(indices),
        color=ctx.color(color),
        columnas_max=int(columnas_max) if columnas_max else None,
    )
    columnas = int(columnas_max) if columnas_max else 0
    if espacio_filas is not None and columnas and len(arreglo.celdas) > columnas:
        n = len(arreglo.celdas)
        filas = []
        for i in range(0, n, columnas):
            miembros = list(arreglo.celdas[i:i + columnas])
            if indices:
                miembros += list(arreglo.indices[i:i + columnas])
            filas.append(VGroup(*miembros))
        for previa, fila in zip(filas, filas[1:]):
            fila.next_to(previa, DOWN, buff=float(espacio_filas), aligned_edge=LEFT)
    setattr(arreglo, ATRIBUTO_PARTES, _Partes(arreglo, _partes_arreglo))
    ctx.colocar(arreglo, zona, alineacion)
    return arreglo


# --- puntero ---------------------------------------------------------------------------------------------------


def _ciclo_puntero(params: dict, estado) -> None:
    base = _base(estado, params.get("arreglo"), ("arreglo",))
    if base is None:
        return
    id_arreglo, _, info = base
    n = info.get("n")
    _en_rango(estado, params.get("en_celda"), n, "en_celda")
    if estado.creando:
        _info(estado)[estado.creando] = {"tipo": "puntero", "arreglo": id_arreglo, "n": n}


@objeto(
    "puntero",
    "Flecha con nombre ('lo', 'hi', 'mid', 'i') pegada a una celda de un arreglo; el verbo 'apuntar' la mueve.",
    params=[
        Param("nombre", "texto", requerido=True, descripcion="Etiqueta del puntero (lo, hi, mid, i...)."),
        Param("arreglo", "objeto", requerido=True, descripcion="Id del arreglo al que apunta."),
        Param("en_celda", "entero", requerido=True, descripcion="Índice de la celda (0-based). Con calculos: '{traza.0.mid}'."),
        Param("direccion", "texto", defecto="arriba", opciones=tuple(LADOS_PILA_DIRECCION),
              descripcion="Lado de la celda donde se ubica ('arriba': la flecha baja hacia la celda)."),
        Param("color", "color", defecto="turquesa", descripcion="Color de la flecha y la etiqueta."),
    ],
    ejemplo={"en": "inicio", "hacer": "mostrar", "id": "p_lo", "tipo": "puntero", "nombre": "lo", "arreglo": "arr",
             "en_celda": 0, "direccion": "abajo"},
    duracion=0.6,
    ciclo=_ciclo_puntero,
)
def crear_puntero(ctx: ContextoGuion, nombre, arreglo, en_celda, direccion, color) -> Mobject:
    dueno = ctx.obtener(arreglo)
    if not isinstance(dueno, ArregloVisual):
        raise _error("E3", f"'{arreglo}' no es un arreglo: un puntero apunta a las celdas de un arreglo", ctx.ubicacion)
    if not 0 <= en_celda < len(dueno.celdas):
        raise _error("E3", f"en_celda={en_celda} fuera del arreglo (0-{len(dueno.celdas) - 1})", ctx.ubicacion)
    puntero = Puntero(nombre, ctx.color(color), LADOS_PILA_DIRECCION[direccion])
    puntero.colocar_en(dueno.celda(en_celda))
    puntero.arreglo_ref = weakref.ref(dueno)  # weakref: Mobject.copy() hace deepcopy y no debe clonar el arreglo
    return puntero


def _celda_de_puntero(ctx: ContextoGuion, id_puntero: str, indice: int) -> Mobject:
    puntero = ctx.obtener(id_puntero)
    referencia = getattr(puntero, "arreglo_ref", None)
    dueno = referencia() if referencia else None
    if dueno is None:
        raise _error("E3", f"'{id_puntero}' no es un puntero de un arreglo vivo", ctx.ubicacion)
    if not 0 <= indice < len(dueno.celdas):
        raise _error("E3", f"a={indice} fuera del arreglo (0-{len(dueno.celdas) - 1})", ctx.ubicacion)
    return dueno.celda(indice)


def _ciclo_apuntar(params: dict, estado) -> None:
    base = _base(estado, params.get("objeto"), ("puntero",))
    if base is not None:
        _en_rango(estado, params.get("a"), base[2].get("n"), "a")


@accion(
    "apuntar",
    "Mueve un puntero a otra celda de su arreglo (con la flecha deslizándose).",
    params=[
        Param("objeto", "objeto", requerido=True, descripcion="Id del puntero."),
        Param("a", "entero", requerido=True, descripcion="Índice de la celda destino. Con calculos: '{traza.1.lo}'."),
    ],
    ejemplo={"en": "inicio", "hacer": "apuntar", "objeto": "p_lo", "a": 3},
    duracion=0.7,
    ciclo=_ciclo_apuntar,
)
def apuntar(ctx: ContextoGuion, objeto, a):
    ctx.marcar_foco(objeto)
    return ctx.obtener(objeto).apuntar_a(_celda_de_puntero(ctx, objeto, int(a)))


# --- verbos sobre arreglos y cuadrículas -------------------------------------------------------------------------


def _indices_de_arreglo(arreglo: ArregloVisual, parte: str | None, indices, desde, hasta) -> list[int]:
    n = len(arreglo.celdas)
    if parte is not None:
        try:
            _celda_de_arreglo(arreglo, parte)
        except ValueError:
            raise ValueError(f"el arreglo no tiene la parte '{parte}' (celda0..celda{n - 1})") from None
        return [int(re.sub(r"\D", "", parte))]
    if indices:
        lista = [int(k) for k in indices]
        malos = [k for k in lista if not 0 <= k < n]
        if malos:
            raise ValueError(f"índices {malos} fuera del arreglo (0-{n - 1})")
        return lista
    if desde is not None or hasta is not None:
        inicio, fin = (0 if desde is None else int(desde)), (n - 1 if hasta is None else int(hasta))
        if not (0 <= inicio <= fin < n):
            raise ValueError(f"rango {inicio}..{fin} fuera del arreglo (0-{n - 1})")
        return list(range(inicio, fin + 1))
    return list(range(n))


def _ciclo_colorear(params: dict, estado) -> None:
    for ref in _como_lista(params.get("objeto")):
        base = _base(estado, ref, ("arreglo", "cuadricula"), admite_parte=True)
        if base is None:
            continue
        id, parte, info = base
        n = info.get("n")
        if estado.tipos.get(id) == "arreglo":
            if parte is not None and not re.fullmatch(r"(?:celda)?\d+", parte):
                estado.error("E3", f"'{ref}': las celdas de un arreglo se llaman celda0, celda1...")
            elif parte is not None:
                _en_rango(estado, int(re.sub(r"\D", "", parte)), n, "celda")
            for k in _como_lista(params.get("indices") or []):
                _en_rango(estado, k, n, "índice")
            _rango_pedido(estado, params, n)
        elif n is not None:
            try:
                celdas_de_parte(parte if parte and not parte.startswith("cabecera") else None, n)
            except ValueError as error:
                estado.error("E3", str(error))


def _pintar_celdas(cuad: CuadriculaVisual, parte: str | None, color: str | None, opacidad: float) -> Animation:
    celdas = cuad.celdas_de(parte)
    if color is None:
        return AnimationGroup(*[Transform(c, c.copy().set_fill(opacity=0.0)) for c in celdas])
    return AnimationGroup(*[Transform(c, c.copy().set_fill(color, opacidad)) for c in celdas])


def _aplicar_a_celdas(ctx: ContextoGuion, objeto, indices, desde, hasta, con_arreglo, con_cuadricula) -> list[Animation]:
    animaciones = []
    for ref in _como_lista(objeto):
        id, parte = separar_ref(ref)
        base = ctx.obtener(id)
        ctx.marcar_foco(id)
        try:
            if isinstance(base, ArregloVisual):
                animaciones.append(con_arreglo(base, _indices_de_arreglo(base, parte, indices, desde, hasta)))
            elif isinstance(base, CuadriculaVisual):
                if parte is not None and parte.startswith("cabecera"):
                    raise ValueError("las cabeceras no se colorean con este verbo; usa 'resaltar'")
                animaciones.append(con_cuadricula(base, parte))
            else:
                raise ValueError(f"'{id}' no es un arreglo ni una cuadrícula")
        except ValueError as error:
            raise _error("E3", str(error), ctx.ubicacion) from error
    return animaciones


@accion(
    "colorear",
    "Rellena celdas con un color (arreglo: por índices o rango; cuadrícula: una fila, columna, celda o cuadrante).",
    params=[
        Param("objeto", "objeto", requerido=True,
              descripcion="'arr' (todas / según indices), 'arr.celda3', 'cuad.fila:2', 'cuad.cuadrante:sd' o lista."),
        Param("indices", "lista", defecto=None, descripcion="Arreglo: índices de las celdas (p. ej. [0, 2, 5])."),
        Param("desde", "entero", defecto=None, descripcion="Arreglo: primer índice de un rango (inclusive)."),
        Param("hasta", "entero", defecto=None, descripcion="Arreglo: último índice del rango (inclusive)."),
        Param("color", "color", defecto="verde", descripcion="Color del relleno."),
        Param("opacidad", "numero", defecto=0.8, descripcion="Opacidad del relleno (≥ 0.5: el valor pasa a oscuro)."),
    ],
    ejemplo={"en": "inicio", "hacer": "colorear", "objeto": "arr", "indices": [0, 1], "color": "verde"},
    duracion=TIEMPO_ENFASIS,
    ciclo=_ciclo_colorear,
)
def colorear(ctx: ContextoGuion, objeto, indices, desde, hasta, color, opacidad):
    hex_color = ctx.color(color)
    return _aplicar_a_celdas(
        ctx, objeto, indices, desde, hasta,
        lambda arr, idx: arr.colorear(idx, hex_color, float(opacidad)),
        lambda cuad, parte: _pintar_celdas(cuad, parte, hex_color, float(opacidad)),
    )


@accion(
    "restablecer_celdas",
    "Devuelve celdas a su aspecto base (quita colores y atenuados); mismas partes que 'colorear'.",
    params=[
        Param("objeto", "objeto", requerido=True, descripcion="'arr', 'arr.celda3', 'cuad.fila:2' o lista."),
        Param("indices", "lista", defecto=None, descripcion="Arreglo: índices a restablecer (defecto: todas)."),
        Param("desde", "entero", defecto=None, descripcion="Arreglo: primer índice de un rango."),
        Param("hasta", "entero", defecto=None, descripcion="Arreglo: último índice del rango."),
    ],
    ejemplo={"en": "inicio", "hacer": "restablecer_celdas", "objeto": "arr"},
    duracion=0.5,
    ciclo=_ciclo_colorear,
)
def restablecer_celdas(ctx: ContextoGuion, objeto, indices, desde, hasta):
    return _aplicar_a_celdas(
        ctx, objeto, indices, desde, hasta,
        lambda arr, idx: arr.restaurar(idx),
        lambda cuad, parte: _pintar_celdas(cuad, parte, None, 0.0),
    )


def _ciclo_atenuar(params: dict, estado) -> None:
    base = _base(estado, params.get("objeto"), ("arreglo",))
    if base is not None:
        _rango_pedido(estado, params, base[2].get("n"))
    opacidad = params.get("opacidad")
    if isinstance(opacidad, (int, float)) and not 0 <= opacidad <= 1:
        estado.error("E3", "opacidad: entre 0 y 1")


@accion(
    "atenuar_rango",
    "Atenúa las celdas desde..hasta (inclusive) de un arreglo: lo descartado en una búsqueda.",
    params=[
        Param("objeto", "objeto", requerido=True, descripcion="Id del arreglo."),
        Param("desde", "entero", requerido=True, descripcion="Primer índice atenuado. Con calculos: '{traza.0.lo}'."),
        Param("hasta", "entero", requerido=True, descripcion="Último índice atenuado (inclusive). Con calculos: '{traza.0.mid}'."),
        Param("opacidad", "numero", defecto=OPACIDAD_ATENUADO, descripcion="Opacidad que queda (0-1)."),
        Param("color", "color", defecto="rojo", descripcion="Tinte del descarte."),
    ],
    ejemplo={"en": "inicio", "hacer": "atenuar_rango", "objeto": "arr", "desde": 0, "hasta": 3},
    duracion=0.9,
    ciclo=_ciclo_atenuar,
)
def atenuar_rango(ctx: ContextoGuion, objeto, desde, hasta, opacidad, color):
    arreglo = ctx.obtener(objeto)
    ctx.marcar_foco(objeto)
    if not isinstance(arreglo, ArregloVisual) or not 0 <= desde <= hasta < len(arreglo.celdas):
        raise _error("E3", f"rango {desde}..{hasta} inválido para '{objeto}'", ctx.ubicacion)
    return arreglo.atenuar_rango(int(desde), int(hasta), float(opacidad), ctx.color(color))


def _ciclo_dos_celdas(params: dict, estado) -> None:
    base = _base(estado, params.get("objeto"), ("arreglo",))
    if base is None:
        return
    n = base[2].get("n")
    for clave in ("i", "j"):
        _en_rango(estado, params.get(clave), n, clave)


@accion(
    "intercambiar",
    "Intercambia dos celdas de un arreglo por arcos opuestos (ordenamientos).",
    params=[
        Param("objeto", "objeto", requerido=True, descripcion="Id del arreglo."),
        Param("i", "entero", requerido=True, descripcion="Primer índice."),
        Param("j", "entero", requerido=True, descripcion="Segundo índice."),
    ],
    ejemplo={"en": "inicio", "hacer": "intercambiar", "objeto": "arr", "i": 0, "j": 1},
    duracion=0.8,
    ciclo=_ciclo_dos_celdas,
)
def intercambiar(ctx: ContextoGuion, objeto, i, j):
    ctx.marcar_foco(objeto)
    return _arreglo(ctx, objeto, i, j).intercambiar(int(i), int(j))


@accion(
    "comparar",
    "Indica a la vez dos celdas de un arreglo (la pregunta 'a[i] > a[j]').",
    params=[
        Param("objeto", "objeto", requerido=True, descripcion="Id del arreglo."),
        Param("i", "entero", requerido=True, descripcion="Primer índice."),
        Param("j", "entero", requerido=True, descripcion="Segundo índice."),
        Param("color", "color", defecto="amarillo", descripcion="Color del destello."),
    ],
    ejemplo={"en": "inicio", "hacer": "comparar", "objeto": "arr", "i": 0, "j": 1},
    duracion=TIEMPO_ENFASIS,
    ciclo=_ciclo_dos_celdas,
)
def comparar(ctx: ContextoGuion, objeto, i, j, color):
    ctx.marcar_foco(objeto)
    return _arreglo(ctx, objeto, i, j).comparar(int(i), int(j), ctx.color(color))


def _arreglo(ctx: ContextoGuion, ref: str, *indices: int) -> ArregloVisual:
    arreglo = ctx.obtener(ref)
    if not isinstance(arreglo, ArregloVisual):
        raise _error("E3", f"'{ref}' no es un arreglo", ctx.ubicacion)
    for k in indices:
        if not 0 <= k < len(arreglo.celdas):
            raise _error("E3", f"índice {k} fuera del arreglo (0-{len(arreglo.celdas) - 1})", ctx.ubicacion)
    return arreglo


# --- trazas de los motores ---------------------------------------------------------------------------------------


def _ciclo_paso_busqueda(params: dict, estado) -> None:
    base = _base(estado, params.get("objeto"), ("arreglo",))
    n = base[2].get("n") if base else None
    traza = _traza_valida(estado, params.get("traza"), n, ("lo", "hi", "mid"))
    if traza is not None:
        _en_rango(estado, params.get("n"), len(traza), "n")
        for paso in traza:
            for clave in ("lo", "hi", "mid"):
                if isinstance(paso[clave], int) and n is not None and paso[clave] > n:
                    estado.error("E3", f"la traza tiene {clave}={paso[clave]} pero el arreglo solo tiene {n} celdas: "
                                       "¿los valores del cálculo son los del arreglo?")
                    break
    for clave in ("lo", "hi", "mid"):
        if params.get(clave) is not None:
            _base(estado, params[clave], ("puntero",))


@accion(
    "paso_busqueda",
    "Aplica el paso N de la traza de 'busqueda_binaria': mueve los punteros lo/hi/mid, atenúa lo descartado y "
    "resalta la celda del medio. Se declara la traza en calculos: y se pasa como traza: \"{traza}\".",
    params=[
        Param("objeto", "objeto", requerido=True, descripcion="Id del arreglo."),
        Param("traza", "lista", requerido=True, descripcion="Pasos del cálculo: \"{nombre_del_calculo}\"."),
        Param("n", "entero", requerido=True, descripcion="Índice del paso en la traza (0 = primera pregunta)."),
        Param("lo", "objeto", defecto=None, descripcion="Id del puntero 'lo' (opcional)."),
        Param("hi", "objeto", defecto=None, descripcion="Id del puntero 'hi' (opcional)."),
        Param("mid", "objeto", defecto=None, descripcion="Id del puntero 'mid' (opcional)."),
        Param("color_descarte", "color", defecto="rojo", descripcion="Tinte de lo descartado."),
        Param("color_medio", "color", defecto="amarillo", descripcion="Borde de la celda del medio."),
    ],
    ejemplo={"en": "inicio", "hacer": "paso_busqueda", "objeto": "arr",
             "traza": [{"lo": 0, "hi": 7, "mid": 3, "comparacion": "<"}], "n": 0},
    duracion=1.0,
    ciclo=_ciclo_paso_busqueda,
)
def paso_busqueda(ctx: ContextoGuion, objeto, traza, n, lo, hi, mid, color_descarte, color_medio):
    arreglo = _arreglo(ctx, objeto)
    ctx.marcar_foco(objeto)
    paso = traza[int(n)]
    total = len(arreglo.celdas)
    animaciones: list[Animation] = []
    for ref, clave in ((lo, "lo"), (hi, "hi"), (mid, "mid")):
        indice = paso.get(clave)
        if ref is not None and indice is not None and 0 <= indice < total:
            animaciones.append(ctx.obtener(ref).apuntar_a(arreglo.celda(indice)))
    descarte = ctx.color(color_descarte)
    if paso["lo"] > 0:
        animaciones.append(arreglo.atenuar_rango(0, min(paso["lo"], total) - 1, color=descarte))
    if paso["hi"] < total - 1:
        animaciones.append(arreglo.atenuar_rango(max(paso["hi"] + 1, 0), total - 1, color=descarte))
    if paso.get("mid") is not None:
        animaciones.append(arreglo.resaltar_celda(paso["mid"], ctx.color(color_medio)))
    return animaciones


def _ciclo_paso_burbuja(params: dict, estado) -> None:
    base = _base(estado, params.get("objeto"), ("arreglo",))
    n = base[2].get("n") if base else None
    traza = _traza_valida(estado, params.get("traza"), n, ("accion", "i", "j"))
    if traza is None:
        return
    if _en_rango(estado, params.get("n"), len(traza), "n"):
        k = params.get("n")
        if isinstance(k, int):
            for clave in ("i", "j"):
                _en_rango(estado, traza[k][clave], n, f"traza[{k}].{clave}")


@accion(
    "paso_burbuja",
    "Aplica el paso N de la traza de 'burbuja': compara o intercambia las dos celdas que indica. "
    "La traza se declara en calculos: y se pasa como traza: \"{traza}\".",
    params=[
        Param("objeto", "objeto", requerido=True, descripcion="Id del arreglo."),
        Param("traza", "lista", requerido=True, descripcion="Pasos del cálculo: \"{nombre_del_calculo}\"."),
        Param("n", "entero", requerido=True, descripcion="Índice del paso en la traza."),
        Param("color", "color", defecto="amarillo", descripcion="Color de la comparación."),
    ],
    ejemplo={"en": "inicio", "hacer": "paso_burbuja", "objeto": "arr",
             "traza": [{"accion": "comparar", "i": 0, "j": 1}], "n": 0},
    duracion=0.8,
    ciclo=_ciclo_paso_burbuja,
)
def paso_burbuja(ctx: ContextoGuion, objeto, traza, n, color):
    paso = traza[int(n)]
    arreglo = _arreglo(ctx, objeto, paso["i"], paso["j"])
    ctx.marcar_foco(objeto)
    if paso["accion"] == "intercambiar":
        return arreglo.intercambiar(int(paso["i"]), int(paso["j"]))
    return arreglo.comparar(int(paso["i"]), int(paso["j"]), ctx.color(color))


# --- codigo -----------------------------------------------------------------------------------------------------


def _ciclo_codigo(params: dict, estado) -> None:
    lineas = params.get("lineas")
    if not isinstance(lineas, list):
        return
    if not 1 <= len(lineas) <= MAX_LINEAS_CODIGO:
        estado.error("E3", f"lineas: entre 1 y {MAX_LINEAS_CODIGO} líneas (hay {len(lineas)})")
    for k, linea in enumerate(lineas, 1):
        if not isinstance(linea, str):
            estado.error("E3", f"lineas[{k}]: cada línea es un texto")
        elif len(linea) > MAX_LINEA_CODIGO:
            estado.error("E3", f"línea {k} de código mide {len(linea)} caracteres (máx. {MAX_LINEA_CODIGO} para que "
                               f"se lea en un móvil): «{linea}»; pártela o abrevia los nombres")
    if estado.creando:
        _info(estado)[estado.creando] = {"tipo": "codigo", "n": len(lineas)}


@objeto(
    "codigo",
    "Bloque de código con la línea activa marcada por una franja; máx. 24 caracteres por línea. "
    "El verbo 'resaltar_linea' mueve la franja.",
    params=[
        Param("lineas", "lista", requerido=True, descripcion=f"Líneas de código (≤ {MAX_LINEA_CODIGO} caracteres cada una)."),
        Param("lenguaje", "texto", defecto="python", descripcion="Lenguaje para el coloreado de sintaxis."),
        Param("tamano", "numero", defecto=FUENTE_MINIMA, descripcion=f"Tamaño en puntos (mínimo {FUENTE_MINIMA})."),
        _PARAM_ZONA,
        _PARAM_ALINEACION,
    ],
    ejemplo={"en": "inicio", "hacer": "mostrar", "id": "cod", "tipo": "codigo",
             "lineas": ["lo, hi = 0, n - 1", "while lo <= hi:", "  mid = (lo + hi) // 2"]},
    duracion=1.0,
    ciclo=_ciclo_codigo,
)
def crear_codigo(ctx: ContextoGuion, lineas, lenguaje, tamano, zona, alineacion) -> Mobject:
    bloque = CodigoResaltado("\n".join(str(k) for k in lineas), lenguaje=lenguaje, tamano=float(tamano))
    return ctx.colocar(bloque, zona, alineacion)


def _ciclo_resaltar_linea(params: dict, estado) -> None:
    base = _base(estado, params.get("objeto"), ("codigo",))
    if base is not None:
        _en_rango(estado, params.get("linea"), base[2].get("n"), "linea", minimo=1)


@accion(
    "resaltar_linea",
    "Mueve (o hace aparecer) la franja amarilla sobre una línea del bloque de código (1 = primera).",
    params=[
        Param("objeto", "objeto", requerido=True, descripcion="Id del bloque de código."),
        Param("linea", "entero", requerido=True, descripcion="Número de línea, empezando en 1."),
    ],
    ejemplo={"en": "inicio", "hacer": "resaltar_linea", "objeto": "cod", "linea": 2},
    duracion=0.5,
    ciclo=_ciclo_resaltar_linea,
)
def resaltar_linea(ctx: ContextoGuion, objeto, linea):
    bloque = ctx.obtener(objeto)
    ctx.marcar_foco(objeto)
    if not isinstance(bloque, CodigoResaltado):
        raise _error("E3", f"'{objeto}' no es un bloque de código", ctx.ubicacion)
    if not 1 <= linea <= bloque.n_lineas:
        raise _error("E3", f"linea={linea} fuera del código (1-{bloque.n_lineas})", ctx.ubicacion)
    return bloque.resaltar_linea(int(linea))


# --- cuadricula ------------------------------------------------------------------------------------------------


def _ciclo_cuadricula(params: dict, estado) -> None:
    n = params.get("n")
    if isinstance(n, int) and not 2 <= n <= MAX_LADO_CUADRICULA:
        estado.error("E3", f"n: entre 2 y {MAX_LADO_CUADRICULA} (hay {n}); una cuadrícula mayor no se ve en un móvil")
    proporcion = params.get("proporcion")
    if isinstance(proporcion, (int, float)) and not 0 < proporcion <= 1:
        estado.error("E3", "proporcion: entre 0 (exclusivo) y 1 (fracción de la zona)")
    if estado.creando and isinstance(n, int):
        _info(estado)[estado.creando] = {"tipo": "cuadricula", "n": n, "cabeceras": bool(params.get("cabeceras"))}


@objeto(
    "cuadricula",
    "Cuadrícula n×n de celdas direccionables ('cuad.fila:2', 'cuad.cuadrante:sd', 'cuad.celda:r,c') con cabeceras "
    "opcionales. Verbos: colorear, cursor, expandir (n → 2n sin cambiar el contorno).",
    params=[
        Param("n", "entero", requerido=True, descripcion=f"Celdas por lado (2-{MAX_LADO_CUADRICULA})."),
        Param("cabeceras", "booleano", defecto=False, descripcion="Cabeceras verdes arriba y a la izquierda (para los cursores)."),
        Param("color", "color", defecto="gris", descripcion="Color del borde de las celdas."),
        Param("proporcion", "numero", defecto=0.75, descripcion="Tamaño como fracción (0-1] de la zona (cabeceras incluidas)."),
        _PARAM_ZONA,
        _PARAM_ALINEACION,
    ],
    ejemplo={"en": "inicio", "hacer": "mostrar", "id": "cuad", "tipo": "cuadricula", "n": 4, "cabeceras": True},
    duracion=1.0,
    ciclo=_ciclo_cuadricula,
)
def crear_cuadricula(ctx: ContextoGuion, n, cabeceras, color, proporcion, zona, alineacion) -> Mobject:
    referencia = ctx.zona_de_referencia(zona)
    ancho_util = (referencia.ancho - 2 * MARGEN_ZONA) * proporcion
    alto_util = (referencia.alto - 2 * MARGEN_ZONA) * proporcion
    lado_total = n * LADO_CUADRO + (n - 1) * SEPARACION_CUADROS
    if cabeceras:
        lado_total += LADO_CUADRO + SEPARACION_CABECERA
    escala = min(ancho_util, alto_util) / lado_total
    cuad = CuadriculaVisual(
        int(n), bool(cabeceras), ctx.color(color), LADO_CUADRO * escala, SEPARACION_CUADROS * escala,
        SEPARACION_CABECERA * escala,
    )
    return ctx.colocar(cuad, zona, alineacion)


def _ciclo_cursor(params: dict, estado) -> None:
    base = _base(estado, params.get("objeto"), ("cuadricula",))
    fila, columna, quitar = params.get("fila"), params.get("columna"), params.get("quitar")
    if not quitar and fila is None and columna is None:
        estado.error("E3", "cursor necesita 'fila' y/o 'columna' (o quitar: true para retirarlos)")
    if base is not None:
        for nombre, valor in (("fila", fila), ("columna", columna)):
            _en_rango(estado, valor, base[2].get("n"), nombre)


@accion(
    "cursor",
    "Cursor amarillo de una cuadrícula: se crea sobre la cabecera de la fila y/o columna dadas y se desliza a la "
    "siguiente vez (o sobre la celda inicial si no hay cabeceras). quitar: true lo retira.",
    params=[
        Param("objeto", "objeto", requerido=True, descripcion="Id de la cuadrícula."),
        Param("fila", "entero", defecto=None, descripcion="Fila (0-based) a la que se lleva el cursor de fila."),
        Param("columna", "entero", defecto=None, descripcion="Columna (0-based) del cursor de columna."),
        Param("color", "color", defecto="amarillo", descripcion="Color del cursor."),
        Param("quitar", "booleano", defecto=False, descripcion="Retira los cursores visibles."),
    ],
    ejemplo={"en": "inicio", "hacer": "cursor", "objeto": "cuad", "fila": 1, "columna": 2},
    duracion=0.5,
    ciclo=_ciclo_cursor,
)
def cursor(ctx: ContextoGuion, objeto, fila, columna, color, quitar):
    cuad = _cuadricula(ctx, objeto)
    ctx.marcar_foco(objeto)
    if quitar:
        return cuad.quitar_cursores()
    try:
        return cuad.mover_cursor(fila, columna, ctx.color(color))
    except ValueError as error:
        raise _error("E3", str(error), ctx.ubicacion) from error


def _cuadricula(ctx: ContextoGuion, ref: str) -> CuadriculaVisual:
    cuad = ctx.obtener(ref)
    if not isinstance(cuad, CuadriculaVisual):
        raise _error("E3", f"'{ref}' no es una cuadrícula", ctx.ubicacion)
    return cuad


def _ciclo_expandir(params: dict, estado) -> None:
    base = _base(estado, params.get("objeto"), ("cuadricula",))
    if base is None:
        return
    id, _, info = base
    n = info.get("n")
    if isinstance(n, int):
        if n * 2 > MAX_LADO_CUADRICULA:
            estado.error("E3", f"expandir: {n}×{n} pasaría a {2 * n}×{2 * n} (máx. {MAX_LADO_CUADRICULA}×{MAX_LADO_CUADRICULA})")
        else:
            info["n"] = 2 * n


@accion(
    "expandir",
    "Duplica el lado de una cuadrícula (8×8 → 16×16) sin cambiar su contorno: las celdas actuales se reducen a la "
    "esquina superior izquierda (conservan su color) y aparecen las nuevas. Los cuadrantes pasan a ser mitades.",
    params=[Param("objeto", "objeto", requerido=True, descripcion="Id de la cuadrícula.")],
    ejemplo={"en": "inicio", "hacer": "expandir", "objeto": "cuad"},
    duracion=1.2,
    ciclo=_ciclo_expandir,
)
def expandir(ctx: ContextoGuion, objeto):
    cuad = _cuadricula(ctx, objeto)
    ctx.marcar_foco(objeto)
    if cuad.n * 2 > MAX_LADO_CUADRICULA:
        raise _error("E3", f"la cuadrícula de {cuad.n}×{cuad.n} no se puede expandir más", ctx.ubicacion)
    animacion, consolidar = cuad.expandir()

    def cerrar() -> None:
        consolidar()
        ctx.consolidar(cuad)

    ctx.despues(cerrar)
    return animacion


# --- pila ------------------------------------------------------------------------------------------------------


def _ciclo_pila(params: dict, estado) -> None:
    elementos = params.get("elementos")
    if isinstance(elementos, list) and len(elementos) > MAX_MARCOS_PILA:
        estado.error("E3", f"elementos: máx. {MAX_MARCOS_PILA} marcos apilados (hay {len(elementos)})")
    if estado.creando:
        _info(estado)[estado.creando] = {"tipo": "pila", "n": len(elementos or [])}


@objeto(
    "pila",
    "Pila vertical de marcos (recursión, llamadas): crece hacia arriba; 'apilar' y 'desapilar' la mueven.",
    params=[
        Param("elementos", "lista", defecto=[], descripcion="Etiquetas iniciales, de abajo hacia arriba."),
        Param("color", "color", defecto="morado", descripcion="Color de los marcos."),
        _PARAM_ZONA,
        Param("alineacion", "texto", defecto="abajo", opciones=tuple(ALINEACIONES),
              descripcion="Borde de la zona al que se pega (abajo deja crecer la pila hacia arriba)."),
    ],
    ejemplo={"en": "inicio", "hacer": "mostrar", "id": "pila", "tipo": "pila", "elementos": ["f(3)", "f(2)"]},
    duracion=1.0,
    ciclo=_ciclo_pila,
)
def crear_pila(ctx: ContextoGuion, elementos, color, zona, alineacion) -> Mobject:
    pila = PilaVisual([str(e) for e in elementos], color=ctx.color(color))
    # Sin escalar: los marcos que se apilen después usan las medidas originales.
    referencia = ctx.zona_de_referencia(zona)
    if isinstance(zona, str):
        pila.move_to(referencia.centro)
        if alineacion == "abajo":
            pila.align_to([0, referencia.y_min + MARGEN_ZONA, 0], DOWN)
    else:
        ctx.colocar(pila, zona, alineacion)
    return pila


def _ciclo_apilar(params: dict, estado) -> None:
    base = _base(estado, params.get("objeto"), ("pila",))
    if base is None:
        return
    info = base[2]
    if info.get("n", 0) >= MAX_MARCOS_PILA:
        estado.error("E3", f"apilar: la pila ya tiene {MAX_MARCOS_PILA} marcos (máx.); desapila antes")
    else:
        info["n"] = info.get("n", 0) + 1


@accion(
    "apilar",
    "Apila un marco nuevo (cae desde arriba) en una pila.",
    params=[
        Param("objeto", "objeto", requerido=True, descripcion="Id de la pila."),
        Param("elemento", "texto", requerido=True, descripcion="Etiqueta del marco (p. ej. 'f(1)')."),
    ],
    ejemplo={"en": "inicio", "hacer": "apilar", "objeto": "pila", "elemento": "f(1)"},
    duracion=0.6,
    ciclo=_ciclo_apilar,
)
def apilar(ctx: ContextoGuion, objeto, elemento):
    pila = ctx.obtener(objeto)
    ctx.marcar_foco(objeto)
    if not isinstance(pila, PilaVisual):
        raise _error("E3", f"'{objeto}' no es una pila", ctx.ubicacion)
    return pila.push(str(elemento))


def _ciclo_desapilar(params: dict, estado) -> None:
    base = _base(estado, params.get("objeto"), ("pila",))
    if base is None:
        return
    info = base[2]
    if info.get("n", 0) <= 0:
        estado.error("E3", "desapilar: la pila está vacía en este punto del guion")
    else:
        info["n"] -= 1


@accion(
    "desapilar",
    "Quita el marco superior de una pila (sale hacia arriba).",
    params=[Param("objeto", "objeto", requerido=True, descripcion="Id de la pila.")],
    ejemplo={"en": "inicio", "hacer": "desapilar", "objeto": "pila"},
    duracion=0.6,
    ciclo=_ciclo_desapilar,
)
def desapilar(ctx: ContextoGuion, objeto):
    pila = ctx.obtener(objeto)
    ctx.marcar_foco(objeto)
    if not isinstance(pila, PilaVisual) or not pila.elementos:
        raise _error("E3", f"'{objeto}' no es una pila con elementos", ctx.ubicacion)
    marco = pila.marcos[-1]
    animacion = pila.pop()
    if ctx.escena is not None:
        ctx.escena.add(marco)  # pop lo saca del grupo: se anima suelto hasta que termine su salida
    return animacion


# --- Objetos previos que necesita el ejemplo de cada verbo (los usa guion_de_ejemplo en los tests) --------------

_EJ_ARREGLO = {"en": "inicio", "hacer": "mostrar", "id": "arr", "tipo": "arreglo",
               "valores": [3, 8, 12, 17, 21, 25, 30, 34], "columnas_max": 4}
_EJ_PUNTERO = {"en": "inicio", "hacer": "mostrar", "id": "p_lo", "tipo": "puntero", "nombre": "lo", "arreglo": "arr",
               "en_celda": 0, "direccion": "abajo"}
_EJ_CODIGO = {"en": "inicio", "hacer": "mostrar", "id": "cod", "tipo": "codigo",
              "lineas": ["lo, hi = 0, n - 1", "while lo <= hi:", "  mid = (lo + hi) // 2"]}
_EJ_CUADRICULA = {"en": "inicio", "hacer": "mostrar", "id": "cuad", "tipo": "cuadricula", "n": 4, "cabeceras": True}
_EJ_PILA = {"en": "inicio", "hacer": "mostrar", "id": "pila", "tipo": "pila", "elementos": ["f(3)", "f(2)"]}

for _fn, _previos in (
    (crear_puntero, [_EJ_ARREGLO]),
    (apuntar, [_EJ_ARREGLO, _EJ_PUNTERO]),
    (colorear, [_EJ_ARREGLO]),
    (restablecer_celdas, [_EJ_ARREGLO]),
    (atenuar_rango, [_EJ_ARREGLO]),
    (intercambiar, [_EJ_ARREGLO]),
    (comparar, [_EJ_ARREGLO]),
    (paso_busqueda, [_EJ_ARREGLO]),
    (paso_burbuja, [_EJ_ARREGLO]),
    (resaltar_linea, [_EJ_CODIGO]),
    (cursor, [_EJ_CUADRICULA]),
    (expandir, [_EJ_CUADRICULA]),
    (apilar, [_EJ_PILA]),
    (desapilar, [_EJ_PILA]),
):
    _fn.previos_ejemplo = _previos
