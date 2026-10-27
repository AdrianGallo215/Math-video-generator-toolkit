"""Tests de toolkit.configuracion: perfiles de calidad 9:16."""

from manim import tempconfig

from toolkit.configuracion import (
    PERFILES,
    aplicar_configuracion_global,
    detectar_perfil,
)


def test_low_quality_da_perfil_borrador():
    with tempconfig({"quality": "low_quality"}):
        perfil = aplicar_configuracion_global()
        assert perfil == PERFILES["borrador"]
        assert perfil.ancho_px == 540
        assert perfil.alto_px == 960
        assert perfil.fps == 30
        from manim import config

        assert config.frame_width == 9.0
        assert config.frame_height == 16.0


def test_medium_quality_da_perfil_media():
    with tempconfig({"quality": "medium_quality"}):
        perfil = aplicar_configuracion_global()
        assert perfil == PERFILES["media"]


def test_high_quality_da_perfil_alta():
    with tempconfig({"quality": "high_quality"}):
        perfil = aplicar_configuracion_global()
        assert perfil == PERFILES["alta"]
        assert perfil.ancho_px == 1080
        assert perfil.alto_px == 1920
        assert perfil.fps == 60


def test_aplicar_es_idempotente():
    with tempconfig({"quality": "low_quality"}):
        primero = aplicar_configuracion_global()
        segundo = aplicar_configuracion_global()
        assert primero == segundo == PERFILES["borrador"]
        tercero = detectar_perfil()
        assert tercero == PERFILES["borrador"]


def test_variable_entorno_gana_sobre_flag_de_manim(monkeypatch):
    monkeypatch.setenv("SHORT_CALIDAD", "media")
    with tempconfig({"quality": "low_quality"}):
        perfil = detectar_perfil()
        assert perfil == PERFILES["media"]


def test_variable_entorno_invalida_se_ignora(monkeypatch):
    monkeypatch.setenv("SHORT_CALIDAD", "no_existe")
    with tempconfig({"quality": "low_quality"}):
        perfil = detectar_perfil()
        assert perfil == PERFILES["borrador"]
