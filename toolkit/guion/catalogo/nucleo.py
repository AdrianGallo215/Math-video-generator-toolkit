"""Verbos del núcleo: ``mostrar``, ``quitar``, ``transformar``, ``resaltar``, ``pulsar``, ``detener``,
``personalizado`` y el tipo ``grupo``.

Estos verbos definen el ciclo de vida de los ids (crear, revelar, consumir, quitar); sus ganchos ``ciclo`` le
explican a la validación estática qué hace cada paso (``toolkit.guion.validar.EstadoValidacion``).
"""

from __future__ import annotations

import ast
from functools import partial

from manim import (
    AnimationGroup,
    Indicate,
    LaggedStart,
    Mobject,
    ReplacementTransform,
    Succession,
    Text,
    TransformFromCopy,
    TransformMatchingShapes,
    VGroup,
)

from toolkit.animaciones import pulso, resaltar as animar_resaltar
from toolkit.estilos import TIEMPO_ENFASIS, TIEMPO_TRANSFORMAR, TIEMPO_TRANSICION
from toolkit.guion.catalogo.modificadores import (
    animacion_entrada,
    animacion_salida,
    ciclo_marcas,
    con_marcas,
    escalonar,
    miembros_de_ola,
)
from toolkit.guion.contexto import (
    ATRIBUTO_MIEMBROS,
    ZONA_CONTENIDO,
    ContextoGuion,
    _ajustar_dentro,
    agrupar,
    separar_ref,
)
from toolkit.guion.esquema import sugerencia
from toolkit.guion.registro import Param, accion, objeto

ESCALA_PULSO = 1.06
ESCALA_INDICAR = 1.15
MODOS_RESALTAR = ("indicar", "rodear", "destello", "subrayar", "ola")
ESCALONADO_OLA = 0.2  # lag_ratio por defecto de la ola


def _como_lista(valor) -> list:
    return list(valor) if isinstance(valor, (list, tuple)) else [valor]


# --- grupo --------------------------------------------------------------------------------------------


def _ciclo_grupo(params: dict, estado) -> None:
    miembros = params.get("de")
    if not isinstance(miembros, list) or len(miembros) < 2:
        estado.error("E3", "'de' debe ser una lista de ≥ 2 ids")
        return
    for m in miembros:
        if not isinstance(m, str) or "." in m:
            estado.error("E3", f"miembro {m!r}: los miembros de un grupo son ids completos (sin '.parte')")
            continue
        estado.usar(m, permitir_reservado=True)
    estado.agrupar(estado.creando, [m for m in miembros if isinstance(m, str)])


@objeto(
    "grupo",
    "Agrupa objetos ya creados bajo un id (cada miembro sigue siendo 'id' y también 'grupo.id').",
    params=[Param("de", "lista", requerido=True, descripcion="Ids de los miembros (≥ 2).")],
    ejemplo={"en": "inicio", "hacer": "mostrar", "id": "todo", "tipo": "grupo", "de": ["a", "b"]},
    duracion=1.0,
    ciclo=_ciclo_grupo,
)
def crear_grupo(ctx: ContextoGuion, de) -> Mobject:
    return agrupar([ctx.obtener(m) for m in de], list(de))


# --- mostrar ------------------------------------------------------------------------------------------


def _ciclo_mostrar(params: dict, estado) -> None:
    id = params.get("id")
    tipo = params.get("tipo")
    propios = {"id", "tipo", "entrada", "escalonado", "rate", "caja", "tachar"}
    extras = {k: v for k, v in params.items() if k not in propios}
    if not isinstance(id, str):
        return
    if tipo is None:
        if extras:
            estado.error("E1", f"'{id}' se revela del escenario: quita {', '.join(extras)} (sus parámetros van en "
                               "escenario.objetos) o pon 'tipo' para crear uno nuevo")
        situacion = estado.estado_de(id)
        if situacion in ("reservado", "parcial"):
            estado.revelar(id)
            ciclo_marcas(params, estado, id)
        elif situacion == "vivo":
            estado.error("E4", f"'{id}' ya está visible; para destacarlo usa resaltar/pulsar")
        else:
            estado.error("E3", f"falta 'tipo' para crear '{id}' (o resérvalo antes en escenario.objetos)")
        return
    if not isinstance(tipo, str):
        estado.error("E3", "'tipo' debe ser el nombre de un tipo de objeto")
        return
    if estado.estado_de(id) == "reservado":
        estado.error("E4", f"'{id}' está reservado en el escenario: para mostrarlo quita 'tipo' y sus parámetros")
        return
    estado.validar_objeto(tipo, extras, id)
    if estado.crear(id, tipo):
        ciclo_marcas(params, estado, id)


@accion(
    "mostrar",
    "Crea un objeto del catálogo (tipo + sus parámetros) y lo anima entrando; sin tipo, revela uno del escenario.",
    params=[
        Param("id", "texto", requerido=True, descripcion="Id nuevo (o el de un objeto reservado en el escenario)."),
        Param("tipo", "texto", descripcion="Tipo de objeto (texto, forma, grupo...). Omitir para revelar un reservado."),
    ],
    ejemplo={"en": "inicio", "hacer": "mostrar", "id": "saludo", "tipo": "texto", "texto": "Hola"},
    duracion=1.0,
    modificadores=("entrada", "escalonado", "rate", "caja", "tachar"),
    ciclo=_ciclo_mostrar,
    admite_extras=True,
)
def mostrar(ctx: ContextoGuion, id, tipo=None, entrada="auto", escalonado=0.0, caja=False, tachar=False, **params):
    mob, animacion = _mostrar(ctx, id, tipo, entrada, escalonado, **params)
    return con_marcas(ctx, animacion, id, None, mob, caja, tachar)


def _mostrar(ctx: ContextoGuion, id, tipo, entrada, escalonado, **params):
    """(mob, animación de entrada o None) de ``mostrar``."""
    if tipo is None:
        mob = ctx.obtener(id)
    else:
        mob = ctx.crear(tipo, **params)
        ctx.registrar(id, mob)
    for revelado in [id, *(getattr(mob, ATRIBUTO_MIEMBROS, None) or [])]:
        ctx.revelar(revelado)
    ctx.marcar_foco(id)
    if ctx.escena is None:
        return mob, animacion_entrada(mob, entrada, escalonado)
    presentes = set(ctx.escena.get_mobject_family_members())
    if mob in presentes:
        return mob, None
    if not any(m in presentes for m in mob.get_family()):
        return mob, animacion_entrada(mob, entrada, escalonado)
    # Parte del objeto ya está en escena (miembros visibles, o una parte que llegó por transformar).
    faltan = [s for s in mob.submobjects if not any(f in presentes for f in s.get_family())]
    ctx.despues(partial(ctx.consolidar, mob))
    if not faltan:
        return mob, None
    return mob, animacion_entrada(VGroup(*faltan) if len(faltan) > 1 else faltan[0], entrada, escalonado)


# --- quitar -------------------------------------------------------------------------------------------


def _ciclo_quitar(params: dict, estado) -> None:
    for ref in _como_lista(params.get("objeto")):
        if not isinstance(ref, str):
            continue
        id, parte = separar_ref(ref)
        if parte is not None:
            estado.error("E3", f"quitar actúa sobre objetos completos: usa '{id}', no '{ref}'")
            continue
        if estado.estado_de(id) == "reservado":
            estado.error("E4", f"'{id}' nunca se mostró (está reservado en el escenario): no hay nada que quitar")
            continue
        if estado.usar(id):
            estado.consumir(id)


@accion(
    "quitar",
    "Saca de escena uno o varios objetos (su id queda libre para reutilizarse).",
    params=[Param("objeto", "objeto", requerido=True, descripcion="Id o lista de ids.")],
    ejemplo={"en": "fin", "hacer": "quitar", "objeto": ["a", "b"], "salida": "arriba"},
    duracion=TIEMPO_TRANSICION,
    modificadores=("salida", "escalonado", "rate"),
    ciclo=_ciclo_quitar,
)
def quitar(ctx: ContextoGuion, objeto, salida="desvanecer", escalonado=0.0):
    refs = _como_lista(objeto)
    mobs = [ctx.obtener(r) for r in refs]
    for r in refs:
        ctx.despues(partial(ctx.quitar, r))
    return animacion_salida(mobs, salida, escalonado)


# --- transformar --------------------------------------------------------------------------------------


def _ciclo_transformar(params: dict, estado) -> None:
    origen = params.get("objeto")
    if isinstance(origen, list):
        estado.error("E3", "transformar actúa sobre un solo objeto de origen")
        return
    if not isinstance(origen, str):
        return
    id_origen, parte_origen = separar_ref(origen)
    copia = bool(params.get("copia", False))
    if not estado.usar(origen):
        return
    if parte_origen is not None and not copia:
        estado.error("E3", f"transformar una parte ('{origen}') requiere copia: true (el objeto '{id_origen}' sigue)")
        return
    destino = params.get("a")
    if isinstance(destino, dict):
        spec = dict(destino)
        nuevo = spec.pop("id", None)
        tipo = spec.pop("tipo", None)
        if not isinstance(tipo, str):
            estado.error("E3", "'a' debe llevar 'tipo' (y sus parámetros), p. ej. {id: b, tipo: texto, texto: ...}")
            return
        if nuevo is None and copia:
            estado.error("E4", "con copia: true el destino necesita un 'id' nuevo en 'a' (el origen conserva el suyo)")
            return
        estado.validar_objeto(tipo, spec, nuevo or id_origen)
        if not copia:
            estado.consumir(id_origen)
        estado.crear(nuevo or id_origen, tipo)
    elif isinstance(destino, str):
        id_destino, parte_destino = separar_ref(destino)
        if id_destino == id_origen:
            estado.error("E4", "el destino no puede ser el mismo objeto de origen")
            return
        if not estado.usar(destino, permitir_reservado=True):
            return
        if not copia:
            estado.consumir(id_origen)
        if estado.estado_de(id_destino) == "reservado":
            estado.revelar(id_destino, parcial=parte_destino is not None)
    else:
        estado.error("E3", "'a' es un objeto nuevo ({id, tipo, ...}) o la referencia de uno existente ('id' o 'id.parte')")


def _es_ecuacion(mob: Mobject) -> bool:
    return hasattr(mob, "tokens") and hasattr(mob, "parte")


@accion(
    "transformar",
    "Convierte un objeto en otro (nuevo o existente, o una parte de otro): el origen se consume y el destino queda "
    "con su id ('a' sin id hereda el del origen). Ecuaciones: tokens emparejados; textos: letras que viajan.",
    params=[
        Param("objeto", "objeto", requerido=True, descripcion="Id (o 'id.parte' con copia: true) de origen."),
        Param("a", "cualquiera", requerido=True,
              descripcion="Destino: {id?, tipo, ...parámetros} (nuevo; sin zona queda donde estaba el origen) o 'id'/'id.parte'."),
        Param("mapa", "mapa", defecto={}, descripcion="Emparejamiento de tokens origen -> destino (ecuaciones)."),
        Param("copia", "booleano", defecto=False, descripcion="true: el origen se queda y una copia viaja al destino."),
        Param("arco", "numero", defecto=0.0, descripcion="Curvatura del recorrido en radianes (1.57 = cuarto de vuelta)."),
    ],
    ejemplo={"en": "inicio", "hacer": "transformar", "objeto": "a", "a": {"tipo": "texto", "texto": "x = 4"}},
    duracion=TIEMPO_TRANSFORMAR,
    modificadores=("rate",),
    ciclo=_ciclo_transformar,
)
def transformar(ctx: ContextoGuion, objeto, a, mapa=None, copia=False, arco=0.0):
    id_origen, _ = separar_ref(objeto)
    origen = ctx.obtener(objeto)
    if isinstance(a, dict):
        spec = dict(a)
        id_destino = spec.pop("id", None) or id_origen
        tipo = spec.pop("tipo")
        destino = ctx.crear(tipo, **spec)
        if "zona" not in spec and not getattr(destino, "fijo_en_zona", False):
            destino.move_to(origen.get_center())
            _ajustar_dentro(destino, ZONA_CONTENIDO)
        if not copia:
            ctx.olvidar(id_origen)
        ctx.registrar(id_destino, destino)
    else:
        id_destino = separar_ref(a)[0]
        destino = ctx.obtener(a)
        if not copia:
            ctx.olvidar(id_origen)
        ctx.revelar(id_destino)
    if not copia:
        ctx.despues(partial(ctx.retirar, origen))
    ctx.marcar_foco(id_destino)
    from toolkit.guion.catalogo.algebra import transicion_algebraica  # ecuaciones/derivaciones: tokens que vuelan

    algebraica = transicion_algebraica(ctx, origen, destino, mapa=mapa, copia=copia, arco=arco)
    if algebraica is not None:
        return algebraica
    if copia:
        return TransformFromCopy(origen, destino, path_arc=arco)
    if isinstance(origen, Text) and isinstance(destino, Text):
        return TransformMatchingShapes(origen, destino, path_arc=arco)
    return ReplacementTransform(origen, destino, path_arc=arco)


# --- resaltar / pulsar -------------------------------------------------------------------------------


def _ciclo_resaltar(params: dict, estado) -> None:
    refs = _como_lista(params.get("objeto"))
    for ref in refs:
        estado.usar(ref)
    if not (params.get("caja") or params.get("tachar")):
        return
    if len(refs) != 1 or not isinstance(refs[0], str):
        estado.error("E3", "caja/tachar marcan un solo objeto: pon un id (o 'id.parte'), no una lista")
        return
    base, parte_ref = separar_ref(refs[0])
    ciclo_marcas(params, estado, base, params.get("parte") or parte_ref)


@accion(
    "resaltar",
    "Énfasis sobrio sobre lo que la voz nombra: indicar, rodear, destello, subrayar u ola (indicar escalonado sobre "
    "las partes). Con caja: true deja una caja de resultado (id '<obj>_caja'); con tachar: true, una línea ('<obj>_tachado').",
    params=[
        Param("objeto", "objeto", requerido=True, descripcion="Id, 'id.parte' o lista de ids."),
        Param("parte", "texto", descripcion="Sub-elemento (token de ecuación, celda, miembro de grupo...)."),
        Param("modo", "texto", defecto="indicar", opciones=MODOS_RESALTAR,
              descripcion="Tipo de énfasis (ola: una respiración que recorre las partes de izquierda a derecha)."),
        Param("color", "color", defecto="amarillo", descripcion="Color del énfasis."),
    ],
    ejemplo={"en": "inicio", "hacer": "resaltar", "objeto": "a", "modo": "rodear"},
    duracion=TIEMPO_ENFASIS,
    modificadores=("escala", "escalonado", "caja", "tachar"),
    ciclo=_ciclo_resaltar,
)
def resaltar(ctx: ContextoGuion, objeto, parte=None, modo="indicar", color="amarillo", escala=None, escalonado=0.0,
             caja=False, tachar=False):
    hex_color = ctx.color(color)
    mobs = [ctx.parte(m, parte) for m in ctx.obtener_varios(objeto)]
    for ref in _como_lista(objeto):
        ctx.marcar_foco(separar_ref(ref)[0])
    anims = []
    for m in mobs:
        if modo == "indicar":
            anims.append(Indicate(m, scale_factor=escala or ESCALA_INDICAR, color=hex_color))
        elif modo == "ola":
            olas = [Indicate(t, scale_factor=escala or ESCALA_INDICAR, color=hex_color) for t in miembros_de_ola(ctx, m)]
            anims.append(LaggedStart(*olas, lag_ratio=escalonado or ESCALONADO_OLA))
        else:
            anims.append(animar_resaltar(m, color=hex_color, modo=modo))
    resultado = escalonar(anims, 0.0 if modo == "ola" else escalonado)
    if caja or tachar:
        base, parte_ref = separar_ref(_como_lista(objeto)[0])
        marcado = con_marcas(ctx, AnimationGroup(*resultado) if isinstance(resultado, list) else resultado,
                             base, parte or parte_ref, mobs[0], caja, tachar)
        return marcado
    return resultado


@accion(
    "pulsar",
    "Respiración sutil (escala y vuelve) de uno o varios objetos; el runtime ya la usa para rellenar huecos.",
    params=[
        Param("objeto", "objeto", requerido=True, descripcion="Id, 'id.parte' o lista de ids."),
        Param("parte", "texto", descripcion="Sub-elemento a pulsar."),
        Param("veces", "entero", defecto=1, descripcion="Nº de respiraciones dentro de dur."),
    ],
    ejemplo={"en": "inicio", "hacer": "pulsar", "objeto": "a", "dur": "resto"},
    duracion=0.8,
    modificadores=("escala", "escalonado"),
)
def pulsar(ctx: ContextoGuion, objeto, parte=None, veces=1, escala=None, escalonado=0.0):
    mobs = [ctx.parte(m, parte) for m in ctx.obtener_varios(objeto)]
    veces = max(1, int(veces))
    anims = []
    for m in mobs:
        latidos = [pulso(m, escala=escala or ESCALA_PULSO, run_time=1.0) for _ in range(veces)]
        anims.append(latidos[0] if veces == 1 else Succession(*latidos))
    return escalonar(anims, escalonado)


# --- detener (efectos persistentes) ------------------------------------------------------------------------


def _ciclo_detener(params: dict, estado) -> None:
    if isinstance(params.get("objeto"), str):
        estado.detener_efecto(params["objeto"])


@accion(
    "detener",
    "Termina un efecto persistente (cámara, variable...) iniciado antes, aunque sea en otro segmento.",
    params=[Param("objeto", "texto", requerido=True, descripcion="Id del efecto (el 'id' con que se inició).")],
    ejemplo={"en": "inicio", "hacer": "detener", "objeto": "cam"},
    duracion=1.0,
    modificadores=("rate",),
    ciclo=_ciclo_detener,
)
def detener(ctx: ContextoGuion, objeto):
    return ctx.detener_efecto(objeto)


# --- personalizado ------------------------------------------------------------------------------------


def _funciones_definidas(ruta) -> set[str]:
    arbol = ast.parse(ruta.read_text(encoding="utf-8"), filename=str(ruta))
    return {n.name for n in arbol.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _ciclo_personalizado(params: dict, estado) -> None:
    archivo, funcion = params.get("archivo"), params.get("funcion")
    if not isinstance(archivo, str) or not isinstance(funcion, str):
        return
    ruta = estado.dir_base / archivo
    if not ruta.is_file():
        estado.error("E9", f"no existe el archivo '{archivo}' (se busca junto al guion: {ruta})")
    else:
        try:
            funciones = _funciones_definidas(ruta)
        except SyntaxError as error:
            estado.error("E9", f"'{archivo}' tiene un error de sintaxis: {error}")
        else:
            if funcion not in funciones:
                estado.error("E9", f"'{archivo}' no define la función '{funcion}'.{sugerencia(funcion, funciones)} "
                                   f"Funciones: {', '.join(sorted(funciones)) or '(ninguna)'}")
    for id in params.get("crea") or []:
        if isinstance(id, str):
            estado.crear(id, "personalizado")


@accion(
    "personalizado",
    "Puerta de escape: llama funcion(ctx, **args) de un .py junto al guion; devuelve animaciones como un verbo.",
    params=[
        Param("archivo", "texto", requerido=True, descripcion="Ruta del .py relativa al guion."),
        Param("funcion", "texto", requerido=True, descripcion="Nombre de la función (recibe ctx y args)."),
        Param("args", "mapa", defecto={}, descripcion="Argumentos con nombre para la función."),
        Param("crea", "lista", defecto=[], descripcion="Ids que la función registra con ctx.registrar (para validar)."),
    ],
    ejemplo={"en": "inicio", "hacer": "personalizado", "archivo": "momentos.py", "funcion": "momento_aja", "dur": 2.0},
    duracion=1.0,
    ciclo=_ciclo_personalizado,
)
def personalizado(ctx: ContextoGuion, archivo, funcion, args=None, crea=None):
    fn = ctx.cargar_funcion(archivo, funcion)
    resultado = fn(ctx, **(args or {}))
    faltan = [i for i in (crea or []) if not ctx.existe(i)]
    if faltan:
        from toolkit.guion.contexto import _error

        raise _error("E9", f"{funcion} debía registrar {faltan} con ctx.registrar(id, mob)", ctx.ubicacion)
    for i in crea or []:
        ctx.marcar_foco(i)
    return resultado
