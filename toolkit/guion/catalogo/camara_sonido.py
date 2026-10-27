"""Cámara (efecto persistente con id, se termina con ``detener``) y efectos de sonido."""

from __future__ import annotations

from manim import Mobject

from toolkit.audio_base import SFX_DISPONIBLES
from toolkit.guion.contexto import ContextoGuion
from toolkit.guion.registro import Param, accion

MODOS_CAMARA = ("zoom", "paneo", "anclar")


@accion(
    "sonido",
    "Efecto de sonido sutil en el instante del ancla (pop al aparecer un resultado, whoosh en transiciones).",
    params=[
        Param("nombre", "texto", requerido=True, opciones=SFX_DISPONIBLES, descripcion="Efecto a reproducir."),
        Param("ganancia_db", "numero", defecto=-8.0, descripcion="Volumen relativo en dB (negativo = más bajo)."),
    ],
    ejemplo={"en": "inicio", "hacer": "sonido", "nombre": "pop"},
    duracion=0.0,
)
def sonido(ctx: ContextoGuion, nombre, ganancia_db):
    ctx.escena.sfx(nombre, ganancia_db=ganancia_db)
    return None


def _ciclo_camara(params: dict, estado) -> None:
    modo = params.get("modo", "zoom")
    objeto = params.get("objeto")
    if modo in ("paneo", "anclar") and objeto is None:
        estado.error("E3", f"la cámara en modo '{modo}' necesita 'objeto' (a dónde mirar)")
    if isinstance(objeto, str):
        estado.usar(objeto)
    factor = params.get("factor", 1.3)
    if isinstance(factor, (int, float)) and factor <= 0:
        estado.error("E3", "factor de zoom: debe ser positivo (>1 acerca, <1 aleja)")
    if isinstance(params.get("id"), str):
        estado.iniciar_efecto(params["id"], "camara")


@accion(
    "camara",
    "Efecto persistente de cámara con id: zoom (acercar/alejar), paneo (mirar a un objeto) o anclar (seguirlo). "
    "Dura hasta 'hacer: detener, objeto: <id>', que devuelve la cámara a su encuadre original.",
    params=[
        Param("id", "texto", requerido=True, descripcion="Id del efecto (para detenerlo)."),
        Param("modo", "texto", defecto="zoom", opciones=MODOS_CAMARA, descripcion="Qué hace la cámara."),
        Param("objeto", "objeto", descripcion="Objeto al que mirar (obligatorio en paneo y anclar)."),
        Param("factor", "numero", defecto=1.3, descripcion="Zoom: >1 acerca, <1 aleja (zoom y anclar)."),
    ],
    ejemplo={"en": "inicio", "hacer": "camara", "id": "cam", "modo": "zoom", "objeto": "a", "factor": 1.2},
    duracion=1.0,
    modificadores=("rate",),
    ciclo=_ciclo_camara,
)
def camara(ctx: ContextoGuion, id, modo="zoom", objeto=None, factor=1.3):
    frame: Mobject = ctx.escena.camera.frame
    centro_original, ancho_original = frame.get_center().copy(), frame.width
    objetivo = ctx.obtener(objeto) if objeto is not None else None
    centro = objetivo.get_center() if objetivo is not None else frame.get_center()
    estado = {"seguidor": None}

    def detener_camara(_ctx: ContextoGuion):
        if estado["seguidor"] is not None:
            frame.remove_updater(estado["seguidor"])
        return frame.animate.move_to(centro_original).scale(ancho_original / frame.width)

    ctx.iniciar_efecto(id, "camara", detener_camara, modo=modo)
    if modo == "paneo":
        return frame.animate.move_to(centro)
    animacion = frame.animate.move_to(centro).scale(1.0 / float(factor))
    if modo == "anclar":

        def empezar_a_seguir() -> None:
            def seguir(f: Mobject) -> None:
                f.move_to(objetivo.get_center())

            estado["seguidor"] = seguir
            if frame not in ctx.escena.mobjects:
                ctx.escena.add(frame)
            frame.add_updater(seguir)

        ctx.despues(empezar_a_seguir)
    return animacion
