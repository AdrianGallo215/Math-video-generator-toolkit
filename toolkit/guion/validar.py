"""Validación del guion técnico antes de renderizar: errores E1–E10 y avisos A1–A9.

``validar(ruta)`` es estática (esquema, catálogo, zonas, colores, anclas contra el texto, ciclo de vida de ids).
``validar(ruta, con_voz=True)`` además sintetiza (o lee de la caché) cada narración con ``MotorNarracion`` y
simula la línea de tiempo del runtime: anclas contra las palabras reales (E7), tramos quietos (A5), duración
total (A6) y pasos que arrancan tarde o recortan su ``dur`` (A7).

Errores: E1 YAML/claves · E2 verbo/tipo/motor inexistente · E3 parámetro ausente o inválido · E4 ciclo de vida
de ids y efectos · E5 zona · E6 color · E7 ancla · E8 texto < FUENTE_MINIMA · E9 personalizado · E10 cálculos.
Avisos: A1 palabras fuera de 150–200 · A2 frase > 14 palabras · A3 segmento sin pasos · A4 objeto sin uso ni
salida · A5 tramo quieto > 1.2 s · A6 duración fuera de 60–90 s · A7 paso tarde o dur recortada · A8 efecto
persistente sin detener · A9 voz sintética (tiempos aproximados).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from toolkit.estilos import FUENTE_MINIMA
from toolkit.guion import registro
from toolkit.guion.contexto import (
    COLORES,
    LADOS,
    ZONAS_BASE,
    derivar_zona,
    error_zona_padre,
    separar_ref,
)
from toolkit.guion.esquema import (
    TOLERANCIA_TARDE,
    UMBRAL_RELLENO,
    Ancla,
    ErrorGuion,
    Guion,
    Hallazgo,
    Paso,
    Segmento,
    agrupar_pasos,
    anima_por_defecto,
    cargar,
    duracion_base,
    evaluar_calculos,
    fin_de_voz,
    resolver_dur,
    sugerencia,
    sustituir_referencias,
    tiempo_de_ancla,
)
from toolkit.medios import normalizar_texto

PALABRAS_MIN, PALABRAS_MAX = 150, 200
PALABRAS_POR_FRASE = 14
TRAMO_QUIETO_MAX = 1.2
DURACION_MIN, DURACION_MAX = 60.0, 90.0
PALABRAS_POR_SEGUNDO_ESTIMADAS = 2.6
_ID = re.compile(r"^[a-z][a-z0-9_]*$")
_FIN_DE_FRASE = re.compile(r"[.!?…]+")


@dataclass
class ReporteValidacion:
    errores: list[Hallazgo] = field(default_factory=list)
    avisos: list[Hallazgo] = field(default_factory=list)
    resumen: dict = field(default_factory=dict)
    guion: Guion | None = field(default=None, repr=False)  # guion con los cálculos sustituidos (si cargó)

    @property
    def ok(self) -> bool:
        return not self.errores

    def como_dict(self) -> dict:
        return {
            "ok": self.ok,
            "errores": [h.como_dict() for h in self.errores],
            "avisos": [h.como_dict() for h in self.avisos],
            "resumen": self.resumen,
        }

    def texto(self) -> str:
        lineas = [f"ERROR {h}" for h in self.errores] + [f"AVISO {h}" for h in self.avisos]
        estado = "OK" if self.ok else f"{len(self.errores)} error(es)"
        lineas.append(f"{estado}, {len(self.avisos)} aviso(s). Resumen: {self.resumen}")
        return "\n".join(lineas)


# --- Estado del ciclo de vida (lo usan los ganchos ``ciclo`` del catálogo) ---------------------------------


class EstadoValidacion:
    """Qué ids existen en cada punto del guion y en qué estado (``reservado`` | ``vivo`` | ``parcial``).

    API para los ganchos ``ciclo(params, estado)`` de las piezas: ``usar``, ``crear``, ``consumir``, ``revelar``,
    ``agrupar``, ``iniciar_efecto``, ``detener_efecto``, ``validar_objeto``, ``estado_de``, ``error``.
    ``creando`` es el id que se está creando mientras se validan los parámetros de su tipo.
    """

    def __init__(self, validador: "_Validador", dir_base: Path) -> None:
        self._v = validador
        self.dir_base = dir_base
        self.ids: dict[str, str] = {}
        self.tipos: dict[str, str] = {}
        self.usos: dict[str, int] = {}
        self.creado_en: dict[str, tuple[str, int | None]] = {}
        self.grupos: dict[str, list[str]] = {}
        self.efectos: dict[str, tuple[str, str, int | None]] = {}
        self.creando: str | None = None
        self.ubicacion = ""
        self.linea: int | None = None

    def ubicar(self, ubicacion: str, linea: int | None) -> None:
        self.ubicacion, self.linea = ubicacion, linea

    def error(self, codigo: str, mensaje: str) -> None:
        self._v.errores.append(Hallazgo(codigo, mensaje, self.ubicacion, self.linea))

    def estado_de(self, id: str) -> str | None:
        return self.ids.get(id)

    def hay_visible(self) -> bool:
        return any(e in ("vivo", "parcial") for e in self.ids.values())

    def _disponibles(self) -> str:
        return ", ".join(f"{i} ({e})" if e != "vivo" else i for i, e in self.ids.items()) or "(ninguno)"

    def usar(self, ref: Any, permitir_reservado: bool = False) -> bool:
        if not isinstance(ref, str) or not ref:
            self.error("E3", f"referencia a objeto inválida {ref!r}: escribe un id ('eq0') o 'id.parte'")
            return False
        id, _ = separar_ref(ref)
        situacion = self.ids.get(id)
        if situacion is None:
            self.error("E4", f"el objeto '{id}' no existe en este punto (no se creó, ya se quitó o se consumió al "
                             f"transformarlo).{sugerencia(id, self.ids)} Objetos disponibles: {self._disponibles()}")
            return False
        if situacion == "reservado" and not permitir_reservado:
            self.error("E4", f"'{id}' está reservado en el escenario y aún no se ve: muéstralo antes con "
                             f"{{hacer: mostrar, id: {id}}}")
            return False
        self.usos[id] = self.usos.get(id, 0) + 1
        return True

    def crear(self, id: Any, tipo: str, oculto: bool = False) -> bool:
        if not isinstance(id, str) or not _ID.match(id):
            self.error("E3", f"id inválido {id!r}: minúsculas, dígitos y _ (sin puntos ni espacios), p. ej. 'eq_final'")
            return False
        if id in self.ids:
            donde, _ = self.creado_en[id]
            self.error("E4", f"el id '{id}' ya existe (creado en {donde}); usa otro id o quítalo antes")
            return False
        if id in self.efectos:
            self.error("E4", f"'{id}' ya es el id de un efecto activo; usa otro id")
            return False
        self.ids[id] = "reservado" if oculto else "vivo"
        self.tipos[id] = tipo
        self.usos[id] = 0
        self.creado_en[id] = (self.ubicacion, self.linea)
        if not oculto:
            self._revelar_miembros(id)
        return True

    def _revelar_miembros(self, id: str) -> None:
        for miembro in self.grupos.get(id, []):
            if self.ids.get(miembro) in ("reservado", "parcial"):
                self.ids[miembro] = "vivo"

    def revelar(self, id: str, parcial: bool = False) -> None:
        if self.ids.get(id) in ("reservado", "parcial"):
            self.ids[id] = "parcial" if parcial else "vivo"
            if not parcial:
                self._revelar_miembros(id)

    def consumir(self, id: str) -> None:
        if self.ids.pop(id, None) is None:
            return
        for miembro in self.grupos.pop(id, []):
            self.ids.pop(miembro, None)
        for miembros in self.grupos.values():
            if id in miembros:
                miembros.remove(id)

    def agrupar(self, id: str | None, miembros: list[str]) -> None:
        for m in miembros:
            for otro, suyos in self.grupos.items():
                if otro != id and m in suyos and otro in self.ids:
                    self.error("E4", f"'{m}' ya pertenece al grupo '{otro}'; un objeto va en un solo grupo a la vez")
        if id is not None:
            self.grupos[id] = list(miembros)

    def iniciar_efecto(self, id: Any, tipo: str) -> None:
        if not isinstance(id, str) or not _ID.match(id):
            self.error("E3", f"id de efecto inválido {id!r}")
            return
        if id in self.efectos:
            self.error("E4", f"el efecto '{id}' ya está activo (iniciado en {self.efectos[id][1]}); detenlo antes")
            return
        if id in self.ids:
            self.error("E4", f"'{id}' ya es el id de un objeto; usa otro id para el efecto")
            return
        self.efectos[id] = (tipo, self.ubicacion, self.linea)

    def detener_efecto(self, id: str) -> None:
        if id not in self.efectos:
            self.error("E4", f"no hay un efecto activo '{id}' que detener (se inicia con camara/variable y ese id)."
                             f"{sugerencia(id, self.efectos)}")
            return
        self.efectos.pop(id)

    def validar_objeto(self, tipo: Any, params: dict, id: str | None = None) -> bool:
        """Valida los parámetros de un objeto del tipo ``tipo`` (E1/E2/E3/E5/E6/E8 + su ciclo)."""
        self.creando = id
        definicion = registro.obtener(tipo, "objeto") if isinstance(tipo, str) else None
        if definicion is None:
            if isinstance(tipo, str) and registro.obtener(tipo, "accion") is not None:
                self.error("E2", f"'{tipo}' es un verbo, no un tipo de objeto. Tipos: {', '.join(registro.nombres('objeto'))}")
            else:
                self.error("E2", f"el tipo '{tipo}' no existe.{sugerencia(tipo, registro.nombres('objeto'))} "
                                 f"Tipos: {', '.join(registro.nombres('objeto'))}")
            return False
        ok = self._v.validar_params(definicion, params, self)
        self._v.aplicar_ciclo(definicion, params, self)
        return ok


# --- Validador ---------------------------------------------------------------------------------------------


def _tipo_valido(p: registro.Param, valor: Any) -> str | None:
    """Mensaje de error si ``valor`` no es del tipo del parámetro ``p`` (o None)."""
    es_num = isinstance(valor, (int, float)) and not isinstance(valor, bool)
    reglas = {
        "texto": (isinstance(valor, str) or es_num, "un texto"),
        "numero": (es_num, "un número"),
        "entero": (isinstance(valor, int) and not isinstance(valor, bool), "un número entero"),
        "booleano": (isinstance(valor, bool), "true o false"),
        "color": (isinstance(valor, str), "el nombre de un color"),
        "lista": (isinstance(valor, list), "una lista [..]"),
        "mapa": (isinstance(valor, dict), "un mapa {clave: valor}"),
        "objeto": (
            isinstance(valor, str) or (isinstance(valor, list) and valor and all(isinstance(v, str) for v in valor)),
            "un id ('a'), 'id.parte' o una lista de ids",
        ),
        "zona": (isinstance(valor, (str, dict)), "el nombre de una zona o {de: id, lado: abajo, espacio: 0.3}"),
        "cualquiera": (True, ""),
    }
    correcto, esperado = reglas[p.tipo]
    return None if correcto else f"'{p.nombre}' debe ser {esperado}, no {valor!r}"


def _indice_de_ancla(ancla: Ancla, fichas: list[str]) -> tuple[int, float] | str:
    """Posición (índice de ficha, mas) del ancla en la narración, o un mensaje de error."""
    if ancla.tipo == "inicio":
        return -1, ancla.mas
    if ancla.tipo == "fin":
        return len(fichas), ancla.mas
    objetivo = normalizar_texto(ancla.texto).split()
    posiciones = [i for i in range(len(fichas) - len(objetivo) + 1) if fichas[i:i + len(objetivo)] == objetivo]
    if len(posiciones) >= ancla.ocurrencia:
        return posiciones[ancla.ocurrencia - 1], ancla.mas
    if posiciones:
        veces = "vez" if len(posiciones) == 1 else "veces"
        return (f"'{ancla.texto}' aparece {len(posiciones)} {veces} en la narración; pediste la ocurrencia "
                f"{ancla.ocurrencia}")
    candidatos = fichas + [" ".join(fichas[i:i + len(objetivo)]) for i in range(len(fichas))] if len(objetivo) > 1 else fichas
    return (f"el ancla '{ancla.texto}' no aparece en la narración.{sugerencia(normalizar_texto(ancla.texto), candidatos)} "
            f"Palabras disponibles: {' '.join(fichas)}")


def _frases(texto: str) -> list[str]:
    return [f.strip() for f in _FIN_DE_FRASE.split(texto) if normalizar_texto(f)]


class _Validador:
    def __init__(self, guion: Guion) -> None:
        self.guion = guion
        self.errores: list[Hallazgo] = []
        self.avisos: list[Hallazgo] = []
        self.estado = EstadoValidacion(self, guion.dir_base)
        self.zonas: dict = dict(ZONAS_BASE)
        # (segmento, grupo) -> ¿había algo visible (para el relleno ambiental) antes del grupo? y al final del segmento
        self.visible_antes: dict[tuple[int, int], bool] = {}
        self.visible_fin: dict[int, bool] = {}
        self.pasos_personalizados = 0
        self.segmentos_con_personalizado = 0

    def aviso(self, codigo: str, mensaje: str, ubicacion: str = "", linea: int | None = None) -> None:
        self.avisos.append(Hallazgo(codigo, mensaje, ubicacion, linea))

    def error(self, codigo: str, mensaje: str, ubicacion: str = "", linea: int | None = None) -> None:
        self.errores.append(Hallazgo(codigo, mensaje, ubicacion, linea))

    # --- parámetros ----------------------------------------------------------------------------------

    def validar_params(self, definicion: registro.Definicion, params: dict, estado: EstadoValidacion) -> bool:
        errores_antes = len(self.errores)
        nombres = definicion.nombres_params
        if not definicion.admite_extras:
            for clave in params:
                if clave not in nombres:
                    estado.error("E1", f"'{definicion.nombre}' no tiene el parámetro '{clave}'.{sugerencia(clave, nombres)} "
                                       f"Parámetros: {', '.join(nombres) or '(ninguno)'}")
        for p in definicion.params:
            valor = params.get(p.nombre)
            if valor is None:
                if p.requerido:
                    estado.error("E3", f"falta '{p.nombre}' en {definicion.nombre}"
                                       f"{': ' + p.descripcion if p.descripcion else ''}")
                continue
            problema = _tipo_valido(p, valor)
            if problema:
                estado.error("E3", problema)
                continue
            if p.opciones and valor not in p.opciones:
                estado.error("E3", f"'{p.nombre}: {valor}' no es válido.{sugerencia(valor, p.opciones)} "
                                   f"Opciones: {', '.join(p.opciones)}")
            if p.tipo == "color" and valor not in COLORES:
                estado.error("E6", f"el color '{valor}' no existe.{sugerencia(valor, COLORES)} Colores: {', '.join(COLORES)}")
            if p.tipo == "zona":
                self._validar_zona(valor, estado)
            if p.nombre == "tamano" and isinstance(valor, (int, float)) and valor < FUENTE_MINIMA:
                estado.error("E8", f"tamano {valor} es menor que FUENTE_MINIMA ({FUENTE_MINIMA}): ilegible en un móvil")
        return len(self.errores) == errores_antes

    def _validar_zona(self, valor: Any, estado: EstadoValidacion) -> None:
        if isinstance(valor, str):
            if valor not in self.zonas:
                estado.error("E5", f"la zona '{valor}' no existe.{sugerencia(valor, self.zonas)} Zonas: {', '.join(self.zonas)}")
            return
        desconocidas = set(valor) - {"de", "lado", "espacio"}
        if desconocidas or not isinstance(valor.get("de"), str):
            estado.error("E3", "zona relativa: usa {de: id_de_otro_objeto, lado: abajo|arriba|izq|der, espacio: 0.3}")
            return
        lado = valor.get("lado", "abajo")
        if lado not in LADOS:
            estado.error("E3", f"lado '{lado}' inválido.{sugerencia(lado, LADOS)} Lados: {', '.join(LADOS)}")
        espacio = valor.get("espacio", 0.25)
        if isinstance(espacio, bool) or not isinstance(espacio, (int, float)) or espacio < 0:
            estado.error("E3", "espacio de la zona relativa: un número ≥ 0")

    def aplicar_ciclo(self, definicion: registro.Definicion, params: dict, estado: EstadoValidacion) -> None:
        completos = registro.resolver_params(definicion, params)
        if definicion.ciclo is not None:
            definicion.ciclo(completos, estado)
            return
        for p in definicion.params:
            valor = params.get(p.nombre)
            if valor is None:
                continue
            if p.tipo == "objeto":
                for ref in valor if isinstance(valor, list) else [valor]:
                    estado.usar(ref)
            elif p.tipo == "zona" and isinstance(valor, dict) and isinstance(valor.get("de"), str):
                estado.usar(valor["de"], permitir_reservado=True)

    # --- bloques -----------------------------------------------------------------------------------

    def _validar_zonas(self) -> None:
        for nombre, d in self.guion.zonas.items():
            padre = self.zonas.get(d.de)
            if padre is None:
                self.errores.append(error_zona_padre(d, self.zonas))
                continue
            self.zonas[nombre] = derivar_zona(padre, d)

    def _validar_subtitulos(self) -> None:
        for palabra, color in self.guion.subtitulos.items():
            if color not in COLORES:
                self.error("E6", f"subtitulos.{palabra}: el color '{color}' no existe.{sugerencia(color, COLORES)} "
                                 f"Colores: {', '.join(COLORES)}", "subtitulos", self.guion.lineas.get(("subtitulos",)))

    def _validar_escenario(self) -> None:
        estado = self.estado
        for obj in self.guion.escenario:
            estado.ubicar(obj.ubicacion, obj.linea)
            estado.validar_objeto(obj.tipo, obj.params, obj.id)
            estado.crear(obj.id, obj.tipo, oculto=obj.oculto)
        ids_escenario = {o.id for o in self.guion.escenario}
        for disp in self.guion.disposiciones:
            estado.ubicar(f"escenario, disposición {disp.indice}", disp.linea)
            for id in disp.ids:
                if id not in ids_escenario:
                    estado.error("E4", f"'{id}' no es un objeto del escenario.{sugerencia(id, ids_escenario)} "
                                       f"Objetos del escenario: {', '.join(ids_escenario) or '(ninguno)'}")
            if disp.zona is not None and disp.zona not in self.zonas:
                estado.error("E5", f"la zona '{disp.zona}' no existe.{sugerencia(disp.zona, self.zonas)}")

    def _validar_anclas(self, segmento: Segmento) -> None:
        fichas = normalizar_texto(segmento.narracion).split()
        previa: tuple[int, float] | None = None
        for paso in segmento.pasos:
            posicion = _indice_de_ancla(paso.en, fichas)
            if isinstance(posicion, str):
                self.error("E7", posicion, paso.ubicacion, paso.linea)
                continue
            if previa is not None and posicion < previa:
                self.error("E7", f"el ancla {paso.en.describir()} retrocede respecto al paso anterior: los pasos van en "
                                 "el orden de la narración (reordénalos o ancla en una palabra posterior)",
                           paso.ubicacion, paso.linea)
            previa = posicion
            if isinstance(paso.dur, Ancla):
                hasta = _indice_de_ancla(paso.dur, fichas)
                if isinstance(hasta, str):
                    self.error("E7", f"dur hasta: {hasta}", paso.ubicacion, paso.linea)
                elif hasta <= posicion:
                    self.error("E7", f"dur hasta {paso.dur.describir()} debe ser posterior al ancla del paso "
                                     f"({paso.en.describir()})", paso.ubicacion, paso.linea)

    def _validar_paso(self, paso: Paso) -> None:
        estado = self.estado
        estado.ubicar(paso.ubicacion, paso.linea)
        definicion = registro.obtener(paso.hacer, "accion")
        if definicion is None:
            if registro.obtener(paso.hacer, "objeto") is not None:
                estado.error("E2", f"'{paso.hacer}' es un tipo de objeto, no un verbo: usa "
                                   f"{{hacer: mostrar, tipo: {paso.hacer}, id: ...}}")
            else:
                verbos = registro.nombres("accion")
                estado.error("E2", f"el verbo '{paso.hacer}' no existe.{sugerencia(paso.hacer, verbos)} "
                                   f"Verbos: {', '.join(verbos)}")
            return
        if paso.hacer == "personalizado":
            self.pasos_personalizados += 1
        self.validar_params(definicion, paso.params, estado)
        self.aplicar_ciclo(definicion, paso.params, estado)

    def _validar_segmento(self, segmento: Segmento) -> None:
        estado = self.estado
        estado.ubicar(segmento.ubicacion, segmento.linea)
        if segmento.ambiente is not None and estado.estado_de(segmento.ambiente) is None:
            estado.error("E4", f"ambiente '{segmento.ambiente}' no existe al empezar el segmento."
                               f"{sugerencia(segmento.ambiente, estado.ids)}")
        for frase in _frases(segmento.narracion):
            n = len(normalizar_texto(frase).split())
            if n > PALABRAS_POR_FRASE:
                self.aviso("A2", f"frase de {n} palabras (> {PALABRAS_POR_FRASE}): «{frase[:60]}»; pártela en dos",
                           segmento.ubicacion, segmento.linea)
        if not segmento.pasos:
            self.aviso("A3", "segmento sin pasos: la pantalla no cambia mientras suena la voz", segmento.ubicacion,
                       segmento.linea)
        self._validar_anclas(segmento)
        if any(p.hacer == "personalizado" for p in segmento.pasos):
            self.segmentos_con_personalizado += 1
        for g, grupo in enumerate(agrupar_pasos(segmento.pasos)):
            self.visible_antes[(segmento.indice, g)] = estado.hay_visible()
            for paso in grupo:
                self._validar_paso(paso)
        self.visible_fin[segmento.indice] = estado.hay_visible()

    def _avisos_finales(self) -> None:
        estado = self.estado
        for id, situacion in estado.ids.items():
            donde, linea = estado.creado_en.get(id, ("", None))
            if situacion == "reservado":
                self.aviso("A4", f"'{id}' se reservó en el escenario y nunca se muestra: quítalo o muéstralo", donde, linea)
            elif estado.usos.get(id, 0) == 0:
                self.aviso("A4", f"'{id}' se crea y nunca se usa ni se quita: resáltalo, úsalo o quítalo al final",
                           donde, linea)
        for id, (tipo, donde, linea) in estado.efectos.items():
            self.aviso("A8", f"el efecto {tipo} '{id}' nunca se detiene: añade {{hacer: detener, objeto: {id}}}", donde, linea)
        palabras = sum(len(normalizar_texto(s.narracion).split()) for s in self.guion.segmentos)
        if not PALABRAS_MIN <= palabras <= PALABRAS_MAX:
            self.aviso("A1", f"la narración suma {palabras} palabras (objetivo {PALABRAS_MIN}-{PALABRAS_MAX} para 60-75 s)")

    def ejecutar(self) -> None:
        self._validar_zonas()
        self._validar_subtitulos()
        self._validar_escenario()
        for segmento in self.guion.segmentos:
            self._validar_segmento(segmento)
        self._avisos_finales()

    def resumen(self) -> dict:
        palabras = sum(len(normalizar_texto(s.narracion).split()) for s in self.guion.segmentos)
        n = len(self.guion.segmentos)
        return {
            "segmentos": n,
            "pasos": sum(len(s.pasos) for s in self.guion.segmentos),
            "palabras": palabras,
            "duracion_estimada_s": round(palabras / PALABRAS_POR_SEGUNDO_ESTIMADAS, 1),
            "pasos_personalizados": self.pasos_personalizados,
            "porcentaje_segmentos_personalizados": round(100 * self.segmentos_con_personalizado / n, 1) if n else 0.0,
        }

    # --- con voz --------------------------------------------------------------------------------------

    def validar_con_voz(self, motor: Any) -> dict:
        """Línea de tiempo real (misma semántica que el runtime); A5/A6/A7 y E7 contra las palabras reales."""
        t_segmento = 0.0
        cambios: list[tuple[float, float]] = []
        segmentos_info: list[tuple[int, float, float]] = []
        sintetico = False
        for segmento in self.guion.segmentos:
            narrado = motor.sintetizar(segmento.narracion)
            sintetico = sintetico or bool(getattr(narrado, "sintetico", False))
            fin_seg = fin_de_voz(narrado) + segmento.pausa
            if not self._anclas_reales(segmento, narrado):
                segmentos_info.append((segmento.indice, t_segmento, t_segmento + fin_seg))
                t_segmento += fin_seg
                continue
            ahora = 0.0
            relleno = segmento.relleno
            ambiente = segmento.ambiente is not None
            for g, grupo in enumerate(agrupar_pasos(segmento.pasos)):
                t_ancla = tiempo_de_ancla(grupo[0].en, narrado)
                hueco = t_ancla - ahora
                if hueco > 0:
                    if relleno and hueco > UMBRAL_RELLENO and (ambiente or self.visible_antes.get((segmento.indice, g))):
                        cambios.append((t_segmento + ahora, t_segmento + t_ancla))
                    ahora = t_ancla
                elif hueco < -TOLERANCIA_TARDE:
                    p = grupo[0]
                    self.aviso("A7", f"el ancla {p.en.describir()} suena a {t_ancla:.2f} s pero lo anterior termina a "
                                     f"{ahora:.2f} s: el paso arranca {-hueco:.2f} s tarde (acorta el dur anterior o "
                                     "ancla en una palabra posterior)", p.ubicacion, p.linea)
                largo = 0.0
                for paso in grupo:
                    if not anima_por_defecto(paso):
                        continue
                    dur, recorte = resolver_dur(duracion_base(paso), ahora + paso.retraso, narrado)
                    if recorte:
                        self.aviso("A7", recorte, paso.ubicacion, paso.linea)
                    largo = max(largo, paso.retraso + dur)
                if largo > 0:
                    cambios.append((t_segmento + ahora, t_segmento + ahora + largo))
                ahora += largo
            if ahora > fin_seg + TOLERANCIA_TARDE and segmento.pasos:
                ultimo = segmento.pasos[-1]
                self.aviso("A7", f"las animaciones terminan {ahora - fin_seg:.2f} s después de la voz (+pausa): el "
                                 "segmento se alarga; acorta dur o usa dur: resto", ultimo.ubicacion, ultimo.linea)
            elif relleno and fin_seg - ahora > UMBRAL_RELLENO and (ambiente or self.visible_fin.get(segmento.indice)):
                cambios.append((t_segmento + ahora, t_segmento + fin_seg))
            duracion = max(ahora, fin_seg)
            segmentos_info.append((segmento.indice, t_segmento, t_segmento + duracion))
            t_segmento += duracion
        quietos = self._tramos_quietos(cambios, t_segmento, segmentos_info)
        if not DURACION_MIN <= t_segmento <= DURACION_MAX:
            self.aviso("A6", f"duración total {t_segmento:.1f} s (objetivo {DURACION_MIN:.0f}-{DURACION_MAX:.0f} s)")
        if sintetico:
            self.aviso("A9", "voz sintética (sin red ni caché): los tiempos son aproximados; valida de nuevo con red")
        return {"duracion_s": round(t_segmento, 2), "tramos_quietos": quietos, "voz_sintetica": sintetico}

    def _anclas_reales(self, segmento: Segmento, narrado: Any) -> bool:
        ok = True
        reales = " ".join(p.texto for p in narrado.palabras)
        for paso in segmento.pasos:
            for ancla in [paso.en] + ([paso.dur] if isinstance(paso.dur, Ancla) else []):
                if ancla.tipo != "palabra":
                    continue
                try:
                    narrado.tiempo_de(ancla.texto, ancla.ocurrencia)
                except KeyError:
                    ok = False
                    self.error("E7", f"la voz real no pronuncia {ancla.describir()} como palabra (edge-tts puede leer "
                                     f"cifras o siglas distinto). Palabras reales: {reales}", paso.ubicacion, paso.linea)
        return ok

    def _tramos_quietos(self, cambios: list[tuple[float, float]], total: float,
                        segmentos_info: list[tuple[int, float, float]]) -> list[dict]:
        intervalos = sorted(cambios)
        quietos: list[dict] = []
        cursor = 0.0
        for a, b in intervalos + [(total, total)]:
            if a - cursor > TRAMO_QUIETO_MAX:
                seg = next((s for s, ini, fin in segmentos_info if ini <= cursor < fin), None)
                quietos.append({"desde": round(cursor, 2), "hasta": round(a, 2), "segmento": seg})
                self.aviso("A5", f"{a - cursor:.1f} s sin cambio visual ({cursor:.1f}-{a:.1f} s): añade un paso o deja "
                                 "relleno: true con algo visible (el runtime respira el último objeto en foco)",
                           f"segmento {seg}" if seg else "")
            cursor = max(cursor, b)
        return quietos


def validar(ruta: str | Path | Guion, con_voz: bool = False, *, motor: Any = None) -> ReporteValidacion:
    """Valida el guion ``ruta`` (archivo YAML o :class:`Guion` ya cargado). Nunca lanza por un guion inválido."""
    import toolkit.guion.catalogo  # noqa: F401  (registra las piezas)

    try:
        guion = ruta if isinstance(ruta, Guion) else cargar(ruta)
    except ErrorGuion as error:
        return ReporteValidacion(errores=error.hallazgos, resumen={"carga": "fallida"})
    resultados, errores_calc = evaluar_calculos(guion)
    guion, errores_ref = sustituir_referencias(guion, resultados)
    validador = _Validador(guion)
    validador.errores.extend(errores_calc + errores_ref)
    validador.ejecutar()
    resumen = validador.resumen()
    if con_voz:
        if validador.errores:
            resumen["voz"] = "omitida: corrige primero los errores"
        else:
            if motor is None:
                from toolkit.narracion import VELOCIDAD_POR_DEFECTO, VOZ_POR_DEFECTO, MotorNarracion

                motor = MotorNarracion(voz=guion.meta.voz or VOZ_POR_DEFECTO,
                                       velocidad=guion.meta.velocidad or VELOCIDAD_POR_DEFECTO)
            resumen.update(validador.validar_con_voz(motor))
    return ReporteValidacion(_por_linea(validador.errores), _por_linea(validador.avisos), resumen, guion)


def _por_linea(hallazgos: list[Hallazgo]) -> list[Hallazgo]:
    """Orden de lectura: por línea del YAML (los hallazgos globales, sin línea, al final)."""
    return sorted(hallazgos, key=lambda h: (h.linea is None, h.linea or 0))


def guion_de_ejemplo(nombre: str, previos: list[dict] | None = None) -> dict:
    """Guion mínimo (dict) que ejercita el ``ejemplo`` de la pieza ``nombre`` (para tests del catálogo).

    Antes del ejemplo crea con ``previos`` (o, por defecto, un ``texto`` por cada id que el ejemplo referencia en
    parámetros de tipo ``objeto``/``lista`` de ids) y su ancla se cambia a ``inicio``.
    """
    import toolkit.guion.catalogo  # noqa: F401

    definicion = registro.CATALOGO[nombre]
    ejemplo = dict(definicion.ejemplo)
    ejemplo["en"] = "inicio"
    if previos is None and getattr(definicion.funcion, "previos_ejemplo", None):
        # La pieza declara qué objetos necesita su ejemplo (p. ej. siguiente_paso: una derivación, no un texto).
        previos = [dict(p) for p in definicion.funcion.previos_ejemplo]
    if previos is None:
        previos = []
        definicion_verbo = registro.obtener(ejemplo["hacer"], "accion")
        referenciados: list[str] = []
        fuentes = [definicion_verbo]
        tipo = ejemplo.get("tipo")
        if ejemplo["hacer"] == "mostrar" and isinstance(tipo, str):
            fuentes.append(registro.obtener(tipo, "objeto"))
        for d in fuentes:
            for p in d.params if d else ():
                valor = ejemplo.get(p.nombre)
                if p.tipo == "zona" and isinstance(valor, dict) and isinstance(valor.get("de"), str):
                    referenciados.append(separar_ref(valor["de"])[0])
                elif p.tipo in ("objeto", "lista") and valor is not None:
                    for ref in valor if isinstance(valor, list) else [valor]:
                        if isinstance(ref, str) and (p.tipo == "objeto" or p.nombre in ("objeto", "de")):
                            referenciados.append(separar_ref(ref)[0])
        for i, ref in enumerate(dict.fromkeys(referenciados)):
            previos.append({"en": "inicio", "hacer": "mostrar", "id": ref, "tipo": "texto", "texto": f"Objeto {i + 1}",
                            "zona": "principal"})
        if ejemplo["hacer"] == "detener":
            previos.append({"en": "inicio", "hacer": "camara", "id": ejemplo["objeto"], "modo": "zoom", "factor": 1.1})
    return {
        "version": 1,
        "meta": {"slug": f"ejemplo_{nombre}", "titulo": f"Ejemplo {nombre}", "clase": f"Ejemplo{nombre.title()}"},
        "segmentos": [{"narracion": "Un ejemplo breve de esta pieza del catálogo.", "pasos": previos + [ejemplo]}],
    }


__all__ = ["ReporteValidacion", "EstadoValidacion", "Hallazgo", "validar", "guion_de_ejemplo"]
