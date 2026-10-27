"""El runtime deja los objetos registrados enteros y sin saltos de valor tras cada grupo de pasos (un ``play``)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
import yaml
from manim import tempconfig

TRES_LINEAS = (
    "from toolkit.guion.runtime import escena_desde_yaml\n\n\n"
    "class {clase}(escena_desde_yaml(\"guion_tecnico.yaml\")):\n    pass\n"
)
NARRACION = "Un millón de datos. Pregunta uno, dos y tres: la barra se parte, y el tiempo se compara."


def _guion(pasos: list[dict]) -> dict:
    return {"version": 1, "meta": {"slug": "grupos", "titulo": "Grupos", "clase": "Grupos"},
            "segmentos": [{"narracion": NARRACION, "pasos": pasos}]}


def _escena(tmp_path: Path, datos: dict, nombre: str):
    from toolkit.narracion import MotorNarracion

    (tmp_path / "guion_tecnico.yaml").write_text(yaml.safe_dump(datos, allow_unicode=True), encoding="utf-8")
    ruta = tmp_path / "escena.py"
    ruta.write_text(TRES_LINEAS.format(clase=datos["meta"]["clase"]), encoding="utf-8")
    spec = importlib.util.spec_from_file_location(nombre, ruta)
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[nombre] = modulo
    spec.loader.exec_module(modulo)

    class Offline(getattr(modulo, datos["meta"]["clase"])):
        def setup(self):
            super().setup()
            self._motor_narracion = MotorNarracion(dir_cache=tmp_path / "tts", permitir_red=False)

    return Offline


def _render(tmp_path: Path, pasos: list[dict], nombre: str):
    clase = _escena(tmp_path, _guion(pasos), nombre)
    config = {"quality": "low_quality", "dry_run": True, "media_dir": str(tmp_path / "media"), "disable_caching": True}
    with tempconfig(config):
        escena = clase()
        escena.render()
    return escena


def _base() -> list[dict]:
    return [
        {"en": "inicio", "hacer": "mostrar", "id": "odo", "tipo": "odometro", "valor": 16, "rotulo": "Datos"},
        {"en": "datos", "hacer": "mostrar", "id": "barra", "tipo": "barra", "valor": 1, "segmentos": 16,
         "zona": {"de": "odo", "lado": "abajo", "espacio": 0.5}},
    ]


@pytest.mark.render
def test_grupo_con_parte_y_objeto_deja_la_barra_entera_sin_ayuda_de_los_verbos(tmp_path, monkeypatch):
    """partir (anima relleno/divisiones) + pulsar (anima la barra) + contar (anima el número) en un mismo play.

    Se anula ``reconsolidar_despues`` de los verbos: el re-ensamblado lo hace solo el runtime.
    """
    from toolkit.guion.catalogo import contadores

    monkeypatch.setattr(contadores, "reconsolidar_despues", lambda ctx, ref: None)
    pasos = _base() + [
        {"en": "uno", "hacer": "partir", "objeto": "barra", "veces": 1, "dur": 0.8},
        {"en": "uno", "hacer": "pulsar", "objeto": "barra", "dur": 0.8},
        {"en": "uno", "hacer": "contar", "objeto": "odo", "a": 8, "dur": 0.8},
    ]
    escena = _render(tmp_path, pasos, "escena_grupo_entera")
    ctx = escena.contexto_guion
    for registrado in (ctx.objetos["barra"], ctx.objetos["odo"]):
        assert registrado in escena.mobjects, "el objeto debe volver a ser UNA entrada de la escena"
        assert len([m for m in escena.mobjects if m is not registrado and set(m.get_family()) & set(registrado.get_family())]) == 0
    barra = ctx.objetos["barra"]
    familia = barra.get_family()
    assert familia.index(ctx.parte(barra, "divisiones")) > familia.index(barra.barra_guion.relleno)
    assert len(barra.submobjects) == 5


@pytest.mark.render
def test_cadena_de_contar_en_un_grupo_no_salta_atras(tmp_path, monkeypatch):
    from toolkit.guion.catalogo import contadores

    valores: list[float] = []
    original = contadores.NumeroOdometro.set_value

    def registrar(self, numero):
        valores.append(float(numero))
        return original(self, numero)

    monkeypatch.setattr(contadores.NumeroOdometro, "set_value", registrar)
    pasos = _base()[:1] + [
        {"en": "datos", "hacer": "contar", "objeto": "odo", "a": 100, "dur": 0.4},
        {"en": "datos", "hacer": "contar", "objeto": "odo", "a": 60, "dur": 0.4, "retraso": 0.5},
        {"en": "datos", "hacer": "contar", "objeto": "odo", "a": 20, "dur": 0.4, "retraso": 1.0},
    ]
    escena = _render(tmp_path, pasos, "escena_grupo_cadena")
    tramo = valores[valores.index(100):]
    assert tramo[-1] == 20
    assert all(b <= a for a, b in zip(tramo, tramo[1:])), tramo
    assert escena.contexto_guion.objetos["odo"].partes_guion["numero"].get_value() == 20
