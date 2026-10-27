"""Guion técnico ejecutable: un YAML validado que el runtime compila en una escena de manim.

Módulos (se importan por separado; este paquete no importa manim para que ``registro``/``esquema`` sirvan sin escena):

- ``registro``: ``Param``, ``Definicion``, ``CATALOGO``, decoradores ``objeto``/``accion``, ``MODIFICADORES``, ``manifiesto()``.
- ``esquema``: dataclasses ``Guion``/``Segmento``/``Paso``, ``cargar(ruta)`` (errores E1), cálculos y semántica temporal.
- ``contexto``: ``ContextoGuion`` (objetos, zonas, colores, efectos persistentes) que reciben las piezas.
- ``validar``: ``validar(ruta, con_voz=False) -> ReporteValidacion`` (E1–E10, A1–A9).
- ``runtime``: ``escena_desde_yaml(ruta)`` -> clase de escena lista para manim.
- ``catalogo``: las piezas (importarlo las registra).
"""
