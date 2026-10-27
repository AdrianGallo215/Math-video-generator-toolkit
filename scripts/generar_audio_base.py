"""CLI: genera los assets de audio base (musica ambiental + SFX) en assets/audio/.

Uso: .venv/Scripts/python scripts/generar_audio_base.py
"""

import sys
import wave
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from toolkit.audio_base import (  # noqa: E402
    RAIZ_AUDIO,
    SFX_DISPONIBLES,
    generar_musica_ambiental,
    generar_sfx,
    ruta_sfx,
)


def _duracion_segundos(ruta: Path) -> float:
    with wave.open(str(ruta), "rb") as wf:
        return wf.getnframes() / wf.getframerate()


def main() -> int:
    RAIZ_AUDIO.mkdir(parents=True, exist_ok=True)

    generados = [
        generar_musica_ambiental(
            RAIZ_AUDIO / "musica_ambiental_01.wav", segundos=64, semilla=7, tonalidad="re_menor"
        ),
        generar_musica_ambiental(
            RAIZ_AUDIO / "musica_ambiental_02.wav", segundos=64, semilla=11, tonalidad="la_menor"
        ),
    ]
    for nombre in SFX_DISPONIBLES:
        generados.append(generar_sfx(nombre, ruta_sfx(nombre)))

    for ruta in generados:
        print(f"{ruta} ({_duracion_segundos(ruta):.2f} s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
