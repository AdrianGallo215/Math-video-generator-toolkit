"""Utilidades de medios: ffmpeg (vía imageio-ffmpeg), conversión/duración de audio, silencios y
normalización de texto para comparar palabras (anclas de narración, subtítulos).

No importa manim: puede usarse desde scripts y tests sin construir escenas.
"""

from __future__ import annotations

import functools
import json
import logging
import re
import subprocess
import unicodedata
import wave
from pathlib import Path

logger = logging.getLogger(__name__)

RAIZ = Path(__file__).resolve().parents[1]

FRECUENCIA_POR_DEFECTO = 48000
_NO_ALFANUMERICO = re.compile(r"[^0-9a-z]+")


@functools.lru_cache(maxsize=1)
def ruta_ffmpeg() -> str:
    """Ruta al binario de ffmpeg empaquetado por ``imageio-ffmpeg`` (ffmpeg no está en PATH)."""
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def ejecutar_ffmpeg(args: list[str]) -> None:
    """Ejecuta ffmpeg con ``-hide_banner -loglevel error -y``; ``RuntimeError`` con stderr si falla."""
    comando = [ruta_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", *args]
    resultado = subprocess.run(comando, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if resultado.returncode != 0:
        raise RuntimeError(
            f"ffmpeg falló (código {resultado.returncode}): {' '.join(args)}\n{resultado.stderr.strip()}"
        )


def convertir_a_wav(origen: Path, destino: Path, frecuencia: int = FRECUENCIA_POR_DEFECTO) -> Path:
    """Convierte ``origen`` a WAV estéreo PCM 16 bit a ``frecuencia`` Hz."""
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    ejecutar_ffmpeg(
        ["-i", str(origen), "-vn", "-ac", "2", "-ar", str(frecuencia), "-c:a", "pcm_s16le", str(destino)]
    )
    return destino


def duracion_audio(ruta: Path) -> float:
    """Duración en segundos. WAV con el módulo ``wave``; otros formatos vía PyAV."""
    ruta = Path(ruta)
    if ruta.suffix.lower() == ".wav":
        try:
            with wave.open(str(ruta), "rb") as wf:
                return wf.getnframes() / float(wf.getframerate())
        except wave.Error:
            logger.debug("%s no es un WAV PCM legible con wave; se usa PyAV", ruta)
    import av

    with av.open(str(ruta)) as contenedor:
        stream = contenedor.streams.audio[0]
        if stream.duration is not None and stream.time_base is not None:
            return float(stream.duration * stream.time_base)
        if contenedor.duration is not None:
            return contenedor.duration / 1_000_000
        # Último recurso: decodificar y sumar muestras.
        muestras = sum(frame.samples for frame in contenedor.decode(stream))
        return muestras / float(stream.rate)


def silencio_wav(destino: Path, segundos: float, frecuencia: int = FRECUENCIA_POR_DEFECTO) -> Path:
    """Escribe un WAV estéreo 16 bit de silencio de ``segundos`` de duración."""
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    n_muestras = max(0, int(round(segundos * frecuencia)))
    with wave.open(str(destino), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(frecuencia)
        wf.writeframes(b"\x00" * (n_muestras * 4))
    return destino


def normalizar_texto(t: str) -> str:
    """Minúsculas, sin tildes (NFD), ñ→n, sin puntuación y con espacios colapsados.

    ``"¿Por qué, Ñandú?"`` ⇒ ``"por que nandu"``. La puntuación se trata como separador.
    """
    descompuesto = unicodedata.normalize("NFD", t.lower())
    sin_marcas = "".join(c for c in descompuesto if unicodedata.category(c) != "Mn")
    return _NO_ALFANUMERICO.sub(" ", sin_marcas).strip()


# --- Video: inspección, concatenación y mezcla final (T12) -------------------------------

CODEC_VIDEO_FINAL = ["-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p"]
CODEC_AUDIO_FINAL = ["-c:a", "aac", "-b:a", "192k", "-ar", str(FRECUENCIA_POR_DEFECTO)]
DUCKING_POR_DEFECTO = "threshold=0.02:ratio=10:attack=15:release=350"
FADE_IN_MUSICA = 1.0
FADE_OUT_MUSICA = 1.5
PICO_VERDADERO_DB = -1.5
RANGO_LOUDNESS = 11
_LOUDNESS_MINIMO_MEDIBLE = -70.0  # por debajo (o -inf) es silencio: loudnorm no puede normalizarlo
_FORMATO_AUDIO = f"aresample={FRECUENCIA_POR_DEFECTO},aformat=sample_fmts=fltp:channel_layouts=stereo"


def _ejecutar_ffmpeg_con_log(args: list[str]) -> str:
    """Como :func:`ejecutar_ffmpeg` pero con ``-loglevel info`` y devolviendo stderr (mediciones)."""
    comando = [ruta_ffmpeg(), "-hide_banner", "-nostats", "-loglevel", "info", "-y", *args]
    resultado = subprocess.run(comando, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if resultado.returncode != 0:
        raise RuntimeError(
            f"ffmpeg falló (código {resultado.returncode}): {' '.join(args)}\n{resultado.stderr[-3000:].strip()}"
        )
    return resultado.stderr


def info_video(ruta: Path) -> dict:
    """Resumen de un video vía PyAV: ancho, alto, fps, duracion (s), codecs y datos del audio."""
    import av

    with av.open(str(ruta)) as contenedor:
        video = contenedor.streams.video[0] if contenedor.streams.video else None
        audio = contenedor.streams.audio[0] if contenedor.streams.audio else None
        if video is not None and video.duration is not None and video.time_base is not None:
            duracion = float(video.duration * video.time_base)
        elif contenedor.duration is not None:
            duracion = contenedor.duration / 1_000_000
        else:
            duracion = 0.0
        duracion_pista_audio = None
        if audio is not None and audio.duration is not None and audio.time_base is not None:
            duracion_pista_audio = float(audio.duration * audio.time_base)
        return {
            "ancho": video.codec_context.width if video else None,
            "alto": video.codec_context.height if video else None,
            "fps": float(video.average_rate) if video is not None and video.average_rate else None,
            "duracion": duracion,
            "codec_video": video.codec_context.name if video else None,
            "codec_audio": audio.codec_context.name if audio else None,
            "frecuencia_audio": audio.codec_context.sample_rate if audio else None,
            "canales_audio": audio.codec_context.layout.nb_channels if audio else None,
            "duracion_audio": duracion_pista_audio,
        }


def tiene_audio(ruta: Path) -> bool:
    """¿El contenedor tiene al menos un stream de audio?"""
    import av

    with av.open(str(ruta)) as contenedor:
        return bool(contenedor.streams.audio)


def duracion_video(ruta: Path) -> float:
    """Duración en segundos del stream de video (o del contenedor si no la declara)."""
    return float(info_video(ruta)["duracion"])


def concatenar_videos(rutas: list[Path], destino: Path) -> Path:
    """Concatena ``rutas`` (misma resolución/fps) re-codificando a H.264 + AAC 48 kHz.

    A las piezas sin audio se les da silencio (``anullsrc``) de su duración; el audio de cada pieza
    se rellena/recorta a la duración de su video para que no se acumule desfase.
    """
    rutas = [Path(r) for r in rutas]
    if not rutas:
        raise ValueError("concatenar_videos necesita al menos un video")
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    entradas: list[str] = []
    filtros: list[str] = []
    etiquetas: list[str] = []
    indice_entrada = 0
    for i, ruta in enumerate(rutas):
        duracion = duracion_video(ruta)
        entradas += ["-i", str(ruta)]
        indice_video = indice_entrada
        indice_entrada += 1
        if tiene_audio(ruta):
            origen_audio = f"[{indice_video}:a]"
        else:
            entradas += ["-f", "lavfi", "-t", f"{duracion:.6f}", "-i", f"anullsrc=r={FRECUENCIA_POR_DEFECTO}:cl=stereo"]
            origen_audio = f"[{indice_entrada}:a]"
            indice_entrada += 1
        filtros.append(f"[{indice_video}:v]setsar=1,format=yuv420p[v{i}]")
        filtros.append(f"{origen_audio}{_FORMATO_AUDIO},apad,atrim=0:{duracion:.6f},asetpts=PTS-STARTPTS[a{i}]")
        etiquetas.append(f"[v{i}][a{i}]")
    filtros.append("".join(etiquetas) + f"concat=n={len(rutas)}:v=1:a=1[v][a]")
    ejecutar_ffmpeg(
        [
            *entradas,
            "-filter_complex", ";".join(filtros),
            "-map", "[v]", "-map", "[a]",
            *CODEC_VIDEO_FINAL, *CODEC_AUDIO_FINAL,
            "-movflags", "+faststart",
            str(destino),
        ]
    )  # fmt: skip
    return destino


def _grafo_mezcla(tiene_voz: bool, con_musica: bool, duracion: float, volumen_db: float, ducking: bool) -> str:
    """Grafo de filtros (sin loudnorm) que deja la mezcla en la etiqueta ``[mezcla]``.

    Entradas: 0 = video (voz en ``0:a``), 1 = música en bucle. Con ducking la voz se divide con
    ``asplit``: una copia va a la mezcla y otra es la señal de control del ``sidechaincompress``.
    """
    partes: list[str] = []
    if con_musica:
        inicio_fade_out = max(0.0, duracion - FADE_OUT_MUSICA)
        partes.append(
            f"[1:a]{_FORMATO_AUDIO},atrim=0:{duracion:.6f},asetpts=PTS-STARTPTS,volume={volumen_db}dB,"
            f"afade=t=in:st=0:d={FADE_IN_MUSICA},afade=t=out:st={inicio_fade_out:.6f}:d={FADE_OUT_MUSICA}[musica]"
        )
    if tiene_voz and con_musica:
        if ducking:
            partes.append(f"[0:a]{_FORMATO_AUDIO},asplit=2[voz][control]")
            partes.append(f"[musica][control]sidechaincompress={DUCKING_POR_DEFECTO}[musica_atenuada]")
            fuente_musica = "[musica_atenuada]"
        else:
            partes.append(f"[0:a]{_FORMATO_AUDIO}[voz]")
            fuente_musica = "[musica]"
        partes.append(f"[voz]{fuente_musica}amix=inputs=2:duration=first:normalize=0[mezcla]")
    elif tiene_voz:
        partes.append(f"[0:a]{_FORMATO_AUDIO}[mezcla]")
    else:
        partes.append("[musica]anull[mezcla]")
    return ";".join(partes)


def _filtro_loudnorm(lufs: float) -> str:
    return f"loudnorm=I={lufs}:TP={PICO_VERDADERO_DB}:LRA={RANGO_LOUDNESS}"


def _medir_loudnorm(entradas: list[str], grafo: str, lufs: float) -> dict:
    """Primera pasada de ``loudnorm`` (``print_format=json``): devuelve las mediciones ``input_*``."""
    filtro = f"{grafo};[mezcla]{_filtro_loudnorm(lufs)}:print_format=json[medido]"
    log = _ejecutar_ffmpeg_con_log([*entradas, "-filter_complex", filtro, "-map", "[medido]", "-f", "null", "-"])
    inicio, fin = log.rfind("{"), log.rfind("}")
    if inicio < 0 or fin < inicio:
        raise RuntimeError(f"loudnorm no devolvió mediciones JSON:\n{log[-2000:]}")
    return json.loads(log[inicio : fin + 1])


def mezclar_musica(
    video: Path,
    musica: Path | None,
    destino: Path,
    volumen_db: float = -24.0,
    ducking: bool = True,
    lufs: float | None = -14.0,
) -> Path:
    """Mezcla final: música en bucle (volumen, fades, ducking bajo la voz) + loudnorm en dos pasadas.

    - ``musica=None`` ⇒ solo normaliza la voz. Video sin audio ⇒ la música va sola.
    - ``lufs=None`` ⇒ sin normalización (útil para medir el ducking).
    - Loudnorm: 1.ª pasada mide (``print_format=json``); 2.ª aplica ``measured_*`` con ``linear=true``
      (ffmpeg cae a modo dinámico si la ganancia lineal violaría el pico verdadero). Una mezcla en
      silencio (narración sintética sin música) no se normaliza.
    - El video se copia (``-c:v copy``); audio AAC 192 kb/s 48 kHz; ``-movflags +faststart``.
    """
    video, destino = Path(video), Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    duracion = duracion_video(video)
    tiene_voz = tiene_audio(video)
    con_musica = musica is not None
    if not tiene_voz and not con_musica:
        raise ValueError(f"{video} no tiene audio y no se indicó música: nada que mezclar")

    entradas = ["-i", str(video)]
    if con_musica:
        entradas += ["-stream_loop", "-1", "-i", str(musica)]
    grafo = _grafo_mezcla(tiene_voz, con_musica, duracion, volumen_db, ducking)
    etiqueta = "[mezcla]"

    if lufs is not None:
        medido = _medir_loudnorm(entradas, grafo, lufs)
        loudness_entrada = float(medido["input_i"])  # "-inf" se convierte sin error
        if loudness_entrada > _LOUDNESS_MINIMO_MEDIBLE:
            grafo += (
                f";[mezcla]{_filtro_loudnorm(lufs)}"
                f":measured_I={medido['input_i']}:measured_TP={medido['input_tp']}"
                f":measured_LRA={medido['input_lra']}:measured_thresh={medido['input_thresh']}"
                f":offset={medido['target_offset']}:linear=true,aresample={FRECUENCIA_POR_DEFECTO}[final]"
            )
            etiqueta = "[final]"
        else:
            logger.warning("Mezcla en silencio (%s LUFS): se omite loudnorm", medido["input_i"])

    ejecutar_ffmpeg(
        [
            *entradas,
            "-filter_complex", grafo,
            "-map", "0:v", "-map", etiqueta,
            "-c:v", "copy", *CODEC_AUDIO_FINAL,
            "-t", f"{duracion:.6f}",
            "-movflags", "+faststart",
            str(destino),
        ]
    )  # fmt: skip
    return destino


def medir_loudness(ruta: Path) -> float:
    """Loudness integrado (LUFS) del audio de ``ruta`` medido con el filtro ``ebur128``."""
    log = _ejecutar_ffmpeg_con_log(["-i", str(ruta), "-map", "0:a:0", "-af", "ebur128", "-f", "null", "-"])
    resumen = log[log.rfind("Summary:") :] if "Summary:" in log else log
    coincidencia = re.search(r"I:\s*(-?[\d.]+|-inf)\s*LUFS", resumen)
    if not coincidencia:
        raise RuntimeError(f"ebur128 no devolvió loudness integrado:\n{log[-1500:]}")
    return float(coincidencia.group(1))
