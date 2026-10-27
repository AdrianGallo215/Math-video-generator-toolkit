"""Runtime del guion técnico: convierte un ``guion_tecnico.yaml`` validado en una escena de manim.

Uso (``escena.py`` de 3 líneas; la ruta es relativa al archivo de la escena)::

    from toolkit.guion.runtime import escena_desde_yaml
    class MiVideo(escena_desde_yaml("guion_tecnico.yaml")):
        pass

Semántica temporal (la misma que simula ``validar(..., con_voz=True)``; helpers en ``toolkit.guion.esquema``):

- Cada segmento es un ``with self.narrar(narracion, pausa_final=pausa)`` con ``RECORTAR_SILENCIO_FINAL = True``:
  el siguiente segmento empieza ``pausa`` s después de la última palabra (sin el silencio final de edge-tts).
- Los pasos se encadenan en orden. Pasos consecutivos con la misma ancla forman un grupo: se espera al ancla
  (``n.esperar_hasta``) y se reproducen en UN ``self.play``; el grupo dura ``max(retraso + dur)``. Si el ancla ya
  pasó, el grupo arranca de inmediato (aviso A7 en el log).
- ``dur`` = segundos | ``resto`` (hasta la última palabra) | ``{hasta: ancla}``; defecto: el de la pieza.
- Relleno ambiental: si faltan más de ``UMBRAL_RELLENO`` s para el siguiente ancla (o para el fin del segmento) y el
  segmento tiene ``relleno: true``, en lugar de una espera ciega el runtime hace respirar el último objeto en foco
  (o ``ambiente``). Nunca hay esperas fijas: todo se mide contra la voz real.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

from manim import AnimationGroup, Succession, Wait, config
from manim.animation.animation import Animation, prepare_animation
from manim.utils.rate_functions import linear, rush_from, rush_into, smooth, there_and_back

from toolkit.animaciones import pulso
from toolkit.base_scene import PlantillaShort
from toolkit.guion import registro
from toolkit.guion.contexto import COLORES, ContextoGuion
from toolkit.guion.esquema import (
    TOLERANCIA_TARDE,
    UMBRAL_RELLENO,
    ErrorGuion,
    Guion,
    Hallazgo,
    Paso,
    Segmento,
    agrupar_pasos,
    duracion_base,
    evaluar_calculos,
    fin_de_voz,
    resolver_dur,
    tiempo_de_ancla,
)
from toolkit.guion.validar import validar
from toolkit.layout import apilar, encajar
from toolkit.narracion import VELOCIDAD_POR_DEFECTO, VOZ_POR_DEFECTO, ControlNarracion

logger = logging.getLogger(__name__)

RATES = {"smooth": smooth, "linear": linear, "rush_from": rush_from, "rush_into": rush_into,
         "there_and_back": there_and_back}
ESCALA_RELLENO = 1.04  # respiración ambiental: sutil (guía §6)
DURACION_RESPIRACION = 1.6  # s por respiración cuando el hueco es largo
DECIMALES = 6


def _como_animaciones(resultado: Any) -> list[Animation]:
    if resultado is None:
        return []
    if isinstance(resultado, (list, tuple)):
        return [prepare_animation(a) for a in resultado if a is not None]
    return [prepare_animation(resultado)]


def _un_fotograma() -> float:
    return 1.0 / config.frame_rate


class EscenaGuion(PlantillaShort):
    """Escena que ejecuta ``GUION`` (la genera :func:`escena_desde_yaml`; no se usa directamente)."""

    GUION: Guion | None = None
    SUBTITULOS = True
    RECORTAR_SILENCIO_FINAL = True
    contexto_guion: ContextoGuion | None = None  # tras construct: objetos, efectos y estado finales (tests, QA)

    def construct(self) -> None:
        if self.GUION is None:
            raise ErrorGuion([Hallazgo("E1", "la escena no tiene GUION: créala con escena_desde_yaml(ruta)")])
        self.contexto_guion = ejecutar_guion(self, self.GUION)


def escena_desde_yaml(ruta: str | Path) -> type[EscenaGuion]:
    """Clase de escena lista para manim a partir de un guion técnico (validado; ``ErrorGuion`` si tiene errores).

    Una ruta relativa se resuelve respecto al archivo que llama (el ``escena.py`` del video).
    """
    ruta = Path(ruta)
    llamador = sys._getframe(1).f_globals
    if not ruta.is_absolute():
        base = llamador.get("__file__")
        ruta = (Path(base).resolve().parent if base else Path.cwd()) / ruta
    reporte = validar(ruta)
    if not reporte.ok:
        raise ErrorGuion(reporte.errores)
    guion = reporte.guion
    assert guion is not None
    meta = guion.meta
    atributos = {
        "GUION": guion,
        "VOZ": meta.voz or VOZ_POR_DEFECTO,
        "VELOCIDAD": meta.velocidad or VELOCIDAD_POR_DEFECTO,
        "COLORES_SUBTITULOS": {palabra: COLORES[color] for palabra, color in guion.subtitulos.items()},
        "__doc__": f"{meta.titulo} (compilada de {ruta.name}).",
        "__module__": llamador.get("__name__", __name__),
    }
    return type(meta.clase, (EscenaGuion,), atributos)


# --- Ejecución ------------------------------------------------------------------------------------------


def ejecutar_guion(escena: PlantillaShort, guion: Guion) -> ContextoGuion:
    """Ejecuta todos los segmentos de ``guion`` en ``escena`` (dentro de ``construct``)."""
    import toolkit.guion.catalogo  # noqa: F401  (registra las piezas)

    ctx = ContextoGuion(escena, guion)
    ctx.calculos, _ = evaluar_calculos(guion)
    _preparar_escenario(ctx, guion)
    for segmento in guion.segmentos:
        _ejecutar_segmento(escena, ctx, segmento)
    for efecto in ctx.efectos.values():
        logger.warning("A8: el efecto %s '%s' termina el video sin detenerse", efecto.tipo, efecto.id)
    return ctx


def _preparar_escenario(ctx: ContextoGuion, guion: Guion) -> None:
    for obj in guion.escenario:
        ctx.paso = obj
        ctx.registrar(obj.id, ctx.crear(obj.tipo, **obj.params), oculto=obj.oculto)
    for disp in guion.disposiciones:
        mobs = [ctx.objetos[i] for i in disp.ids]
        zona = ctx.zona(disp.zona or "principal")
        if disp.modo == "apilar":
            apilar(*mobs, zona=zona, espacio=disp.espacio)
        else:
            from manim import RIGHT, VGroup

            encajar(VGroup(*mobs).arrange(RIGHT, buff=disp.espacio), zona=zona)
    for obj in guion.escenario:
        if not obj.oculto:
            ctx.escena.add(ctx.objetos[obj.id])
            ctx.marcar_foco(obj.id)
    ctx.paso = None


def _ejecutar_segmento(escena: PlantillaShort, ctx: ContextoGuion, segmento: Segmento) -> None:
    with escena.narrar(segmento.narracion, pausa_final=segmento.pausa) as n:
        ctx.control = n
        for grupo in agrupar_pasos(segmento.pasos):
            _ejecutar_grupo(escena, ctx, n, segmento, grupo)
        _rellenar(escena, ctx, segmento, n.inicio + fin_de_voz(n.segmento) + segmento.pausa)
    ctx.control = None


def _tiempo_absoluto(n: ControlNarracion, paso: Paso, ancla) -> float:
    try:
        return n.inicio + tiempo_de_ancla(ancla, n.segmento)
    except KeyError as error:
        reales = " ".join(p.texto for p in n.segmento.palabras)
        raise ErrorGuion([Hallazgo("E7", f"la voz real no pronuncia {ancla.describir()} como palabra. Palabras reales: "
                                         f"{reales} (valida con --voz antes de renderizar)", paso.ubicacion,
                                   paso.linea)]) from error


def _esperar_hasta(escena: PlantillaShort, t: float) -> None:
    espera = round(t - escena.renderer.time, DECIMALES)
    if espera > _un_fotograma():
        escena.wait(espera)


def _rellenar(escena: PlantillaShort, ctx: ContextoGuion, segmento: Segmento, objetivo: float) -> None:
    """Si faltan más de ``UMBRAL_RELLENO`` s hasta ``objetivo``, respira el objeto en foco hasta ese instante."""
    hueco = round(objetivo - escena.renderer.time, DECIMALES)
    if not segmento.relleno or hueco <= UMBRAL_RELLENO:
        return
    mob = None
    if segmento.ambiente and ctx.existe(segmento.ambiente) and not ctx.oculto(segmento.ambiente):
        mob = ctx.objetos[segmento.ambiente]
    if mob is None:
        mob = ctx.foco()
    if mob is None:
        return
    veces = max(1, round(hueco / DURACION_RESPIRACION))
    latidos = [pulso(mob, escala=ESCALA_RELLENO, run_time=hueco / veces) for _ in range(veces)]
    escena.play(latidos[0] if veces == 1 else Succession(*latidos))
    ctx.reensamblar()


def _ejecutar_grupo(escena: PlantillaShort, ctx: ContextoGuion, n: ControlNarracion, segmento: Segmento,
                    grupo: list[Paso]) -> None:
    primero = grupo[0]
    ancla = primero.en
    t_ancla = _tiempo_absoluto(n, primero, ancla)
    _rellenar(escena, ctx, segmento, t_ancla)
    if ancla.tipo == "palabra" and ancla.mas == 0:
        n.esperar_hasta(ancla.texto, ancla.ocurrencia)
    else:
        _esperar_hasta(escena, t_ancla)
    ahora = escena.renderer.time
    if ahora - t_ancla > TOLERANCIA_TARDE:
        logger.warning("A7 %s: el ancla %s ya pasó hace %.2f s; el paso arranca de inmediato",
                       primero.ubicacion, ancla.describir(), ahora - t_ancla)
    animaciones = []
    for paso in grupo:
        ctx.paso = paso
        animacion = _construir_paso(ctx, n, paso, ahora - n.inicio)
        if animacion is not None:
            animaciones.append(animacion)
    if animaciones:
        # Orden cronológico de FIN (estable): ``AnimationGroup.finish`` reaplica el valor final de cada animación
        # en el orden de la lista, así que gana la que termina más tarde (una cadena de pasos sobre el mismo
        # valor no salta atrás aunque el YAML no la liste en orden temporal).
        animaciones.sort(key=lambda a: a.run_time)
        escena.play(animaciones[0] if len(animaciones) == 1 else AnimationGroup(*animaciones))
    # manim desarma los objetos cuyas partes se animaron dentro del grupo (ver ContextoGuion.reensamblar).
    ctx.reensamblar()
    ctx.ejecutar_pendientes()
    ctx.paso = None


def _construir_paso(ctx: ContextoGuion, n: ControlNarracion, paso: Paso, inicio_grupo: float) -> Animation | None:
    """Llama a la pieza del paso y devuelve su animación con ``dur``, ``rate`` y ``retraso`` aplicados."""
    definicion = registro.obtener(paso.hacer, "accion")
    if definicion is None:  # validado antes: solo si alguien ejecuta un guion sin validar
        raise ErrorGuion([Hallazgo("E2", f"el verbo '{paso.hacer}' no existe", paso.ubicacion, paso.linea)])
    params = registro.resolver_params(definicion, paso.params)
    rate = params.pop("rate", None) if "rate" in definicion.nombres_params else None
    animaciones = _como_animaciones(definicion.funcion(ctx, **params))
    if not animaciones:
        return None
    dur, recorte = resolver_dur(duracion_base(paso), inicio_grupo + paso.retraso, n.segmento)
    if recorte:
        logger.warning("A7 %s: %s", paso.ubicacion, recorte)
    dur = max(dur, _un_fotograma())
    if rate is not None:
        for animacion in animaciones:
            animacion.rate_func = RATES[rate]
    animacion = animaciones[0] if len(animaciones) == 1 else AnimationGroup(*animaciones)
    animacion.run_time = round(dur, DECIMALES)
    if paso.retraso > 0:
        animacion = Succession(Wait(run_time=paso.retraso), animacion)
    return animacion


__all__ = ["EscenaGuion", "escena_desde_yaml", "ejecutar_guion", "RATES"]
