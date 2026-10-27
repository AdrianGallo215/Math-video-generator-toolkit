"""Musica ambiental y SFX procedurales, generados con numpy (sin licencias externas).

Todo se sintetiza con osciladores deterministas (mismo codigo + misma semilla ⇒
mismos bytes) y se escribe en WAV PCM 16 bit estereo a 44.1 kHz con el modulo
``wave`` de la biblioteca estandar.
"""

import logging
import wave
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

FRECUENCIA_MUESTREO = 44100
CANALES = 2
BITS_POR_MUESTRA = 16

RAIZ_AUDIO = Path(__file__).resolve().parent.parent / "assets" / "audio"

DURACION_ACORDE_S = 8.0
CROSSFADE_ACORDES_S = 1.5
FRECUENCIA_TREMOLO_HZ = 0.2
PROFUNDIDAD_TREMOLO = 0.06
GANANCIA_ARPEGIO_DB = -12.0

PICO_MUSICA_DBFS = -6.0
PICO_SFX_DBFS = -3.0

# Progresiones de acordes por tonalidad; cada acorde es una lista de notas MIDI.
# re_menor: Dm - Bb - F - C (8 s cada uno ⇒ ciclo de 32 s).
# la_menor: Am - F - C - G (8 s cada uno ⇒ ciclo de 32 s).
PROGRESIONES: dict[str, list[list[int]]] = {
    "re_menor": [
        [38, 41, 45, 50],  # Dm  (D2 F2 A2 D3)
        [46, 50, 53, 58],  # Bb  (Bb2 D3 F3 Bb3)
        [41, 45, 48, 53],  # F   (F2 A2 C3 F3)
        [48, 52, 55, 60],  # C   (C3 E3 G3 C4)
    ],
    "la_menor": [
        [45, 48, 52, 57],  # Am  (A2 C3 E3 A3)
        [41, 45, 48, 53],  # F   (F2 A2 C3 F3)
        [48, 52, 55, 60],  # C   (C3 E3 G3 C4)
        [43, 47, 50, 55],  # G   (G2 B2 D3 G3)
    ],
}

# Arpegio pentatonico (menor) por tonalidad, una octava por encima del acorde.
ARPEGIOS: dict[str, list[int]] = {
    "re_menor": [62, 65, 67, 69, 72, 69, 67, 65],  # D F G A C (pentatonica de Re menor)
    "la_menor": [57, 60, 62, 64, 67, 64, 62, 60],  # A C D E G (pentatonica de La menor)
}

SFX_DISPONIBLES = ("pop", "whoosh", "ding", "tick", "exito")


def ruta_sfx(nombre: str) -> Path:
    """Devuelve la ruta canonica del WAV de un efecto de sonido.

    Lanza ``ValueError`` si ``nombre`` no esta en ``SFX_DISPONIBLES``.
    """
    if nombre not in SFX_DISPONIBLES:
        raise ValueError(f"sfx desconocido: {nombre!r}. Disponibles: {SFX_DISPONIBLES}")
    return RAIZ_AUDIO / f"sfx_{nombre}.wav"


# --- utilidades numericas compartidas ---------------------------------------


def _frecuencia_de_nota_midi(midi: int) -> float:
    """Convierte un numero de nota MIDI a frecuencia en Hz (A4=440 Hz, midi=69)."""
    return 440.0 * (2.0 ** ((midi - 69) / 12.0))


def _db_a_amplitud(db: float) -> float:
    return 10.0 ** (db / 20.0)


def _triangulo_banda_limitada(t: np.ndarray, freq: float, sr: int, max_armonicos: int = 15) -> np.ndarray:
    """Onda triangular por sintesis aditiva de armonicos impares (evita aliasing).

    Se detiene antes de acercarse a Nyquist para no generar aliasing chillon.
    """
    señal = np.zeros_like(t)
    nyquist = sr / 2.0
    for k in range(max_armonicos):
        n = 2 * k + 1
        f_n = n * freq
        if f_n >= nyquist * 0.85:
            break
        signo = 1.0 if k % 2 == 0 else -1.0
        señal += (signo / (n**2)) * np.sin(2 * np.pi * f_n * t)
    return señal * (8.0 / np.pi**2)


def _normalizar_pico(señal: np.ndarray, pico_dbfs: float) -> np.ndarray:
    pico_actual = float(np.max(np.abs(señal))) if señal.size else 0.0
    if pico_actual < 1e-12:
        return señal
    objetivo = _db_a_amplitud(pico_dbfs)
    return señal * (objetivo / pico_actual)


def _fade_bordes(señal: np.ndarray, sr: int, entrada_s: float = 0.003, salida_s: float = 0.008) -> np.ndarray:
    """Aplica un fade coseno muy corto en los bordes para evitar clics de arranque/corte."""
    n = len(señal)
    resultado = señal.copy()
    n_in = min(n, int(entrada_s * sr))
    n_out = min(n, int(salida_s * sr))
    if n_in > 1:
        x = np.linspace(0.0, 1.0, n_in)
        resultado[:n_in] *= 0.5 * (1 - np.cos(np.pi * x))
    if n_out > 1:
        x = np.linspace(0.0, 1.0, n_out)
        resultado[n - n_out :] *= 0.5 * (1 + np.cos(np.pi * x))
    return resultado


def _bucle_perfecto(señal: np.ndarray, objetivo_muestras: int, cf_muestras: int) -> np.ndarray:
    """Recorta ``señal`` (mas larga que ``objetivo_muestras``) a un bucle sin salto.

    Mezcla el tramo extra que sigue a ``objetivo_muestras`` (la "cola") con el
    principio de la señal, de modo que la ultima muestra del resultado y la
    primera queden practicamente contiguas (la señal original es continua ahi).
    """
    salida = señal[:objetivo_muestras].copy()
    cola = señal[objetivo_muestras : objetivo_muestras + cf_muestras]
    cf = min(cf_muestras, len(cola), len(salida))
    if cf <= 1:
        return salida
    x = np.arange(cf) / (cf - 1)
    fade_in = 0.5 * (1 - np.cos(np.pi * x))  # 0 -> 1 (peso de la propia señal)
    fade_out = 1.0 - fade_in  # 1 -> 0 (peso de la cola/continuacion)
    salida[:cf] = salida[:cf] * fade_in + cola[:cf] * fade_out
    return salida


def _guardar_wav(ruta: Path, estereo_float: np.ndarray, sr: int) -> Path:
    """Escribe un array float (n, 2) en [-1, 1] como WAV PCM 16 bit estereo."""
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    datos = np.clip(np.round(estereo_float * 32767.0), -32768, 32767).astype(np.int16)
    with wave.open(str(ruta), "wb") as wf:
        wf.setnchannels(CANALES)
        wf.setsampwidth(BITS_POR_MUESTRA // 8)
        wf.setframerate(sr)
        wf.writeframes(datos.tobytes())
    return ruta


# --- musica ambiental ---------------------------------------------------------


def _envolvente_acorde(t_local: np.ndarray, inicio_bloque: float, duracion: float, cf: float) -> np.ndarray:
    """Ventana con crossfade coseno en ambos bordes; 0 fuera de [inicio-cf/2, fin+cf/2]."""
    ini_ventana = inicio_bloque - cf / 2
    fin_ventana = inicio_bloque + duracion + cf / 2
    env = np.ones_like(t_local)

    en_subida = (t_local >= ini_ventana) & (t_local < ini_ventana + cf)
    if np.any(en_subida):
        x = (t_local[en_subida] - ini_ventana) / cf
        env[en_subida] = 0.5 * (1 - np.cos(np.pi * x))

    en_bajada = (t_local >= fin_ventana - cf) & (t_local <= fin_ventana)
    if np.any(en_bajada):
        x = (t_local[en_bajada] - (fin_ventana - cf)) / cf
        env[en_bajada] = 0.5 * (1 + np.cos(np.pi * x))

    fuera = (t_local < ini_ventana) | (t_local > fin_ventana)
    env[fuera] = 0.0
    return env


def generar_musica_ambiental(
    ruta: Path,
    segundos: int = 64,
    semilla: int = 7,
    tonalidad: str = "re_menor",
) -> Path:
    """Genera un pad ambiental calido en bucle perfecto y lo guarda en ``ruta``.

    Progresion de acordes (8 s cada uno), senos + triangulo suavizado (banda
    limitada, sin aliasing), crossfade de 1.5 s entre acordes, tremolo de
    0.2 Hz y un arpegio pentatonico suave (-12 dB relativo). Pico final a
    -6 dBFS. ``segundos`` debe ser multiplo de 32 (duracion del ciclo
    armonico) para que el bucle sea musicalmente perfecto.
    """
    if tonalidad not in PROGRESIONES:
        raise ValueError(f"tonalidad desconocida: {tonalidad!r}. Disponibles: {tuple(PROGRESIONES)}")
    if segundos <= 0 or segundos % 32 != 0:
        raise ValueError("segundos debe ser un multiplo positivo de 32 (duracion del ciclo de acordes)")

    sr = FRECUENCIA_MUESTREO
    cf_s = CROSSFADE_ACORDES_S
    duracion_generada = segundos + cf_s
    n_generado = int(round(duracion_generada * sr))
    t = np.arange(n_generado) / sr

    progresion = PROGRESIONES[tonalidad]
    notas_arpegio = ARPEGIOS[tonalidad]
    rng = np.random.default_rng(semilla)

    pad = np.zeros(n_generado)
    arpegio = np.zeros(n_generado)

    n_bloques = int(np.ceil(duracion_generada / DURACION_ACORDE_S)) + 1
    paso_arpegio_s = 1.0
    pasos_por_bloque = int(DURACION_ACORDE_S / paso_arpegio_s)

    for i in range(n_bloques):
        inicio_bloque = i * DURACION_ACORDE_S
        ini_ventana = inicio_bloque - cf_s / 2
        fin_ventana = inicio_bloque + DURACION_ACORDE_S + cf_s / 2
        idx_ini = max(0, int(np.floor(ini_ventana * sr)))
        idx_fin = min(n_generado, int(np.ceil(fin_ventana * sr)))
        if idx_ini >= idx_fin:
            continue

        t_local = t[idx_ini:idx_fin]
        envolvente = _envolvente_acorde(t_local, inicio_bloque, DURACION_ACORDE_S, cf_s)

        notas_midi = progresion[i % len(progresion)]
        for midi in notas_midi:
            freq = _frecuencia_de_nota_midi(midi)
            onda = 0.6 * np.sin(2 * np.pi * freq * t_local) + 0.4 * _triangulo_banda_limitada(t_local, freq, sr)
            pad[idx_ini:idx_fin] += onda * envolvente / len(notas_midi)

        for p in range(pasos_por_bloque):
            jitter_t = rng.uniform(-0.015, 0.015)
            jitter_amp = 1.0 + rng.uniform(-0.1, 0.1)
            inicio_nota = inicio_bloque + p * paso_arpegio_s + jitter_t
            if inicio_nota < 0 or inicio_nota >= duracion_generada:
                continue
            midi_arp = notas_arpegio[(i * pasos_por_bloque + p) % len(notas_arpegio)]
            freq_arp = _frecuencia_de_nota_midi(midi_arp)
            dur_nota = 0.9
            idx_n_ini = int(inicio_nota * sr)
            idx_n_fin = min(n_generado, idx_n_ini + int(dur_nota * sr))
            if idx_n_ini >= idx_n_fin:
                continue
            t_n = np.arange(idx_n_fin - idx_n_ini) / sr
            env_n = np.exp(-t_n / 0.35) * np.minimum(1.0, t_n / 0.01)
            arpegio[idx_n_ini:idx_n_fin] += np.sin(2 * np.pi * freq_arp * t_n) * env_n * jitter_amp

    ganancia_arpegio = _db_a_amplitud(GANANCIA_ARPEGIO_DB)
    señal = pad + arpegio * ganancia_arpegio

    tremolo = 1.0 + PROFUNDIDAD_TREMOLO * np.sin(2 * np.pi * FRECUENCIA_TREMOLO_HZ * t)
    señal = señal * tremolo

    objetivo_muestras = int(round(segundos * sr))
    cf_muestras = int(round(cf_s * sr))
    señal_bucle = _bucle_perfecto(señal, objetivo_muestras, cf_muestras)
    señal_normalizada = _normalizar_pico(señal_bucle, PICO_MUSICA_DBFS)

    estereo = np.stack([señal_normalizada, señal_normalizada], axis=1)
    ruta_final = _guardar_wav(Path(ruta), estereo, sr)
    logger.debug("musica ambiental generada: %s (%s s, %s)", ruta_final, segundos, tonalidad)
    return ruta_final


# --- efectos de sonido (SFX) --------------------------------------------------


def _sfx_pop(sr: int) -> np.ndarray:
    duracion = 0.09
    n = int(duracion * sr)
    t = np.arange(n) / sr
    freq = 880.0 * (440.0 / 880.0) ** (t / duracion)  # deslizamiento exponencial 880 -> 440 Hz
    fase = 2 * np.pi * np.cumsum(freq) / sr
    envolvente = np.exp(-t / 0.025)
    return np.sin(fase) * envolvente


def _sfx_whoosh(sr: int) -> np.ndarray:
    duracion = 0.45
    n = int(duracion * sr)
    t = np.arange(n) / sr
    rng = np.random.default_rng(4242)
    ruido = rng.standard_normal(n)
    corte = 200.0 * (4000.0 / 200.0) ** (t / duracion)  # barrido de corte 200 -> 4000 Hz
    alpha = 1.0 - np.exp(-2 * np.pi * corte / sr)
    filtrado = np.zeros(n)
    anterior = 0.0
    for i in range(n):
        anterior = anterior + alpha[i] * (ruido[i] - anterior)
        filtrado[i] = anterior
    envolvente = np.sin(np.pi * np.clip(t / duracion, 0.0, 1.0)) ** 0.7
    return filtrado * envolvente


def _sfx_ding(sr: int) -> np.ndarray:
    duracion = 1.2
    t = np.arange(int(duracion * sr)) / sr
    fundamental = 880.0
    onda = np.sin(2 * np.pi * fundamental * 1.0 * t) * np.exp(-t / 0.9)
    onda += 0.6 * np.sin(2 * np.pi * fundamental * 2.76 * t) * np.exp(-t / 0.5)
    onda += 0.35 * np.sin(2 * np.pi * fundamental * 5.4 * t) * np.exp(-t / 0.25)
    return onda


def _sfx_tick(sr: int) -> np.ndarray:
    duracion = 0.015
    n = int(duracion * sr)
    t = np.arange(n) / sr
    rng = np.random.default_rng(99)
    ruido = rng.standard_normal(n)
    envolvente = np.exp(-t / 0.004)
    tono = np.sin(2 * np.pi * 3000.0 * t)
    return (0.6 * tono + 0.4 * ruido) * envolvente


def _sfx_exito(sr: int) -> np.ndarray:
    duracion = 0.5
    n = int(duracion * sr)
    t = np.arange(n) / sr
    freq = 660.0 * (990.0 / 660.0) ** (t / duracion)  # 660 -> 990 Hz
    fase = 2 * np.pi * np.cumsum(freq) / sr
    ataque_s, salida_s = 0.03, 0.1
    envolvente = np.minimum(1.0, t / ataque_s)
    envolvente = np.minimum(envolvente, (duracion - t) / salida_s)
    envolvente = np.clip(envolvente, 0.0, 1.0)
    return np.sin(fase) * envolvente


_GENERADORES_SFX = {
    "pop": _sfx_pop,
    "whoosh": _sfx_whoosh,
    "ding": _sfx_ding,
    "tick": _sfx_tick,
    "exito": _sfx_exito,
}


def generar_sfx(nombre: str, ruta: Path) -> Path:
    """Genera un efecto de sonido corto y lo guarda en ``ruta`` (pico -3 dBFS).

    Lanza ``ValueError`` si ``nombre`` no esta en ``SFX_DISPONIBLES``.
    """
    if nombre not in SFX_DISPONIBLES:
        raise ValueError(f"sfx desconocido: {nombre!r}. Disponibles: {SFX_DISPONIBLES}")

    sr = FRECUENCIA_MUESTREO
    mono = _GENERADORES_SFX[nombre](sr)
    mono = _fade_bordes(mono, sr)
    mono = _normalizar_pico(mono, PICO_SFX_DBFS)

    estereo = np.stack([mono, mono], axis=1)
    ruta_final = _guardar_wav(Path(ruta), estereo, sr)
    logger.debug("sfx generado: %s", ruta_final)
    return ruta_final
