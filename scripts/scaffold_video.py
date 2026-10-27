"""Scaffold de un video nuevo: crea ``videos_generados/<slug>/{guion.md, escena.py, video.yaml}``.

Uso:
    .venv/Scripts/python scripts/scaffold_video.py --slug v0X_nombre --titulo "..." --clase NombreClase

No sobrescribe archivos existentes: si la carpeta ya tiene alguno de los tres, solo crea los que
faltan; si ya existen los tres, falla (``FileExistsError`` / salida 1). Así se puede correr sobre
una carpeta con ``guion.md`` escrito a mano (p. ej. por G-VNN) sin perder ese contenido.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

PLANTILLA_GUION = """# Guion — {titulo}

## Idea clave
TODO: una frase con la idea central del video (el momento "¡ajá!": qué se ve exactamente).

## Gancho (0-3 s)
TODO: pregunta o afirmación sorprendente; el fotograma 1 ya tiene movimiento.

## Paleta semántica
| Concepto | Token (toolkit.estilos) |
|---|---|
| TODO | AZUL |

## Tabla de segmentos
| # | Narración | Visual | Ancla | Duración est. |
|---|---|---|---|---|
| 1 | TODO texto EXACTO que ira a narrar() | TODO objetos/animacion/funcion del toolkit | TODO palabra ancla | TODO s |

Total de palabras: TODO (objetivo 160-200 para 62-80 s). Ver docs/guia_estilo_3b1b.md §2.

## Verificación matemática
TODO: comando python/sympy usado para comprobar cada cifra/formula, y su salida.

## Riesgos de layout
TODO: que objetos compiten por espacio y como se resuelve con toolkit/layout.py.

## Checklist QA
- [ ] Duracion >= 60 s
- [ ] Foco unico en cada momento (docs/guia_estilo_3b1b.md §8)
- [ ] Colores semanticos coherentes entre dibujo, ecuacion y subtitulo
- [ ] Momento "¡ajá!" con enfasis visual claro
- [ ] Cierre con remate + CTA; ultimo fotograma sirve de miniatura
- [ ] Tildes y ñ correctos en todo el texto visible
"""

PLANTILLA_ESCENA = '''"""{titulo}

Generado por scripts/scaffold_video.py. Sigue videos_generados/{slug}/guion.md: cada
`narrar()` debe usar el texto EXACTO de la columna Narracion, y `construct()` solo llama
a metodos de seccion (uno por bloque del guion). Antes de una API de manim de la que no
estes seguro, verificala con `inspect`; ver docs/agentes/toolkit_reference.md.
"""

from __future__ import annotations

from manim import FadeIn

from toolkit.base_scene import PlantillaShort
from toolkit.estilos import AZUL
from toolkit.layout import ZONA_TITULO, encajar
from toolkit.tipografia import Texto


class {clase}(PlantillaShort):
    """TODO: idea clave de una frase (ver guion.md)."""

    VOZ = "es-PE-AlexNeural"
    VELOCIDAD = "+5%"
    SUBTITULOS = True
    COLORES_SUBTITULOS = {{
        # "palabra_clave": AZUL,
    }}

    def construct(self) -> None:
        self.seccion_gancho()
        self.seccion_desarrollo()
        self.seccion_cierre()

    def seccion_gancho(self) -> None:
        """TODO: gancho (0-3 s), ver guion.md."""
        titulo = Texto("{titulo}", color=AZUL)
        encajar(titulo, zona=ZONA_TITULO)
        with self.narrar("TODO: texto EXACTO del guion para esta seccion.") as n:
            self.play(FadeIn(titulo, shift=[0, 0.3, 0]))
            n.esperar_hasta("TODO")

    def seccion_desarrollo(self) -> None:
        """TODO: planteamiento + exploracion + "¡ajá!" (ver guion.md)."""
        # TODO: usa DerivacionVisual / ArregloVisual / PlanoShort segun corresponda;
        # posiciona con toolkit.layout, nunca con coordenadas magicas.

    def seccion_cierre(self) -> None:
        """TODO: consecuencia + remate + CTA (ver guion.md)."""
        # TODO: caja_resultado + sfx("pop") en el momento "¡ajá!".
'''

PLANTILLA_YAML = """# video.yaml de {slug} (esquema T12: scripts/producir_video.py)
slug: {slug}
titulo: "{titulo}"
escenas:
  - {{archivo: escena.py, clase: {clase}}}
# musica: assets/audio/musica_ambiental_01.wav
volumen_musica_db: -24
ducking: true
loudness_lufs: -14
"""

_ARCHIVOS = ("guion.md", "escena.py", "video.yaml")


def _contenidos(slug: str, titulo: str, nombre_clase: str) -> dict[str, str]:
    return {
        "guion.md": PLANTILLA_GUION.format(titulo=titulo),
        "escena.py": PLANTILLA_ESCENA.format(titulo=titulo, clase=nombre_clase, slug=slug),
        "video.yaml": PLANTILLA_YAML.format(slug=slug, titulo=titulo, clase=nombre_clase),
    }


def crear_scaffold(directorio: Path, titulo: str, nombre_clase: str) -> list[Path]:
    """Crea, en ``directorio``, los archivos de ``_ARCHIVOS`` que aun no existan.

    ``directorio`` puede ya existir (p. ej. con un ``guion.md`` escrito a mano por G-VNN):
    en ese caso solo se crean los que faltan. Si los tres ya existen, lanza
    ``FileExistsError`` (el CLI lo traduce a salida 1) para no pisar nada por accidente.
    Devuelve las rutas creadas (puede ser una lista vacia... no: si no falta nada, lanza).
    """
    directorio = Path(directorio)
    slug = directorio.name
    contenidos = _contenidos(slug, titulo, nombre_clase)
    faltantes = {
        nombre: contenido
        for nombre, contenido in contenidos.items()
        if not (directorio / nombre).exists()
    }
    if not faltantes:
        raise FileExistsError(
            f"{directorio}: ya existen guion.md, escena.py y video.yaml; nada que crear"
        )
    directorio.mkdir(parents=True, exist_ok=True)
    creados: list[Path] = []
    for nombre in _ARCHIVOS:
        if nombre not in faltantes:
            continue
        ruta = directorio / nombre
        ruta.write_text(faltantes[nombre], encoding="utf-8")
        creados.append(ruta)
    return creados


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Crea el andamiaje de un video nuevo en videos_generados/<slug>/."
    )
    parser.add_argument("--slug", required=True, help="Nombre de la carpeta (ej. v01_suma_gauss)")
    parser.add_argument("--titulo", required=True, help="Titulo del video (para guion.md/video.yaml)")
    parser.add_argument("--clase", required=True, help="Nombre de la clase Python (ej. SumaGauss)")
    args = parser.parse_args()

    directorio = RAIZ / "videos_generados" / args.slug
    try:
        creados = crear_scaffold(directorio, args.titulo, args.clase)
    except FileExistsError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    for ruta in creados:
        print(f"creado: {ruta.relative_to(RAIZ)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
