"""Tests de toolkit.narracion: motor TTS con caché y fallback, segmentos y narrar() en escenas."""

import json
import wave

import pytest
from manim import FadeIn, Square, tempconfig

from toolkit.medios import duracion_audio, silencio_wav
from toolkit.narracion import (
    ControlNarracion,
    MotorNarracion,
    PalabraTemporizada,
    SegmentoNarrado,
)


def _segmento(textos: list[str], paso: float = 0.5) -> SegmentoNarrado:
    palabras = [
        PalabraTemporizada(t, i * paso, i * paso + paso * 0.8) for i, t in enumerate(textos)
    ]
    return SegmentoNarrado(
        texto=" ".join(textos),
        ruta_wav=None,  # type: ignore[arg-type]
        duracion=len(textos) * paso,
        palabras=palabras,
        sintetico=True,
    )


# --- MotorNarracion: clave, fallback y caché -----------------------------------


def test_clave_depende_de_voz_velocidad_tono_y_texto(tmp_path):
    motor = MotorNarracion(dir_cache=tmp_path, permitir_red=False)
    clave = motor.clave("hola")
    assert len(clave) == 16
    assert clave == motor.clave("hola")
    assert clave != motor.clave("hola.")
    otro = MotorNarracion(voz="es-MX-DaliaNeural", dir_cache=tmp_path, permitir_red=False)
    assert otro.clave("hola") != clave


def test_permitir_red_por_defecto_lee_variable_de_entorno(tmp_path, monkeypatch):
    monkeypatch.setenv("SHORT_TTS_OFFLINE", "1")
    assert MotorNarracion(dir_cache=tmp_path).permitir_red is False
    monkeypatch.delenv("SHORT_TTS_OFFLINE")
    assert MotorNarracion(dir_cache=tmp_path).permitir_red is True


def test_fallback_sintetico_sin_red(tmp_path):
    motor = MotorNarracion(dir_cache=tmp_path, permitir_red=False)
    seg = motor.sintetizar("uno dos tres cuatro")
    assert seg.sintetico is True
    assert [p.texto for p in seg.palabras] == ["uno", "dos", "tres", "cuatro"]
    inicios = [p.inicio for p in seg.palabras]
    assert inicios == sorted(inicios) and len(set(inicios)) == 4
    assert all(p.fin > p.inicio for p in seg.palabras)
    assert seg.palabras[-1].fin <= seg.duracion
    assert seg.duracion == pytest.approx(max(1.0, 4 / 2.7 + 0.3))
    assert seg.ruta_wav.exists()
    assert duracion_audio(seg.ruta_wav) == pytest.approx(seg.duracion, abs=0.01)
    # Los sintéticos NO van a la caché real (un reintento con red debe poder sustituirlos).
    assert seg.ruta_wav.parent == tmp_path / "sinteticos"
    assert not (tmp_path / f"{motor.clave('uno dos tres cuatro')}.wav").exists()


def test_fallback_texto_corto_dura_al_menos_un_segundo(tmp_path):
    seg = MotorNarracion(dir_cache=tmp_path, permitir_red=False).sintetizar("Hola.")
    assert seg.duracion == pytest.approx(1.0)
    assert len(seg.palabras) == 1


def test_carga_desde_cache_sin_red(tmp_path):
    motor = MotorNarracion(dir_cache=tmp_path, permitir_red=False)
    texto = "Esto viene de la caché"
    clave = motor.clave(texto)
    silencio_wav(tmp_path / f"{clave}.wav", 2.0)
    datos = {
        "texto": texto,
        "voz": motor.voz,
        "velocidad": motor.velocidad,
        "duracion": 2.0,
        "sintetico": False,
        "palabras": [
            {"texto": "Esto", "inicio": 0.1, "fin": 0.3},
            {"texto": "viene", "inicio": 0.35, "fin": 0.6},
        ],
    }
    (tmp_path / f"{clave}.json").write_text(json.dumps(datos), encoding="utf-8")
    seg = motor.sintetizar(texto)
    assert seg.sintetico is False
    assert seg.duracion == pytest.approx(2.0)
    assert seg.ruta_wav == tmp_path / f"{clave}.wav"
    assert seg.palabras[1] == PalabraTemporizada("viene", 0.35, 0.6)
    assert seg.tiempo_de("viene") == pytest.approx(0.35)


# --- SegmentoNarrado: anclas ---------------------------------------------------


def test_tiempo_de_secuencia_y_ocurrencias():
    seg = _segmento(["Uno,", "dos", "tres.", "Dos", "tres", "¡cuatro!"])
    assert seg.tiempo_de("dos tres") == pytest.approx(0.5)
    assert seg.tiempo_de("Dos, tres", ocurrencia=2) == pytest.approx(1.5)
    assert seg.tiempo_de("cuatro") == pytest.approx(2.5)
    assert seg.fin_de("dos tres") == pytest.approx(1.0 + 0.4)
    assert seg.fin_de("dos tres", ocurrencia=2) == pytest.approx(2.0 + 0.4)


def test_tiempo_de_ignora_tildes_y_mayusculas():
    seg = _segmento(["¿Por", "qué", "Ñandú?"])
    assert seg.tiempo_de("por que") == pytest.approx(0.0)
    assert seg.tiempo_de("nandu") == pytest.approx(1.0)


def test_tiempo_de_inexistente_lanza_key_error_con_palabras():
    seg = _segmento(["uno", "dos"])
    with pytest.raises(KeyError, match="uno"):
        seg.tiempo_de("inexistente")
    with pytest.raises(KeyError):
        seg.tiempo_de("dos", ocurrencia=2)
    with pytest.raises(KeyError):
        seg.tiempo_de("¿?")


# --- ControlNarracion ----------------------------------------------------------


class _RendererFalso:
    def __init__(self):
        self.time = 0.0


class _EscenaFalsa:
    def __init__(self):
        self.renderer = _RendererFalso()
        self.esperas: list[float] = []

    def wait(self, t):
        self.esperas.append(t)
        self.renderer.time += t


def test_control_narracion_tiempos_relativos():
    escena = _EscenaFalsa()
    escena.renderer.time = 10.0
    seg = _segmento(["uno", "dos", "tres", "cuatro"])  # duración 2.0
    control = ControlNarracion(escena, seg, 10.0)
    escena.renderer.time = 10.2
    assert control.transcurrido == pytest.approx(0.2)
    assert control.restante == pytest.approx(1.8)
    assert control.tiempo_hasta("tres") == pytest.approx(0.8)
    assert control.tiempo_hasta("uno") == 0.0
    control.esperar_hasta("tres")
    assert escena.esperas == [pytest.approx(0.8)]
    control.esperar_hasta("dos")  # ya pasó: no espera
    assert len(escena.esperas) == 1
    assert control.hasta_el_final() == pytest.approx(1.0)
    assert control.hasta_el_final(margen=0.25) == pytest.approx(0.75)
    escena.renderer.time = 30.0
    assert control.hasta_el_final() > 0


# --- Escena real (render offline) ----------------------------------------------


def _config_prueba(tmp_path) -> dict:
    return {
        "quality": "low_quality",
        "dry_run": True,
        "media_dir": str(tmp_path / "media"),
        "disable_caching": True,
    }


@pytest.mark.render
@pytest.mark.parametrize("modulo_clase", ["toolkit.base_scene:PlantillaShort", "toolkit.utils_3d:PlantillaShort3D"])
def test_narrar_en_escena_avanza_el_reloj(tmp_path, modulo_clase):
    import importlib

    modulo, nombre = modulo_clase.split(":")
    base = getattr(importlib.import_module(modulo), nombre)
    registro: dict = {}

    class EscenaNarrada(base):
        def construct(self):
            self._motor_narracion = MotorNarracion(dir_cache=tmp_path / "tts", permitir_red=False)
            ganchos = []
            self._al_narrar = lambda seg, inicio: ganchos.append((seg, inicio))
            inicio = self.renderer.time
            with self.narrar("hola mundo") as n:
                registro["control"] = n
                n.esperar_hasta("mundo")
                registro["t_mundo"] = self.renderer.time - inicio
                self.play(FadeIn(Square()), run_time=0.2)
            registro["dt"] = self.renderer.time - inicio
            registro["ganchos"] = ganchos
            registro["segmentos"] = list(self.segmentos_narrados)

    with tempconfig(_config_prueba(tmp_path)):
        EscenaNarrada().render()

    seg = registro["control"].segmento
    assert registro["dt"] >= seg.duracion
    assert registro["t_mundo"] == pytest.approx(seg.tiempo_de("mundo"), abs=0.1)
    assert len(registro["segmentos"]) == 1 and registro["segmentos"][0][1] is seg
    assert registro["ganchos"] == [(seg, registro["segmentos"][0][0])]


# --- Red real (edge-tts) -------------------------------------------------------


@pytest.mark.red
def test_sintesis_real_con_edge_tts(tmp_path):
    motor = MotorNarracion(dir_cache=tmp_path, permitir_red=True)
    texto = "Fíjate en esta escalera de bloques que sube despacio."
    seg = motor.sintetizar(texto)
    assert seg.sintetico is False
    assert len(seg.palabras) >= 3
    inicios = [p.inicio for p in seg.palabras]
    assert inicios == sorted(inicios)
    assert all(p.fin >= p.inicio for p in seg.palabras)
    assert seg.palabras[-1].fin <= seg.duracion + 0.05
    with wave.open(str(seg.ruta_wav), "rb") as wf:
        assert wf.getnchannels() == 2
    datos = json.loads((tmp_path / f"{motor.clave(texto)}.json").read_text(encoding="utf-8"))
    assert duracion_audio(seg.ruta_wav) == pytest.approx(datos["duracion"], abs=0.02)
    assert seg.tiempo_de("escalera") > seg.tiempo_de("fijate")
    # Segunda llamada: sale de caché, sin red.
    offline = MotorNarracion(dir_cache=tmp_path, permitir_red=False)
    seg2 = offline.sintetizar(texto)
    assert seg2.sintetico is False and seg2.palabras == seg.palabras


@pytest.mark.render
def test_rerender_con_cache_conserva_audio_y_reloj(tmp_path):
    """Con la caché de manim activa, un segundo render conserva el audio y el mismo reloj.

    Tras un play servido desde caché, ``Scene.add_sound`` descartaría el sonido y el reloj avanzaría
    ``run_time`` exacto en vez de fotogramas enteros: ``narrar`` y ``play`` lo compensan.
    """
    import av
    from manim import Rotate

    from toolkit.base_scene import PlantillaShort

    class EscenaCache(PlantillaShort):
        def construct(self):
            self._motor_narracion = MotorNarracion(dir_cache=tmp_path / "tts", permitir_red=False)
            cuadrado = Square()
            self.add(cuadrado)
            for _ in range(4):
                self.play(Rotate(cuadrado, 0.1), run_time=0.21)  # 6.3 ⇒ 7 fotogramas reales
                self.wait(0.13)  # espera congelada: 3 fotogramas reales
            with self.narrar("hola mundo"):
                pass

    configuracion = {
        "quality": "low_quality",
        "media_dir": str(tmp_path / "media"),
        "progress_bar": "none",
        "disable_caching": False,
    }
    resultados = []
    for _ in range(2):
        with tempconfig(configuracion):
            escena = EscenaCache()
            escena.render()
            with av.open(str(escena.renderer.file_writer.movie_file_path)) as contenedor:
                audio = contenedor.streams.audio
                duracion_audio_mp4 = float(audio[0].duration * audio[0].time_base) if audio else None
            resultados.append((escena.segmentos_narrados[0][0], duracion_audio_mp4))

    (inicio_1, audio_1), (inicio_2, audio_2) = resultados
    assert audio_1 is not None and audio_2 is not None
    assert inicio_2 == pytest.approx(inicio_1, abs=1e-6)
    assert audio_2 == pytest.approx(audio_1, abs=0.05)


@pytest.mark.render
def test_recortar_silencio_final_acorta_la_espera(tmp_path, monkeypatch):
    """Con RECORTAR_SILENCIO_FINAL la escena termina en la ultima palabra + pausa, no en el fin del wav."""
    from manim import tempconfig
    from toolkit.base_scene import PlantillaShort
    from toolkit.narracion import PalabraTemporizada, SegmentoNarrado
    from toolkit.medios import silencio_wav

    wav = silencio_wav(tmp_path / "s.wav", 3.0)
    seg = SegmentoNarrado("hola mundo", wav, 3.0, [PalabraTemporizada("hola", 0.1, 0.6),
                                                     PalabraTemporizada("mundo", 0.7, 1.5)], False)

    def construir(recortar):
        class Escena(PlantillaShort):
            SUBTITULOS = False
            RECORTAR_SILENCIO_FINAL = recortar
            def construct(self):
                monkeypatch.setattr(self.motor_narracion, "sintetizar", lambda t: seg)
                with self.narrar("hola mundo", pausa_final=0.2):
                    pass
        with tempconfig({"quality": "low_quality", "dry_run": True, "media_dir": str(tmp_path)}):
            e = Escena(); e.render(); return e.renderer.time

    assert abs(construir(False) - 3.2) < 0.1
    assert abs(construir(True) - 1.7) < 0.1


def test_hasta_ultima_palabra_ignora_silencio_final(tmp_path):
    from toolkit.narracion import ControlNarracion, PalabraTemporizada, SegmentoNarrado

    seg = SegmentoNarrado("a b", tmp_path / "x.wav", 3.0,
                          [PalabraTemporizada("a", 0.1, 0.5), PalabraTemporizada("b", 0.6, 1.4)], False)

    class Renderer:
        time = 0.4

    class Escena:
        renderer = Renderer()

    control = ControlNarracion(Escena(), seg, 0.0)
    assert abs(control.hasta_ultima_palabra() - 1.0) < 1e-6
    assert abs(control.hasta_el_final() - 2.6) < 1e-6
