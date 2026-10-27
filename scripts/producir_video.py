"""Pipeline de producción: video.yaml ⇒ render de escenas ⇒ concatenación ⇒ música + ducking ⇒
loudnorm ⇒ ``salidas/<slug>_<calidad>.mp4`` + reporte ``.json``.

Uso:
    .venv/Scripts/python scripts/producir_video.py <video.yaml> --calidad borrador|media|alta

Formato de ``video.yaml``::

    slug: v01_suma_gauss
    titulo: "¿Cuánto es 1 + 2 + … + 100?"
    escenas:
      - {archivo: escena.py, clase: SumaGauss}     # relativo a la carpeta del yaml; en orden
    musica: assets/audio/musica_ambiental_01.wav    # relativo a la raíz; opcional
    volumen_musica_db: -24
    ducking: true
    loudness_lufs: -14

Narración sintética: el pipeline no ve las escenas, así que la detecta en la salida del render
(``MotorNarracion`` loguea un WARNING con "narración sintética" al caer al fallback de silencio).
Mejora pendiente: que ``narrar`` escriba un manifiesto ``<Clase>.narracion.json`` junto al mp4.
"""

from __future__ import annotations

import argparse
import ast
import json
import logging
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import yaml  # noqa: E402

from scripts.manim_runner import CALIDADES, ejecutar_manim  # noqa: E402
from toolkit.medios import (  # noqa: E402
    concatenar_videos,
    info_video,
    medir_loudness,
    mezclar_musica,
    normalizar_texto,
)

logger = logging.getLogger("producir_video")

DIR_SALIDAS = RAIZ / "salidas"
AVISO_SINTETICO = "NARRACIÓN SIN VOZ REAL"
_MARCA_SINTETICA = "narracion sintetica"  # normalizada: tolera tildes/codificación de la consola


class ErrorConfiguracion(ValueError):
    """``video.yaml`` inválido (clave faltante, archivo o clase inexistente, tipo incorrecto)."""


@dataclass(frozen=True)
class EscenaConfig:
    archivo: Path
    clase: str


@dataclass(frozen=True)
class ConfigVideo:
    slug: str
    escenas: list[EscenaConfig]
    titulo: str = ""
    musica: Path | None = None
    volumen_musica_db: float = -24
    ducking: bool = True
    loudness_lufs: float | None = -14
    ruta_yaml: Path = field(default=Path("video.yaml"))


def _clases_definidas(ruta: Path) -> list[str]:
    """Nombres de las clases de primer nivel de ``ruta`` (vía ``ast``, sin importar el módulo)."""
    try:
        arbol = ast.parse(ruta.read_text(encoding="utf-8"), filename=str(ruta))
    except SyntaxError as error:
        raise ErrorConfiguracion(f"{ruta} tiene un error de sintaxis: {error}") from error
    return [nodo.name for nodo in arbol.body if isinstance(nodo, ast.ClassDef)]


def cargar_configuracion(ruta_yaml: Path) -> ConfigVideo:
    """Lee y valida ``video.yaml``; lanza :class:`ErrorConfiguracion` con un mensaje claro."""
    ruta_yaml = Path(ruta_yaml).resolve()
    if not ruta_yaml.exists():
        raise ErrorConfiguracion(f"No existe el archivo de configuración: {ruta_yaml}")
    try:
        datos = yaml.safe_load(ruta_yaml.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as error:
        raise ErrorConfiguracion(f"{ruta_yaml} no es YAML válido: {error}") from error
    if not isinstance(datos, dict):
        raise ErrorConfiguracion(f"{ruta_yaml}: se esperaba un mapeo clave: valor en la raíz")

    for clave in ("slug", "escenas"):
        if clave not in datos:
            raise ErrorConfiguracion(f"{ruta_yaml}: falta la clave obligatoria '{clave}'")
    slug = str(datos["slug"]).strip()
    if not slug:
        raise ErrorConfiguracion(f"{ruta_yaml}: 'slug' no puede estar vacío")
    lista = datos["escenas"]
    if not isinstance(lista, list) or not lista:
        raise ErrorConfiguracion(f"{ruta_yaml}: 'escenas' debe ser una lista no vacía de {{archivo, clase}}")

    escenas: list[EscenaConfig] = []
    for i, entrada in enumerate(lista, start=1):
        if not isinstance(entrada, dict) or "archivo" not in entrada or "clase" not in entrada:
            raise ErrorConfiguracion(f"{ruta_yaml}: la escena #{i} necesita las claves 'archivo' y 'clase'")
        archivo = (ruta_yaml.parent / str(entrada["archivo"])).resolve()
        if not archivo.is_file():
            raise ErrorConfiguracion(f"{ruta_yaml}: escena #{i}: no existe el archivo {entrada['archivo']} ({archivo})")
        clase = str(entrada["clase"])
        disponibles = _clases_definidas(archivo)
        if clase not in disponibles:
            raise ErrorConfiguracion(
                f"{ruta_yaml}: escena #{i}: la clase {clase} no está definida en {archivo.name}; "
                f"clases disponibles: {', '.join(disponibles) or '(ninguna)'}"
            )
        escenas.append(EscenaConfig(archivo, clase))

    musica = None
    if datos.get("musica"):
        musica = (RAIZ / str(datos["musica"])).resolve()
        if not musica.is_file():
            raise ErrorConfiguracion(f"{ruta_yaml}: no existe la música {datos['musica']} ({musica})")

    try:
        volumen = float(datos.get("volumen_musica_db", -24))
        lufs = datos.get("loudness_lufs", -14)
        lufs = None if lufs is None else float(lufs)
    except (TypeError, ValueError) as error:
        raise ErrorConfiguracion(f"{ruta_yaml}: 'volumen_musica_db' y 'loudness_lufs' deben ser números") from error

    return ConfigVideo(
        slug=slug,
        escenas=escenas,
        titulo=str(datos.get("titulo", "")),
        musica=musica,
        volumen_musica_db=volumen,
        ducking=bool(datos.get("ducking", True)),
        loudness_lufs=lufs,
        ruta_yaml=ruta_yaml,
    )


def detectar_segmentos_sinteticos(salida_render: str) -> list[str]:
    """Líneas de la salida del render que delatan narración sintética (fallback sin edge-tts)."""
    return [linea.strip() for linea in salida_render.splitlines() if _MARCA_SINTETICA in normalizar_texto(linea)]


def _avisar(mensaje: str) -> None:
    logger.warning(mensaje)
    print(f"WARNING: {mensaje}", file=sys.stderr, flush=True)


def producir(
    ruta_yaml: Path,
    calidad: str = "borrador",
    media_dir: Path | None = None,
    dir_salidas: Path = DIR_SALIDAS,
) -> Path:
    """Produce el video final descrito por ``ruta_yaml`` y devuelve la ruta del mp4.

    ``RuntimeError`` si alguna escena falla (con la ruta del ``reporte_error.json``).
    """
    if calidad not in CALIDADES:
        raise ValueError(f"Calidad desconocida: {calidad!r}. Usa una de {sorted(CALIDADES)}.")
    cfg = cargar_configuracion(ruta_yaml)
    dir_salidas = Path(dir_salidas)
    dir_salidas.mkdir(parents=True, exist_ok=True)
    base = f"{cfg.slug}_{calidad}"
    destino = dir_salidas / f"{base}.mp4"

    videos: list[Path] = []
    escenas_reporte: list[dict] = []
    sinteticos: list[str] = []
    inicio = 0.0
    for escena in cfg.escenas:
        print(f"[render] {escena.archivo.name}::{escena.clase} ({calidad})...", flush=True)
        resultado = ejecutar_manim(escena.archivo, escena.clase, calidad, media_dir=media_dir)
        if not resultado.exito or resultado.ruta_video is None:
            raise RuntimeError(
                f"Falló el render de {escena.clase} ({escena.archivo}). Reporte: {resultado.reporte_error}\n"
                f"{resultado.salida[-1500:]}"
            )
        duracion = info_video(resultado.ruta_video)["duracion"]
        detectados = detectar_segmentos_sinteticos(resultado.salida)
        sinteticos += [f"{escena.clase}: {linea}" for linea in detectados]
        print(f"[render] OK {resultado.ruta_video} ({duracion:.2f} s de video, {resultado.segundos:.1f} s)", flush=True)
        videos.append(resultado.ruta_video)
        escenas_reporte.append(
            {
                "archivo": str(escena.archivo),
                "clase": escena.clase,
                "video": str(resultado.ruta_video),
                "inicio": round(inicio, 3),
                "duracion": round(duracion, 3),
                "segundos_render": round(resultado.segundos, 2),
                "segmentos_sinteticos": len(detectados),
            }
        )
        inicio += duracion

    dir_temporal = dir_salidas / f".tmp_{base}"
    dir_temporal.mkdir(parents=True, exist_ok=True)
    try:
        if len(videos) > 1:
            print(f"[concat] {len(videos)} escenas...", flush=True)
            unido = concatenar_videos(videos, dir_temporal / "concatenado.mp4")
        else:
            unido = videos[0]
        print("[mezcla] música, ducking y loudnorm (2 pasadas)...", flush=True)
        mezclar_musica(
            unido,
            cfg.musica,
            destino,
            volumen_db=cfg.volumen_musica_db,
            ducking=cfg.ducking,
            lufs=cfg.loudness_lufs,
        )
    finally:
        shutil.rmtree(dir_temporal, ignore_errors=True)

    info = info_video(destino)
    reporte = {
        "slug": cfg.slug,
        "titulo": cfg.titulo,
        "calidad": calidad,
        "video": str(destino),
        "duracion": round(info["duracion"], 3),
        "resolucion": [info["ancho"], info["alto"]],
        "fps": info["fps"],
        "codec_audio": info["codec_audio"],
        "loudness_lufs_objetivo": cfg.loudness_lufs,
        "loudness_lufs_medido": medir_loudness(destino) if info["codec_audio"] else None,
        "musica": str(cfg.musica) if cfg.musica else None,
        "ducking": cfg.ducking,
        "escenas": escenas_reporte,
        "narracion_sintetica": bool(sinteticos),
        "segmentos_sinteticos": sinteticos,
    }
    destino.with_suffix(".json").write_text(json.dumps(reporte, ensure_ascii=False, indent=2), encoding="utf-8")
    if sinteticos:
        _avisar(f"{AVISO_SINTETICO}: {len(sinteticos)} segmento(s) sintéticos (silencio). No publicar este video.")
    return destino


def main() -> int:
    for flujo in (sys.stdout, sys.stderr):
        if hasattr(flujo, "reconfigure"):
            flujo.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Produce un short a partir de su video.yaml")
    parser.add_argument("yaml", help="Ruta a video.yaml")
    parser.add_argument("--calidad", default="borrador", choices=sorted(CALIDADES))
    parser.add_argument("--media-dir", default=None, help="Directorio de media de manim (default: <raíz>/media)")
    parser.add_argument("--salidas", default=str(DIR_SALIDAS), help="Carpeta de salida (default: <raíz>/salidas)")
    args = parser.parse_args()
    try:
        destino = producir(
            Path(args.yaml),
            args.calidad,
            media_dir=Path(args.media_dir) if args.media_dir else None,
            dir_salidas=Path(args.salidas),
        )
    except (ErrorConfiguracion, RuntimeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    reporte = json.loads(destino.with_suffix(".json").read_text(encoding="utf-8"))
    print(
        f"Video listo: {destino}\n"
        f"  {reporte['resolucion'][0]}x{reporte['resolucion'][1]} @ {reporte['fps']:g} fps, "
        f"{reporte['duracion']:.2f} s, audio {reporte['codec_audio']}, "
        f"loudness {reporte['loudness_lufs_medido']} LUFS"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
