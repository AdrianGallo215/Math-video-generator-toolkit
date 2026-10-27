"""Tests de tipografia: registro de fuentes, helpers Texto/TextoTex."""

import pytest

from toolkit.estilos import FUENTE_MINIMA
from toolkit.tipografia import (
    FUENTE_SERIF,
    Texto,
    TextoTex,
    fuente_por_defecto,
    plantilla_tex_es,
    registrar_fuentes,
)


def test_registrar_fuentes_es_idempotente():
    primero = registrar_fuentes()
    segundo = registrar_fuentes()
    assert primero == segundo


def test_texto_tamano_menor_que_minimo_lanza_value_error():
    with pytest.raises(ValueError):
        Texto("Hola", tamano=FUENTE_MINIMA - 1)


def test_fuente_por_defecto_es_cmu_serif_si_esta_registrada():
    registrar_fuentes()
    fuente = fuente_por_defecto()
    assert fuente in (FUENTE_SERIF, "")


def test_plantilla_tex_es_singleton():
    assert plantilla_tex_es() is plantilla_tex_es()


@pytest.mark.render
def test_texto_construye_busqueda():
    texto = Texto("Búsqueda")
    assert texto.width > 0


@pytest.mark.render
def test_texto_tex_construye_con_tildes_y_enie():
    texto = TextoTex(r"¿Por qué? Ñandú áéíóú")
    assert texto.width > 0
