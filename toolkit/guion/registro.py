"""Registro del catálogo de piezas del guion técnico (objetos y acciones) y su manifiesto.

Cada pieza se registra con un decorador al importar ``toolkit.guion.catalogo``::

    @objeto("texto", "Texto legible encajado en una zona.", params=[...], ejemplo={...})
    def crear_texto(ctx, texto, zona, tamano, color, alineacion): ...      # -> Mobject

    @accion("resaltar", "Énfasis sobre un objeto.", params=[...], ejemplo={...}, duracion=0.8,
            modificadores=("escala",))
    def resaltar(ctx, objeto, parte, modo, color, escala): ...              # -> Animation | [Animation] | None

Extensiones sobre el contrato §2 del plan (todas opcionales, con defecto neutro):

- ``modificadores``: nombres de :data:`MODIFICADORES` (parámetros comunes como ``entrada``, ``escalonado``,
  ``rate``...) que la pieza acepta; se agregan a sus ``params``. ``rate`` y la clave de paso ``retraso`` los
  aplica el runtime; el resto los interpreta la función de la pieza.
- ``ciclo``: gancho de validación del ciclo de vida de ids (``ciclo(params, estado)``, ver
  ``toolkit.guion.validar.EstadoValidacion``). Sin gancho, cada parámetro de tipo ``objeto`` debe referirse
  a un objeto visible.
- ``admite_extras``: la acción acepta claves que no están en ``params`` (``mostrar`` recibe los parámetros
  del tipo); su ``ciclo`` debe validarlas.

Este módulo no importa manim: el manifiesto y la validación estática lo usan sin escena.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

TIPOS_PARAM = ("texto", "numero", "entero", "booleano", "color", "lista", "mapa", "objeto", "zona", "cualquiera")
CLASES = ("objeto", "accion")
VERSION_MANIFIESTO = 1
_IDENTIFICADOR = re.compile(r"^[a-z][a-z0-9_]*$")


class ErrorRegistro(ValueError):
    """Definición de pieza mal formada (error del programador del catálogo, no del guion)."""


@dataclass(frozen=True)
class Param:
    nombre: str
    tipo: str  # uno de TIPOS_PARAM
    requerido: bool = False
    defecto: Any = None
    descripcion: str = ""
    opciones: tuple[str, ...] = ()  # valores permitidos (enum), si aplica


@dataclass(frozen=True)
class Definicion:
    nombre: str
    clase: str  # "objeto" | "accion"
    descripcion: str
    params: tuple[Param, ...]
    ejemplo: dict  # un paso YAML válido
    funcion: Callable
    duracion: float = 1.0  # dur por defecto
    modificadores: tuple[str, ...] = ()
    ciclo: Callable | None = field(default=None, compare=False)
    admite_extras: bool = False

    def param(self, nombre: str) -> Param | None:
        for p in self.params:
            if p.nombre == nombre:
                return p
        return None

    @property
    def nombres_params(self) -> list[str]:
        return [p.nombre for p in self.params]


CATALOGO: dict[str, Definicion] = {}

# --- Modificadores comunes (cada definición elige cuáles acepta) ------------------------------

ENTRADAS = (
    "auto",
    "desvanecer",
    "escribir",
    "crear",
    "crecer",
    "crecer_izq",
    "desde_arriba",
    "desde_abajo",
    "desde_izquierda",
    "desde_derecha",
)
SALIDAS = ("desvanecer", "arriba", "abajo", "izquierda", "derecha", "encoger")
RATES = ("smooth", "linear", "rush_from", "rush_into", "there_and_back")

MODIFICADORES: dict[str, Param] = {
    "entrada": Param("entrada", "texto", defecto="auto", opciones=ENTRADAS,
                     descripcion="Cómo entra el objeto ('auto' elige según el tipo: texto se escribe, figuras se dibujan)."),
    "salida": Param("salida", "texto", defecto="desvanecer", opciones=SALIDAS,
                    descripcion="Cómo sale el objeto (fundido, hacia un lado o encogiéndose)."),
    "escalonado": Param("escalonado", "numero", defecto=0.0,
                        descripcion="Desfase entre miembros/objetos (lag_ratio 0-1; 0 = a la vez, 0.1-0.3 típico)."),
    "escala": Param("escala", "numero", defecto=None,
                    descripcion="Factor de escala del énfasis (defecto: el del verbo)."),
    "rate": Param("rate", "texto", defecto=None, opciones=RATES,
                  descripcion="Curva de tiempo de la animación (la aplica el runtime; defecto: la del verbo)."),
    "caja": Param("caja", "booleano", defecto=False,
                  descripcion="Deja una caja de resultado alrededor del objeto (pieza que lo implemente)."),
    "tachar": Param("tachar", "booleano", defecto=False,
                    descripcion="Tacha el objeto con una línea (pieza que lo implemente)."),
}

# Claves de paso universales (no son parámetros de ninguna pieza). Documentadas en el manifiesto.
CLAVES_PASO = {
    "en": "Ancla: inicio | fin | \"palabra\" | [\"palabra\", n] | {ancla: \"palabra\", ocurrencia: n, mas: 0.4}.",
    "hacer": "Verbo del catálogo (acciones).",
    "dur": "Segundos | resto (hasta la última palabra) | {hasta: <ancla>}. Defecto: el de la pieza.",
    "retraso": "Segundos desde el inicio del grupo hasta que arranca este paso (defecto 0).",
}


def _validar_definicion(
    nombre: str,
    clase: str,
    params: Iterable[Param],
    ejemplo: dict,
    duracion: float,
    modificadores: Iterable[str],
) -> tuple[tuple[Param, ...], tuple[str, ...]]:
    if not isinstance(nombre, str) or not _IDENTIFICADOR.match(nombre):
        raise ErrorRegistro(f"nombre {nombre!r}: debe ser un identificador en minúsculas (a-z, 0-9, _)")
    if nombre in CATALOGO:
        raise ErrorRegistro(
            f"{nombre!r} ya está registrado como {CATALOGO[nombre].clase}; los nombres de objetos y acciones no se repiten"
        )
    if clase not in CLASES:
        raise ErrorRegistro(f"clase {clase!r} desconocida (usa {CLASES})")
    if duracion < 0:
        raise ErrorRegistro(f"{nombre}: duracion negativa")
    lista = list(params)
    modificadores = tuple(modificadores)
    for mod in modificadores:
        if mod not in MODIFICADORES:
            raise ErrorRegistro(f"{nombre}: modificador {mod!r} desconocido (disponibles: {sorted(MODIFICADORES)})")
        lista.append(MODIFICADORES[mod])
    vistos: set[str] = set()
    for p in lista:
        if not isinstance(p, Param):
            raise ErrorRegistro(f"{nombre}: cada parámetro debe ser un Param, no {type(p).__name__}")
        if p.tipo not in TIPOS_PARAM:
            raise ErrorRegistro(f"{nombre}.{p.nombre}: tipo de parámetro {p.tipo!r} desconocido (usa {TIPOS_PARAM})")
        if p.nombre in vistos:
            raise ErrorRegistro(f"{nombre}: parámetro {p.nombre!r} repetido")
        if p.nombre in CLAVES_PASO:
            raise ErrorRegistro(f"{nombre}: {p.nombre!r} es una clave de paso reservada")
        vistos.add(p.nombre)
        if p.opciones and p.defecto is not None and p.defecto not in p.opciones:
            raise ErrorRegistro(f"{nombre}.{p.nombre}: el defecto {p.defecto!r} no está en sus opciones {p.opciones}")
    if not isinstance(ejemplo, dict) or "en" not in ejemplo or "hacer" not in ejemplo:
        raise ErrorRegistro(f"{nombre}: el ejemplo debe ser un paso (dict con 'en' y 'hacer')")
    if clase == "accion" and ejemplo["hacer"] != nombre:
        raise ErrorRegistro(f"{nombre}: el ejemplo de una acción debe usar hacer: {nombre}")
    if clase == "objeto" and (ejemplo["hacer"] != "mostrar" or ejemplo.get("tipo") != nombre):
        raise ErrorRegistro(f"{nombre}: el ejemplo de un objeto debe ser hacer: mostrar, tipo: {nombre}")
    return tuple(lista), modificadores


def _registrar(
    clase: str,
    nombre: str,
    descripcion: str,
    params: Iterable[Param],
    ejemplo: dict,
    duracion: float,
    modificadores: Iterable[str],
    ciclo: Callable | None,
    admite_extras: bool,
) -> Callable[[Callable], Callable]:
    params_finales, mods = _validar_definicion(nombre, clase, params, ejemplo, duracion, modificadores)

    def decorar(funcion: Callable) -> Callable:
        CATALOGO[nombre] = Definicion(
            nombre=nombre,
            clase=clase,
            descripcion=descripcion,
            params=params_finales,
            ejemplo=copy.deepcopy(ejemplo),
            funcion=funcion,
            duracion=float(duracion),
            modificadores=mods,
            ciclo=ciclo,
            admite_extras=admite_extras,
        )
        return funcion

    return decorar


def objeto(
    nombre: str,
    descripcion: str,
    params: Iterable[Param],
    ejemplo: dict,
    duracion: float = 1.0,
    *,
    modificadores: Iterable[str] = (),
    ciclo: Callable | None = None,
) -> Callable[[Callable], Callable]:
    """Decorador de un tipo de objeto: ``fn(ctx, **params) -> Mobject`` (``duracion`` = dur de su entrada)."""
    return _registrar("objeto", nombre, descripcion, params, ejemplo, duracion, modificadores, ciclo, False)


def accion(
    nombre: str,
    descripcion: str,
    params: Iterable[Param],
    ejemplo: dict,
    duracion: float = 1.0,
    *,
    modificadores: Iterable[str] = (),
    ciclo: Callable | None = None,
    admite_extras: bool = False,
) -> Callable[[Callable], Callable]:
    """Decorador de un verbo: ``fn(ctx, **params) -> Animation | Sequence[Animation] | None``."""
    return _registrar("accion", nombre, descripcion, params, ejemplo, duracion, modificadores, ciclo, admite_extras)


# --- Consulta ------------------------------------------------------------------------------------


def obtener(nombre: str, clase: str | None = None) -> Definicion | None:
    """La definición ``nombre`` (de la ``clase`` pedida, si se indica) o ``None``."""
    definicion = CATALOGO.get(nombre)
    if definicion is None or (clase is not None and definicion.clase != clase):
        return None
    return definicion


def nombres(clase: str) -> list[str]:
    """Nombres registrados de ``clase`` ("objeto" | "accion"), en orden alfabético."""
    return sorted(n for n, d in CATALOGO.items() if d.clase == clase)


def resolver_params(definicion: Definicion, datos: dict) -> dict:
    """``datos`` + los defectos de los parámetros ausentes (copias: nunca comparte listas/dicts).

    Los parámetros de tipo ``texto`` que llegan como número (``parte: 16`` en YAML) se convierten a texto.
    """
    resultado = dict(datos)
    for p in definicion.params:
        if p.nombre not in resultado or resultado[p.nombre] is None:
            resultado[p.nombre] = copy.deepcopy(p.defecto)
        valor = resultado[p.nombre]
        if p.tipo == "texto" and isinstance(valor, (int, float)) and not isinstance(valor, bool):
            resultado[p.nombre] = str(valor)
    return resultado


# --- Manifiesto ----------------------------------------------------------------------------------


def _json_seguro(valor: Any) -> Any:
    if isinstance(valor, dict):
        return {str(k): _json_seguro(v) for k, v in valor.items()}
    if isinstance(valor, (list, tuple, set, frozenset)):
        return [_json_seguro(v) for v in valor]
    if valor is None or isinstance(valor, (bool, int, float, str)):
        return valor
    return str(valor)


def _param_a_dict(p: Param) -> dict:
    return {
        "nombre": p.nombre,
        "tipo": p.tipo,
        "requerido": p.requerido,
        "defecto": _json_seguro(p.defecto),
        "descripcion": p.descripcion,
        "opciones": list(p.opciones),
    }


def _definicion_a_dict(d: Definicion) -> dict:
    return {
        "descripcion": d.descripcion,
        "duracion": d.duracion,
        "params": [_param_a_dict(p) for p in d.params],
        "modificadores": list(d.modificadores),
        "admite_extras": d.admite_extras,
        "ejemplo": _json_seguro(d.ejemplo),
    }


def manifiesto() -> dict:
    """Descripción JSON-serializable del catálogo: objetos, acciones, modificadores y claves de paso."""
    return {
        "version": VERSION_MANIFIESTO,
        "objetos": {n: _definicion_a_dict(CATALOGO[n]) for n in nombres("objeto")},
        "acciones": {n: _definicion_a_dict(CATALOGO[n]) for n in nombres("accion")},
        "modificadores": {n: _param_a_dict(p) for n, p in MODIFICADORES.items()},
        "claves_paso": dict(CLAVES_PASO),
    }
