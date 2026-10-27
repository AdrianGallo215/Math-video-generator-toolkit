"""Escenas base de los shorts: PlantillaShort (2D con cámara móvil) y utilidades comunes.

- ``PlantillaShort`` hereda de ``MovingCameraScene``: toda escena puede hacer zoom/paneo con
  ``self.camera.frame`` y mantener una capa HUD (``capa_hud``) fija a la cámara.
- La resolución la decide el perfil de calidad vigente (``toolkit.configuracion``), nunca un valor fijo.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Callable

import numpy as np
from manim import UL, Mobject, MovingCameraScene, VGroup, VMobject, config

from .auditor_layout import VARIABLE_ENTORNO_AUDITAR, Hallazgo, auditar_escena, escribir_reporte
from .configuracion import COLOR_FONDO_GLOBAL, aplicar_configuracion_global
from .guias_visuales import obtener_todas_las_guias
from .layout import ZONA_SEGURA, colocar_en
from .narracion import MixinNarracion, SegmentoNarrado, agregar_sonido
from .subtitulos import SubtitulosKaraoke
from .tipografia import FUENTE_SERIF, registrar_fuentes

logger = logging.getLogger(__name__)

Z_INDEX_HUD = 100
Z_INDEX_GUIAS = 999
OPACIDAD_MARCA_DE_AGUA = 0.3
VARIABLE_ENTORNO_GUIAS = "SHORT_GUIAS"


def resolver_mostrar_guias(valor: bool | None) -> bool:
    """``None`` ⇒ lee la variable de entorno ``SHORT_GUIAS`` (activa solo si vale "1")."""
    if valor is None:
        return os.environ.get(VARIABLE_ENTORNO_GUIAS) == "1"
    return bool(valor)


def reproducir_sfx(escena, nombre: str, ganancia_db: float = -8.0) -> None:
    """Añade el efecto de sonido ``nombre`` (ver ``toolkit.audio_base``) en el instante actual."""
    from toolkit.audio_base import ruta_sfx  # import perezoso: el audio es opcional

    agregar_sonido(escena, ruta_sfx(nombre), ganancia_db)


class _ComunPlantilla(MixinNarracion):
    """Métodos compartidos por PlantillaShort y PlantillaShort3D (incluye ``narrar`` de T08)."""

    capa_hud: VGroup
    guias: VGroup | None

    def sfx(self, nombre: str, ganancia_db: float = -8.0) -> None:
        """Reproduce un SFX procedural (``pop``, ``whoosh``, ``ding``, ``tick``, ``exito``)."""
        reproducir_sfx(self, nombre, ganancia_db)

    def fijar_marca_de_agua(self, mobject: Mobject) -> None:
        """Compat: marca tenue (opacidad 0.3) en la esquina UL de ZONA_SEGURA, fija a cámara."""
        mobject.set_opacity(OPACIDAD_MARCA_DE_AGUA)
        colocar_en(mobject, ZONA_SEGURA, UL)
        self._a_coordenadas_de_camara(mobject)
        self.fijar_a_camara(mobject)

    def _a_coordenadas_de_camara(self, mobject: Mobject) -> None:
        """Convierte un mob posicionado en coordenadas de pantalla (cuadro 9x16) a las de la cámara.

        En 3D no hace nada: ``add_fixed_in_frame_mobjects`` ya trabaja en coordenadas de pantalla.
        """

    # T08: narrar(texto, ...) -> ControlNarracion viene de MixinNarracion (toolkit.narracion).

    # --- T09: subtítulos karaoke --------------------------------------------------------

    SUBTITULOS: bool = True
    COLORES_SUBTITULOS: dict[str, str] = {}  # palabra (se normaliza) -> color semántico

    subtitulos: SubtitulosKaraoke | None

    def _crear_subtitulos(self, forzar: bool = False) -> None:
        """Crea ``self.subtitulos`` (si ``SUBTITULOS`` o ``forzar``) y lo añade a la capa HUD."""
        self.subtitulos = None
        if not (self.SUBTITULOS or forzar):
            return
        fuente = FUENTE_SERIF if getattr(self, "_fuente_serif_disponible", False) else None
        self.subtitulos = SubtitulosKaraoke(self, colores_palabra=self.COLORES_SUBTITULOS, fuente=fuente)
        # Sigue a la cámara por su cuenta (su contenido cambia de tamaño): _sincronizar_hud lo invoca.
        self.subtitulos._updater_hud = _actualizar_hud_subtitulos  # type: ignore[attr-defined]
        self._anclar_subtitulos(self.subtitulos)

    def _anclar_subtitulos(self, subtitulos: SubtitulosKaraoke) -> None:
        self.capa_hud.add(subtitulos)
        self.add(self.capa_hud)

    def activar_subtitulos(self, activos: bool = True) -> None:
        """Enciende o apaga los subtítulos de las próximas narraciones (apagar borra el bloque visible)."""
        if not activos:
            if self.subtitulos is not None:
                self.subtitulos.bloques = []
                self.subtitulos.actualizar()
            self._subtitulos_apagados = True
            return
        self._subtitulos_apagados = False
        if getattr(self, "subtitulos", None) is None:
            self._crear_subtitulos(forzar=True)

    def _al_narrar(self, segmento: SegmentoNarrado, inicio: float) -> None:
        subtitulos = getattr(self, "subtitulos", None)
        if subtitulos is None or getattr(self, "_subtitulos_apagados", False):
            return
        if subtitulos not in self.get_mobject_family_members():
            # Alguna animación o self.clear() sacó el HUD de la escena: se re-ancla.
            self._anclar_subtitulos(subtitulos)
        subtitulos.programar(segmento, inicio)

    def play(self, *args: Any, **kwargs: Any) -> None:
        # Antes de compilar la animación: el estado del subtítulo (y su tiempo) entra en el hash de
        # la caché de manim y decide si un wait() puede congelar el frame.
        subtitulos = getattr(self, "subtitulos", None)
        if subtitulos is not None:
            subtitulos.actualizar()
        super().play(*args, **kwargs)
        self._auditar()

    # --- T07: auditor automático de layout -----------------------------------------------

    def _auditar(self) -> None:
        """Si ``SHORT_AUDITAR=1``, audita el estado actual y acumula hallazgos (ver tear_down).

        ``wait()`` delega en ``play()`` (``Scene.wait`` llama a ``self.play(Wait(...))``), así que
        enganchar solo ``play`` cubre ambos. Nunca debe romper el render: cualquier excepción del
        auditor se registra como advertencia y se descarta.
        """
        if os.environ.get(VARIABLE_ENTORNO_AUDITAR) != "1":
            return
        if not hasattr(self, "_hallazgos_layout"):
            self._hallazgos_layout: list[Hallazgo] = []
        try:
            self._hallazgos_layout.extend(auditar_escena(self))
        except Exception:
            logger.warning("El auditor de layout falló en %s; se ignora.", type(self).__name__, exc_info=True)

    def tear_down(self) -> None:
        super().tear_down()
        hallazgos = getattr(self, "_hallazgos_layout", None)
        if not hallazgos:
            return
        ruta = Path(config.media_dir) / type(self).__name__ / "auditoria_layout.json"
        try:
            escribir_reporte(hallazgos, ruta)
        except Exception:
            logger.warning("No se pudo escribir el reporte de auditoría de layout en %s.", ruta, exc_info=True)
            return
        logger.warning(
            "Auditoría de layout: %d hallazgo(s) en %s (ver %s).", len(hallazgos), type(self).__name__, ruta
        )


def _actualizar_hud_subtitulos(mob: Mobject) -> None:
    mob.actualizar()  # type: ignore[attr-defined]


class PlantillaShort(_ComunPlantilla, MovingCameraScene):
    """Escena base de todos los shorts 2D (cámara móvil + HUD fijo a cámara).

    ``mostrar_guias_seguras=None`` ⇒ se activan si la variable de entorno ``SHORT_GUIAS`` vale "1".
    """

    def __init__(self, mostrar_guias_seguras: bool | None = None, **kwargs: Any) -> None:
        self.mostrar_guias_seguras = resolver_mostrar_guias(mostrar_guias_seguras)
        aplicar_configuracion_global()
        super().__init__(**kwargs)

    def setup(self) -> None:
        """Fondo, fuentes, capa HUD y guías (idempotente: escenas legado llaman setup() otra vez)."""
        self.camera.background_color = COLOR_FONDO_GLOBAL
        self._fuente_serif_disponible = registrar_fuentes()
        if getattr(self, "_plantilla_preparada", False):
            return
        self._plantilla_preparada = True
        self.frame_referencia_ancho = self.camera.frame.width
        self.capa_hud = VGroup()
        self.add(self.capa_hud)
        self.guias = None
        if self.mostrar_guias_seguras:
            self.guias = obtener_todas_las_guias()
            self._a_coordenadas_de_camara(self.guias)
            self.fijar_a_camara(self.guias, z_index=Z_INDEX_GUIAS)
        self._crear_subtitulos()

    # --- HUD fijo a cámara -------------------------------------------------------------

    def fijar_a_camara(self, *mobs: Mobject, z_index: int = Z_INDEX_HUD) -> None:
        """Ancla ``mobs`` a la cámara: conservan posición y tamaño relativos al cuadro visible.

        La relación se toma en el momento de fijar (``offset`` respecto al centro del cuadro y
        ancho del cuadro). Mientras un mob está siendo animado por su propia animación, manim
        suspende sus updaters y no sigue a la cámara hasta que la animación termina.
        """
        frame = self.camera.frame
        for mob in mobs:
            self._quitar_updater_hud(mob)
            updater = _crear_updater_hud(frame, mob)
            mob._updater_hud = updater  # type: ignore[attr-defined]
            mob.add_updater(updater)
            mob.set_z_index(z_index)
            if mob not in self.capa_hud.submobjects:
                self.capa_hud.add(mob)
        # Re-añadir la capa la consolida si alguna animación la había "disuelto" en la escena.
        self.add(self.capa_hud)

    def soltar_de_camara(self, *mobs: Mobject) -> None:
        """Deshace ``fijar_a_camara``: el mob queda en la escena, en coordenadas del mundo."""
        for mob in mobs:
            self._quitar_updater_hud(mob)
            if mob in self.capa_hud.submobjects:
                self.capa_hud.remove(mob)
            self.add(mob)

    @staticmethod
    def _quitar_updater_hud(mob: Mobject) -> None:
        updater = getattr(mob, "_updater_hud", None)
        if updater is not None:
            mob.remove_updater(updater)
            mob._updater_hud = None  # type: ignore[attr-defined]

    def _sincronizar_hud(self) -> None:
        """Aplica una vez los updaters del HUD (p. ej. tras mover la cámara sin animación)."""
        capa = getattr(self, "capa_hud", None)
        if capa is None:
            return
        for mob in capa.submobjects:
            if not mob.updating_suspended:
                updater = getattr(mob, "_updater_hud", None)
                if updater is not None:
                    updater(mob)

    def _a_coordenadas_de_camara(self, mobject: Mobject) -> None:
        frame = self.camera.frame
        factor = frame.width / self.frame_referencia_ancho
        if not np.isclose(factor, 1.0):
            _escalar(mobject, factor, about_point=np.zeros(3))
        mobject.shift(frame.get_center())

    def play(self, *args: Any, **kwargs: Any) -> None:
        # Un wait() sin updaters temporales se renderiza como frame congelado (sin updaters):
        # sincronizamos antes para cubrir cambios instantáneos de cámara.
        self._sincronizar_hud()
        super().play(*args, **kwargs)

    def update_mobjects(self, dt: float) -> None:
        super().update_mobjects(dt)
        # Al final: si la cámara tiene updaters propios dentro de la escena, el HUD va detrás.
        self._sincronizar_hud()


def _crear_updater_hud(frame: Mobject, mob: Mobject) -> Callable[[Mobject], None]:
    """Updater (no temporal) que mantiene ``mob`` fijo respecto a ``frame``."""
    ancho_ref = frame.width
    offset = mob.get_center() - frame.get_center()
    estado = {"ancho": ancho_ref}

    def updater(m: Mobject) -> None:
        ancho = frame.width
        factor = ancho / estado["ancho"]
        if not np.isclose(factor, 1.0, rtol=1e-9, atol=0.0):
            _escalar(m, factor)
            estado["ancho"] = ancho
        m.move_to(frame.get_center() + offset * (ancho / ancho_ref))

    return updater


def _escalar(mob: Mobject, factor: float, **kwargs: Any) -> None:
    """Escala ``mob`` escalando también el grosor de trazo si es un VMobject.

    En cairo el grosor de trazo está en unidades de escena: sin escalarlo, un HUD con trazos se
    vería más fino tras un zoom-out.
    """
    if isinstance(mob, VMobject):
        mob.scale(factor, scale_stroke=True, **kwargs)
    else:
        mob.scale(factor, **kwargs)
