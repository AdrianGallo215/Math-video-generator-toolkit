"""Esquema del guion técnico (YAML ``version: 1`` + enmiendas v1.1): dataclasses y carga con errores E1.

``cargar(ruta)`` / ``cargar_texto(texto)`` devuelven un :class:`Guion` o lanzan :class:`ErrorGuion` con TODOS los
problemas estructurales encontrados (código ``E1``, línea aproximada y sugerencia de la clave más parecida).
Aquí no se consulta el catálogo: verbos, tipos, parámetros, zonas y anclas se validan en ``validar.py``.

También vive aquí el bloque ``calculos:`` (motores en lista blanca) y la sustitución ``{nombre.ruta[:formato]}``
en los parámetros de los pasos y del escenario (errores ``E10``).
"""

from __future__ import annotations

import copy
import difflib
import keyword
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from toolkit.medios import normalizar_texto

VERSION = 1
PAUSA_POR_DEFECTO = 0.3
DUR_RESTO = "resto"
CLAVES_RAIZ = ("version", "meta", "subtitulos", "zonas", "calculos", "escenario", "segmentos")
CLAVES_META = ("slug", "titulo", "clase", "voz", "velocidad", "musica", "volumen_musica_db")
CLAVES_SEGMENTO = ("narracion", "pausa", "pasos", "relleno", "ambiente")
CLAVES_PASO = ("en", "hacer", "dur", "retraso")
CLAVES_ZONA = ("de", "filas", "fila", "columnas", "columna", "espacio")
CLAVES_ESCENARIO = ("objetos", "disposicion")
CLAVES_DISPOSICION = ("apilar", "fila", "espacio", "zona")
ESPACIO_DISPOSICION = 0.5
NOMBRES_ZONAS_BASE = ("titulo", "principal", "subtitulos", "segura")  # siempre existen (toolkit.layout)
_ID = re.compile(r"^[a-z][a-z0-9_]*$")
_VELOCIDAD = re.compile(r"^[+-]\d{1,3}%$")


# --- Hallazgos y errores ----------------------------------------------------------------------


@dataclass
class Hallazgo:
    """Un problema del guion: ``codigo`` (E1..E10 / A1..A9), qué corregir, dónde y línea aproximada."""

    codigo: str
    mensaje: str
    ubicacion: str = ""
    linea: int | None = None

    def __str__(self) -> str:
        donde = self.ubicacion or "guion"
        if self.linea is not None:
            donde += f" (línea {self.linea})"
        return f"[{self.codigo}] {donde}: {self.mensaje}"

    def como_dict(self) -> dict:
        return {"codigo": self.codigo, "mensaje": self.mensaje, "ubicacion": self.ubicacion, "linea": self.linea}


class ErrorGuion(ValueError):
    """Guion inválido: ``hallazgos`` lista cada problema con lo que hay que corregir."""

    def __init__(self, hallazgos: list[Hallazgo]) -> None:
        self.hallazgos = list(hallazgos)
        super().__init__("\n".join(str(h) for h in self.hallazgos) or "guion inválido")


def sugerencia(valor: Any, opciones, prefijo: str = " ¿Quisiste decir ") -> str:
    """`` ¿Quisiste decir 'x'?`` con la opción más parecida (difflib), o "" si ninguna se parece."""
    if not isinstance(valor, str):
        return ""
    lista = [str(o) for o in opciones]
    parecidas = difflib.get_close_matches(valor, lista, n=1, cutoff=0.6)
    if not parecidas:
        parecidas = difflib.get_close_matches(normalizar_texto(valor), lista, n=1, cutoff=0.6)
    return f"{prefijo}'{parecidas[0]}'?" if parecidas else ""


# --- Anclas y duraciones ------------------------------------------------------------------------


@dataclass(frozen=True)
class Ancla:
    """Momento de la narración: ``inicio``, ``fin`` (fin de la última palabra) o una palabra/frase."""

    tipo: str  # "inicio" | "fin" | "palabra"
    texto: str = ""
    ocurrencia: int = 1
    mas: float = 0.0  # desplazamiento en segundos

    @property
    def clave(self) -> tuple:
        """Igualdad de anclas para agrupar pasos (texto normalizado)."""
        return (self.tipo, normalizar_texto(self.texto), self.ocurrencia, round(self.mas, 6))

    def describir(self) -> str:
        base = self.tipo if self.tipo != "palabra" else repr(self.texto)
        if self.tipo == "palabra" and self.ocurrencia != 1:
            base += f" (ocurrencia {self.ocurrencia})"
        if self.mas:
            base += f" {self.mas:+g} s"
        return base


def _parsear_base_ancla(valor: Any) -> tuple[str, str, int]:
    if isinstance(valor, bool) or valor is None:
        raise ValueError(f"ancla inválida {valor!r}: usa inicio, fin, \"palabra\" o [\"palabra\", n]")
    if isinstance(valor, (int, float)):
        valor = str(valor)
    if isinstance(valor, str):
        if not normalizar_texto(valor):
            raise ValueError(f"ancla vacía {valor!r}: escribe una palabra de la narración")
        if valor in ("inicio", "fin"):
            return valor, "", 1
        return "palabra", valor, 1
    if isinstance(valor, list):
        if len(valor) != 2 or not isinstance(valor[0], str) or isinstance(valor[1], bool) or not isinstance(valor[1], int):
            raise ValueError(f"ancla {valor!r}: la forma de lista es [\"palabra\", n] con n ≥ 1 (n-ésima ocurrencia)")
        if valor[1] < 1:
            raise ValueError(f"ancla {valor!r}: la ocurrencia empieza en 1")
        if not normalizar_texto(valor[0]):
            raise ValueError(f"ancla vacía {valor!r}")
        return "palabra", valor[0], valor[1]
    raise ValueError(f"ancla inválida {valor!r}: usa inicio, fin, \"palabra\", [\"palabra\", n] o {{ancla: ..., mas: s}}")


def parsear_ancla(valor: Any) -> Ancla:
    """Convierte el valor YAML de ``en`` (o de ``dur: {hasta: ...}``) en un :class:`Ancla`; ``ValueError`` si no vale."""
    if isinstance(valor, dict):
        desconocidas = set(valor) - {"ancla", "ocurrencia", "mas"}
        if desconocidas or "ancla" not in valor:
            raise ValueError(
                f"ancla {valor!r}: la forma de mapa es {{ancla: \"palabra\", ocurrencia: n, mas: segundos}}"
            )
        tipo, texto, ocurrencia = _parsear_base_ancla(valor["ancla"])
        if "ocurrencia" in valor:
            n = valor["ocurrencia"]
            if isinstance(n, bool) or not isinstance(n, int) or n < 1:
                raise ValueError(f"ancla {valor!r}: 'ocurrencia' debe ser un entero ≥ 1")
            ocurrencia = n
        mas = valor.get("mas", 0.0)
        if isinstance(mas, bool) or not isinstance(mas, (int, float)) or not math.isfinite(mas):
            raise ValueError(f"ancla {valor!r}: 'mas' debe ser un número de segundos")
        return Ancla(tipo, texto, ocurrencia, float(mas))
    tipo, texto, ocurrencia = _parsear_base_ancla(valor)
    return Ancla(tipo, texto, ocurrencia)


def parsear_dur(valor: Any) -> float | str | Ancla | None:
    """``dur``: número > 0 | ``resto`` | ``{hasta: ancla}`` | ``None`` (defecto de la pieza)."""
    if valor is None:
        return None
    if isinstance(valor, bool):
        raise ValueError("dur debe ser un número de segundos, 'resto' o {hasta: ancla}")
    if isinstance(valor, (int, float)):
        if not math.isfinite(valor) or valor <= 0:
            raise ValueError(f"dur {valor!r}: debe ser mayor que 0 (usa otro verbo si no quieres animar)")
        return float(valor)
    if valor == DUR_RESTO:
        return DUR_RESTO
    if isinstance(valor, dict) and set(valor) == {"hasta"}:
        return parsear_ancla(valor["hasta"])
    raise ValueError(f"dur {valor!r} inválida: usa segundos (1.2), 'resto' o {{hasta: \"palabra\"}}")


# --- Dataclasses del guion ----------------------------------------------------------------------


@dataclass
class Meta:
    slug: str
    titulo: str
    clase: str
    voz: str | None = None
    velocidad: str | None = None
    musica: str | None = None
    volumen_musica_db: float | None = None


@dataclass
class DefZona:
    nombre: str
    de: str
    filas: list[float] | None = None
    columnas: list[float] | None = None
    indice: int = 0
    espacio: float = 0.0
    linea: int | None = None


@dataclass
class Calculo:
    nombre: str
    motor: str
    params: dict[str, Any]
    linea: int | None = None


@dataclass
class ObjetoEscenario:
    id: str
    tipo: str
    params: dict[str, Any]
    oculto: bool = True
    indice: int = 0
    linea: int | None = None

    @property
    def ubicacion(self) -> str:
        return f"escenario, objeto {self.indice} ('{self.id}')"


@dataclass
class Disposicion:
    modo: str  # "apilar" | "fila"
    ids: list[str]
    espacio: float = ESPACIO_DISPOSICION
    zona: str | None = None
    indice: int = 0
    linea: int | None = None


@dataclass
class Paso:
    en: Ancla
    hacer: str
    params: dict[str, Any] = field(default_factory=dict)
    dur: float | str | Ancla | None = None
    retraso: float = 0.0
    indice: int = 0  # 1-based dentro del segmento
    segmento: int = 0  # 1-based
    linea: int | None = None

    @property
    def ubicacion(self) -> str:
        return f"segmento {self.segmento}, paso {self.indice}"


@dataclass
class Segmento:
    narracion: str
    pasos: list[Paso] = field(default_factory=list)
    pausa: float = PAUSA_POR_DEFECTO
    relleno: bool = True
    ambiente: str | None = None
    indice: int = 0
    linea: int | None = None

    @property
    def ubicacion(self) -> str:
        return f"segmento {self.indice}"


@dataclass
class Guion:
    version: int
    meta: Meta
    segmentos: list[Segmento]
    subtitulos: dict[str, str] = field(default_factory=dict)
    zonas: dict[str, DefZona] = field(default_factory=dict)
    calculos: dict[str, Calculo] = field(default_factory=dict)
    escenario: list[ObjetoEscenario] = field(default_factory=list)
    disposiciones: list[Disposicion] = field(default_factory=list)
    ruta: Path | None = None
    lineas: dict[tuple, int] = field(default_factory=dict, repr=False)

    @property
    def dir_base(self) -> Path:
        """Carpeta del YAML (rutas de ``personalizado`` relativas a ella); cwd si no hay archivo."""
        return self.ruta.parent if self.ruta is not None else Path.cwd()

    def pasos(self):
        for segmento in self.segmentos:
            yield from segmento.pasos


# --- Carga -------------------------------------------------------------------------------------------


class _Lector:
    """Acumula hallazgos E1 mientras recorre los datos crudos."""

    def __init__(self, lineas: dict[tuple, int]) -> None:
        self.lineas = lineas
        self.hallazgos: list[Hallazgo] = []

    def linea(self, ruta: tuple) -> int | None:
        while ruta:
            if ruta in self.lineas:
                return self.lineas[ruta]
            ruta = ruta[:-1]
        return self.lineas.get((), None)

    def error(self, mensaje: str, ubicacion: str, ruta: tuple, codigo: str = "E1") -> None:
        self.hallazgos.append(Hallazgo(codigo, mensaje, ubicacion, self.linea(ruta)))

    def claves(self, datos: dict, permitidas, ubicacion: str, ruta: tuple, que: str) -> None:
        for clave in datos:
            if clave not in permitidas:
                self.error(
                    f"clave desconocida '{clave}' en {que}.{sugerencia(clave, permitidas)} "
                    f"Claves válidas: {', '.join(permitidas)}.",
                    ubicacion,
                    ruta + (clave,),
                )


def _mapa_lineas(texto: str, lector_hallazgos: list[Hallazgo]) -> dict[tuple, int]:
    """Ruta (claves/índices) -> línea 1-based de cada nodo; detecta claves duplicadas (E1)."""
    lineas: dict[tuple, int] = {}
    raiz = yaml.compose(texto)
    if raiz is None:
        return lineas

    def recorrer(nodo, ruta: tuple) -> None:
        lineas[ruta] = nodo.start_mark.line + 1
        if isinstance(nodo, yaml.MappingNode):
            vistas: dict[Any, int] = {}
            for clave_nodo, valor_nodo in nodo.value:
                clave = clave_nodo.value
                if clave in vistas:
                    lector_hallazgos.append(
                        Hallazgo(
                            "E1",
                            f"clave '{clave}' duplicada (ya aparece en la línea {vistas[clave]}); deja una sola",
                            ".".join(str(r) for r in ruta) or "raíz",
                            clave_nodo.start_mark.line + 1,
                        )
                    )
                vistas[clave] = clave_nodo.start_mark.line + 1
                recorrer(valor_nodo, ruta + (clave,))
        elif isinstance(nodo, yaml.SequenceNode):
            for i, hijo in enumerate(nodo.value):
                recorrer(hijo, ruta + (i,))

    recorrer(raiz, ())
    return lineas


def _es_numero(valor: Any) -> bool:
    return isinstance(valor, (int, float)) and not isinstance(valor, bool) and math.isfinite(valor)


def _leer_meta(datos: Any, lector: _Lector) -> Meta | None:
    ruta = ("meta",)
    if not isinstance(datos, dict):
        lector.error("falta el bloque 'meta' (slug, titulo, clase) o no es un mapa", "meta", ruta)
        return None
    lector.claves(datos, CLAVES_META, "meta", ruta, "meta")
    for clave in ("slug", "titulo", "clase"):
        if not isinstance(datos.get(clave), str) or not datos.get(clave, "").strip():
            lector.error(f"falta meta.{clave} (texto no vacío)", "meta", ruta + (clave,))
    clase = datos.get("clase")
    if isinstance(clase, str) and clase.strip() and (not clase.isidentifier() or keyword.iskeyword(clase)):
        lector.error(f"meta.clase '{clase}' no es un nombre de clase Python válido (p. ej. 'BusquedaBinaria')",
                     "meta", ruta + ("clase",))
    voz = datos.get("voz")
    if voz is not None:
        from toolkit.narracion import VOCES_DISPONIBLES

        if voz not in VOCES_DISPONIBLES:
            lector.error(f"meta.voz '{voz}' no está disponible.{sugerencia(voz, VOCES_DISPONIBLES)} "
                         f"Voces: {', '.join(VOCES_DISPONIBLES)}", "meta", ruta + ("voz",))
    velocidad = datos.get("velocidad")
    if velocidad is not None and (not isinstance(velocidad, str) or not _VELOCIDAD.match(velocidad)):
        lector.error(f"meta.velocidad {velocidad!r}: usa un porcentaje entre comillas, p. ej. \"+5%\"",
                     "meta", ruta + ("velocidad",))
    volumen = datos.get("volumen_musica_db")
    if volumen is not None and not _es_numero(volumen):
        lector.error("meta.volumen_musica_db debe ser un número (dB, p. ej. -24)", "meta", ruta + ("volumen_musica_db",))
    return Meta(
        slug=str(datos.get("slug", "")),
        titulo=str(datos.get("titulo", "")),
        clase=str(datos.get("clase", "")),
        voz=voz,
        velocidad=velocidad,
        musica=datos.get("musica"),
        volumen_musica_db=volumen,
    )


def _leer_subtitulos(datos: Any, lector: _Lector) -> dict[str, str]:
    if datos is None:
        return {}
    if not isinstance(datos, dict) or not all(isinstance(v, str) for v in datos.values()):
        lector.error("'subtitulos' debe ser un mapa palabra -> nombre de color (p. ej. ene: azul)",
                     "subtitulos", ("subtitulos",))
        return {}
    return {normalizar_texto(str(k)): v for k, v in datos.items()}


def _lista_positiva(valor: Any) -> bool:
    return isinstance(valor, list) and len(valor) >= 2 and all(_es_numero(v) and v > 0 for v in valor)


def _leer_zonas(datos: Any, lector: _Lector) -> dict[str, DefZona]:
    if datos is None:
        return {}
    if not isinstance(datos, dict):
        lector.error("'zonas' debe ser un mapa nombre -> {de, filas|columnas, fila|columna}", "zonas", ("zonas",))
        return {}
    zonas: dict[str, DefZona] = {}
    for nombre, spec in datos.items():
        ruta = ("zonas", nombre)
        ubic = f"zonas.{nombre}"
        if not isinstance(nombre, str) or not _ID.match(nombre):
            lector.error(f"nombre de zona {nombre!r} inválido (minúsculas, dígitos y _)", ubic, ruta)
            continue
        if nombre in NOMBRES_ZONAS_BASE:
            lector.error(f"'{nombre}' es una zona base; elige otro nombre", ubic, ruta)
            continue
        if not isinstance(spec, dict):
            lector.error("cada zona es un mapa {de: zona, filas: [..], fila: i} o {de, columnas, columna, espacio}", ubic, ruta)
            continue
        lector.claves(spec, CLAVES_ZONA, ubic, ruta, "la zona")
        if not isinstance(spec.get("de"), str):
            lector.error("falta 'de' (zona de la que se deriva, p. ej. principal)", ubic, ruta)
            continue
        tiene_filas, tiene_columnas = "filas" in spec, "columnas" in spec
        if tiene_filas == tiene_columnas:
            lector.error("usa 'filas' + 'fila' o 'columnas' + 'columna' (uno de los dos)", ubic, ruta)
            continue
        clave_lista, clave_indice = ("filas", "fila") if tiene_filas else ("columnas", "columna")
        proporciones = spec[clave_lista]
        if not _lista_positiva(proporciones):
            lector.error(f"'{clave_lista}' debe ser una lista de ≥ 2 proporciones positivas, p. ej. [0.55, 0.45]",
                         ubic, ruta + (clave_lista,))
            continue
        indice = spec.get(clave_indice)
        if isinstance(indice, bool) or not isinstance(indice, int) or not 0 <= indice < len(proporciones):
            lector.error(f"'{clave_indice}' debe ser un entero entre 0 y {len(proporciones) - 1}", ubic, ruta)
            continue
        espacio = spec.get("espacio", 0.0)
        if tiene_filas and "espacio" in spec:
            lector.error("'espacio' solo aplica a columnas (las filas no llevan hueco)", ubic, ruta + ("espacio",))
            continue
        if not _es_numero(espacio) or espacio < 0:
            lector.error("'espacio' debe ser un número ≥ 0", ubic, ruta + ("espacio",))
            continue
        zonas[nombre] = DefZona(
            nombre=nombre,
            de=spec["de"],
            filas=list(proporciones) if tiene_filas else None,
            columnas=list(proporciones) if tiene_columnas else None,
            indice=indice,
            espacio=float(espacio),
            linea=lector.linea(ruta),
        )
    return zonas


def _leer_calculos(datos: Any, lector: _Lector) -> dict[str, Calculo]:
    if datos is None:
        return {}
    if not isinstance(datos, dict):
        lector.error("'calculos' debe ser un mapa nombre -> {motor: ..., parámetros}", "calculos", ("calculos",))
        return {}
    calculos: dict[str, Calculo] = {}
    for nombre, spec in datos.items():
        ruta = ("calculos", nombre)
        ubic = f"calculos.{nombre}"
        if not isinstance(nombre, str) or not _ID.match(nombre):
            lector.error(f"nombre de cálculo {nombre!r} inválido (minúsculas, dígitos y _)", ubic, ruta)
            continue
        if not isinstance(spec, dict) or not isinstance(spec.get("motor"), str):
            lector.error("cada cálculo es un mapa con 'motor' (p. ej. {motor: lineal, a: 2, b: 3, c: 11})", ubic, ruta)
            continue
        params = {k: v for k, v in spec.items() if k != "motor"}
        calculos[nombre] = Calculo(nombre, spec["motor"], params, lector.linea(ruta))
    return calculos


def _leer_escenario(datos: Any, lector: _Lector) -> tuple[list[ObjetoEscenario], list[Disposicion]]:
    if datos is None:
        return [], []
    if not isinstance(datos, dict):
        lector.error("'escenario' debe ser un mapa {objetos: [...], disposicion: [...]}", "escenario", ("escenario",))
        return [], []
    lector.claves(datos, CLAVES_ESCENARIO, "escenario", ("escenario",), "escenario")
    objetos: list[ObjetoEscenario] = []
    lista = datos.get("objetos", [])
    if not isinstance(lista, list):
        lector.error("'escenario.objetos' debe ser una lista", "escenario", ("escenario", "objetos"))
        lista = []
    for i, item in enumerate(lista, start=1):
        ruta = ("escenario", "objetos", i - 1)
        ubic = f"escenario, objeto {i}"
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not isinstance(item.get("tipo"), str):
            lector.error("cada objeto del escenario necesita 'id' y 'tipo' (más los parámetros del tipo)", ubic, ruta)
            continue
        oculto = item.get("oculto", True)
        if not isinstance(oculto, bool):
            lector.error("'oculto' debe ser true o false", ubic, ruta + ("oculto",))
            continue
        params = {k: v for k, v in item.items() if k not in ("id", "tipo", "oculto")}
        objetos.append(ObjetoEscenario(item["id"], item["tipo"], params, oculto, i, lector.linea(ruta)))
    disposiciones: list[Disposicion] = []
    lista = datos.get("disposicion", [])
    if not isinstance(lista, list):
        lector.error("'escenario.disposicion' debe ser una lista", "escenario", ("escenario", "disposicion"))
        lista = []
    for i, item in enumerate(lista, start=1):
        ruta = ("escenario", "disposicion", i - 1)
        ubic = f"escenario, disposición {i}"
        if not isinstance(item, dict):
            lector.error("cada disposición es un mapa {apilar: [ids], espacio: 0.5, zona: principal}", ubic, ruta)
            continue
        lector.claves(item, CLAVES_DISPOSICION, ubic, ruta, "la disposición")
        modos = [m for m in ("apilar", "fila") if m in item]
        if len(modos) != 1:
            lector.error("usa exactamente una de 'apilar' (vertical) o 'fila' (horizontal)", ubic, ruta)
            continue
        ids = item[modos[0]]
        if not isinstance(ids, list) or len(ids) < 2 or not all(isinstance(x, str) for x in ids):
            lector.error(f"'{modos[0]}' debe ser una lista de ≥ 2 ids del escenario", ubic, ruta + (modos[0],))
            continue
        espacio = item.get("espacio", ESPACIO_DISPOSICION)
        if not _es_numero(espacio) or espacio < 0:
            lector.error("'espacio' debe ser un número ≥ 0", ubic, ruta + ("espacio",))
            continue
        zona = item.get("zona")
        if zona is not None and not isinstance(zona, str):
            lector.error("'zona' de una disposición es el nombre de una zona", ubic, ruta + ("zona",))
            continue
        disposiciones.append(Disposicion(modos[0], list(ids), float(espacio), zona, i, lector.linea(ruta)))
    return objetos, disposiciones


def _leer_paso(datos: Any, lector: _Lector, i_seg: int, i_paso: int) -> Paso | None:
    ruta = ("segmentos", i_seg - 1, "pasos", i_paso - 1)
    ubic = f"segmento {i_seg}, paso {i_paso}"
    if not isinstance(datos, dict):
        lector.error("cada paso es un mapa {en: ancla, hacer: verbo, ...}", ubic, ruta)
        return None
    ok = True
    if "hacer" not in datos or not isinstance(datos["hacer"], str):
        lector.error("falta 'hacer' (el verbo: mostrar, quitar, resaltar...)", ubic, ruta)
        ok = False
    if "en" not in datos:
        lector.error("falta 'en' (el ancla: inicio, fin o una palabra de la narración)", ubic, ruta)
        ok = False
    ancla = None
    if "en" in datos:
        try:
            ancla = parsear_ancla(datos["en"])
        except ValueError as error:
            lector.error(str(error), ubic, ruta + ("en",))
            ok = False
    dur = None
    try:
        dur = parsear_dur(datos.get("dur"))
    except ValueError as error:
        lector.error(str(error), ubic, ruta + ("dur",))
        ok = False
    retraso = datos.get("retraso", 0.0)
    if not _es_numero(retraso) or retraso < 0:
        lector.error(f"retraso {retraso!r}: debe ser un número de segundos ≥ 0", ubic, ruta + ("retraso",))
        ok = False
    if not ok:
        return None
    params = {k: v for k, v in datos.items() if k not in CLAVES_PASO}
    return Paso(ancla, datos["hacer"], params, dur, float(retraso), i_paso, i_seg, lector.linea(ruta))


def _leer_segmentos(datos: Any, lector: _Lector) -> list[Segmento]:
    if not isinstance(datos, list) or not datos:
        lector.error("falta 'segmentos' (lista no vacía de {narracion, pasos})", "segmentos", ("segmentos",))
        return []
    segmentos: list[Segmento] = []
    for i, item in enumerate(datos, start=1):
        ruta = ("segmentos", i - 1)
        ubic = f"segmento {i}"
        if not isinstance(item, dict):
            lector.error("cada segmento es un mapa {narracion: \"...\", pasos: [...]}", ubic, ruta)
            continue
        lector.claves(item, CLAVES_SEGMENTO, ubic, ruta, "el segmento")
        narracion = item.get("narracion")
        if not isinstance(narracion, str) or not normalizar_texto(narracion):
            lector.error("falta 'narracion' (el texto exacto que dirá la voz)", ubic, ruta + ("narracion",))
            continue
        pausa = item.get("pausa", PAUSA_POR_DEFECTO)
        if not _es_numero(pausa) or pausa < 0:
            lector.error("'pausa' debe ser un número de segundos ≥ 0", ubic, ruta + ("pausa",))
            pausa = PAUSA_POR_DEFECTO
        relleno = item.get("relleno", True)
        if not isinstance(relleno, bool):
            lector.error("'relleno' debe ser true o false", ubic, ruta + ("relleno",))
            relleno = True
        ambiente = item.get("ambiente")
        if ambiente is not None and not isinstance(ambiente, str):
            lector.error("'ambiente' es el id del objeto que respira en los huecos", ubic, ruta + ("ambiente",))
            ambiente = None
        pasos_crudos = item.get("pasos", [])
        if pasos_crudos is None:
            pasos_crudos = []
        if not isinstance(pasos_crudos, list):
            lector.error("'pasos' debe ser una lista", ubic, ruta + ("pasos",))
            pasos_crudos = []
        pasos = [p for j, crudo in enumerate(pasos_crudos, start=1) if (p := _leer_paso(crudo, lector, i, j))]
        segmentos.append(Segmento(narracion, pasos, float(pausa), relleno, ambiente, i, lector.linea(ruta)))
    return segmentos


def cargar_texto(texto: str, ruta: Path | str | None = None) -> Guion:
    """Parsea el YAML ``texto``; lanza :class:`ErrorGuion` (E1) con todos los problemas estructurales."""
    ubic_archivo = str(ruta) if ruta is not None else "guion"
    try:
        datos = yaml.safe_load(texto)
        duplicadas: list[Hallazgo] = []
        lineas = _mapa_lineas(texto, duplicadas)
    except yaml.YAMLError as error:
        marca = getattr(error, "problem_mark", None)
        linea = marca.line + 1 if marca is not None else None
        problema = getattr(error, "problem", None) or str(error)
        raise ErrorGuion([Hallazgo("E1", f"YAML mal formado: {problema} (revisa comillas, dos puntos e indentación)",
                                   ubic_archivo, linea)]) from error
    lector = _Lector(lineas)
    lector.hallazgos.extend(duplicadas)
    if not isinstance(datos, dict):
        lector.error("el guion debe ser un mapa con version, meta y segmentos", ubic_archivo, ())
        raise ErrorGuion(lector.hallazgos)
    lector.claves(datos, CLAVES_RAIZ, "raíz", (), "la raíz del guion")
    if datos.get("version") != VERSION:
        lector.error(f"version {datos.get('version')!r} no soportada: escribe 'version: {VERSION}'", "raíz", ("version",))
    meta = _leer_meta(datos.get("meta"), lector)
    subtitulos = _leer_subtitulos(datos.get("subtitulos"), lector)
    zonas = _leer_zonas(datos.get("zonas"), lector)
    calculos = _leer_calculos(datos.get("calculos"), lector)
    escenario, disposiciones = _leer_escenario(datos.get("escenario"), lector)
    segmentos = _leer_segmentos(datos.get("segmentos"), lector)
    if lector.hallazgos or meta is None:
        raise ErrorGuion(lector.hallazgos)
    return Guion(
        version=VERSION,
        meta=meta,
        segmentos=segmentos,
        subtitulos=subtitulos,
        zonas=zonas,
        calculos=calculos,
        escenario=escenario,
        disposiciones=disposiciones,
        ruta=Path(ruta).resolve() if ruta is not None else None,
        lineas=lineas,
    )


def cargar(ruta: Path | str) -> Guion:
    """Lee y parsea ``ruta``; :class:`ErrorGuion` (E1) si no existe o es inválido."""
    ruta = Path(ruta)
    if not ruta.is_file():
        raise ErrorGuion([Hallazgo("E1", f"no existe el guion {ruta}", str(ruta))])
    return cargar_texto(ruta.read_text(encoding="utf-8"), ruta)


# --- Cálculos: motores en lista blanca y sustitución {nombre.ruta[:formato]} ------------------------------


def _paso_algebra_a_dict(paso) -> dict:
    return {
        "tokens": list(paso.tokens),
        "latex": paso.latex,
        "explicacion": paso.explicacion,
        "resaltar": list(paso.resaltar),
    }


def _motor_algebra(nombre_funcion: str):
    def ejecutar(a, b, c, variable: str = "x"):
        from toolkit import motor_algebra

        funcion = getattr(motor_algebra, nombre_funcion)
        return [_paso_algebra_a_dict(p) for p in funcion(a, b, c, variable=variable)]

    return ejecutar


def _motor_busqueda_binaria(valores, objetivo):
    from toolkit.algoritmos_visual import pasos_busqueda_binaria

    return pasos_busqueda_binaria(valores, objetivo)


def _motor_burbuja(valores):
    from toolkit.algoritmos_visual import pasos_burbuja

    return [{"accion": accion, "i": i, "j": j} for accion, i, j in pasos_burbuja(valores)]


def _motor_fisica(funcion, **kwargs):
    from toolkit import motor_fisica

    permitidas = [n for n in motor_fisica.__all__ if n != "G_TIERRA"]
    if funcion not in permitidas:
        raise ValueError(f"funcion '{funcion}' no está en motor_fisica.{sugerencia(funcion, permitidas)} "
                         f"Disponibles: {', '.join(permitidas)}")
    resultado = getattr(motor_fisica, funcion)(**kwargs)
    return list(resultado) if isinstance(resultado, tuple) else resultado


MOTORES: dict[str, Any] = {
    "busqueda_binaria": _motor_busqueda_binaria,
    "burbuja": _motor_burbuja,
    "completar_cuadrado": _motor_algebra("completar_cuadrado"),
    "cuadratica": _motor_algebra("resolver_cuadratica_formula"),
    "lineal": _motor_algebra("resolver_lineal"),
    "fisica": _motor_fisica,
}

_REFERENCIA = re.compile(r"\{([a-z][a-z0-9_]*)((?:\.[A-Za-z0-9_]+)*)(?::([^{}]*))?\}")


def evaluar_calculos(guion: Guion) -> tuple[dict[str, Any], list[Hallazgo]]:
    """Ejecuta cada cálculo con su motor; errores E2 (motor inexistente) y E10 (parámetros/fallo)."""
    resultados: dict[str, Any] = {}
    hallazgos: list[Hallazgo] = []
    for nombre, calculo in guion.calculos.items():
        ubic = f"calculos.{nombre}"
        motor = MOTORES.get(calculo.motor)
        if motor is None:
            hallazgos.append(Hallazgo("E2", f"motor '{calculo.motor}' inexistente.{sugerencia(calculo.motor, MOTORES)} "
                                            f"Motores: {', '.join(MOTORES)}", ubic, calculo.linea))
            continue
        try:
            resultados[nombre] = motor(**calculo.params)
        except TypeError as error:
            hallazgos.append(Hallazgo("E10", f"parámetros inválidos para el motor '{calculo.motor}': {error}", ubic,
                                      calculo.linea))
        except (ValueError, ArithmeticError) as error:
            hallazgos.append(Hallazgo("E10", f"el motor '{calculo.motor}' falló: {error}", ubic, calculo.linea))
    return resultados, hallazgos


def _resolver_ruta(valor: Any, ruta: list[str]) -> Any:
    recorrido = []
    for clave in ruta:
        recorrido.append(clave)
        if isinstance(valor, dict):
            if clave not in valor:
                raise KeyError(f"'{'.'.join(recorrido)}' no existe; claves disponibles: {', '.join(map(str, valor))}")
            valor = valor[clave]
        elif isinstance(valor, (list, tuple)):
            if not clave.isdigit() or int(clave) >= len(valor):
                raise KeyError(f"'{'.'.join(recorrido)}': índice inválido (hay {len(valor)} elementos: 0-{len(valor) - 1})")
            valor = valor[int(clave)]
        else:
            raise KeyError(f"'{'.'.join(recorrido)}': {valor!r} no tiene partes")
    return valor


def _como_texto(valor: Any, formato: str | None) -> str:
    if formato:
        return format(valor, formato)
    if isinstance(valor, float):
        return format(valor, "g")
    if isinstance(valor, (list, tuple)):
        return " ".join(_como_texto(v, None) for v in valor)
    return str(valor)


def sustituir(valor: Any, resultados: dict[str, Any]) -> Any:
    """Reemplaza ``{calculo.ruta[:formato]}`` en ``valor`` (recursivo). ``KeyError``/``ValueError`` si no existe.

    Solo se tocan referencias cuyo primer nombre es un cálculo declarado (el LaTeX ``\\frac{1}{2}`` queda igual).
    Si la cadena ES solo la referencia (sin formato), se devuelve el valor con su tipo (número, lista...).
    """
    if isinstance(valor, dict):
        return {k: sustituir(v, resultados) for k, v in valor.items()}
    if isinstance(valor, list):
        return [sustituir(v, resultados) for v in valor]
    if not isinstance(valor, str):
        return valor
    completa = _REFERENCIA.fullmatch(valor)
    if completa and completa.group(1) in resultados and completa.group(3) is None:
        return copy.deepcopy(_resolver_ruta(resultados[completa.group(1)], completa.group(2).split(".")[1:]))

    def reemplazar(coincidencia: re.Match) -> str:
        nombre, ruta, formato = coincidencia.groups()
        if nombre not in resultados:
            return coincidencia.group(0)
        dato = _resolver_ruta(resultados[nombre], ruta.split(".")[1:])
        try:
            return _como_texto(dato, formato)
        except (ValueError, TypeError) as error:
            raise ValueError(f"formato ':{formato}' inválido para {dato!r}: {error}") from error

    return _REFERENCIA.sub(reemplazar, valor)


def referencias_a_calculos_inexistentes(valor: Any, calculos: dict) -> list[str]:
    """Referencias ``{x.y}`` cuyo nombre parece un cálculo mal escrito (para sugerir); no incluye LaTeX corto."""
    encontrados: list[str] = []
    if isinstance(valor, dict):
        for v in valor.values():
            encontrados += referencias_a_calculos_inexistentes(v, calculos)
    elif isinstance(valor, list):
        for v in valor:
            encontrados += referencias_a_calculos_inexistentes(v, calculos)
    elif isinstance(valor, str):
        for m in _REFERENCIA.finditer(valor):
            if m.group(1) not in calculos and m.group(2):  # {algo.ruta}: forma de referencia, no LaTeX
                encontrados.append(m.group(0))
    return encontrados


def sustituir_referencias(guion: Guion, resultados: dict[str, Any]) -> tuple[Guion, list[Hallazgo]]:
    """Copia de ``guion`` con las referencias sustituidas en pasos y escenario; hallazgos E10."""
    nuevo = copy.deepcopy(guion)
    hallazgos: list[Hallazgo] = []

    def procesar(params: dict, ubic: str, linea: int | None) -> dict:
        for ref in referencias_a_calculos_inexistentes(params, resultados):
            nombre = ref[1:].split(".")[0].split(":")[0].rstrip("}")
            hallazgos.append(Hallazgo("E10", f"referencia {ref}: no hay un cálculo '{nombre}'."
                                             f"{sugerencia(nombre, list(guion.calculos))} Declara el cálculo en 'calculos:'.",
                                      ubic, linea))
        try:
            return sustituir(params, resultados)
        except (KeyError, ValueError) as error:
            mensaje = error.args[0] if error.args else str(error)
            hallazgos.append(Hallazgo("E10", f"referencia a cálculo inválida: {mensaje}", ubic, linea))
            return params

    for objeto_esc in nuevo.escenario:
        objeto_esc.params = procesar(objeto_esc.params, objeto_esc.ubicacion, objeto_esc.linea)
    for paso in nuevo.pasos():
        paso.params = procesar(paso.params, paso.ubicacion, paso.linea)
    return nuevo, hallazgos


# --- Semántica temporal (compartida por el runtime y la validación con voz) ---------------------------

UMBRAL_RELLENO = 1.0  # s sin animación a partir de los cuales el runtime respira el último objeto en foco
DUR_MINIMA_RELATIVA = 0.3  # piso de dur: resto / {hasta} cuando el ancla ya casi pasó
TOLERANCIA_TARDE = 0.1  # s de retraso de un grupo respecto a su ancla antes de avisar (A7)


def fin_de_voz(narrado) -> float:
    """Fin (s, relativo al segmento) de la última palabra; si no hay palabras, la duración del audio."""
    return narrado.palabras[-1].fin if narrado.palabras else narrado.duracion


def tiempo_de_ancla(ancla: Ancla, narrado) -> float:
    """Instante (s, relativo al segmento) del ancla con la voz real (``KeyError`` si la palabra no está)."""
    if ancla.tipo == "inicio":
        base = 0.0
    elif ancla.tipo == "fin":
        base = fin_de_voz(narrado)
    else:
        base = narrado.tiempo_de(ancla.texto, ancla.ocurrencia)
    return max(0.0, base + ancla.mas)


def duracion_base(paso: Paso) -> float | str | Ancla:
    """``dur`` del paso o el defecto de su pieza (para ``mostrar`` con ``tipo``: la duración de entrada del tipo)."""
    from toolkit.guion import registro

    if paso.dur is not None:
        return paso.dur
    tipo = paso.params.get("tipo") if paso.hacer == "mostrar" else None
    definicion = registro.obtener(tipo, "objeto") if isinstance(tipo, str) else None
    if definicion is None:
        definicion = registro.obtener(paso.hacer, "accion")
    return definicion.duracion if definicion is not None else 1.0


def anima_por_defecto(paso: Paso) -> bool:
    """False para pasos que no animan (su pieza tiene duración 0, p. ej. ``sonido``) y no fijan ``dur``."""
    base = duracion_base(paso)
    return not (isinstance(base, float) and base <= 0)


def resolver_dur(base: float | str | Ancla, inicio: float, narrado) -> tuple[float, str | None]:
    """Segundos de animación de un paso que arranca en ``inicio`` (relativo al segmento) y un aviso si se recorta."""
    if isinstance(base, (int, float)):
        return float(base), None
    if base == DUR_RESTO:
        objetivo, que = fin_de_voz(narrado), "el fin de la narración"
    else:
        objetivo, que = tiempo_de_ancla(base, narrado), f"el ancla {base.describir()}"
    dur = objetivo - inicio
    if dur < DUR_MINIMA_RELATIVA:
        return DUR_MINIMA_RELATIVA, (
            f"dur hasta {que} queda en {max(dur, 0):.2f} s (el paso arranca tarde); se usa {DUR_MINIMA_RELATIVA} s"
        )
    return round(dur, 6), None


def agrupar_pasos(pasos: list[Paso]) -> list[list[Paso]]:
    """Pasos consecutivos con la misma ancla (``en``) forman un grupo que se reproduce a la vez."""
    grupos: list[list[Paso]] = []
    for paso in pasos:
        if grupos and grupos[-1][0].en.clave == paso.en.clave:
            grupos[-1].append(paso)
        else:
            grupos.append([paso])
    return grupos
