"""``ContextoGuion``: lo que reciben las piezas del catálogo al ejecutarse (escena, objetos vivos, zonas, colores).

Las piezas nunca manejan coordenadas: piden ``ctx.zona(nombre)`` / ``ctx.colocar(mob, zona)`` y ``ctx.color(nombre)``.
El ciclo de vida de los ids (registrar, obtener "id" o "id.parte", quitar, reservar/revelar del escenario) y los
efectos persistentes (``iniciar_efecto`` / ``detener_efecto``) viven aquí, no en el runtime, para que el catálogo
pueda crecer sin tocarlo.
"""

from __future__ import annotations

import importlib.util
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from manim import DOWN, LEFT, ORIGIN, RIGHT, UP, Mobject, VGroup

from toolkit.estilos import (
    AMARILLO,
    AZUL,
    BLANCO,
    GRIS,
    GRIS_OSCURO,
    MORADO,
    NARANJA,
    ROJO,
    TURQUESA,
    VERDE,
)
from toolkit.guion import registro
from toolkit.guion.esquema import NOMBRES_ZONAS_BASE, DefZona, ErrorGuion, Hallazgo, sugerencia
from toolkit.layout import (
    MARGEN_ENTRE_BLOQUES,
    ZONA_PRINCIPAL,
    ZONA_SEGURA,
    ZONA_SUBTITULOS,
    ZONA_TITULO,
    Zona,
    dividir_horizontal,
    dividir_vertical,
    encajar,
)

logger = logging.getLogger(__name__)

COLORES: dict[str, str] = {
    "azul": AZUL,
    "amarillo": AMARILLO,
    "verde": VERDE,
    "rojo": ROJO,
    "naranja": NARANJA,
    "morado": MORADO,
    "turquesa": TURQUESA,
    "gris": GRIS,
    "gris_oscuro": GRIS_OSCURO,
    "blanco": BLANCO,
}
ZONAS_BASE: dict[str, Zona] = {
    "titulo": ZONA_TITULO,
    "principal": ZONA_PRINCIPAL,
    "subtitulos": ZONA_SUBTITULOS,
    "segura": ZONA_SEGURA,
}
assert set(ZONAS_BASE) == set(NOMBRES_ZONAS_BASE)
# Donde puede quedar contenido colocado junto a otro objeto: la zona segura sin la franja de subtítulos.
ZONA_CONTENIDO = Zona("contenido", ZONA_SEGURA.x_min, ZONA_SEGURA.x_max, ZONA_PRINCIPAL.y_min, ZONA_SEGURA.y_max)
LADOS: dict[str, Any] = {"abajo": DOWN, "arriba": UP, "izq": LEFT, "der": RIGHT}
ALINEACIONES: dict[str, Any] = {"centro": ORIGIN, "arriba": UP, "abajo": DOWN, "izquierda": LEFT, "derecha": RIGHT}
MARGEN_ZONA = 0.15
ATRIBUTO_PARTES = "partes_guion"  # dict nombre -> Mobject que una pieza expone como "id.nombre"
ATRIBUTO_MIEMBROS = "miembros_guion"  # ids registrados que forman un grupo


def _error(codigo: str, mensaje: str, ubicacion: str = "") -> ErrorGuion:
    return ErrorGuion([Hallazgo(codigo, mensaje, ubicacion)])


def separar_ref(ref: str) -> tuple[str, str | None]:
    """``"eq0.16"`` -> ``("eq0", "16")``; ``"eq0"`` -> ``("eq0", None)`` (los ids no llevan puntos)."""
    ref = str(ref)
    if "." in ref:
        base, parte = ref.split(".", 1)
        return base, parte
    return ref, None


def derivar_zona(padre: Zona, d: DefZona) -> Zona:
    """La franja/columna ``d.indice`` de ``padre`` según ``d`` (``dividir_vertical``/``dividir_horizontal``)."""
    if d.filas is not None:
        partes = dividir_vertical(padre, d.filas)
    else:
        partes = dividir_horizontal(padre, d.columnas or [1], espacio=d.espacio)
    z = partes[d.indice]
    return Zona(d.nombre, z.x_min, z.x_max, z.y_min, z.y_max)


def error_zona_padre(d: DefZona, zonas: dict[str, Zona]) -> Hallazgo:
    return Hallazgo(
        "E5",
        f"la zona '{d.nombre}' se deriva de '{d.de}', que no existe (declárala antes).{sugerencia(d.de, zonas)} "
        f"Zonas: {', '.join(zonas)}",
        f"zonas.{d.nombre}",
        d.linea,
    )


def construir_zonas(definiciones: dict[str, DefZona]) -> dict[str, Zona]:
    """Zonas base + derivadas (en orden de declaración; ``de`` puede ser una base o una derivada previa).

    ``ErrorGuion`` (E5) si ``de`` no existe.
    """
    zonas = dict(ZONAS_BASE)
    for nombre, d in definiciones.items():
        padre = zonas.get(d.de)
        if padre is None:
            raise ErrorGuion([error_zona_padre(d, zonas)])
        zonas[nombre] = derivar_zona(padre, d)
    return zonas


def _ajustar_dentro(mob: Mobject, zona: Zona, margen: float = MARGEN_ZONA) -> None:
    """Escala hacia abajo si no cabe y desplaza ``mob`` lo mínimo para que quede dentro de ``zona``."""
    ancho, alto = zona.ancho - 2 * margen, zona.alto - 2 * margen
    if mob.width > ancho or mob.height > alto:
        mob.scale(min(ancho / mob.width, alto / mob.height))
    dx = max(0.0, zona.x_min + margen - mob.get_left()[0]) - max(0.0, mob.get_right()[0] - (zona.x_max - margen))
    dy = max(0.0, zona.y_min + margen - mob.get_bottom()[1]) - max(0.0, mob.get_top()[1] - (zona.y_max - margen))
    mob.shift(RIGHT * dx + UP * dy)


@dataclass
class Efecto:
    """Comportamiento persistente con id (cámara, variable...) que dura hasta ``hacer: detener``."""

    id: str
    tipo: str
    detener: Callable[["ContextoGuion"], Any]
    datos: dict = field(default_factory=dict)


class ContextoGuion:
    """Estado de ejecución de un guion dentro de una escena (una instancia por render)."""

    def __init__(self, escena: Any, guion: Any = None, zonas: dict[str, Zona] | None = None) -> None:
        self.escena = escena
        self.guion = guion
        self.objetos: dict[str, Mobject] = {}
        self.control = None  # ControlNarracion del segmento en curso
        self.estado: dict[str, Any] = {}  # estado compartido libre (p. ej. para ``personalizado``)
        self.efectos: dict[str, Efecto] = {}
        self.reservados: set[str] = set()  # ids construidos por el escenario y aún no mostrados
        self.calculos: dict[str, Any] = {}
        self.paso = None  # Paso en ejecución (para mensajes)
        self._focos: list[str] = []
        self._pendientes: list[Callable[[], None]] = []
        self._modulos: dict[Path, Any] = {}
        if zonas is None:
            zonas = construir_zonas(guion.zonas if guion is not None else {})
        self.zonas = zonas

    # --- ubicación para mensajes ---------------------------------------------------------------

    @property
    def ubicacion(self) -> str:
        return getattr(self.paso, "ubicacion", "") or ""

    @property
    def dir_base(self) -> Path:
        return self.guion.dir_base if self.guion is not None else Path.cwd()

    # --- objetos ---------------------------------------------------------------------------------

    def registrar(self, id: str, mob: Mobject, oculto: bool = False) -> None:
        """Da de alta ``id`` (``oculto``: reservado por el escenario, aún no visible)."""
        if id in self.objetos:
            raise _error("E4", f"el id '{id}' ya existe; usa otro id o quítalo antes", self.ubicacion)
        self.objetos[id] = mob
        if oculto:
            self.reservados.add(id)
        else:
            self.reservados.discard(id)

    def existe(self, id: str) -> bool:
        return id in self.objetos

    def oculto(self, id: str) -> bool:
        return id in self.reservados

    def revelar(self, id: str) -> None:
        self.reservados.discard(id)

    def obtener(self, ref: str) -> Mobject:
        """Mobject de ``"id"`` o de ``"id.parte"``; ``ErrorGuion`` (E4) con el id más parecido si no existe."""
        id, parte = separar_ref(ref)
        if id not in self.objetos:
            raise _error(
                "E4",
                f"el objeto '{id}' no existe (no se creó o ya se quitó).{sugerencia(id, self.objetos)} "
                f"Objetos vivos: {', '.join(self.objetos) or '(ninguno)'}",
                self.ubicacion,
            )
        return self.parte(self.objetos[id], parte)

    def obtener_varios(self, refs: str | list[str]) -> list[Mobject]:
        """``obtener`` de una referencia o de una lista de referencias."""
        if isinstance(refs, (list, tuple)):
            return [self.obtener(r) for r in refs]
        return [self.obtener(refs)]

    def parte(self, mob: Mobject, parte: str | int | None) -> Mobject:
        """Sub-elemento: ``partes_guion[parte]``, ``mob.parte(token)`` (Ecuacion), ``mob.celda(i)`` o ``mob[i]``."""
        if parte is None or parte == "":
            return mob
        parte = str(parte)
        partes = getattr(mob, ATRIBUTO_PARTES, None)
        if isinstance(partes, dict) and parte in partes:
            return partes[parte]
        if isinstance(partes, dict) and "." in parte:
            base, resto = parte.split(".", 1)
            if base in partes:
                return self.parte(partes[base], resto)
        metodo = getattr(mob, "parte", None)
        if callable(metodo):
            try:
                return metodo(parte)
            except (KeyError, ValueError, IndexError):
                pass
        celda = getattr(mob, "celda", None)
        if callable(celda) and parte.isdigit():
            try:
                return celda(int(parte))
            except (KeyError, IndexError, ValueError):
                pass
        if parte.isdigit() and int(parte) < len(mob.submobjects):
            return mob.submobjects[int(parte)]
        disponibles = list(partes) if isinstance(partes, dict) else []
        raise _error(
            "E4",
            f"el objeto no tiene la parte '{parte}'.{sugerencia(parte, disponibles)} "
            f"Partes: {', '.join(disponibles) or f'índices 0-{len(mob.submobjects) - 1}'}",
            self.ubicacion,
        )

    def olvidar(self, id: str) -> Mobject | None:
        """Da de baja ``id`` (y a sus miembros si es un grupo; lo saca de los grupos que lo contengan) sin
        tocar la escena. Devuelve su Mobject."""
        mob = self.objetos.pop(id, None)
        self.reservados.discard(id)
        if mob is None:
            return None
        for miembro in list(getattr(mob, ATRIBUTO_MIEMBROS, []) or []):
            self.objetos.pop(miembro, None)
            self.reservados.discard(miembro)
        for otro in self.objetos.values():
            miembros = getattr(otro, ATRIBUTO_MIEMBROS, None)
            if miembros and id in miembros:
                miembros.remove(id)
                partes = getattr(otro, ATRIBUTO_PARTES, {}) or {}
                partes.pop(id, None)
                if mob in otro.submobjects:
                    otro.remove(mob)
        return mob

    def retirar(self, mob: Mobject | None) -> None:
        """Saca de la escena ``mob`` y toda su familia (las animaciones dejan partes sueltas o restauradas)."""
        if mob is not None and self.escena is not None:
            self.escena.remove(*mob.get_family())

    def quitar(self, id: str) -> None:
        """Olvida ``id`` y saca de la escena toda su familia.

        Llamarlo DESPUÉS de la animación de salida (``ctx.despues(lambda: ctx.quitar(id))``). Si ``id`` es un
        grupo, también olvida a sus miembros; si es miembro de un grupo, sale del grupo.
        """
        self.retirar(self.olvidar(id))

    def consolidar(self, mob: Mobject, conservar_orden: bool = False) -> None:
        """Deja ``mob`` como una sola entrada de la escena: quita las entradas sueltas que solo contienen partes
        suyas (miembros añadidos por separado, grupos temporales de una entrada parcial) y añade ``mob``.

        Con ``conservar_orden`` no añade ``mob`` si no quedan piezas sueltas suyas (no lo "resucita") y lo coloca
        donde estaba la primera pieza suelta en lugar de al final (encima de todo).
        """
        if self.escena is None:
            return
        familia = set(mob.get_family())
        entradas = self.escena.mobjects
        sueltas = [
            m for m in entradas
            if m is not mob and all(f in familia or f is m for f in m.get_family()) and len(m.get_family()) > 0
            and any(f in familia for f in m.get_family())
        ]
        if conservar_orden and not sueltas:
            return
        indice = min((entradas.index(m) for m in sueltas), default=len(entradas))
        if sueltas:
            self.escena.remove(*sueltas)
        if mob not in self.escena.mobjects:
            if conservar_orden:
                self.escena.mobjects.insert(min(indice, len(self.escena.mobjects)), mob)
            else:
                self.escena.add(mob)

    def reensamblar(self) -> None:
        """Devuelve a la escena, enteros, los objetos registrados que un ``play`` dejó desarmados.

        Causa: cuando una animación de un grupo tiene como objetivo una PARTE de un objeto (el relleno de una
        barra, el número de un odómetro), manim la añade a la escena y ``restructure_mobjects`` reemplaza al padre
        en ``escena.mobjects`` por sus hijos sueltos, con la parte movida al final (se pinta encima de sus
        hermanas). El padre conserva sus ``submobjects``: basta volver a ponerlo como una sola entrada, en el
        puesto que ocupaba la primera pieza suelta (así se respeta el orden de pintado original).

        Solo actúa sobre objetos raíz (no contenidos en otro objeto registrado) visibles y de los que queda alguna
        pieza suelta en la escena; los quitados o aún reservados por el escenario no se tocan.
        """
        if self.escena is None:
            return
        registrados = [m for i, m in self.objetos.items() if i not in self.reservados]
        contenidos = {id(f) for m in self.objetos.values() for f in m.get_family() if f is not m}
        for raiz in registrados:
            if id(raiz) in contenidos:
                continue
            self.consolidar(raiz, conservar_orden=True)

    def en_escena(self, mob: Mobject) -> bool:
        return self.escena is not None and mob in self.escena.get_mobject_family_members()

    # --- foco (para el relleno ambiental) ----------------------------------------------------------

    def marcar_foco(self, id: str) -> None:
        if id in self._focos:
            self._focos.remove(id)
        self._focos.append(id)

    def foco(self) -> Mobject | None:
        """El último objeto en foco que sigue vivo, visible y en escena (o ``None``)."""
        for id in reversed(self._focos):
            mob = self.objetos.get(id)
            if mob is not None and id not in self.reservados and self.en_escena(mob):
                return mob
        return None

    # --- zonas, colocación y colores -----------------------------------------------------------------

    def zona(self, nombre: str) -> Zona:
        if nombre not in self.zonas:
            raise _error("E5", f"la zona '{nombre}' no existe.{sugerencia(nombre, self.zonas)} "
                               f"Zonas: {', '.join(self.zonas)}", self.ubicacion)
        return self.zonas[nombre]

    def colocar(self, mob: Mobject, zona: str | dict = "principal", alineacion: str = "centro",
                margen: float = MARGEN_ZONA) -> Mobject:
        """Encaja ``mob`` en la zona ``zona`` (nombre) o lo pone junto a otro objeto (``{de, lado, espacio}``).

        Junto a otro objeto nunca se sale de la zona segura (ni invade los subtítulos): se desplaza/escala lo mínimo.
        """
        if isinstance(zona, dict):
            ref = self.obtener(zona["de"])
            lado = LADOS[zona.get("lado", "abajo")]
            mob.next_to(ref, lado, buff=float(zona.get("espacio", MARGEN_ENTRE_BLOQUES)))
            _ajustar_dentro(mob, ZONA_CONTENIDO)
            return mob
        return encajar(mob, self.zona(zona), margen=margen, alineacion=ALINEACIONES.get(alineacion, ORIGIN))

    def zona_de_referencia(self, zona: str | dict) -> Zona:
        """La zona que da escala a una pieza: la nombrada o, si va junto a otro objeto, la principal."""
        return self.zona(zona) if isinstance(zona, str) else self.zona("principal")

    def color(self, nombre: str) -> str:
        if nombre not in COLORES:
            raise _error("E6", f"el color '{nombre}' no existe.{sugerencia(nombre, COLORES)} "
                               f"Colores: {', '.join(COLORES)}", self.ubicacion)
        return COLORES[nombre]

    # --- construcción de objetos del catálogo -------------------------------------------------------------

    def crear(self, tipo: str, **params: Any) -> Mobject:
        """Construye un objeto del tipo ``tipo`` del catálogo (con los defectos de sus parámetros)."""
        definicion = registro.obtener(tipo, "objeto")
        if definicion is None:
            raise _error("E2", f"el tipo '{tipo}' no existe.{sugerencia(tipo, registro.nombres('objeto'))}",
                         self.ubicacion)
        return definicion.funcion(self, **registro.resolver_params(definicion, params))

    # --- tareas tras la animación del grupo en curso ------------------------------------------------------

    def despues(self, tarea: Callable[[], None]) -> None:
        """Programa ``tarea`` para justo después del ``play`` del grupo en curso (antes del siguiente fotograma)."""
        self._pendientes.append(tarea)

    def ejecutar_pendientes(self) -> None:
        pendientes, self._pendientes = self._pendientes, []
        for tarea in pendientes:
            tarea()

    # --- efectos persistentes -------------------------------------------------------------------------

    def iniciar_efecto(self, id: str, tipo: str, detener: Callable[["ContextoGuion"], Any], **datos: Any) -> Efecto:
        if id in self.efectos:
            raise _error("E4", f"el efecto '{id}' ya está activo; detenlo antes o usa otro id", self.ubicacion)
        efecto = Efecto(id, tipo, detener, dict(datos))
        self.efectos[id] = efecto
        return efecto

    def detener_efecto(self, id: str) -> Any:
        """Termina el efecto ``id`` y devuelve las animaciones de su cierre (o ``None``)."""
        efecto = self.efectos.pop(id, None)
        if efecto is None:
            raise _error("E4", f"no hay un efecto activo '{id}'.{sugerencia(id, self.efectos)}", self.ubicacion)
        return efecto.detener(self)

    # --- personalizado ---------------------------------------------------------------------------------

    def cargar_funcion(self, archivo: str, funcion: str) -> Callable:
        """Función ``funcion`` del módulo ``archivo`` (relativo a la carpeta del guion); E9 si no existe."""
        ruta = (self.dir_base / archivo).resolve()
        if not ruta.is_file():
            raise _error("E9", f"no existe el archivo '{archivo}' ({ruta})", self.ubicacion)
        modulo = self._modulos.get(ruta)
        if modulo is None:
            nombre = f"_guion_personalizado_{len(self._modulos)}_{ruta.stem}"
            spec = importlib.util.spec_from_file_location(nombre, ruta)
            modulo = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(modulo)  # type: ignore[union-attr]
            self._modulos[ruta] = modulo
        objetivo = getattr(modulo, funcion, None)
        if not callable(objetivo):
            raise _error("E9", f"'{archivo}' no define la función '{funcion}'", self.ubicacion)
        return objetivo


def agrupar(mobs: list[Mobject], ids: list[str]) -> VGroup:
    """``VGroup`` de ``mobs`` direccionable como ``grupo.<id>`` (partes) y con sus ids de miembros."""
    grupo = VGroup(*mobs)
    setattr(grupo, ATRIBUTO_PARTES, dict(zip(ids, mobs)))
    setattr(grupo, ATRIBUTO_MIEMBROS, list(ids))
    return grupo
