"""Acciones comunes del guion: ``enfocar``, ``restaurar``, ``mover``, ``titulo`` y los tipos ``llave`` y ``flecha``.

Envuelven ``toolkit.animaciones`` (``enfocar``, ``restaurar``, ``titulo_seccion``, ``transicion_seccion``,
``llave_con_etiqueta``, ``flecha_etiquetada``) sin duplicar su lógica. Todas se colocan con ``ctx.colocar`` /
``ctx.zona`` (nunca con coordenadas) y respetan la zona segura.
"""

from __future__ import annotations

from functools import partial
from typing import Any

from manim import (
    RIGHT,
    AnimationGroup,
    Group,
    Mobject,
    Succession,
    Transform,
    VGroup,
)

from toolkit.animaciones import (
    aparecer,
    enfocar as animar_enfocar,
    flecha_etiquetada,
    llave_con_etiqueta,
    restaurar as animar_restaurar,
    titulo_seccion,
    transicion_seccion,
)
from toolkit.estilos import FUENTE_ETIQUETA, FUENTE_MINIMA, OPACIDAD_ATENUADO, TIEMPO_TRANSFORMAR
from toolkit.guion.catalogo.modificadores import es_marca_de
from toolkit.guion.contexto import (
    ALINEACIONES,
    ATRIBUTO_PARTES,
    LADOS,
    ZONA_CONTENIDO,
    ContextoGuion,
    _ajustar_dentro,
    separar_ref,
)
from toolkit.guion.registro import Param, accion, objeto
from toolkit.layout import solapan

TODO = "todo"
DURACION_ENFOQUE = 0.5
MAX_PASOS_DESPEJE = 30
PASO_DESPEJE = 0.1
_PARAM_ZONA_DESTINO_DOC = "Zona (nombre) o {de: id, lado: abajo|arriba|izq|der, espacio: 0.3}."


def _como_lista(valor: Any) -> list:
    return list(valor) if isinstance(valor, (list, tuple)) else [valor]


# --- enfocar / restaurar ---------------------------------------------------------------------------------------


def _visibles_menos(ctx: ContextoGuion, excluir: set[str]) -> list[Mobject]:
    """Objetos visibles (no reservados, en escena) salvo ``excluir`` y las marcas (caja/tachado) de los excluidos."""
    resultado = []
    presentes = set(ctx.escena.get_mobject_family_members()) if ctx.escena is not None else None
    for id, mob in ctx.objetos.items():
        if id in excluir or ctx.oculto(id) or any(es_marca_de(id, e) for e in excluir):
            continue
        # visible = alguna parte suya está en escena (una entrada escalonada añade los miembros por separado)
        if presentes is not None and not any(f in presentes for f in mob.get_family()):
            continue
        resultado.append(mob)
    return resultado


def _ciclo_enfocar(params: dict, estado) -> None:
    for ref in _como_lista(params.get("objeto")):
        estado.usar(ref)
    resto = params.get("resto")
    if resto is None or resto == TODO:
        return
    if not isinstance(resto, list) or not resto or not all(isinstance(r, str) for r in resto):
        estado.error("E3", f"'resto' es \"{TODO}\" o una lista de ids a atenuar, no {resto!r}")
        return
    for ref in resto:
        estado.usar(ref)


@accion(
    "enfocar",
    "Atenúa todo salvo lo que la voz nombra (objeto: id, 'id.parte' o lista). Se deshace con restaurar.",
    params=[
        Param("objeto", "objeto", requerido=True, descripcion="Lo que queda a plena luz: id, 'id.parte' o lista."),
        Param("resto", "cualquiera", defecto=TODO,
              descripcion=f"Qué se atenúa: \"{TODO}\" (todo lo visible salvo el foco y sus marcas) o una lista de ids."),
        Param("opacidad", "numero", defecto=OPACIDAD_ATENUADO, descripcion="Opacidad relativa del resto (0-1)."),
    ],
    ejemplo={"en": "inicio", "hacer": "enfocar", "objeto": "a", "resto": "todo"},
    duracion=DURACION_ENFOQUE,
    modificadores=("rate",),
    ciclo=_ciclo_enfocar,
)
def enfocar(ctx: ContextoGuion, objeto, resto=TODO, opacidad=OPACIDAD_ATENUADO):
    refs = _como_lista(objeto)
    focos = ctx.obtener_varios(refs)
    ids_foco = {separar_ref(r)[0] for r in refs}
    atenuados = _visibles_menos(ctx, ids_foco) if resto == TODO else ctx.obtener_varios(resto)
    for id in ids_foco:
        ctx.marcar_foco(id)
    foco = focos[0] if len(focos) == 1 else Group(*focos)
    return animar_enfocar(foco, atenuados, opacidad=float(opacidad), run_time=DURACION_ENFOQUE)


def _ciclo_restaurar(params: dict, estado) -> None:
    objetos = params.get("objeto")
    if objetos is None or objetos == TODO:
        return
    for ref in _como_lista(objetos):
        estado.usar(ref)


@accion(
    "restaurar",
    "Devuelve a plena opacidad lo atenuado por enfocar (sin 'objeto': todo lo visible).",
    params=[Param("objeto", "objeto", defecto=TODO, descripcion=f"Id, 'id.parte', lista de ids o \"{TODO}\".")],
    ejemplo={"en": "fin", "hacer": "restaurar"},
    duracion=DURACION_ENFOQUE,
    modificadores=("rate",),
    ciclo=_ciclo_restaurar,
)
def restaurar(ctx: ContextoGuion, objeto=TODO):
    if objeto == TODO:
        mobs = _visibles_menos(ctx, set())
    else:
        mobs = ctx.obtener_varios(objeto)
    if not mobs:
        return None
    return animar_restaurar(mobs, run_time=DURACION_ENFOQUE)


# --- mover -----------------------------------------------------------------------------------------------------


def _ciclo_mover(params: dict, estado) -> None:
    ref = params.get("objeto")
    if not isinstance(ref, str):
        estado.error("E3", "mover actúa sobre un solo objeto (id o 'id.parte'), no una lista")
        return
    estado.usar(ref)
    destino = params.get("a")
    if isinstance(destino, dict) and isinstance(destino.get("de"), str):
        if separar_ref(destino["de"])[0] == separar_ref(ref)[0]:
            estado.error("E4", "'a.de' no puede ser el mismo objeto que se mueve")
        else:
            estado.usar(destino["de"])
    escala = params.get("escala")
    if isinstance(escala, (int, float)) and escala <= 0:
        estado.error("E3", "escala: debe ser positiva (1 = igual, 0.5 = mitad)")


@accion(
    "mover",
    "Lleva un objeto a una zona o junto a otro objeto (a: {de, lado, espacio}), con escala y arco opcionales. "
    "Las cajas/tachados del objeto viajan con él.",
    params=[
        Param("objeto", "objeto", requerido=True, descripcion="Id (o 'id.parte') del objeto que se mueve."),
        Param("a", "zona", requerido=True, descripcion=_PARAM_ZONA_DESTINO_DOC),
        Param("alineacion", "texto", defecto="centro", opciones=tuple(ALINEACIONES),
              descripcion="Borde de la zona al que se pega (solo con zona nombrada)."),
        Param("arco", "numero", defecto=0.0, descripcion="Curvatura del recorrido en radianes (1.57 = cuarto de vuelta)."),
    ],
    ejemplo={"en": "inicio", "hacer": "mover", "objeto": "a", "a": {"de": "b", "lado": "abajo", "espacio": 0.3},
             "escala": 0.8},
    duracion=TIEMPO_TRANSFORMAR,
    modificadores=("escala", "rate"),
    ciclo=_ciclo_mover,
)
def mover(ctx: ContextoGuion, objeto, a, alineacion="centro", arco=0.0, escala=None):
    id, parte = separar_ref(objeto)
    origen = ctx.obtener(objeto)
    destino = origen.copy()
    if escala:
        destino.scale(float(escala))
    ctx.colocar(destino, a, alineacion)
    ctx.marcar_foco(id)
    animaciones = [Transform(origen, destino, path_arc=float(arco))]
    if parte is None:
        factor = destino.width / origen.width if origen.width > 1e-9 else 1.0
        desplazamiento = destino.get_center() - origen.get_center()
        centro = origen.get_center()
        for otro, marca in ctx.objetos.items():
            if es_marca_de(otro, id):
                final = marca.copy().scale(factor, about_point=centro).shift(desplazamiento)
                animaciones.append(Transform(marca, final, path_arc=float(arco)))
    return animaciones[0] if len(animaciones) == 1 else AnimationGroup(*animaciones)


# --- titulo ----------------------------------------------------------------------------------------------------


class _Recolector:
    """Falso ``Scene`` que guarda lo que ``transicion_seccion`` reproduciría (y le pasa el sfx a la escena real)."""

    def __init__(self, escena: Any) -> None:
        self.animaciones: list = []
        self._escena = escena

    def play(self, *animaciones, **_kwargs) -> None:
        self.animaciones.extend(animaciones)

    def sfx(self, nombre: str, *args, **kwargs) -> None:
        if self._escena is not None:
            self._escena.sfx(nombre, *args, **kwargs)


def _ciclo_titulo(params: dict, estado) -> None:
    salientes = params.get("sale")
    for ref in _como_lista(salientes) if salientes is not None else []:
        if not isinstance(ref, str):
            continue
        if separar_ref(ref)[1] is not None:
            estado.error("E3", f"sale: usa ids completos, no '{ref}'")
        elif estado.usar(ref):
            estado.consumir(ref)
    estado.crear(params.get("id"), "titulo")


@accion(
    "titulo",
    "Título de sección (gris, subrayado fino) en la zona de título. Con 'sale', esos objetos se van con la transición "
    "de sección (fundido hacia arriba + whoosh) y luego entra el título; el id nuevo queda disponible.",
    params=[
        Param("id", "texto", requerido=True, descripcion="Id del título (para quitarlo o reemplazarlo después)."),
        Param("texto", "texto", requerido=True, descripcion="Texto del título, con tildes."),
        Param("zona", "zona", defecto="titulo", descripcion="Zona del título (defecto: la franja de título)."),
        Param("sale", "objeto", descripcion="Id o lista de ids que salen antes de que entre el título."),
    ],
    ejemplo={"en": "inicio", "hacer": "titulo", "id": "seccion", "texto": "Paso 1", "sale": ["a"]},
    duracion=1.4,
    modificadores=("rate",),
    ciclo=_ciclo_titulo,
)
def titulo(ctx: ContextoGuion, id, texto, zona="titulo", sale=None):
    zona_base = ctx.zona(zona) if isinstance(zona, str) else ctx.zona("titulo")
    nuevo = titulo_seccion(texto, zona_base)
    if isinstance(zona, dict):
        ctx.colocar(nuevo, zona)
    entrada = aparecer(nuevo)
    ctx.marcar_foco(id)
    if sale is None:
        ctx.registrar(id, nuevo)
        return entrada
    refs = _como_lista(sale)
    recolector = _Recolector(ctx.escena)
    transicion_seccion(recolector, ctx.obtener_varios(refs))
    for ref in refs:
        ctx.despues(partial(ctx.quitar, ref))
    ctx.registrar(id, nuevo)
    return Succession(*recolector.animaciones, entrada)


# --- llave -----------------------------------------------------------------------------------------------------


def _ciclo_llave(params: dict, estado) -> None:
    ref = params.get("objeto")
    if not isinstance(ref, str):
        estado.error("E3", f"la llave abarca un solo objeto (id o 'id.parte'), no {ref!r}: agrúpalos antes con tipo: grupo")
        return
    estado.usar(ref)


@objeto(
    "llave",
    "Llave (Brace) con etiqueta sobre un objeto o parte suya. Etiqueta MathTex si empieza por '$' o lleva '\\\\'; "
    "partes: 'id.llave', 'id.etiqueta'.",
    params=[
        Param("objeto", "objeto", requerido=True, descripcion="Objeto (o 'id.parte') que se abarca."),
        Param("etiqueta", "texto", requerido=True, descripcion="Texto de la etiqueta (o '$x^2$' para matemática)."),
        Param("lado", "texto", defecto="abajo", opciones=tuple(LADOS), descripcion="Lado del objeto donde va la llave."),
        Param("color", "color", defecto="gris", descripcion="Color de la llave (y de la etiqueta si no se da color_etiqueta)."),
        Param("color_etiqueta", "color", descripcion="Color semántico de la etiqueta (defecto: el de la llave)."),
        Param("tamano", "numero", defecto=FUENTE_ETIQUETA, descripcion=f"Tamaño de la etiqueta en puntos (mínimo {FUENTE_MINIMA})."),
    ],
    ejemplo={"en": "inicio", "hacer": "mostrar", "id": "llave_a", "tipo": "llave", "objeto": "a", "etiqueta": "n términos",
             "lado": "abajo", "color_etiqueta": "amarillo"},
    duracion=1.0,
    ciclo=_ciclo_llave,
)
def crear_llave(ctx: ContextoGuion, objeto, etiqueta, lado, color, color_etiqueta, tamano) -> Mobject:
    destino = ctx.obtener(objeto)
    grupo, _ = llave_con_etiqueta(destino, etiqueta, LADOS[lado], ctx.color(color), float(tamano))
    if color_etiqueta:
        grupo[1].set_color(ctx.color(color_etiqueta))
    setattr(grupo, ATRIBUTO_PARTES, {"llave": grupo[0], "etiqueta": grupo[1]})
    _ajustar_dentro(grupo, ZONA_CONTENIDO)
    return grupo


# --- flecha ----------------------------------------------------------------------------------------------------


def _ciclo_flecha(params: dict, estado) -> None:
    refs = [params.get("de"), params.get("a")]
    for nombre, ref in zip(("de", "a"), refs):
        if not isinstance(ref, str):
            estado.error("E3", f"'{nombre}' de la flecha es un solo id (o 'id.parte'), no {ref!r}")
            return
    if refs[0] == refs[1]:
        estado.error("E4", "la flecha necesita dos extremos distintos ('de' y 'a' apuntan a lo mismo)")
    for ref in refs:
        estado.usar(ref)


def _despejar_etiqueta(etiqueta: Mobject, flecha: Mobject, extremos: list[Mobject]) -> None:
    """Aparta la etiqueta de la flecha, de lado, hasta que no pise a los objetos que une (flechas cortas)."""
    lateral = etiqueta.get_center() - flecha.point_from_proportion(0.5)
    norma = float((lateral**2).sum() ** 0.5)
    lateral = lateral / norma if norma > 1e-6 else RIGHT
    for _ in range(MAX_PASOS_DESPEJE):
        if not any(solapan(etiqueta, e) for e in extremos):
            return
        etiqueta.shift(lateral * PASO_DESPEJE)


@objeto(
    "flecha",
    "Flecha entre dos objetos (o partes), pegada a sus bordes, con etiqueta opcional al medio y curvatura. "
    "Partes: 'id.flecha', 'id.etiqueta'.",
    params=[
        Param("de", "objeto", requerido=True, descripcion="Origen: id o 'id.parte'."),
        Param("a", "objeto", requerido=True, descripcion="Destino: id o 'id.parte'."),
        Param("etiqueta", "texto", defecto="", descripcion="Texto junto a la flecha (vacío = sin etiqueta; '$..$' = MathTex); deja ≥ 1.2 entre los extremos."),
        Param("color", "color", defecto="gris", descripcion="Color de la flecha y su etiqueta."),
        Param("curvatura", "numero", defecto=0.0, descripcion="Ángulo del arco en radianes (0 = recta; el signo elige el lado)."),
    ],
    ejemplo={"en": "inicio", "hacer": "mostrar", "id": "flecha_ab", "tipo": "flecha", "de": "a", "a": "b",
             "etiqueta": "suma", "color": "azul", "curvatura": 0.5},
    duracion=1.0,
    ciclo=_ciclo_flecha,
)
def crear_flecha(ctx: ContextoGuion, de, a, etiqueta, color, curvatura) -> Mobject:
    origen, destino = ctx.obtener(de), ctx.obtener(a)
    grupo, _ = flecha_etiquetada(origen, destino, etiqueta or "x", ctx.color(color), float(curvatura))
    if etiqueta:
        _despejar_etiqueta(grupo[1], grupo[0], [origen, destino])
    if not etiqueta:
        grupo = VGroup(grupo[0])
        setattr(grupo, ATRIBUTO_PARTES, {"flecha": grupo[0]})
    else:
        setattr(grupo, ATRIBUTO_PARTES, {"flecha": grupo[0], "etiqueta": grupo[1]})
    return grupo

