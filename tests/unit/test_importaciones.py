"""Verifica que cada modulo existente de toolkit sea importable y que los
nombres publicos de compatibilidad (ver CLAUDE.md y plan_calidad_3b1b.md
seccion 2) sigan existiendo.
"""

import importlib

import pytest

MODULOS_TOOLKIT = [
    "toolkit",
    "toolkit.algebra_visual",
    "toolkit.base_scene",
    "toolkit.configuracion",
    "toolkit.estilos",
    "toolkit.geometria_visual",
    "toolkit.guias_visuales",
    "toolkit.motor_algebra",
    "toolkit.motor_geometria",
    "toolkit.utils_3d",
    "toolkit.utils_escalas",
    "toolkit.utils_grafos",
]

# Nombres publicos de compatibilidad exigidos por modulo (solo modulos que los definen).
NOMBRES_COMPATIBILIDAD = {
    "toolkit.base_scene": ["PlantillaShort"],
    "toolkit.utils_3d": ["PlantillaShort3D", "crear_esfera_transparente"],
    "toolkit.utils_escalas": [
        "PlantillaShortZoom",
        "crear_odometro",
        "zoom_out_exponencial",
    ],
    "toolkit.estilos": [
        "COLORES_MARCA",
        "MAPA_COLORES_MATEMATICOS",
        "FUENTE_TITULO",
        "FUENTE_CUERPO",
        "FUENTE_MATEMATICA",
        "GROSOR_LINEA_FINA",
        "GROSOR_LINEA_MEDIA",
        "GROSOR_LINEA_GRUESA",
    ],
    "toolkit.algebra_visual": ["EcuacionColoreada", "animar_paso_algebraico"],
    "toolkit.motor_algebra": ["resolver_ecuacion_cuadratica"],
    "toolkit.motor_geometria": [
        "extraer_regiones_intersecadas",
        "calcular_interseccion_rectas",
    ],
    "toolkit.geometria_visual": ["LineaAuxiliar", "EtiquetaAngulo"],
    "toolkit.utils_grafos": ["crear_red_neuronal", "pulso_de_activacion"],
}


@pytest.mark.parametrize("nombre_modulo", MODULOS_TOOLKIT)
def test_modulo_importable(nombre_modulo):
    """Cada modulo existente de toolkit debe poder importarse sin error."""
    modulo = importlib.import_module(nombre_modulo)
    assert modulo is not None


@pytest.mark.parametrize("nombre_modulo", sorted(NOMBRES_COMPATIBILIDAD))
def test_nombres_compatibilidad_existen(nombre_modulo):
    """Los nombres publicos de compatibilidad listados en el plan deben existir."""
    modulo = importlib.import_module(nombre_modulo)
    for nombre in NOMBRES_COMPATIBILIDAD[nombre_modulo]:
        assert hasattr(modulo, nombre), (
            f"{nombre_modulo} deberia exponer '{nombre}' por compatibilidad"
        )
