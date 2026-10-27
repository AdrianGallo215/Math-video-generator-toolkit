"""Tests del sistema de diseno (paleta, tipografia, trazos, tiempos) de
toolkit/estilos.py.
"""

import re

import pytest

from toolkit import estilos

HEX_VALIDO = re.compile(r"^#[0-9A-F]{6}$")

NOMBRES_COLORES_HEX = [
    "AZUL",
    "AMARILLO",
    "VERDE",
    "ROJO",
    "NARANJA",
    "MORADO",
    "TURQUESA",
    "GRIS",
    "GRIS_OSCURO",
    "BLANCO",
    "FONDO",
]


@pytest.mark.parametrize("nombre", NOMBRES_COLORES_HEX)
def test_colores_base_son_hex_validos(nombre):
    valor = getattr(estilos, nombre)
    assert HEX_VALIDO.match(valor), f"{nombre}={valor!r} no es hex #RRGGBB valido"


def test_colores_marca_son_hex_validos():
    for clave, valor in estilos.COLORES_MARCA.items():
        assert HEX_VALIDO.match(valor), f"COLORES_MARCA[{clave!r}]={valor!r} invalido"


def test_color_semantico_son_hex_validos():
    for token, valor in estilos.COLOR_SEMANTICO.items():
        assert HEX_VALIDO.match(valor), f"COLOR_SEMANTICO[{token!r}]={valor!r} invalido"


def test_orden_tamanos_fuente():
    assert (
        estilos.FUENTE_MINIMA
        <= estilos.FUENTE_ETIQUETA
        < estilos.FUENTE_CUERPO
        < estilos.FUENTE_TITULO
    )


def test_mapa_colores_matematicos_es_alias_de_color_semantico():
    assert estilos.MAPA_COLORES_MATEMATICOS is estilos.COLOR_SEMANTICO


def test_claves_color_semantico_son_una_letra_o_comando_latex():
    for token in estilos.COLOR_SEMANTICO:
        assert len(token) == 1 or token.startswith("\\"), (
            f"Clave {token!r} de COLOR_SEMANTICO deberia ser una letra o comando LaTeX"
        )


def test_paleta_secuencial_sin_duplicados():
    assert len(estilos.PALETA_SECUENCIAL) == len(set(estilos.PALETA_SECUENCIAL))


def test_nombres_compatibilidad_siguen_existiendo():
    for nombre in (
        "COLORES_MARCA",
        "MAPA_COLORES_MATEMATICOS",
        "FUENTE_TITULO",
        "FUENTE_CUERPO",
        "FUENTE_MATEMATICA",
        "GROSOR_LINEA_FINA",
        "GROSOR_LINEA_MEDIA",
        "GROSOR_LINEA_GRUESA",
    ):
        assert hasattr(estilos, nombre)
