"""Escena base 3D (``PlantillaShort3D``) con HUD fijo a cámara, y utilidades 3D."""

from __future__ import annotations

from typing import Any

from manim import DEGREES, Mobject, Sphere, ThreeDScene, VGroup

from .base_scene import Z_INDEX_GUIAS, Z_INDEX_HUD, _ComunPlantilla, resolver_mostrar_guias
from .configuracion import COLOR_FONDO_GLOBAL, aplicar_configuracion_global
from .guias_visuales import obtener_todas_las_guias
from .tipografia import registrar_fuentes

PHI_INICIAL = 75 * DEGREES
THETA_INICIAL = 30 * DEGREES


class PlantillaShort3D(_ComunPlantilla, ThreeDScene):
    """Equivalente 3D de ``PlantillaShort``: orientación inicial estilo 3B1B y HUD fijo a cámara.

    ``fijar_a_camara`` usa ``add_fixed_in_frame_mobjects`` (coordenadas de pantalla: el mob no rota
    ni se aleja con la cámara). ``mostrar_guias_seguras=None`` ⇒ lee ``SHORT_GUIAS``.
    """

    def __init__(self, mostrar_guias_seguras: bool | None = None, **kwargs: Any) -> None:
        self.mostrar_guias_seguras = resolver_mostrar_guias(mostrar_guias_seguras)
        aplicar_configuracion_global()
        super().__init__(**kwargs)

    def setup(self) -> None:
        """Fondo, fuentes, orientación inicial, capa HUD y guías (idempotente)."""
        self.camera.background_color = COLOR_FONDO_GLOBAL
        self._fuente_serif_disponible = registrar_fuentes()
        if getattr(self, "_plantilla_preparada", False):
            return
        self._plantilla_preparada = True
        # Orientación inicial clásica de 3B1B (ligeramente inclinada)
        self.set_camera_orientation(phi=PHI_INICIAL, theta=THETA_INICIAL)
        self.capa_hud = VGroup()
        self.add(self.capa_hud)
        self.guias = None
        if self.mostrar_guias_seguras:
            self.guias = obtener_todas_las_guias()
            self.fijar_a_camara(self.guias, z_index=Z_INDEX_GUIAS)
        self._crear_subtitulos()

    def _anclar_subtitulos(self, subtitulos) -> None:
        # Contenedor fijo al cuadro; SubtitulosKaraoke registra como fijos los glifos de cada bloque.
        self.fijar_a_camara(subtitulos)

    def fijar_a_camara(self, *mobs: Mobject, z_index: int = Z_INDEX_HUD) -> None:
        """Fija ``mobs`` al cuadro (no rotan ni se escalan con la cámara 3D)."""
        for mob in mobs:
            mob.set_z_index(z_index)
            if mob not in self.capa_hud.submobjects:
                self.capa_hud.add(mob)
        self.add_fixed_in_frame_mobjects(*mobs)
        # add_fixed_in_frame_mobjects hace self.add(mob), que "disuelve" la capa: la consolidamos.
        self.add(self.capa_hud)

    def soltar_de_camara(self, *mobs: Mobject) -> None:
        """Deshace ``fijar_a_camara``: el mob vuelve a moverse con la cámara 3D."""
        self.remove_fixed_in_frame_mobjects(*mobs)
        for mob in mobs:
            if mob in self.capa_hud.submobjects:
                self.capa_hud.remove(mob)
            self.add(mob)


def crear_esfera_transparente(radio, color, opacidad=0.2, resolucion=(15, 30)):
    """
    Genera una esfera con estilo "Kepler", optimizada para no colapsar el renderizado.
    """
    esfera = Sphere(
        radius=radio,
        resolution=resolucion,
    )
    esfera.set_color(color)
    esfera.set_opacity(opacidad)
    return esfera
