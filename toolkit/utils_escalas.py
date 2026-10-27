"""Utilidades de escalas masivas: odómetro y zoom-out de cámara.

``PlantillaShortZoom`` se mantiene por compatibilidad: es un alias de ``PlantillaShort``,
que ya hereda de ``MovingCameraScene``.
"""

from __future__ import annotations

from manim import DecimalNumber, ValueTracker

from .base_scene import PlantillaShort

PlantillaShortZoom = PlantillaShort  # alias de compatibilidad


def crear_odometro(valor_inicial=0, font_size=48, color="#FFFFFF", num_decimales=0):
    """
    Retorna una tupla: (Tracker_Matematico, Objeto_Visual).
    Al animar el Tracker (tracker.animate.set_value(1000000)), el objeto visual
    "rueda" por todos los números intermedios automáticamente, añadiendo comas de miles.
    """
    tracker = ValueTracker(valor_inicial)

    numero_visual = DecimalNumber(
        valor_inicial,
        show_ellipsis=False,
        num_decimal_places=num_decimales,
        include_sign=False,
        group_with_commas=True,  # Vital para números masivos (ej. 1,000,000)
        font_size=font_size,
        color=color,
    )

    # Atar el visual al valor interno matemático
    numero_visual.add_updater(lambda d: d.set_value(tracker.get_value()))

    return tracker, numero_visual


def zoom_out_exponencial(escena, factor: float = 10, run_time: float = 3.0):
    """Animación que multiplica por ``factor`` el ancho visible de la cámara en ``run_time`` s.

    En manim 0.21 ``_AnimationBuilder`` no tiene ``set_run_time`` (encadenarlo solo creaba un
    atributo en el mob destino), así que el ``run_time`` se pasa al builder: ``animate(run_time=...)``.
    """
    frame = escena.camera.frame
    ancho_actual = frame.get_width()
    return frame.animate(run_time=run_time).set_width(ancho_actual * factor)
