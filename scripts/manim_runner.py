"""Runner robusto de escenas Manim: construye el comando, prepara el entorno,
ejecuta el subproceso y localiza el mp4 resultante (o escribe un reporte de error)."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from toolkit.configuracion import PERFILES  # noqa: E402

CALIDADES = {"borrador": "-ql", "media": "-qm", "alta": "-qh"}


@dataclass
class ResultadoRender:
    """Resultado de un intento de render con :func:`ejecutar_manim`."""

    exito: bool
    ruta_video: Path | None
    segundos: float
    reporte_error: Path | None
    salida: str

    def __bool__(self) -> bool:
        # Compat con codigo existente que hace `if ejecutar_manim(...):`.
        return self.exito


def construir_comando(
    ruta_script: str | Path,
    clase: str,
    calidad: str = "borrador",
    media_dir: Path = RAIZ / "media",
    extra: tuple[str, ...] = (),
) -> list[str]:
    """Arma el comando de `manim render` para la escena y calidad dadas.

    Nunca incluye `-p`/`--preview`.
    """
    if calidad not in CALIDADES:
        raise ValueError(
            f"Calidad desconocida: {calidad!r}. Usa una de {sorted(CALIDADES)}."
        )
    return [
        sys.executable,
        "-m",
        "manim",
        "render",
        CALIDADES[calidad],
        "--media_dir",
        str(media_dir),
        str(ruta_script),
        clase,
        *extra,
    ]


def entorno_render(calidad: str, auditar: bool = False) -> dict:
    """Copia `os.environ` y agrega las variables que necesita la escena para
    detectar la calidad y (opcionalmente) auditar el layout."""
    env = os.environ.copy()
    raiz_str = str(RAIZ)
    previo = env.get("PYTHONPATH")
    env["PYTHONPATH"] = raiz_str if not previo else raiz_str + os.pathsep + previo
    env["SHORT_CALIDAD"] = calidad
    env["PYTHONIOENCODING"] = "utf-8"
    if auditar:
        env["SHORT_AUDITAR"] = "1"
    return env


def localizar_video(
    media_dir: Path, ruta_script: str | Path, clase: str, calidad: str
) -> Path | None:
    """Ubica el mp4 generado por manim para `clase` bajo `media_dir`.

    Primero intenta la ruta canonica `media_dir/videos/<stem>/<alto>p<fps>/<clase>.mp4`
    segun el perfil de calidad; si no existe, busca con glob el `<clase>.mp4` mas
    reciente bajo `media_dir`.
    """
    media_dir = Path(media_dir)
    stem = Path(ruta_script).stem
    perfil = PERFILES[calidad]
    carpeta_calidad = f"{perfil.alto_px}p{perfil.fps}"
    candidato = media_dir / "videos" / stem / carpeta_calidad / f"{clase}.mp4"
    if candidato.exists():
        return candidato

    coincidencias = list(media_dir.glob(f"**/{clase}.mp4"))
    if not coincidencias:
        return None
    return max(coincidencias, key=lambda p: p.stat().st_mtime)


def _escribir_reporte_error(
    ruta_script: str | Path,
    nombre_clase: str,
    calidad: str,
    comando: list[str],
    salida: str,
) -> Path:
    """Escribe `reporte_error.json` junto al script con el formato historico
    (status, archivo, clase, excepcion_principal, traceback_completo,
    instruccion_para_llm) mas los campos nuevos calidad, comando y salida_final
    (ultimas 60 lineas de la salida combinada)."""
    match = re.search(r"(Traceback \(most recent call last\):.*)", salida, re.DOTALL)
    traceback_limpio = match.group(1) if match else salida[-2000:]
    lineas_traceback = [linea for linea in traceback_limpio.split("\n") if linea.strip()]
    excepcion_final = lineas_traceback[-1] if lineas_traceback else "Error desconocido"

    lineas_salida = salida.splitlines()
    salida_final = "\n".join(lineas_salida[-60:])

    reporte = {
        "status": "failed",
        "archivo": str(ruta_script),
        "clase": nombre_clase,
        "excepcion_principal": excepcion_final,
        "traceback_completo": traceback_limpio,
        "instruccion_para_llm": (
            "Corrige el codigo en base a la excepcion_principal y el traceback. "
            "Asegurate de no usar variables no definidas o importaciones erroneas."
        ),
        "calidad": calidad,
        "comando": comando,
        "salida_final": salida_final,
    }

    ruta_reporte = Path(ruta_script).parent / "reporte_error.json"
    with open(ruta_reporte, "w", encoding="utf-8") as f:
        json.dump(reporte, f, indent=2, ensure_ascii=False)
    return ruta_reporte


def ejecutar_manim(
    ruta_script: str | Path,
    nombre_clase: str,
    calidad: str = "borrador",
    media_dir: Path | None = None,
    auditar: bool = False,
    timeout: int = 3600,
) -> ResultadoRender:
    """Renderiza `nombre_clase` de `ruta_script` con manim como subproceso.

    Si falla (returncode != 0 o timeout), escribe `reporte_error.json` junto al
    script. Nunca lanza excepcion: el fallo se refleja en `ResultadoRender.exito`.
    """
    media_dir_efectivo = Path(media_dir) if media_dir is not None else RAIZ / "media"
    comando = construir_comando(ruta_script, nombre_clase, calidad, media_dir_efectivo)
    env = entorno_render(calidad, auditar)

    inicio = time.time()
    try:
        resultado = subprocess.run(
            comando,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=timeout,
        )
        segundos = time.time() - inicio
        salida = (resultado.stdout or "") + (resultado.stderr or "")
        returncode = resultado.returncode
    except subprocess.TimeoutExpired as exc:
        segundos = time.time() - inicio
        salida = (exc.stdout or "") + (exc.stderr or "")
        returncode = 1

    if returncode != 0:
        reporte = _escribir_reporte_error(
            ruta_script, nombre_clase, calidad, comando, salida
        )
        return ResultadoRender(False, None, segundos, reporte, salida)

    ruta_video = localizar_video(media_dir_efectivo, ruta_script, nombre_clase, calidad)
    return ResultadoRender(True, ruta_video, segundos, None, salida)


def main() -> int:
    for flujo in (sys.stdout, sys.stderr):
        if hasattr(flujo, "reconfigure"):
            flujo.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Runner robusto de escenas Manim")
    parser.add_argument("--script", required=True, help="Ruta al archivo .py")
    parser.add_argument("--clase", required=True, help="Nombre de la clase Scene")
    parser.add_argument(
        "--calidad", default="borrador", choices=sorted(CALIDADES), help="Perfil de calidad"
    )
    parser.add_argument("--media-dir", default=None, help="Directorio de media (default: <raiz>/media)")
    parser.add_argument(
        "--auditar", action="store_true", help="Activa SHORT_AUDITAR=1 para la escena"
    )
    args = parser.parse_args()

    media_dir = Path(args.media_dir) if args.media_dir else None
    resultado = ejecutar_manim(
        args.script, args.clase, args.calidad, media_dir, args.auditar
    )

    if resultado.exito:
        print(f"Render OK: {resultado.ruta_video} ({resultado.segundos:.1f}s)")
        return 0

    print(f"Render FALLIDO. Reporte: {resultado.reporte_error}")
    print(resultado.salida[-2000:])
    return 1


if __name__ == "__main__":
    sys.exit(main())
