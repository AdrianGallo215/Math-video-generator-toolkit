"""Tests del pipeline de producción (scripts/producir_video.py) y de las utilidades de video de
toolkit/medios.py que usa (info, concatenación y mezcla con música + ducking + loudnorm)."""

from __future__ import annotations

import json
import wave
from pathlib import Path

import numpy as np
import pytest

from scripts.producir_video import (
    RAIZ,
    ErrorConfiguracion,
    cargar_configuracion,
    detectar_segmentos_sinteticos,
    producir,
)
from toolkit.medios import (
    concatenar_videos,
    duracion_video,
    ejecutar_ffmpeg,
    info_video,
    medir_loudness,
    mezclar_musica,
    tiene_audio,
)

ESCENA_VALIDA = "from manim import Scene\n\nclass MiEscena(Scene):\n    def construct(self):\n        pass\n"


# --- utilidades de test ------------------------------------------------------------------


def _escribir_yaml(carpeta: Path, contenido: str) -> Path:
    ruta = carpeta / "video.yaml"
    ruta.write_text(contenido, encoding="utf-8")
    return ruta


def _video_prueba(destino: Path, segundos: float, con_audio: bool, tono_hz: float = 440.0) -> Path:
    """MP4 minúsculo 54×96 a 30 fps (testsrc) con o sin audio (seno)."""
    args = ["-f", "lavfi", "-i", f"testsrc=size=54x96:rate=30:duration={segundos}"]
    if con_audio:
        args += ["-f", "lavfi", "-i", f"sine=frequency={tono_hz}:sample_rate=48000:duration={segundos}"]
    args += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "ultrafast"]
    if con_audio:
        args += ["-c:a", "aac", "-ac", "2", "-shortest"]
    ejecutar_ffmpeg([*args, str(destino)])
    return destino


def _leer_audio_mono(ruta: Path, frecuencia: int = 48000) -> np.ndarray:
    """Decodifica el audio de ``ruta`` a float mono con PyAV."""
    import av

    with av.open(str(ruta)) as contenedor:
        remuestreador = av.AudioResampler(format="flt", layout="mono", rate=frecuencia)
        trozos = []
        for cuadro in contenedor.decode(contenedor.streams.audio[0]):
            for salida in remuestreador.resample(cuadro):
                trozos.append(salida.to_ndarray().reshape(-1))
    return np.concatenate(trozos)


def _energia_graves(senal: np.ndarray, frecuencia: int, desde: float, hasta: float, corte_hz: float = 1200) -> float:
    """Energía RMS de ``senal`` en [desde, hasta) s por debajo de ``corte_hz`` (vía FFT)."""
    tramo = senal[int(desde * frecuencia) : int(hasta * frecuencia)]
    espectro = np.fft.rfft(tramo * np.hanning(len(tramo)))
    frecuencias = np.fft.rfftfreq(len(tramo), 1 / frecuencia)
    return float(np.sqrt(np.sum(np.abs(espectro[frecuencias < corte_hz]) ** 2)) / len(tramo))


# --- validación del YAML ---------------------------------------------------------------


def test_configuracion_valida_con_valores_por_defecto(tmp_path):
    (tmp_path / "escena.py").write_text(ESCENA_VALIDA, encoding="utf-8")
    ruta = _escribir_yaml(tmp_path, "slug: prueba\nescenas:\n  - {archivo: escena.py, clase: MiEscena}\n")

    cfg = cargar_configuracion(ruta)

    assert cfg.slug == "prueba"
    assert cfg.escenas[0].archivo == (tmp_path / "escena.py").resolve()
    assert cfg.escenas[0].clase == "MiEscena"
    assert cfg.musica is None
    assert cfg.volumen_musica_db == -24
    assert cfg.ducking is True
    assert cfg.loudness_lufs == -14


def test_configuracion_clave_faltante(tmp_path):
    ruta = _escribir_yaml(tmp_path, "slug: prueba\n")
    with pytest.raises(ErrorConfiguracion, match="escenas"):
        cargar_configuracion(ruta)


def test_configuracion_archivo_de_escena_inexistente(tmp_path):
    ruta = _escribir_yaml(tmp_path, "slug: prueba\nescenas:\n  - {archivo: no_existe.py, clase: X}\n")
    with pytest.raises(ErrorConfiguracion, match="no_existe.py"):
        cargar_configuracion(ruta)


def test_configuracion_clase_inexistente(tmp_path):
    (tmp_path / "escena.py").write_text(ESCENA_VALIDA, encoding="utf-8")
    ruta = _escribir_yaml(tmp_path, "slug: prueba\nescenas:\n  - {archivo: escena.py, clase: OtraClase}\n")
    with pytest.raises(ErrorConfiguracion, match="OtraClase.*MiEscena"):
        cargar_configuracion(ruta)


def test_configuracion_musica_inexistente(tmp_path):
    (tmp_path / "escena.py").write_text(ESCENA_VALIDA, encoding="utf-8")
    ruta = _escribir_yaml(
        tmp_path,
        "slug: prueba\nmusica: assets/audio/no_hay.wav\nescenas:\n  - {archivo: escena.py, clase: MiEscena}\n",
    )
    with pytest.raises(ErrorConfiguracion, match="no_hay.wav"):
        cargar_configuracion(ruta)


# --- detección de narración sintética ------------------------------------------------------


def test_detectar_segmentos_sinteticos_en_salida_del_render():
    salida = (
        "Manim Community v0.21.0\n"
        "Red deshabilitada para TTS; narración sintética para 'Hola mundo.'\n"
        "File ready at media/x.mp4\n"
        "edge-tts no disponible (timeout); se usa narración sintética\n"
    )
    detectados = detectar_segmentos_sinteticos(salida)
    assert len(detectados) == 2
    assert "Hola mundo." in detectados[0]
    assert detectar_segmentos_sinteticos("File ready at media/x.mp4\n") == []


# --- utilidades de video en medios.py --------------------------------------------------------


def test_info_video_y_tiene_audio(tmp_path):
    con = _video_prueba(tmp_path / "con.mp4", 1.0, con_audio=True)
    sin = _video_prueba(tmp_path / "sin.mp4", 1.0, con_audio=False)

    info = info_video(con)
    assert (info["ancho"], info["alto"]) == (54, 96)
    assert info["fps"] == pytest.approx(30)
    assert info["duracion"] == pytest.approx(1.0, abs=0.1)
    assert info["codec_audio"] == "aac"
    assert tiene_audio(con) is True
    assert tiene_audio(sin) is False
    assert info_video(sin)["codec_audio"] is None
    assert duracion_video(sin) == pytest.approx(1.0, abs=0.1)


def test_concatenar_videos_rellena_audio_faltante(tmp_path):
    a = _video_prueba(tmp_path / "a.mp4", 1.0, con_audio=True)
    b = _video_prueba(tmp_path / "b.mp4", 1.5, con_audio=False)

    destino = concatenar_videos([a, b], tmp_path / "concat.mp4")

    info = info_video(destino)
    assert info["codec_audio"] == "aac"
    assert info["duracion"] == pytest.approx(2.5, abs=0.15)


def test_mezclar_musica_atenua_la_musica_bajo_la_voz(tmp_path):
    """Video de 8 s; «voz» = tono de 5 kHz (≈ −6 dBFS pico) de 1 s a 3 s. La música (pad grave) debe
    quedar ≥ 10 dB más baja con ducking que sin él mientras suena la voz, y casi igual fuera."""
    voz_wav = tmp_path / "voz.wav"
    ejecutar_ffmpeg(
        [
            "-f", "lavfi", "-i", "sine=frequency=5000:sample_rate=48000:duration=2",
            "-af", "volume=12dB,adelay=1000|1000,apad=whole_dur=8", "-ac", "2", str(voz_wav),
        ]
    )  # fmt: skip
    video = tmp_path / "video.mp4"
    ejecutar_ffmpeg(
        [
            "-f", "lavfi", "-i", "testsrc=size=54x96:rate=30:duration=8", "-i", str(voz_wav),
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "ultrafast", "-c:a", "aac", "-b:a", "256k",
            "-shortest", str(video),
        ]
    )  # fmt: skip
    musica = RAIZ / "assets" / "audio" / "musica_ambiental_01.wav"

    con_ducking = mezclar_musica(video, musica, tmp_path / "duck.mp4", volumen_db=-24, ducking=True, lufs=None)
    sin_ducking = mezclar_musica(video, musica, tmp_path / "plano.mp4", volumen_db=-24, ducking=False, lufs=None)

    senal_duck, senal_plano = _leer_audio_mono(con_ducking), _leer_audio_mono(sin_ducking)

    def diferencia_db(desde: float, hasta: float) -> float:
        return 20 * np.log10(
            _energia_graves(senal_duck, 48000, desde, hasta) / _energia_graves(senal_plano, 48000, desde, hasta)
        )

    assert diferencia_db(1.6, 2.8) < -10  # durante la voz
    assert abs(diferencia_db(4.0, 5.5)) < 1.5  # tras el release, antes del fade-out
    assert duracion_video(con_ducking) == pytest.approx(8.0, abs=0.1)
    assert info_video(con_ducking)["codec_video"] == "h264"


def test_mezclar_musica_normaliza_loudness(tmp_path):
    video = _video_prueba(tmp_path / "v.mp4", 6.0, con_audio=True, tono_hz=300)
    musica = RAIZ / "assets" / "audio" / "musica_ambiental_02.wav"

    salida = mezclar_musica(video, musica, tmp_path / "norm.mp4", volumen_db=-24, ducking=True, lufs=-14)

    assert medir_loudness(salida) == pytest.approx(-14, abs=1.0)


def test_mezclar_musica_sin_voz_deja_la_musica_sola(tmp_path):
    video = _video_prueba(tmp_path / "mudo.mp4", 2.0, con_audio=False)
    musica = RAIZ / "assets" / "audio" / "musica_ambiental_01.wav"

    salida = mezclar_musica(video, musica, tmp_path / "solo.mp4", volumen_db=-24, ducking=True, lufs=-14)

    assert tiene_audio(salida)
    assert duracion_video(salida) == pytest.approx(2.0, abs=0.1)


# --- pipeline completo ----------------------------------------------------------------------


@pytest.mark.render
def test_pipeline_minimo_offline(tmp_path, monkeypatch):
    monkeypatch.setenv("SHORT_TTS_OFFLINE", "1")
    monkeypatch.setenv("SHORT_TTS_CACHE", str(tmp_path / "cache_tts"))
    ruta_yaml = RAIZ / "ejemplos" / "pipeline_minimo" / "video.yaml"

    salida = producir(ruta_yaml, "borrador", media_dir=tmp_path / "media", dir_salidas=tmp_path / "salidas")

    assert salida.exists()
    info = info_video(salida)
    assert (info["ancho"], info["alto"]) == (540, 960)
    assert info["codec_audio"] == "aac"
    reporte = json.loads(salida.with_suffix(".json").read_text(encoding="utf-8"))
    suma = sum(e["duracion"] for e in reporte["escenas"])
    assert len(reporte["escenas"]) == 2
    assert info["duracion"] == pytest.approx(suma, abs=0.3)
    assert reporte["narracion_sintetica"] is True
    assert reporte["segmentos_sinteticos"]


def test_wav_de_musica_existe():
    """Precondición de los tests de mezcla: la música versionada (T10) está disponible."""
    with wave.open(str(RAIZ / "assets" / "audio" / "musica_ambiental_01.wav"), "rb") as wf:
        assert wf.getnframes() / wf.getframerate() == pytest.approx(64, abs=0.01)
