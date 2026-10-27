"""Catálogo de piezas del guion técnico: importar este paquete registra todos los tipos y verbos.

Un módulo por familia. Para sumar una familia: crear el módulo con sus ``@objeto``/``@accion`` y agregarlo a la
importación de abajo; el runtime y la validación no cambian.
"""

from toolkit.guion.catalogo import (  # noqa: F401  (registran al importar)
    acciones,
    algebra,
    algoritmos,
    camara_sonido,
    contadores,
    graficos,
    nucleo,
    texto_formas,
)

MODULOS = (nucleo, texto_formas, camara_sonido, acciones, algebra, algoritmos, graficos, contadores)
