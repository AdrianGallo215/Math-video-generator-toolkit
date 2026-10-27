"""Tests de la validación del guion: cada regla E*/A* con un guion que la dispara y otro válido."""

from pathlib import Path

import pytest
import yaml

import toolkit.guion.catalogo  # noqa: F401  (registra las piezas: la parametrización las recorre)
from toolkit.guion import registro
from toolkit.guion.validar import guion_de_ejemplo, validar
from toolkit.narracion import PalabraTemporizada, SegmentoNarrado

NARRACION = "Fíjate en este cuadrado azul que aparece ahora. Luego se va."


def _paso(en, hacer, **params):
    return {"en": en, "hacer": hacer, **params}


def _guion(pasos=None, narracion=NARRACION, segmentos=None, **extra) -> dict:
    datos = {
        "version": 1,
        "meta": {"slug": "prueba", "titulo": "Prueba", "clase": "Prueba"},
        "segmentos": segmentos if segmentos is not None else [{"narracion": narracion, "pasos": pasos or []}],
    }
    datos.update(extra)
    return datos


def _validar(tmp_path: Path, datos: dict, **kw):
    ruta = tmp_path / "guion_tecnico.yaml"
    ruta.write_text(yaml.safe_dump(datos, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return validar(ruta, **kw)


def _codigos(hallazgos) -> list[str]:
    return [h.codigo for h in hallazgos]


MOSTRAR_CUADRADO = _paso("inicio", "mostrar", id="c", tipo="forma", figura="rect")
RESALTAR_CUADRADO = _paso("cuadrado", "resaltar", objeto="c")
QUITAR_CUADRADO = _paso("va", "quitar", objeto="c")
VALIDO = [MOSTRAR_CUADRADO, RESALTAR_CUADRADO, QUITAR_CUADRADO]


def test_guion_valido_no_tiene_errores(tmp_path):
    reporte = _validar(tmp_path, _guion(VALIDO))
    assert reporte.ok, reporte.texto()
    assert reporte.resumen["segmentos"] == 1 and reporte.resumen["pasos"] == 3
    assert reporte.guion is not None


# --- E1 --------------------------------------------------------------------------------------------


def test_e1_yaml_roto_no_lanza_y_reporta(tmp_path):
    ruta = tmp_path / "g.yaml"
    ruta.write_text("version: 1\nmeta: {slug: [\n", encoding="utf-8")
    reporte = validar(ruta)
    assert _codigos(reporte.errores) == ["E1"]


def test_e1_parametro_desconocido_sugiere(tmp_path):
    reporte = _validar(tmp_path, _guion([MOSTRAR_CUADRADO, _paso("cuadrado", "resaltar", objeto="c", colr="rojo")]))
    assert "E1" in _codigos(reporte.errores)
    assert any("color" in h.mensaje for h in reporte.errores)


# --- E2 --------------------------------------------------------------------------------------------


def test_e2_verbo_inexistente_sugiere(tmp_path):
    reporte = _validar(tmp_path, _guion([MOSTRAR_CUADRADO, _paso("cuadrado", "resaltr", objeto="c")]))
    (h,) = [h for h in reporte.errores if h.codigo == "E2"]
    assert "resaltar" in h.mensaje and h.ubicacion == "segmento 1, paso 2"


def test_e2_tipo_usado_como_verbo_y_tipo_inexistente(tmp_path):
    reporte = _validar(tmp_path, _guion([_paso("inicio", "texto", id="t", texto="hola"),
                                         _paso("cuadrado", "mostrar", id="c", tipo="formas", figura="rect")]))
    mensajes = [h.mensaje for h in reporte.errores if h.codigo == "E2"]
    assert any("es un tipo de objeto" in m for m in mensajes)
    assert any("'forma'" in m for m in mensajes)


# --- E3 --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "paso",
    [
        _paso("inicio", "mostrar", id="t", tipo="texto"),  # falta texto
        _paso("inicio", "mostrar", id="t", tipo="texto", texto="a", tamano="grande"),  # tipo incorrecto
        _paso("inicio", "mostrar", id="c", tipo="forma", figura="triangulo"),  # fuera de opciones
        _paso("inicio", "mostrar", id="c", tipo="forma", figura="rect", proporcion=2),  # validación del tipo
        _paso("inicio", "mostrar", id="C mayus", tipo="forma", figura="rect"),  # id inválido
    ],
)
def test_e3_parametros_invalidos(tmp_path, paso):
    reporte = _validar(tmp_path, _guion([paso]))
    assert "E3" in _codigos(reporte.errores), reporte.texto()


# --- E4 --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "pasos, fragmento",
    [
        ([RESALTAR_CUADRADO], "no existe"),
        ([MOSTRAR_CUADRADO, _paso("cuadrado", "quitar", objeto="c"), _paso("va", "resaltar", objeto="c")], "no existe"),
        ([MOSTRAR_CUADRADO, _paso("cuadrado", "mostrar", id="c", tipo="texto", texto="x")], "ya existe"),
        ([_paso("inicio", "detener", objeto="cam")], "efecto"),
        ([MOSTRAR_CUADRADO, _paso("cuadrado", "transformar", objeto="c", a={"id": "d", "tipo": "texto", "texto": "d"}),
          _paso("va", "resaltar", objeto="c")], "no existe"),
        ([MOSTRAR_CUADRADO, _paso("cuadrado", "mostrar", id="g", tipo="grupo", de=["c", "zz"])], "no existe"),
    ],
)
def test_e4_ciclo_de_vida(tmp_path, pasos, fragmento):
    reporte = _validar(tmp_path, _guion(pasos))
    errores = [h for h in reporte.errores if h.codigo == "E4"]
    assert errores and any(fragmento in h.mensaje for h in errores), reporte.texto()


def test_e4_valido_reutilizar_id_tras_quitar_y_transformar_hereda_id(tmp_path):
    pasos = [
        MOSTRAR_CUADRADO,
        _paso("cuadrado", "quitar", objeto="c"),
        _paso("azul", "mostrar", id="c", tipo="texto", texto="otra vez"),
        _paso("aparece", "transformar", objeto="c", a={"tipo": "texto", "texto": "nuevo"}),
        _paso("Luego", "resaltar", objeto="c"),
        _paso("va", "quitar", objeto="c"),
    ]
    reporte = _validar(tmp_path, _guion(pasos))
    assert reporte.ok, reporte.texto()


def test_e4_grupo_quitar_quita_sus_miembros(tmp_path):
    pasos = [
        _paso("inicio", "mostrar", id="a", tipo="texto", texto="a"),
        _paso("inicio", "mostrar", id="b", tipo="texto", texto="b", zona={"de": "a", "lado": "abajo"}),
        _paso("cuadrado", "mostrar", id="g", tipo="grupo", de=["a", "b"]),
        _paso("azul", "pulsar", objeto="g.a"),
        _paso("Luego", "quitar", objeto="g"),
        _paso("va", "resaltar", objeto="a"),
    ]
    reporte = _validar(tmp_path, _guion(pasos))
    assert [h.codigo for h in reporte.errores] == ["E4"], reporte.texto()
    assert reporte.errores[0].ubicacion == "segmento 1, paso 6"


# --- E5 / E6 -------------------------------------------------------------------------------------------


def test_e5_zona_inexistente_y_zona_derivada_valida(tmp_path):
    malo = _validar(tmp_path, _guion([_paso("inicio", "mostrar", id="t", tipo="texto", texto="x", zona="arrib")]))
    assert "E5" in _codigos(malo.errores)
    zonas = {"arriba": {"de": "principal", "filas": [1, 1], "fila": 0}}
    bueno = _validar(tmp_path, _guion([_paso("inicio", "mostrar", id="t", tipo="texto", texto="x", zona="arriba"),
                                       _paso("va", "quitar", objeto="t")], zonas=zonas))
    assert bueno.ok, bueno.texto()
    derivada_mala = _validar(tmp_path, _guion(VALIDO, zonas={"x": {"de": "nada", "filas": [1, 1], "fila": 0}}))
    assert "E5" in _codigos(derivada_mala.errores)


def test_e6_color_inexistente_en_paso_y_en_subtitulos(tmp_path):
    reporte = _validar(tmp_path, _guion([MOSTRAR_CUADRADO, _paso("cuadrado", "resaltar", objeto="c", color="celeste")],
                                        subtitulos={"cuadrado": "azull"}))
    e6 = [h for h in reporte.errores if h.codigo == "E6"]
    assert len(e6) == 2 and any("azul" in h.mensaje for h in e6)


# --- E7 --------------------------------------------------------------------------------------------


def test_e7_ancla_ausente_sugiere_y_lista_palabras(tmp_path):
    reporte = _validar(tmp_path, _guion([MOSTRAR_CUADRADO, _paso("cuadrdo", "resaltar", objeto="c")]))
    (h,) = [h for h in reporte.errores if h.codigo == "E7"]
    assert "'cuadrado'" in h.mensaje and "Palabras disponibles" in h.mensaje


def test_e7_ancla_retrocede_y_ocurrencia_inexistente(tmp_path):
    retrocede = _validar(tmp_path, _guion([MOSTRAR_CUADRADO, _paso("aparece", "resaltar", objeto="c"),
                                           _paso("cuadrado", "pulsar", objeto="c")]))
    assert any("retrocede" in h.mensaje for h in retrocede.errores)
    ocurrencia = _validar(tmp_path, _guion([MOSTRAR_CUADRADO, _paso(["cuadrado", 2], "resaltar", objeto="c")]))
    assert any("aparece 1 vez" in h.mensaje for h in ocurrencia.errores)


def test_e7_dur_hasta(tmp_path):
    malo = _validar(tmp_path, _guion([_paso("aparece", "mostrar", id="c", tipo="forma", figura="rect",
                                            dur={"hasta": "cuadrado"})]))
    assert any(h.codigo == "E7" and "posterior" in h.mensaje for h in malo.errores)
    bueno = _validar(tmp_path, _guion([_paso("cuadrado", "mostrar", id="c", tipo="forma", figura="rect",
                                             dur={"hasta": "aparece"}), _paso("va", "quitar", objeto="c")]))
    assert bueno.ok, bueno.texto()


# --- E8 / E9 / E10 ----------------------------------------------------------------------------------------


def test_e8_tamano_menor_que_minimo(tmp_path):
    reporte = _validar(tmp_path, _guion([_paso("inicio", "mostrar", id="t", tipo="texto", texto="x", tamano=30)]))
    assert "E8" in _codigos(reporte.errores)


def test_e9_personalizado(tmp_path):
    (tmp_path / "momentos.py").write_text("def momento_aja(ctx):\n    return None\n", encoding="utf-8")
    sin_archivo = _validar(tmp_path, _guion([_paso("inicio", "personalizado", archivo="otro.py", funcion="f")]))
    assert "E9" in _codigos(sin_archivo.errores)
    sin_funcion = _validar(tmp_path, _guion([_paso("inicio", "personalizado", archivo="momentos.py", funcion="momento")]))
    assert any(h.codigo == "E9" and "momento_aja" in h.mensaje for h in sin_funcion.errores)
    bueno = _validar(tmp_path, _guion([_paso("inicio", "personalizado", archivo="momentos.py", funcion="momento_aja",
                                             crea=["m"]), _paso("va", "quitar", objeto="m")]))
    assert bueno.ok, bueno.texto()
    assert bueno.resumen["pasos_personalizados"] == 1


def test_e10_calculos_y_sustitucion(tmp_path):
    calculos = {"sol": {"motor": "lineal", "a": 2, "b": 3, "c": 11},
                "traza": {"motor": "busqueda_binaria", "valores": [1, 3, 5, 7, 9], "objetivo": 7}}
    pasos = [
        _paso("inicio", "mostrar", id="t", tipo="texto", texto="{sol.4.explicacion}"),
        _paso("cuadrado", "mostrar", id="u", tipo="texto", texto="medio {traza.0.mid}", zona={"de": "t"}),
        _paso("va", "quitar", objeto=["t", "u"]),
    ]
    bueno = _validar(tmp_path, _guion(pasos, calculos=calculos))
    assert bueno.ok, bueno.texto()
    textos = [p.params.get("texto") for p in bueno.guion.segmentos[0].pasos]
    assert textos[:2] == ["Resultado: x = 4", "medio 2"]
    malo = _validar(tmp_path, _guion([_paso("inicio", "mostrar", id="t", tipo="texto", texto="{sol.9.latex}"),
                                      _paso("va", "mostrar", id="u", tipo="texto", texto="{sl.0.latex}")],
                                     calculos=calculos))
    assert _codigos(malo.errores).count("E10") == 2
    assert any("sol" in h.mensaje for h in malo.errores)
    motor_malo = _validar(tmp_path, _guion(VALIDO, calculos={"x": {"motor": "linea", "a": 1}}))
    assert "E2" in _codigos(motor_malo.errores)


def test_latex_con_llaves_no_se_confunde_con_calculos(tmp_path):
    pasos = [_paso("inicio", "mostrar", id="t", tipo="texto", texto="\\frac{1}{2} y {x}"), _paso("va", "quitar", objeto="t")]
    reporte = _validar(tmp_path, _guion(pasos, calculos={"sol": {"motor": "lineal", "a": 2, "b": 3, "c": 11}}))
    assert reporte.ok, reporte.texto()
    assert reporte.guion.segmentos[0].pasos[0].params["texto"] == "\\frac{1}{2} y {x}"


# --- Escenario --------------------------------------------------------------------------------------------


def test_escenario_reserva_y_revela(tmp_path):
    escenario = {
        "objetos": [
            {"id": "a", "tipo": "texto", "texto": "arriba"},
            {"id": "b", "tipo": "texto", "texto": "abajo", "zona": {"de": "a", "lado": "abajo"}},
            {"id": "fondo", "tipo": "forma", "figura": "rect", "oculto": False},
        ],
        "disposicion": [{"apilar": ["a", "b"], "espacio": 0.5}],
    }
    pasos = [_paso("inicio", "mostrar", id="a"), _paso("cuadrado", "mostrar", id="b"),
             _paso("azul", "resaltar", objeto=["a", "b", "fondo"]), _paso("va", "quitar", objeto=["a", "b", "fondo"])]
    bueno = _validar(tmp_path, _guion(pasos, escenario=escenario))
    assert bueno.ok, bueno.texto()
    assert "A4" not in _codigos(bueno.avisos)
    # usar antes de revelar, mostrar con tipo un reservado, disposición con id ajeno
    malos = _validar(tmp_path, _guion([_paso("inicio", "resaltar", objeto="a"),
                                       _paso("cuadrado", "mostrar", id="b", tipo="texto", texto="x")],
                                      escenario={**escenario, "disposicion": [{"apilar": ["a", "zz"]}]}))
    assert _codigos(malos.errores).count("E4") == 3, malos.texto()
    assert "A4" in _codigos(malos.avisos)  # 'b' reservado y nunca mostrado


# --- Avisos estáticos --------------------------------------------------------------------------------------


def test_a1_palabras_fuera_de_rango(tmp_path):
    corto = _validar(tmp_path, _guion(VALIDO))
    assert "A1" in _codigos(corto.avisos)
    frases = ". ".join(" ".join(["uno"] * 9) for _ in range(18)) + ". " + NARRACION
    largo_ok = _validar(tmp_path, _guion(VALIDO, narracion=frases))
    assert "A1" not in _codigos(largo_ok.avisos), largo_ok.resumen


def test_a2_frase_larga(tmp_path):
    larga = "Fíjate en este cuadrado azul que aparece ahora y que se queda un buen rato en la pantalla. Luego se va."
    reporte = _validar(tmp_path, _guion(VALIDO, narracion=larga))
    assert "A2" in _codigos(reporte.avisos)
    assert "A2" not in _codigos(_validar(tmp_path, _guion(VALIDO)).avisos)


def test_a3_segmento_sin_pasos(tmp_path):
    reporte = _validar(tmp_path, _guion(segmentos=[{"narracion": NARRACION, "pasos": VALIDO},
                                                   {"narracion": "Otra frase sin nada."}]))
    assert "A3" in _codigos(reporte.avisos) and reporte.ok


def test_a4_objeto_sin_uso(tmp_path):
    reporte = _validar(tmp_path, _guion([MOSTRAR_CUADRADO]))
    assert "A4" in _codigos(reporte.avisos)
    assert "A4" not in _codigos(_validar(tmp_path, _guion(VALIDO)).avisos)


def test_a8_efecto_sin_detener(tmp_path):
    pasos = VALIDO[:2] + [_paso("aparece", "camara", id="cam", objeto="c", factor=1.2)] + VALIDO[2:]
    sin_detener = _validar(tmp_path, _guion(pasos))
    assert "A8" in _codigos(sin_detener.avisos) and sin_detener.ok
    detenido = _validar(tmp_path, _guion(segmentos=[{"narracion": NARRACION, "pasos": pasos[:3]},
                                                    {"narracion": "Y la cámara vuelve.",
                                                     "pasos": [_paso("inicio", "detener", objeto="cam"),
                                                               _paso("vuelve", "quitar", objeto="c")]}]))
    assert detenido.ok, detenido.texto()
    assert "A8" not in _codigos(detenido.avisos)


# --- Con voz (A5 / A6 / A7 / E7 real) con un motor falso determinista ----------------------------------------


class MotorFalso:
    """Cada palabra dura ``paso`` s (80 % sonando); 0.9 s de silencio final como edge-tts."""

    def __init__(self, paso: float = 0.4, sustituir: dict | None = None) -> None:
        self.paso = paso
        self.sustituir = sustituir or {}

    def sintetizar(self, texto: str) -> SegmentoNarrado:
        palabras = [self.sustituir.get(p, p) for p in texto.split()]
        tiempos = [PalabraTemporizada(p, round(i * self.paso, 4), round(i * self.paso + 0.8 * self.paso, 4))
                   for i, p in enumerate(palabras)]
        return SegmentoNarrado(texto, Path("falso.wav"), len(palabras) * self.paso + 0.9, tiempos, sintetico=False)


def test_a5_tramo_quieto_sin_relleno_y_relleno_lo_evita(tmp_path):
    # 11 palabras * 0.4 = 4.4 s; solo hay animación al inicio (1 s) y al final.
    pasos = [MOSTRAR_CUADRADO, _paso("va", "quitar", objeto="c")]
    sin_relleno = _validar(tmp_path, _guion(segmentos=[{"narracion": NARRACION, "pasos": pasos, "relleno": False}]),
                           con_voz=True, motor=MotorFalso())
    assert "A5" in _codigos(sin_relleno.avisos)
    assert sin_relleno.resumen["tramos_quietos"]
    con_relleno = _validar(tmp_path, _guion(pasos), con_voz=True, motor=MotorFalso())
    assert "A5" not in _codigos(con_relleno.avisos), con_relleno.texto()
    assert "A6" in _codigos(con_relleno.avisos)  # 4.7 s: fuera de 60-90 s


def test_a6_duracion_en_rango(tmp_path):
    # ~160 palabras a 0.4 s = 64 s
    narracion = ". ".join(" ".join(["uno"] * 9) for _ in range(17)) + ". " + NARRACION
    reporte = _validar(tmp_path, _guion(VALIDO, narracion=narracion), con_voz=True, motor=MotorFalso())
    assert "A6" not in _codigos(reporte.avisos), reporte.resumen
    assert 60 <= reporte.resumen["duracion_s"] <= 90


def test_a7_paso_que_arranca_tarde_y_dur_recortada(tmp_path):
    # "este" suena a 0.8 s pero el mostrar dura 3 s; el pulsar arranca tarde y su {hasta} queda corto.
    pasos = [_paso("inicio", "mostrar", id="c", tipo="forma", figura="rect", dur=3.0),
             _paso("este", "resaltar", objeto="c"),
             _paso("azul", "pulsar", objeto="c", dur={"hasta": "que"}),
             _paso("va", "quitar", objeto="c")]
    reporte = _validar(tmp_path, _guion(pasos), con_voz=True, motor=MotorFalso())
    a7 = [h.mensaje for h in reporte.avisos if h.codigo == "A7"]
    assert any("tarde" in m for m in a7), reporte.texto()
    assert any("dur hasta" in m for m in a7), reporte.texto()
    assert not reporte.errores


def test_e7_con_voz_palabra_que_la_voz_dice_distinto(tmp_path):
    reporte = _validar(tmp_path, _guion(VALIDO), con_voz=True, motor=MotorFalso(sustituir={"cuadrado": "cuadrado,"}))
    assert reporte.ok  # la puntuación se normaliza
    reporte = _validar(tmp_path, _guion(VALIDO), con_voz=True, motor=MotorFalso(sustituir={"cuadrado": "cuadro"}))
    assert any(h.codigo == "E7" and "voz real" in h.mensaje for h in reporte.errores)


def test_voz_se_omite_si_hay_errores_estaticos(tmp_path):
    reporte = _validar(tmp_path, _guion([RESALTAR_CUADRADO]), con_voz=True, motor=MotorFalso())
    assert "omitida" in reporte.resumen["voz"]


# --- Ejemplos del catálogo ----------------------------------------------------------------------------------


@pytest.mark.parametrize("nombre", sorted(registro.CATALOGO))
def test_cada_ejemplo_del_catalogo_valida(tmp_path, nombre):
    if nombre == "personalizado":
        (tmp_path / "momentos.py").write_text("def momento_aja(ctx):\n    return None\n", encoding="utf-8")
    reporte = _validar(tmp_path, guion_de_ejemplo(nombre))
    assert reporte.ok, reporte.texto()
