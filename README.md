# Fábrica de shorts educativos (ManimCE)

Toolkit en Python + ManimCE 0.21.0 para producir programáticamente shorts verticales (9:16, 60–90 s) que explican
matemática, física, ingeniería de software y algoritmos con estilo visual 3Blue1Brown, narrados en español
latinoamericano con voz neural, subtítulos karaoke y música ambiental.

## Videos producidos

| Video | Tema | Duración | Archivo |
|---|---|---|---|
| V01 | ¿Por qué 1 + 2 + … + n = n(n+1)/2? (dos escaleras) | 87.7 s | `salidas/v01_suma_gauss_alta.mp4` |
| V02 | Completar el cuadrado con un dibujo | 86.2 s | `salidas/v02_completar_cuadrado_alta.mp4` |
| V03 | Búsqueda binaria: un millón en 20 preguntas | 89.2 s | `salidas/v03_busqueda_binaria_alta.mp4` |
| V04 | Big-O: por qué O(n²) te arruina | 87.9 s | `salidas/v04_big_o_alta.mp4` |
| V05 | Tiro parabólico: por qué 45° llega más lejos | 88.0 s | `salidas/v05_tiro_parabolico_alta.mp4` |

Todos: 1080×1920 a 60 fps, H.264 + AAC, −14 LUFS, voz real (edge-tts `es-PE-AlexNeural`), aprobados por el ciclo
guion → implementación → QA del director visual → correcciones → producción.

## Instalación (Windows + Git Bash)

```bash
python -m venv --system-site-packages .venv      # hereda manim 0.21.0 instalado en el sistema
.venv/Scripts/python -m pip install -r requirements-dev.txt
.venv/Scripts/python scripts/generar_audio_base.py # música y SFX procedurales (ya versionados)
```
Requiere MiKTeX (LaTeX) en PATH. ffmpeg lo aporta `imageio-ffmpeg`. La voz necesita red la primera vez (luego se cachea
en `assets/cache_tts/`; sin red se usa silencio con tiempos estimados y el pipeline avisa "NARRACIÓN SIN VOZ REAL").

## Crear un video nuevo

Con Claude Code: `/nuevo-video <tema>`. Orquesta guionista → **aprobación humana del guion conceptual** →
guion técnico YAML validado → borrador + QA automática → director visual (máx. 3 rondas de correcciones) →
producción alta. Roles, puertas y artefactos: `docs/flujo_nuevo_video.md`. Sin Python: la escena se compila de
`guion_tecnico.yaml`.

A mano, con el CLI `short`:

```bash
.venv/Scripts/python scripts/short.py nuevo --slug v06_tema --titulo "…" --clase MiVideo   # conceptual, YAML, escena, video.yaml
.venv/Scripts/python scripts/short.py catalogo                  # piezas disponibles (tipos y verbos)
# 1. escribir guion_conceptual.md (skill .claude/skills/guion-conceptual) y aprobarlo
# 2. escribir guion_tecnico.yaml (skill .claude/skills/guion-tecnico; ejemplos en ejemplos/guion_*/)
.venv/Scripts/python scripts/short.py validar videos_generados/v06_tema --voz
.venv/Scripts/python scripts/short.py render videos_generados/v06_tema --auditar
.venv/Scripts/python scripts/short.py qa videos_generados/v06_tema    # hojas en videos_generados/v06_tema/qa/
.venv/Scripts/python scripts/short.py producir videos_generados/v06_tema --calidad alta
```

## Estructura

- `toolkit/` — librería:
  - base: `configuracion` (perfiles borrador/media/alta 9:16), `estilos` (paleta 3B1B, color semántico), `tipografia`
    (CMU Serif, TeX en español), `layout` (zonas seguras), `base_scene` (PlantillaShort con HUD fijo a cámara),
    `auditor_layout`.
  - audio: `narracion` (edge-tts con caché, `narrar()` anclado por palabra), `subtitulos` (karaoke alineado al guion),
    `audio_base` (música y SFX procedurales), `medios` (ffmpeg, mezcla, loudness).
  - visual: `animaciones` (enfocar, resaltar, llaves, flechas, transiciones), `algebra_visual` + `motor_algebra`
    (derivaciones tokenizadas con sympy), `geometria_visual` + `motor_geometria`, `graficos`, `algoritmos_visual`,
    `utils_grafos`, `utils_3d`, `utils_escalas`, `motor_fisica`.
- `scripts/` — `short.py` (CLI del guion ejecutable), `manim_runner.py`, `producir_video.py`, `capturar_fotogramas.py`, `scaffold_video.py`, `generar_audio_base.py`.
- `videos_generados/<slug>/` — `guion_conceptual.md`, `guion_tecnico.yaml`, `escena.py` (3 líneas), `video.yaml`
  (V01–V05 son legado: `guion.md` + `escena.py` escrita a mano).
- `.claude/` — skills (`guion-conceptual`, `guion-tecnico`, `ejecutar-guion`, `qa-visual`), agentes y `/nuevo-video`.
- `docs/` — `guia_estilo_3b1b.md` (norma visual y narrativa), `agentes/toolkit_reference.md` (API verificada por test),
  `planes/plan_calidad_3b1b.md` (plan maestro de esta iteración).
- `ejemplos/` — demos por módulo y escenas legado.

## Tests

```bash
.venv/Scripts/python -m pytest -q            # 528 unitarios
.venv/Scripts/python -m pytest -q -m render  # 46 de humo que construyen escenas
.venv/Scripts/python -m pytest -q -m red     # 1 que usa edge-tts real
```

## Próximos pasos

- Probar `/nuevo-video` con un video piloto y ampliar el catálogo con los defectos `[CATÁLOGO]` que detecte el director.
- `narrar()` debería escribir un manifiesto JSON por escena (hoy el pipeline detecta la voz sintética leyendo el log).
- Activar `RECORTAR_SILENCIO_FINAL` por defecto (hoy es opcional por compatibilidad con V02).
- Auditor en 3D (hoy solo audita lo fijo al cuadro) y detección automática de tramos quietos > 1.2 s en el pipeline.
- Revisar de oído la música procedural y la pronunciación de edge-tts en términos técnicos.
- Formatos 16:9 y exportación de subtítulos .srt para YouTube.
