"""Tests de subtítulos karaoke: alineación con el texto del guion, bloques, palabra activa y escena."""

from __future__ import annotations

import pytest
from manim import Text, tempconfig

from toolkit.layout import ZONA_SUBTITULOS
from toolkit.narracion import MotorNarracion, PalabraTemporizada, SegmentoNarrado
from toolkit.subtitulos import (
    BloqueSubtitulo,
    agrupar_en_bloques,
    alinear_con_texto,
    dividir_en_lineas,
    indice_palabra_activa,
)


def _p(texto: str, inicio: float, fin: float) -> PalabraTemporizada:
    return PalabraTemporizada(texto, inicio, fin)


def _textos(palabras) -> list[str]:
    return [p.texto for p in palabras]


# --- alinear_con_texto ----------------------------------------------------------

# Tiempos reales de edge-tts (es-PE-AlexNeural, +5 %) para el texto de abajo.
TEXTO_GAUSS = "¿Cuánto da uno más dos, y así hasta cien?"
PALABRAS_GAUSS = [
    _p("Cuánto", 0.1017, 0.4253),
    _p("da", 0.4382, 0.5676),
    _p("uno", 0.5805, 0.8135),
    _p("más", 0.8264, 1.0723),
    _p("dos", 1.0852, 1.4087),
    _p("y", 1.6416, 1.7581),
    _p("así", 1.771, 2.0686),
    _p("hasta", 2.0816, 2.3145),
    _p("cien", 2.3274, 2.7027),
]


def test_alinear_recupera_puntuacion_y_signos_de_apertura():
    alineadas = alinear_con_texto(PALABRAS_GAUSS, TEXTO_GAUSS)
    assert _textos(alineadas) == ["¿Cuánto", "da", "uno", "más", "dos,", "y", "así", "hasta", "cien?"]
    # Los tiempos no cambian.
    assert [(p.inicio, p.fin) for p in alineadas] == [(p.inicio, p.fin) for p in PALABRAS_GAUSS]


def test_alinear_con_palabra_unida_por_edge_tts():
    # Caso real: edge-tts entrega "1 a 100" como UNA palabra.
    texto = "Suma de 1 a 100: son 5050. ¡Increíble!"
    palabras = [
        _p("Suma", 0.1017, 0.477),
        _p("de", 0.49, 0.6194),
        _p("1 a 100", 0.6323, 1.2405),
        _p("son", 1.5122, 1.771),
        _p("5050", 1.784, 2.9874),
        _p("Increíble", 3.882, 4.6713),
    ]
    alineadas = alinear_con_texto(palabras, texto)
    assert _textos(alineadas) == ["Suma", "de", "1 a 100:", "son", "5050.", "¡Increíble!"]
    assert [(p.inicio, p.fin) for p in alineadas] == [(p.inicio, p.fin) for p in palabras]


def test_alinear_numero_con_otra_forma():
    texto = "Súmalos hasta 100, ¿ves?"
    palabras = [_p("Súmalos", 0.1, 0.5), _p("hasta", 0.5, 0.8), _p("cien", 0.8, 1.2), _p("ves", 1.5, 1.8)]
    assert _textos(alinear_con_texto(palabras, texto)) == ["Súmalos", "hasta", "100,", "¿ves?"]


def test_alinear_token_partido_en_varias_palabras_une_los_tiempos():
    texto = "Mira: x²+2x crece."
    palabras = [_p("Mira", 0.0, 0.3), _p("x²", 0.4, 0.8), _p("+", 0.8, 1.0), _p("2x", 1.0, 1.4), _p("crece", 1.5, 2.0)]
    alineadas = alinear_con_texto(palabras, texto)
    assert _textos(alineadas) == ["Mira:", "x²+2x", "crece."]
    assert (alineadas[1].inicio, alineadas[1].fin) == (0.4, 1.4)


def test_alinear_palabra_sin_par_se_une_a_la_anterior():
    texto = "Uno, eh, dos y tres."
    palabras = [_p("Uno", 0.0, 0.3), _p("dos", 0.6, 0.9), _p("y", 0.9, 1.0), _p("tres", 1.0, 1.4)]
    assert _textos(alinear_con_texto(palabras, texto)) == ["Uno, eh,", "dos", "y", "tres."]


def test_alinear_puntuacion_suelta_y_mayusculas():
    texto = "Fíjate — ¡aquí está la CLAVE!"
    palabras = [_p("fíjate", 0.0, 0.4), _p("aquí", 0.5, 0.8), _p("está", 0.8, 1.0), _p("la", 1.0, 1.1), _p("clave", 1.1, 1.5)]
    assert _textos(alinear_con_texto(palabras, texto)) == ["Fíjate —", "¡aquí", "está", "la", "CLAVE!"]


def test_alinear_bordes():
    assert alinear_con_texto([], "hola mundo") == []
    palabras = [_p("hola", 0.0, 0.5), _p("mundo", 0.5, 1.0)]
    assert alinear_con_texto(palabras, "") == palabras
    assert _textos(alinear_con_texto(palabras, "Hola, mundo.")) == ["Hola,", "mundo."]


def test_alinear_textos_muy_distintos_conserva_cobertura_temporal():
    palabras = [_p("a", 0.0, 0.2), _p("b", 0.2, 0.4), _p("c", 0.4, 0.6)]
    alineadas = alinear_con_texto(palabras, "totalmente distinto")
    assert " ".join(_textos(alineadas)) == "totalmente distinto"
    assert alineadas[0].inicio == 0.0 and alineadas[-1].fin == 0.6
    assert all(a.inicio <= b.inicio for a, b in zip(alineadas, alineadas[1:]))


# --- agrupar_en_bloques --------------------------------------------------------


def _palabras_seguidas(textos: list[str], paso: float = 0.3) -> list[PalabraTemporizada]:
    return [_p(t, round(i * paso, 4), round(i * paso + 0.25, 4)) for i, t in enumerate(textos)]


def test_bloques_respetan_max_palabras_y_caracteres():
    palabras = _palabras_seguidas("uno dos tres cuatro cinco seis siete ocho nueve".split())
    bloques = agrupar_en_bloques(palabras, 0.0, max_palabras=4, max_caracteres=22)
    for bloque in bloques:
        assert len(bloque.palabras) <= 4
        assert len(" ".join(p.texto for p in bloque.palabras)) <= 22
    assert [p for b in bloques for p in b.palabras] == palabras


def test_bloques_cortan_en_caracteres():
    palabras = _palabras_seguidas(["extraordinariamente", "largo", "sí"])
    bloques = agrupar_en_bloques(palabras, 0.0, max_palabras=4, max_caracteres=22)
    assert [len(b.palabras) for b in bloques] == [1, 2]


def test_bloques_cortan_tras_puntuacion():
    palabras = _palabras_seguidas(["¿Cuánto", "da?", "Uno,", "dos", "y", "tres."])
    bloques = agrupar_en_bloques(palabras, 0.0)
    assert [[p.texto for p in b.palabras] for b in bloques] == [["¿Cuánto", "da?"], ["Uno,"], ["dos", "y", "tres."]]


def test_bloques_equilibrados_sin_huerfanas():
    palabras = alinear_con_texto(PALABRAS_GAUSS, TEXTO_GAUSS)
    bloques = agrupar_en_bloques(palabras, 0.0)
    assert [" ".join(p.texto for p in b.palabras) for b in bloques] == [
        "¿Cuánto da",
        "uno más dos,",
        "y así hasta cien?",
    ]
    textos = "Fíjate en esta escalera de bloques que sube paso a paso.".split()
    bloques = agrupar_en_bloques(_palabras_seguidas(textos), 0.0)
    assert all(len(b.palabras) >= 2 for b in bloques)


def test_bloques_contiguos_absolutos_y_ordenados():
    palabras = _palabras_seguidas("a b c d e f g h i".split())
    bloques = agrupar_en_bloques(palabras, 10.0, max_palabras=4)
    assert bloques[0].inicio == pytest.approx(10.0)
    for anterior, siguiente in zip(bloques, bloques[1:]):
        assert anterior.fin == pytest.approx(siguiente.inicio)
        assert anterior.inicio < siguiente.inicio
    assert bloques[-1].fin == pytest.approx(10.0 + palabras[-1].fin + 0.2)
    assert bloques[0].palabras[0].inicio == pytest.approx(10.0 + palabras[0].inicio)  # palabras absolutas
    assert agrupar_en_bloques([], 3.0) == []


def test_bloque_es_inmutable():
    bloque = agrupar_en_bloques(_palabras_seguidas(["hola"]), 0.0)[0]
    assert isinstance(bloque, BloqueSubtitulo)
    with pytest.raises(Exception):
        bloque.inicio = 5.0  # type: ignore[misc]


# --- palabra activa y líneas --------------------------------------------------


def test_indice_palabra_activa():
    # Tiempos absolutos de escena (el segmento empezó en t = 10).
    bloque = BloqueSubtitulo(
        palabras=(_p("uno", 10.0, 10.3), _p("dos", 10.5, 10.8), _p("tres", 10.9, 11.2)), inicio=10.0, fin=12.0
    )
    assert indice_palabra_activa(bloque, 10.1) == 0
    assert indice_palabra_activa(bloque, 10.4) == 0  # hueco corto: sigue la anterior
    assert indice_palabra_activa(bloque, 10.6) == 1
    assert indice_palabra_activa(bloque, 11.0) == 2
    assert indice_palabra_activa(bloque, 11.9) is None  # ya se dijo todo
    assert indice_palabra_activa(bloque, 9.0) is None


def test_dividir_en_lineas_equilibra():
    assert dividir_en_lineas(["uno"]) == [["uno"]]
    assert dividir_en_lineas(["¿Cuánto", "da", "uno", "más"]) == [["¿Cuánto", "da"], ["uno", "más"]]
    assert dividir_en_lineas(["a", "b", "extraordinario"]) == [["a", "b"], ["extraordinario"]]


# --- Escena (render offline) -----------------------------------------------------


def _config_prueba(tmp_path) -> dict:
    return {
        "quality": "low_quality",
        "dry_run": True,
        "media_dir": str(tmp_path / "media"),
        "disable_caching": True,
    }


def _a_pantalla(mob, frame, ancho_ref: float):
    """Esquinas (inf-izq, sup-der) de ``mob`` en coordenadas de pantalla (cuadro 9x16)."""
    factor = ancho_ref / frame.width
    centro = frame.get_center()
    return (mob.get_corner([-1, -1, 0]) - centro) * factor, (mob.get_corner([1, 1, 0]) - centro) * factor


def _dentro_de_zona(esquinas, zona, tol: float = 0.02) -> bool:
    inf, sup = esquinas
    return (
        inf[0] >= zona.x_min - tol
        and sup[0] <= zona.x_max + tol
        and inf[1] >= zona.y_min - tol
        and sup[1] <= zona.y_max + tol
    )


def _textos_visibles(subtitulos) -> list[str]:
    return [m.text for m in subtitulos.get_family() if isinstance(m, Text)]


TEXTO_OCHO = "Uno dos tres cuatro, cinco seis siete ocho."


@pytest.mark.render
def test_subtitulos_en_escena_2d_con_zoom(tmp_path):
    from toolkit.base_scene import PlantillaShort

    info: dict = {}

    class EscenaSubtitulos(PlantillaShort):
        def construct(self):
            self._motor_narracion = MotorNarracion(dir_cache=tmp_path / "tts", permitir_red=False)
            frame = self.camera.frame
            info["vacio_al_inicio"] = len(self.subtitulos.submobjects) == 0
            with self.narrar(TEXTO_OCHO) as n:
                seg: SegmentoNarrado = n.segmento
                bloques = self.subtitulos.bloques
                info["n_bloques"] = len(bloques)
                segundo = bloques[1]
                n.esperar_hasta("seis")  # 6ª palabra ⇒ dentro del 2º bloque
                info["textos_bloque2"] = _textos_visibles(self.subtitulos)
                info["activa"] = self.subtitulos.indice_activo
                info["zona_antes"] = _dentro_de_zona(
                    _a_pantalla(self.subtitulos, frame, self.frame_referencia_ancho), ZONA_SUBTITULOS
                )
                self.play(frame.animate.scale(2.0), run_time=0.3)
                info["zona_zoom"] = _dentro_de_zona(
                    _a_pantalla(self.subtitulos, frame, self.frame_referencia_ancho), ZONA_SUBTITULOS
                )
                info["alto_relativo"] = self.subtitulos.height / frame.height
                info["segundo"] = (segundo.inicio, segundo.fin, n.inicio)
                info["seg"] = seg
            self.wait(0.5)
            info["vacio_al_final"] = len(self.subtitulos.submobjects) == 0

    with tempconfig(_config_prueba(tmp_path)):
        EscenaSubtitulos().render()

    assert info["vacio_al_inicio"]
    assert info["n_bloques"] == 2
    assert any("cinco" in t for t in info["textos_bloque2"])  # 5ª palabra visible en el 2º bloque
    assert not any("Uno" in t for t in info["textos_bloque2"])
    assert info["activa"] == 1  # "seis" dentro de "cinco seis siete ocho."
    assert info["zona_antes"] and info["zona_zoom"]
    assert 0.02 < info["alto_relativo"] < 0.1  # no crece con el zoom-out
    assert info["vacio_al_final"]


@pytest.mark.render
def test_subtitulos_desactivados_y_3d(tmp_path):
    from toolkit.base_scene import PlantillaShort
    from toolkit.utils_3d import PlantillaShort3D

    info: dict = {}

    class SinSubtitulos(PlantillaShort):
        SUBTITULOS = False

        def construct(self):
            self._motor_narracion = MotorNarracion(dir_cache=tmp_path / "tts", permitir_red=False)
            with self.narrar("hola mundo"):
                pass
            info["sin"] = getattr(self, "subtitulos", None)

    class Con3D(PlantillaShort3D):
        COLORES_SUBTITULOS = {"mundo": "#58C4DD"}

        def construct(self):
            self._motor_narracion = MotorNarracion(dir_cache=tmp_path / "tts", permitir_red=False)
            with self.narrar("hola mundo") as n:
                n.esperar_hasta("mundo")
                info["textos3d"] = _textos_visibles(self.subtitulos)
                fijos = self.renderer.camera.fixed_in_frame_mobjects
                info["fijos"] = all(m in fijos for m in self.subtitulos.get_family())
                info["dentro3d"] = ZONA_SUBTITULOS.contiene(self.subtitulos)

    with tempconfig(_config_prueba(tmp_path)):
        SinSubtitulos().render()
        Con3D().render()

    assert info["sin"] is None
    assert any("mundo" in t for t in info["textos3d"])
    assert info["fijos"]
    assert info["dentro3d"]


def test_colores_palabra_normalizados():
    from toolkit.subtitulos import color_base_de

    colores = {"n": "#58C4DD", "Cien": "#F7D96F"}
    assert color_base_de("n,", colores, "#FFFFFF") == "#58C4DD"
    assert color_base_de("¿cien?", colores, "#FFFFFF") == "#F7D96F"
    assert color_base_de("otra", colores, "#FFFFFF") == "#FFFFFF"


@pytest.mark.render
def test_bloque_largo_en_dos_lineas_sin_reducir_y_dentro_de_zona():
    from toolkit.configuracion import aplicar_configuracion_global
    from toolkit.estilos import FUENTE_SUBTITULOS
    from toolkit.subtitulos import SubtitulosKaraoke
    from toolkit.tipografia import Texto, registrar_fuentes

    aplicar_configuracion_global()
    registrar_fuentes()
    subtitulos = SubtitulosKaraoke(None)
    bloque = BloqueSubtitulo((_p("permanecen", 0.0, 0.5), _p("inmóviles!", 0.5, 1.0)), 0.0, 1.2)
    subtitulos.add(*subtitulos._construir(bloque))
    lineas = [m for m in subtitulos.get_family() if isinstance(m, Text)]
    assert [m.text for m in lineas] == ["permanecen", "inmóviles!"]
    referencia = Texto("permanecen", tamano=FUENTE_SUBTITULOS, font=subtitulos.fuente, disable_ligatures=True)
    assert lineas[0].height == pytest.approx(referencia.height, rel=0.01)
    assert ZONA_SUBTITULOS.contiene(subtitulos)
