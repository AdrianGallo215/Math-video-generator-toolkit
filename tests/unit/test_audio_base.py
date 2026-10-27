"""Tests de toolkit.audio_base: musica ambiental y SFX procedurales."""

import hashlib
import wave

import numpy as np
import pytest

from toolkit.audio_base import (
    SFX_DISPONIBLES,
    generar_musica_ambiental,
    generar_sfx,
    ruta_sfx,
)


def _sha1_de(ruta) -> str:
    return hashlib.sha1(ruta.read_bytes()).hexdigest()


def _leer_muestras(ruta) -> np.ndarray:
    """Lee un WAV PCM 16 bit y devuelve un array float en [-1, 1], shape (n, canales)."""
    with wave.open(str(ruta), "rb") as wf:
        canales = wf.getnchannels()
        crudo = wf.readframes(wf.getnframes())
    datos = np.frombuffer(crudo, dtype=np.int16).astype(np.float64) / 32768.0
    return datos.reshape(-1, canales)


# --- musica ambiental ---------------------------------------------------------


def test_musica_ambiental_es_determinista(tmp_path):
    ruta_a = generar_musica_ambiental(tmp_path / "a.wav", segundos=32, semilla=7)
    ruta_b = generar_musica_ambiental(tmp_path / "b.wav", segundos=32, semilla=7)
    assert _sha1_de(ruta_a) == _sha1_de(ruta_b)


def test_musica_ambiental_semillas_distintas_dan_audio_distinto(tmp_path):
    ruta_a = generar_musica_ambiental(tmp_path / "a.wav", segundos=32, semilla=7)
    ruta_b = generar_musica_ambiental(tmp_path / "b.wav", segundos=32, semilla=11)
    assert _sha1_de(ruta_a) != _sha1_de(ruta_b)


def test_musica_ambiental_duracion_y_formato(tmp_path):
    ruta = generar_musica_ambiental(tmp_path / "musica.wav", segundos=32, semilla=7)
    with wave.open(str(ruta), "rb") as wf:
        assert wf.getnchannels() == 2
        assert wf.getsampwidth() == 2
        assert wf.getframerate() == 44100
        duracion = wf.getnframes() / wf.getframerate()
    assert duracion == pytest.approx(32.0, abs=0.01)


def test_musica_ambiental_sin_clipping_y_pico_esperado(tmp_path):
    ruta = generar_musica_ambiental(tmp_path / "musica.wav", segundos=32, semilla=7)
    muestras = _leer_muestras(ruta)
    pico = np.max(np.abs(muestras))
    assert pico <= 1.0
    # Pico objetivo -6 dBFS ~= 0.501; tolerancia por cuantizacion a 16 bit.
    assert pico == pytest.approx(10 ** (-6.0 / 20.0), abs=0.01)


def test_musica_ambiental_bucle_sin_salto_audible(tmp_path):
    ruta = generar_musica_ambiental(tmp_path / "musica.wav", segundos=32, semilla=7)
    muestras = _leer_muestras(ruta)[:, 0]
    diferencia = abs(float(muestras[-1]) - float(muestras[0]))
    # Debe ser una diferencia de muestra a muestra (continuidad), no un salto de nivel.
    assert diferencia < 0.02


def test_musica_ambiental_duracion_debe_ser_multiplo_de_32(tmp_path):
    with pytest.raises(ValueError):
        generar_musica_ambiental(tmp_path / "musica.wav", segundos=40, semilla=7)


def test_musica_ambiental_tonalidad_invalida(tmp_path):
    with pytest.raises(ValueError):
        generar_musica_ambiental(tmp_path / "musica.wav", segundos=32, tonalidad="mi_mayor")


# --- SFX -----------------------------------------------------------------------


@pytest.mark.parametrize("nombre", SFX_DISPONIBLES)
def test_sfx_es_determinista(nombre, tmp_path):
    ruta_a = generar_sfx(nombre, tmp_path / f"{nombre}_a.wav")
    ruta_b = generar_sfx(nombre, tmp_path / f"{nombre}_b.wav")
    assert _sha1_de(ruta_a) == _sha1_de(ruta_b)


@pytest.mark.parametrize("nombre", SFX_DISPONIBLES)
def test_sfx_sin_clipping_y_pico_esperado(nombre, tmp_path):
    ruta = generar_sfx(nombre, tmp_path / f"{nombre}.wav")
    muestras = _leer_muestras(ruta)
    pico = np.max(np.abs(muestras))
    assert pico <= 1.0
    assert pico == pytest.approx(10 ** (-3.0 / 20.0), abs=0.01)


@pytest.mark.parametrize("nombre", SFX_DISPONIBLES)
def test_sfx_formato_wav(nombre, tmp_path):
    ruta = generar_sfx(nombre, tmp_path / f"{nombre}.wav")
    with wave.open(str(ruta), "rb") as wf:
        assert wf.getnchannels() == 2
        assert wf.getsampwidth() == 2
        assert wf.getframerate() == 44100


def test_ruta_sfx_nombre_invalido():
    with pytest.raises(ValueError):
        ruta_sfx("no_existe")


def test_ruta_sfx_nombre_valido():
    for nombre in SFX_DISPONIBLES:
        ruta = ruta_sfx(nombre)
        assert ruta.name == f"sfx_{nombre}.wav"
