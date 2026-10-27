"""Tests de toolkit.medios: ffmpeg, conversión y duración de audio, silencios y normalización de texto."""

import wave
from pathlib import Path

import pytest

from toolkit.medios import (
    RAIZ,
    convertir_a_wav,
    duracion_audio,
    ejecutar_ffmpeg,
    normalizar_texto,
    ruta_ffmpeg,
    silencio_wav,
)


def test_raiz_es_la_raiz_del_repo():
    assert (RAIZ / "toolkit" / "medios.py").exists()


def test_normalizar_texto_quita_tildes_enie_y_puntuacion():
    assert normalizar_texto("¿Por qué, Ñandú?") == "por que nandu"


def test_normalizar_texto_colapsa_espacios_y_minusculas():
    assert normalizar_texto("  Hola,   MUNDO!\n¡Ánimo!  ") == "hola mundo animo"
    assert normalizar_texto("...") == ""


def test_silencio_wav_tiene_la_duracion_pedida(tmp_path):
    ruta = silencio_wav(tmp_path / "sub" / "s.wav", 1.37)
    assert ruta.exists()
    assert duracion_audio(ruta) == pytest.approx(1.37, abs=0.01)
    with wave.open(str(ruta), "rb") as wf:
        assert wf.getnchannels() == 2
        assert wf.getsampwidth() == 2
        assert wf.getframerate() == 48000


def test_ruta_ffmpeg_existe_y_se_cachea():
    ruta = ruta_ffmpeg()
    assert Path(ruta).exists()
    assert ruta_ffmpeg() is ruta


def test_convertir_a_wav_y_duracion_de_otros_formatos(tmp_path):
    origen = silencio_wav(tmp_path / "s.wav", 0.8, frecuencia=22050)
    mp3 = tmp_path / "s.mp3"
    ejecutar_ffmpeg(["-i", str(origen), str(mp3)])
    assert duracion_audio(mp3) == pytest.approx(0.8, abs=0.08)
    destino = convertir_a_wav(mp3, tmp_path / "salida" / "s.wav")
    with wave.open(str(destino), "rb") as wf:
        assert wf.getnchannels() == 2
        assert wf.getframerate() == 48000
    assert duracion_audio(destino) == pytest.approx(0.8, abs=0.08)


def test_ejecutar_ffmpeg_falla_con_runtime_error(tmp_path):
    with pytest.raises(RuntimeError):
        ejecutar_ffmpeg(["-i", str(tmp_path / "no_existe.wav"), str(tmp_path / "x.wav")])
