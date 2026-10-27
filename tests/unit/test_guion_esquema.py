"""Tests del esquema del guion técnico: carga, anclas, dur, líneas y errores E1."""

import pytest

from toolkit.guion.esquema import (
    Ancla,
    ErrorGuion,
    Guion,
    cargar,
    cargar_texto,
    parsear_ancla,
    parsear_dur,
)

MINIMO = """\
version: 1
meta:
  slug: prueba
  titulo: "Prueba"
  clase: Prueba
segmentos:
  - narracion: "Fíjate en este cuadrado azul."
    pasos:
      - {en: inicio, hacer: mostrar, id: c, tipo: forma, figura: rect}
      - {en: cuadrado, hacer: resaltar, objeto: c}
"""


def test_cargar_texto_minimo():
    guion = cargar_texto(MINIMO)
    assert isinstance(guion, Guion)
    assert guion.meta.clase == "Prueba"
    seg = guion.segmentos[0]
    assert seg.pausa == pytest.approx(0.3)
    assert seg.relleno is True
    assert [p.hacer for p in seg.pasos] == ["mostrar", "resaltar"]
    paso = seg.pasos[1]
    assert paso.en == Ancla("palabra", "cuadrado", 1, 0.0)
    assert paso.params == {"objeto": "c"}
    assert paso.ubicacion == "segmento 1, paso 2"
    assert paso.linea == 10


def test_cargar_desde_archivo_guarda_ruta(tmp_path):
    ruta = tmp_path / "guion_tecnico.yaml"
    ruta.write_text(MINIMO, encoding="utf-8")
    guion = cargar(ruta)
    assert guion.ruta == ruta.resolve()
    assert guion.dir_base == tmp_path.resolve()


@pytest.mark.parametrize(
    "valor, esperado",
    [
        ("inicio", Ancla("inicio")),
        ("fin", Ancla("fin")),
        ("Dieciséis", Ancla("palabra", "Dieciséis", 1)),
        (["mayor", 2], Ancla("palabra", "mayor", 2)),
        ({"ancla": "mayor", "ocurrencia": 2, "mas": 0.4}, Ancla("palabra", "mayor", 2, 0.4)),
        ({"ancla": ["mayor", 2], "mas": -0.2}, Ancla("palabra", "mayor", 2, -0.2)),
        ({"ancla": "inicio", "mas": 0.5}, Ancla("inicio", "", 1, 0.5)),
        (7, Ancla("palabra", "7", 1)),
    ],
)
def test_parsear_ancla(valor, esperado):
    assert parsear_ancla(valor) == esperado


@pytest.mark.parametrize("valor", [["mayor"], ["mayor", 0], {"mas": 1}, {"ancla": "x", "otra": 1}, "", None])
def test_parsear_ancla_invalida(valor):
    with pytest.raises(ValueError):
        parsear_ancla(valor)


def test_clave_de_ancla_normaliza():
    assert parsear_ancla("Dieciséis").clave == parsear_ancla(["dieciseis", 1]).clave
    assert parsear_ancla("mayor").clave != parsear_ancla(["mayor", 2]).clave


def test_parsear_dur():
    assert parsear_dur(None) is None
    assert parsear_dur(1.5) == 1.5
    assert parsear_dur("resto") == "resto"
    assert parsear_dur({"hasta": "ocho"}) == Ancla("palabra", "ocho", 1)
    for malo in (0, -1, "todo", {"hasta": None}, True):
        with pytest.raises(ValueError):
            parsear_dur(malo)


def test_yaml_mal_formado_da_e1_con_linea():
    with pytest.raises(ErrorGuion) as info:
        cargar_texto("version: 1\nmeta: {slug: a\n")
    (hallazgo,) = info.value.hallazgos
    assert hallazgo.codigo == "E1"
    assert hallazgo.linea is not None


def test_clave_desconocida_en_raiz_sugiere_la_parecida():
    with pytest.raises(ErrorGuion) as info:
        cargar_texto(MINIMO + "segmento: []\n")
    mensajes = [h.mensaje for h in info.value.hallazgos]
    assert any("segmento" in m and "segmentos" in m for m in mensajes), mensajes
    assert all(h.codigo == "E1" for h in info.value.hallazgos)


def test_clave_duplicada_es_e1():
    texto = MINIMO.replace("  clase: Prueba\n", "  clase: Prueba\n  clase: Otra\n")
    with pytest.raises(ErrorGuion) as info:
        cargar_texto(texto)
    assert any("duplicada" in h.mensaje for h in info.value.hallazgos)


@pytest.mark.parametrize(
    "reemplazo, fragmento",
    [
        (("{en: cuadrado, hacer: resaltar, objeto: c}", "{en: cuadrado, objeto: c}"), "hacer"),
        (("{en: cuadrado, hacer: resaltar, objeto: c}", "{hacer: resaltar, objeto: c}"), "en"),
        (("{en: cuadrado, hacer: resaltar, objeto: c}", "{en: [a, b, c], hacer: resaltar, objeto: c}"), "ancla"),
        (("{en: cuadrado, hacer: resaltar, objeto: c}", "{en: cuadrado, hacer: resaltar, objeto: c, dur: 0}"), "dur"),
        (("{en: cuadrado, hacer: resaltar, objeto: c}", "{en: cuadrado, hacer: resaltar, objeto: c, retraso: -1}"), "retraso"),
        (("clase: Prueba", "clase: 1Prueba"), "clase"),
        (("version: 1", "version: 2"), "version"),
        (('narracion: "Fíjate en este cuadrado azul."', "narracion: ''"), "narracion"),
    ],
)
def test_errores_estructurales_e1(reemplazo, fragmento):
    viejo, nuevo = reemplazo
    with pytest.raises(ErrorGuion) as info:
        cargar_texto(MINIMO.replace(viejo, nuevo))
    assert any(fragmento in h.mensaje for h in info.value.hallazgos), [str(h) for h in info.value.hallazgos]


def test_bloques_opcionales_zonas_calculos_escenario():
    texto = MINIMO + """\
zonas:
  arriba: {de: principal, filas: [1, 1], fila: 0}
  izq: {de: arriba, columnas: [1, 1], columna: 0, espacio: 0.3}
calculos:
  sol: {motor: lineal, a: 2, b: 3, c: 11}
escenario:
  objetos:
    - {id: t, tipo: texto, texto: hola, zona: arriba}
    - {id: u, tipo: texto, texto: chao, oculto: false}
  disposicion:
    - {apilar: [t, u], espacio: 0.5}
subtitulos: {cuadrado: azul}
"""
    guion = cargar_texto(texto)
    assert guion.zonas["izq"].columnas == [1, 1] and guion.zonas["izq"].espacio == 0.3
    assert guion.calculos["sol"].motor == "lineal"
    assert guion.calculos["sol"].params == {"a": 2, "b": 3, "c": 11}
    assert [o.id for o in guion.escenario] == ["t", "u"]
    assert guion.escenario[0].oculto is True and guion.escenario[1].oculto is False
    assert guion.disposiciones[0].modo == "apilar" and guion.disposiciones[0].ids == ["t", "u"]
    assert guion.subtitulos == {"cuadrado": "azul"}
