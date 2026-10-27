"""CLI ``short``: flujo del guion técnico ejecutable (YAML -> validar -> render -> qa -> producir).

Uso:  .venv/Scripts/python scripts/short.py <comando> ...

Comandos:
  nuevo --slug S --titulo T [--clase C]   crea videos_generados/S/{guion_conceptual.md, guion_tecnico.yaml, escena.py, video.yaml}
                                          (nunca sobrescribe; solo crea lo que falta; falla si ya existen los cuatro)
  catalogo [nombre] [--json]              tipos y verbos con parámetros y ejemplos (desde toolkit.guion.registro.manifiesto())
  validar RUTA [--voz] [--json]           reglas E*/A*; salida != 0 si hay errores
  render RUTA [--calidad borrador] [--auditar]   valida y renderiza (SHORT_AUDITAR=1 con --auditar)
  qa RUTA [--json]                        render borrador auditado + hojas de contacto (--cada 2 --guias) + tramos quietos
  producir RUTA [--calidad alta]          scripts/producir_video.py sobre el video.yaml
  estado SLUG [--json]                    artefactos existentes y puertas superadas

RUTA puede ser el guion_tecnico.yaml, la carpeta del video o su video.yaml (se resuelve al guion de esa carpeta).
Códigos de salida: 0 = OK; 1 = error del guion/render/uso (o tramos quietos en qa); 2 = argumentos inválidos (argparse).

Esquemas ``--json`` (estables; solo se añaden claves):
  validar:  {"ok": bool, "errores": [{"codigo","mensaje","ubicacion","linea"}], "avisos": [...], "resumen": {...}}
  catalogo: el manifiesto {"version","objetos","acciones","modificadores","claves_paso"}; con nombre:
            {"nombre", "clase": "objeto"|"accion", ...definicion}
  qa:       {"ok": bool, "video": str, "duracion_s": float, "tramos_quietos": [{"inicio","fin","duracion"}],
             "hojas": [str], "salida": str}
  estado:   {"slug", "carpeta", "artefactos": {nombre: bool}, "puertas": {"validado","borrador","qa","produccion"},
             "ultimo_borrador": str|None, "ultima_produccion": str|None}
Ante cualquier error de comando con --json: {"ok": false, "error": "qué corregir"}.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

DIR_VIDEOS = RAIZ / "videos_generados"
NOMBRE_GUION = "guion_tecnico.yaml"
MINIMO_QUIETO_S = 1.2
UMBRAL_PIXEL = 12          # diferencia de brillo (0-255) para contar un píxel como cambiado
UMBRAL_FRACCION = 0.0008   # fracción de píxeles cambiados para contar un fotograma como "con movimiento"

PLANTILLA_CONCEPTUAL = """# Guion conceptual — {titulo}

> Aprobación humana requerida antes de escribir `guion_tecnico.yaml`.

## Tema
TODO: qué se explica, en una frase.

## Público
TODO: quién lo ve y qué sabe ya (nicho preuniversitario Perú/LatAm).

## Idea clave
TODO: la idea central en una frase.

## Momento "¡ajá!"
TODO: qué se ve exactamente cuando el espectador lo entiende.

## Estructura (gancho -> cierre, tiempos objetivo; total 60-90 s, 150-200 palabras)
| Bloque | Objetivo | Tiempo |
|---|---|---|
| Gancho | pregunta o afirmación sorprendente; movimiento en el fotograma 1 | 0-5 s |
| Desarrollo | TODO | 5-40 s |
| ¡ajá! | TODO | 40-55 s |
| Cierre | remate + llamada a la acción | 55-70 s |

## Qué se debe ver
TODO: objetos, colores semánticos y transiciones por bloque (piezas de `short catalogo`).

## Riesgos
TODO: objetos que compiten por espacio, momentos que necesitarán `personalizado`, cifras a verificar con sympy.
"""

PLANTILLA_TECNICA = """# Guion técnico ejecutable (version 1). Piezas disponibles: short.py catalogo. Validar: short.py validar <esta ruta>.
# Cada `en:` ancla el paso a una palabra de la narración (nunca segundos). TODO: reemplaza los segmentos de ejemplo.
version: 1
meta:
  slug: {slug}
  titulo: "{titulo}"
  clase: {clase}
segmentos:
  # Segmento 1 (gancho): la narración es EXACTAMENTE lo que dirá la voz.
  - narracion: "TODO gancho: una pregunta que despierte curiosidad."
    pasos:
      - {{en: inicio, hacer: mostrar, id: titulo, tipo: texto, texto: "TODO título", zona: titulo}}
  # Segmento 2 (desarrollo): `en` debe ser una palabra presente en la narración de ESTE segmento.
  # - narracion: "TODO desarrollo con una palabra ancla."
  #   pasos:
  #     - {{en: inicio, hacer: mostrar, id: idea, tipo: texto, texto: "TODO idea", tamano: 64}}
  #     - {{en: "ancla", hacer: resaltar, objeto: idea, modo: rodear}}
  # Segmento 3 (cierre): quita lo que ya no hace falta y remata.
  # - narracion: "TODO cierre y llamada a la acción."
  #   pasos:
  #     - {{en: "cierre", hacer: quitar, objeto: idea}}
"""

PLANTILLA_ESCENA = """from toolkit.guion.runtime import escena_desde_yaml


class {clase}(escena_desde_yaml("{guion}")):
    pass
"""

PLANTILLA_VIDEO = """slug: {slug}
titulo: "{titulo}"
escenas:
  - {{archivo: escena.py, clase: {clase}}}
musica: assets/audio/musica_ambiental_01.wav
volumen_musica_db: -24
ducking: true
loudness_lufs: -14
"""


class ErrorCLI(Exception):
    """Error de uso con mensaje que dice qué corregir."""


def _configurar_consola() -> None:
    for flujo in (sys.stdout, sys.stderr):
        if hasattr(flujo, "reconfigure"):
            flujo.reconfigure(encoding="utf-8", errors="replace")


def resolver_guion(ruta: str | Path) -> Path:
    """Acepta guion_tecnico.yaml, la carpeta del video o su video.yaml; devuelve la ruta del guion."""
    p = Path(ruta)
    if p.is_dir():
        p = p / NOMBRE_GUION
    elif p.name == "video.yaml":
        p = p.parent / NOMBRE_GUION
    return p


def _salida_json(datos: dict) -> None:
    print(json.dumps(datos, ensure_ascii=False, indent=2))


def _fallo(mensaje: str, como_json: bool = False) -> int:
    if como_json:
        _salida_json({"ok": False, "error": mensaje})
    else:
        print(f"ERROR: {mensaje}", file=sys.stderr)
    return 1


# --- nuevo -------------------------------------------------------------------------------------------


def _clase_desde_slug(slug: str) -> str:
    partes = [p for p in slug.split("_") if p]
    return "".join(p[:1].upper() + p[1:] for p in partes) or "MiVideo"


def crear_video(slug: str, titulo: str, clase: str | None = None, base: Path | None = None) -> tuple[Path, list[str], list[str]]:
    """Crea los archivos que falten. Devuelve (carpeta, creados, existentes). Nunca sobrescribe."""
    if not re.fullmatch(r"[a-z0-9][a-z0-9_]*", slug):
        raise ErrorCLI(f"slug inválido {slug!r}: usa minúsculas, dígitos y guion bajo, sin tildes (p. ej. v06_gauss).")
    clase = clase or _clase_desde_slug(slug)
    if not clase.isidentifier():
        raise ErrorCLI(f"clase inválida {clase!r}: debe ser un identificador Python (p. ej. VideoGauss).")
    if clase[0].isdigit():
        raise ErrorCLI(f"clase inválida {clase!r}: no puede empezar por dígito; pasa --clase VideoGauss.")
    carpeta = (base or DIR_VIDEOS) / slug
    carpeta.mkdir(parents=True, exist_ok=True)
    datos = {"slug": slug, "titulo": titulo.replace('"', "'"), "clase": clase, "guion": NOMBRE_GUION}
    plantillas = {
        "guion_conceptual.md": PLANTILLA_CONCEPTUAL,
        NOMBRE_GUION: PLANTILLA_TECNICA,
        "escena.py": PLANTILLA_ESCENA,
        "video.yaml": PLANTILLA_VIDEO,
    }
    creados: list[str] = []
    existentes: list[str] = []
    for nombre, plantilla in plantillas.items():
        destino = carpeta / nombre
        if destino.exists():
            existentes.append(nombre)
            continue
        destino.write_text(plantilla.format(**datos), encoding="utf-8")
        creados.append(nombre)
    if not creados:
        raise ErrorCLI(f"{carpeta} ya contiene los cuatro archivos; no se sobrescribió nada. Usa otro --slug o bórralos a mano.")
    return carpeta, creados, existentes


def cmd_nuevo(args: argparse.Namespace) -> int:
    carpeta, creados, existentes = crear_video(args.slug, args.titulo, args.clase)
    print(f"Video {args.slug}: {carpeta}")
    for n in creados:
        print(f"  creado     {n}")
    for n in existentes:
        print(f"  conservado {n} (ya existía; no se sobrescribió)")
    print(f"Siguiente paso: rellena guion_conceptual.md y {NOMBRE_GUION}; luego: short.py validar {carpeta / NOMBRE_GUION}")
    return 0


# --- catalogo ----------------------------------------------------------------------------------------


def _linea_param(p: dict) -> str:
    extra = []
    if p.get("requerido"):
        extra.append("requerido")
    if p.get("opciones"):
        extra.append("opciones: " + "|".join(p["opciones"]))
    if p.get("defecto") is not None:
        extra.append(f"defecto: {p['defecto']}")
    sufijo = f" ({'; '.join(extra)})" if extra else ""
    return f"      - {p['nombre']}: {p['tipo']}{sufijo} — {p.get('descripcion', '')}"


def _describir(nombre: str, d: dict, detalle: bool) -> list[str]:
    lineas = [f"  {nombre} — {d['descripcion']}"]
    if detalle:
        lineas += [_linea_param(p) for p in d["params"]]
        lineas.append(f"      ejemplo: {json.dumps(d['ejemplo'], ensure_ascii=False)}")
    else:
        nombres = ", ".join(p["nombre"] + ("*" if p.get("requerido") else "") for p in d["params"])
        lineas.append(f"      params: {nombres or '(ninguno)'}")
    return lineas


def cmd_catalogo(args: argparse.Namespace) -> int:
    import toolkit.guion.catalogo  # noqa: F401  (registra las piezas)
    from toolkit.guion.registro import manifiesto

    m = manifiesto()
    if args.nombre:
        for clave, clase in (("objetos", "objeto"), ("acciones", "accion")):
            if args.nombre in m[clave]:
                d = m[clave][args.nombre]
                if args.json:
                    _salida_json({"nombre": args.nombre, "clase": clase, **d})
                else:
                    print(f"[{clase}]")
                    print("\n".join(_describir(args.nombre, d, True)))
                return 0
        disponibles = sorted(list(m["objetos"]) + list(m["acciones"]))
        return _fallo(f"no existe {args.nombre!r} en el catálogo. Disponibles: {', '.join(disponibles)}", args.json)
    if args.json:
        _salida_json(m)
        return 0
    print(f"Catálogo (manifiesto v{m.get('version')}); * = parámetro requerido. Detalle: short.py catalogo <nombre>")
    print(f"\nTIPOS de objeto ({len(m['objetos'])}) — `hacer: mostrar, tipo: <nombre>`:")
    for n, d in m["objetos"].items():
        print("\n".join(_describir(n, d, False)))
    print(f"\nVERBOS ({len(m['acciones'])}) — `hacer: <nombre>`:")
    for n, d in m["acciones"].items():
        print("\n".join(_describir(n, d, False)))
    if m.get("modificadores"):
        print("\nMODIFICADORES comunes: " + ", ".join(m["modificadores"]))
    return 0


# --- validar -----------------------------------------------------------------------------------------


def cmd_validar(args: argparse.Namespace) -> int:
    from toolkit.guion.validar import validar

    guion = resolver_guion(args.ruta)
    reporte = validar(guion, con_voz=args.voz)
    if args.json:
        _salida_json(reporte.como_dict())
    else:
        print(reporte.texto())
        if not reporte.ok:
            print("\nCorrige los errores indicados (cada uno dice qué cambiar) y vuelve a ejecutar `short.py validar`.", file=sys.stderr)
    return 0 if reporte.ok else 1


# --- render ------------------------------------------------------------------------------------------


def _renderizar(guion: Path, calidad: str, auditar: bool):
    from scripts.manim_runner import ejecutar_manim
    from toolkit.guion.esquema import cargar
    from toolkit.guion.validar import validar

    reporte = validar(guion)
    if not reporte.ok:
        raise ErrorCLI("el guion tiene errores; no se renderiza.\n" + reporte.texto())
    escena = guion.parent / "escena.py"
    if not escena.is_file():
        raise ErrorCLI(f"falta {escena}; créala con `short.py nuevo` o con 3 líneas que llamen a escena_desde_yaml.")
    clase = cargar(guion).meta.clase
    return ejecutar_manim(escena, clase, calidad, auditar=auditar), reporte


def cmd_render(args: argparse.Namespace) -> int:
    guion = resolver_guion(args.ruta)
    resultado, reporte = _renderizar(guion, args.calidad, args.auditar)
    for h in reporte.avisos:
        print(f"AVISO {h}")
    if resultado.exito:
        print(f"Render OK: {resultado.ruta_video} ({resultado.segundos:.1f}s)")
        if args.auditar:
            hallazgos = [ln for ln in resultado.salida.splitlines() if "audit" in ln.lower() or "hallazgo" in ln.lower()]
            print("\n".join(hallazgos[-20:]) if hallazgos else "Auditoría: sin hallazgos en la salida.")
        return 0
    return _fallo(f"render fallido. Reporte: {resultado.reporte_error}\n{resultado.salida[-1500:]}")


# --- qa ----------------------------------------------------------------------------------------------


def detectar_tramos_quietos(
    video: Path,
    minimo_s: float = MINIMO_QUIETO_S,
    umbral_pixel: int = UMBRAL_PIXEL,
    umbral_fraccion: float = UMBRAL_FRACCION,
) -> tuple[list[dict], float]:
    """Tramos > ``minimo_s`` sin cambio visual fuera de la franja de subtítulos (PyAV; gris a 1/4 de resolución).

    Devuelve (tramos [{"inicio","fin","duracion"}], duración del video en s).
    """
    import av
    import numpy as np

    from toolkit.layout import ZONA_SUBTITULOS

    tramos: list[dict] = []
    previo = None
    mascara = None
    inicio_quieto: float | None = None
    ultimo_t = 0.0

    def cerrar(fin: float) -> None:
        if inicio_quieto is not None and fin - inicio_quieto > minimo_s:
            tramos.append({"inicio": round(inicio_quieto, 2), "fin": round(fin, 2), "duracion": round(fin - inicio_quieto, 2)})

    with av.open(str(video)) as contenedor:
        flujo = contenedor.streams.video[0]
        for cuadro in contenedor.decode(flujo):
            t = float(cuadro.time) if cuadro.time is not None else ultimo_t
            gris = cuadro.to_ndarray(format="gray").astype(np.int16)[::4, ::4]
            if mascara is None:
                alto = gris.shape[0]
                fila0 = int((8 - ZONA_SUBTITULOS.y_max) / 16 * alto)
                fila1 = int(np.ceil((8 - ZONA_SUBTITULOS.y_min) / 16 * alto))
                mascara = np.ones(gris.shape, dtype=bool)
                mascara[fila0:fila1, :] = False
            if previo is not None:
                cambiado = (np.abs(gris - previo) > umbral_pixel) & mascara
                if cambiado.sum() / mascara.sum() > umbral_fraccion:
                    cerrar(t)
                    inicio_quieto = None
                elif inicio_quieto is None:
                    inicio_quieto = ultimo_t
            previo = gris
            ultimo_t = t
    cerrar(ultimo_t)
    return tramos, round(ultimo_t, 2)


def cmd_qa(args: argparse.Namespace) -> int:
    from scripts.capturar_fotogramas import capturar

    guion = resolver_guion(args.ruta)
    try:
        resultado, _ = _renderizar(guion, "borrador", auditar=True)
    except ErrorCLI as e:
        return _fallo(str(e), args.json)
    if not resultado.exito or resultado.ruta_video is None:
        return _fallo(f"render fallido. Reporte: {resultado.reporte_error}\n{resultado.salida[-1500:]}", args.json)
    video = Path(resultado.ruta_video)
    rutas = capturar(video, guion.parent / "qa", cada=2.0, guias=True)
    hojas = [str(r) for r in rutas if r.name.startswith("hoja_")]
    tramos, duracion = detectar_tramos_quietos(video)
    informe = {
        "ok": not tramos,
        "video": str(video),
        "duracion_s": duracion,
        "tramos_quietos": tramos,
        "hojas": hojas,
        "salida": resultado.salida[-1500:],
    }
    if args.json:
        _salida_json(informe)
        return 0 if informe["ok"] else 1
    print(f"Video borrador: {video} ({duracion:.1f} s)")
    if tramos:
        print(f"Tramos quietos > {MINIMO_QUIETO_S} s:")
        for t in tramos:
            print(f"  {t['inicio']:.1f}s -> {t['fin']:.1f}s ({t['duracion']:.1f}s): añade un paso visual (pulsar/resaltar/mover) en ese tramo")
    else:
        print(f"Tramos quietos > {MINIMO_QUIETO_S} s: ninguno")
    print("Hojas de contacto (míralas y compara con docs/guia_estilo_3b1b.md):")
    for h in hojas:
        print(f"  {h}")
    return 0 if informe["ok"] else 1


# --- producir ----------------------------------------------------------------------------------------


def cmd_producir(args: argparse.Namespace) -> int:
    from scripts.producir_video import ErrorConfiguracion, producir
    from toolkit.guion.validar import validar

    guion = resolver_guion(args.ruta)
    reporte = validar(guion)
    if not reporte.ok:
        return _fallo("el guion tiene errores; no se produce.\n" + reporte.texto())
    video_yaml = guion.parent / "video.yaml"
    if not video_yaml.is_file():
        return _fallo(f"falta {video_yaml}; créalo con `short.py nuevo` o copia el de ejemplos/guion_minimo.")
    try:
        destino = producir(video_yaml, args.calidad)
    except (ErrorConfiguracion, RuntimeError, ValueError) as e:
        return _fallo(str(e))
    print(f"Video listo: {destino}")
    return 0


# --- estado ------------------------------------------------------------------------------------------


def _video_borrador_en_media(carpeta: Path, media: Path) -> Path | None:
    """El mp4 borrador que dejan ``render``/``qa`` (``scripts/manim_runner``): ruta canónica de manim
    ``media/videos/<stem de escena.py>/<alto>p<fps>/<Clase>.mp4`` (sin el glob de respaldo del runner, que
    podría confundirse con otro video de la misma clase)."""
    from toolkit.configuracion import PERFILES
    from toolkit.guion.esquema import cargar

    guion, escena = carpeta / NOMBRE_GUION, carpeta / "escena.py"
    if not (guion.is_file() and escena.is_file()):
        return None
    try:
        clase = cargar(guion).meta.clase
    except Exception:  # guion ilegible: la puerta "validado" ya lo reporta
        return None
    perfil = PERFILES["borrador"]
    ruta = media / "videos" / escena.stem / f"{perfil.alto_px}p{perfil.fps}" / f"{clase}.mp4"
    return ruta if ruta.is_file() else None


def estado_de(slug: str, base: Path | None = None, salidas: Path | None = None, media: Path | None = None) -> dict:
    carpeta = (base or DIR_VIDEOS) / slug
    if not carpeta.is_dir():
        raise ErrorCLI(f"no existe {carpeta}; créalo con `short.py nuevo --slug {slug} --titulo ...`.")
    salidas = salidas or (RAIZ / "salidas")
    artefactos = {n: (carpeta / n).is_file() for n in ("guion_conceptual.md", NOMBRE_GUION, "escena.py", "video.yaml")}
    qa = carpeta / "qa"
    artefactos["qa/"] = qa.is_dir() and any(qa.iterdir())
    validado = False
    if artefactos[NOMBRE_GUION]:
        from toolkit.guion.validar import validar

        validado = validar(carpeta / NOMBRE_GUION).ok
    borrador = salidas / f"{slug}_borrador.mp4"
    if not borrador.is_file():  # `producir` escribe en salidas/; `render` y `qa` dejan el video en media/
        borrador = _video_borrador_en_media(carpeta, media or RAIZ / "media") or borrador
    alta = salidas / f"{slug}_alta.mp4"
    return {
        "slug": slug,
        "carpeta": str(carpeta),
        "artefactos": artefactos,
        "puertas": {
            "validado": validado,
            "borrador": borrador.is_file(),
            "qa": artefactos["qa/"],
            "produccion": alta.is_file(),
        },
        "ultimo_borrador": str(borrador) if borrador.is_file() else None,
        "ultima_produccion": str(alta) if alta.is_file() else None,
    }


def cmd_estado(args: argparse.Namespace) -> int:
    info = estado_de(args.slug)
    if args.json:
        _salida_json(info)
        return 0
    print(f"Video {info['slug']} ({info['carpeta']})")
    for n, ok in info["artefactos"].items():
        print(f"  [{'x' if ok else ' '}] {n}")
    nombres = {
        "validado": "short validar sin errores",
        "borrador": "render borrador (salidas/ o media/)",
        "qa": "short qa (hojas en qa/)",
        "produccion": "producción alta (salidas/)",
    }
    print("Puertas:")
    for k, ok in info["puertas"].items():
        print(f"  [{'x' if ok else ' '}] {nombres[k]}")
    if not info["puertas"]["validado"]:
        print("Siguiente: short.py validar y corregir errores.")
    elif not info["puertas"]["qa"]:
        print("Siguiente: short.py qa (revisa hojas y tramos quietos).")
    elif not info["puertas"]["produccion"]:
        print("Siguiente: short.py producir --calidad alta.")
    return 0


# --- main --------------------------------------------------------------------------------------------


def construir_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="short", description="Guion técnico ejecutable: nuevo, catalogo, validar, render, qa, producir, estado")
    sub = p.add_subparsers(dest="comando", required=True)

    s = sub.add_parser("nuevo", help="crea la carpeta de un video con plantillas")
    s.add_argument("--slug", required=True)
    s.add_argument("--titulo", required=True)
    s.add_argument("--clase", default=None, help="nombre de la clase de escena (defecto: derivado del slug)")
    s.set_defaults(fn=cmd_nuevo)

    s = sub.add_parser("catalogo", help="lista tipos y verbos")
    s.add_argument("nombre", nargs="?")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_catalogo)

    s = sub.add_parser("validar", help="valida el guion técnico")
    s.add_argument("ruta")
    s.add_argument("--voz", action="store_true", help="línea de tiempo real con la voz (A5/A6)")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_validar)

    s = sub.add_parser("render", help="valida y renderiza")
    s.add_argument("ruta")
    s.add_argument("--calidad", default="borrador", choices=["borrador", "media", "alta"])
    s.add_argument("--auditar", action="store_true", help="SHORT_AUDITAR=1")
    s.set_defaults(fn=cmd_render)

    s = sub.add_parser("qa", help="auditor + hojas de contacto + tramos quietos")
    s.add_argument("ruta")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_qa)

    s = sub.add_parser("producir", help="producción final (video.yaml)")
    s.add_argument("ruta")
    s.add_argument("--calidad", default="alta", choices=["borrador", "media", "alta"])
    s.set_defaults(fn=cmd_producir)

    s = sub.add_parser("estado", help="artefactos y puertas de un video")
    s.add_argument("slug")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_estado)
    return p


def main(argv: list[str] | None = None) -> int:
    _configurar_consola()
    args = construir_parser().parse_args(argv)
    try:
        return args.fn(args)
    except ErrorCLI as e:
        return _fallo(str(e), getattr(args, "json", False))


if __name__ == "__main__":
    sys.exit(main())
