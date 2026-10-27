"""CLI para capturar fotogramas y generar hojas de contacto de un video, para QA visual.

Decodifica con PyAV (sin depender de un binario externo de ffmpeg en PATH).

Uso:
    .venv/Scripts/python scripts/capturar_fotogramas.py --video X.mp4 --salida qa/<nombre>
        [--cada 2.0] [--tiempos 0.5,3,10.2] [--columnas 4] [--ancho-miniatura 270] [--guias]
"""

from __future__ import annotations

import argparse
import logging
import math
from pathlib import Path

import av
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

CADA_POR_DEFECTO = 2.0
COLUMNAS_POR_DEFECTO = 4
ANCHO_MINIATURA_POR_DEFECTO = 270
MAX_MINIATURAS_POR_HOJA = 12
FUENTE_ETIQUETA_PX = 20

# Respaldo si `toolkit.layout` aun no define las zonas (ver docs/guia_estilo_3b1b.md, seccion
# "Zona segura"): (x_min, x_max, y_min, y_max) en coordenadas de escena de Manim.
_ZONA_SEGURA_RESPALDO = (-3.15, 3.15, -4.0, 5.6)
_ZONA_SUBTITULOS_RESPALDO = (-3.15, 3.15, -3.9, -2.4)


def _zonas_guia() -> tuple[tuple[float, float, float, float], tuple[float, float, float, float]]:
    """Devuelve (zona_segura, zona_subtitulos) como (x_min, x_max, y_min, y_max).

    Importa perezosamente `toolkit.layout` para evitar un acoplamiento fuerte mientras ese
    modulo esta en desarrollo; si no existe (o aun no define las constantes), usa los valores
    numericos de la guia de estilo como respaldo.
    """
    try:
        from toolkit.layout import ZONA_SEGURA, ZONA_SUBTITULOS

        return ZONA_SEGURA, ZONA_SUBTITULOS
    except ImportError:
        logger.debug("toolkit.layout no disponible aun; usando zonas de respaldo de la guia")
        return _ZONA_SEGURA_RESPALDO, _ZONA_SUBTITULOS_RESPALDO


def _coords_pixeles(
    zona: object, ancho: int, alto: int
) -> tuple[float, float, float, float]:
    """Convierte una zona en coordenadas de escena de Manim (frame 9x16 centrado en el
    origen) a un rectangulo en pixeles (x0, y0, x1, y1).

    Acepta tanto una tupla ``(x_min, x_max, y_min, y_max)`` (respaldo) como un objeto con
    esos mismos atributos (p. ej. ``toolkit.layout.Zona``).

    px = (x + 4.5) / 9 * ancho ; py = (8 - y) / 16 * alto
    """
    if hasattr(zona, "x_min"):
        x_min, x_max, y_min, y_max = zona.x_min, zona.x_max, zona.y_min, zona.y_max
    else:
        x_min, x_max, y_min, y_max = zona
    x0 = (x_min + 4.5) / 9 * ancho
    x1 = (x_max + 4.5) / 9 * ancho
    y0 = (8 - y_max) / 16 * alto
    y1 = (8 - y_min) / 16 * alto
    return x0, y0, x1, y1


def _generar_tiempos(
    duracion: float, cada: float | None, tiempos: list[float] | None
) -> list[float]:
    """Calcula la lista ordenada de instantes (segundos) a capturar."""
    if tiempos:
        return sorted(t for t in tiempos if 0 <= t <= duracion)
    paso = cada if cada is not None else CADA_POR_DEFECTO
    if paso <= 0:
        raise ValueError("cada debe ser positivo")
    n = int(duracion / paso) + 1
    return [i * paso for i in range(n) if i * paso <= duracion]


def _cargar_fuente(tamano_px: int) -> ImageFont.FreeTypeFont:
    """Carga una fuente TrueType legible; recurre a la fuente por defecto de PIL si falla."""
    for nombre in ("arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(nombre, tamano_px)
        except OSError:
            continue
    return ImageFont.load_default(size=tamano_px)


def _dibujar_etiqueta_tiempo(imagen: Image.Image, tiempo_s: float) -> None:
    """Dibuja la etiqueta de tiempo en la esquina superior izquierda, sobre un fondo
    negro semitransparente."""
    texto = f"{tiempo_s:05.2f}s"
    fuente = _cargar_fuente(FUENTE_ETIQUETA_PX)
    capa = Image.new("RGBA", imagen.size, (0, 0, 0, 0))
    dibujo = ImageDraw.Draw(capa)
    caja = dibujo.textbbox((0, 0), texto, font=fuente)
    ancho_texto = caja[2] - caja[0]
    alto_texto = caja[3] - caja[1]
    margen = 6
    dibujo.rectangle(
        [0, 0, ancho_texto + 2 * margen, alto_texto + 2 * margen],
        fill=(0, 0, 0, 160),
    )
    dibujo.text((margen, margen - caja[1]), texto, font=fuente, fill=(255, 255, 255, 255))
    imagen.alpha_composite(capa)


def _dibujar_guias(imagen: Image.Image) -> None:
    """Dibuja los contornos de ZONA_SEGURA (amarillo) y ZONA_SUBTITULOS (cian)."""
    zona_segura, zona_subtitulos = _zonas_guia()
    ancho, alto = imagen.size
    capa = Image.new("RGBA", imagen.size, (0, 0, 0, 0))
    dibujo = ImageDraw.Draw(capa)
    for zona, color in (
        (zona_segura, (255, 255, 0, 220)),
        (zona_subtitulos, (0, 255, 255, 220)),
    ):
        x0, y0, x1, y1 = _coords_pixeles(zona, ancho, alto)
        dibujo.rectangle([x0, y0, x1, y1], outline=color, width=3)
    imagen.alpha_composite(capa)


def _decodificar_fotograma(contenedor: "av.container.InputContainer", flujo, tiempo_s: float):
    """Busca (seek) y decodifica el primer fotograma con tiempo >= tiempo_s segundos."""
    offset = int(tiempo_s / flujo.time_base)
    contenedor.seek(offset, stream=flujo, backward=True, any_frame=False)
    ultimo = None
    for frame in contenedor.decode(flujo):
        ultimo = frame
        if frame.time is not None and frame.time >= tiempo_s - 1e-6:
            return frame
    return ultimo


def _duracion_segundos(contenedor: "av.container.InputContainer", flujo) -> float:
    if flujo.duration is not None:
        return float(flujo.duration * flujo.time_base)
    if contenedor.duration is not None:
        return float(contenedor.duration) / av.time_base
    raise ValueError("No se pudo determinar la duracion del video")


def _redimensionar_miniatura(imagen: Image.Image, ancho_miniatura: int) -> Image.Image:
    factor = ancho_miniatura / imagen.width
    alto_miniatura = max(1, round(imagen.height * factor))
    return imagen.resize((ancho_miniatura, alto_miniatura), Image.LANCZOS)


def _construir_hojas(
    miniaturas: list[Image.Image], columnas: int, salida: Path
) -> list[Path]:
    """Arma hojas de contacto de hasta MAX_MINIATURAS_POR_HOJA miniaturas cada una."""
    rutas: list[Path] = []
    ancho_mini, alto_mini = miniaturas[0].size
    for indice_hoja, inicio in enumerate(
        range(0, len(miniaturas), MAX_MINIATURAS_POR_HOJA), start=1
    ):
        lote = miniaturas[inicio : inicio + MAX_MINIATURAS_POR_HOJA]
        filas = math.ceil(len(lote) / columnas)
        hoja = Image.new(
            "RGBA", (ancho_mini * columnas, alto_mini * filas), (32, 32, 32, 255)
        )
        for i, miniatura in enumerate(lote):
            fila, columna = divmod(i, columnas)
            hoja.paste(miniatura, (columna * ancho_mini, fila * alto_mini))
        ruta_hoja = salida / f"hoja_{indice_hoja:02d}.png"
        hoja.convert("RGB").save(ruta_hoja)
        rutas.append(ruta_hoja)
    return rutas


def capturar(
    video: str | Path,
    salida: str | Path,
    cada: float | None = None,
    tiempos: list[float] | None = None,
    columnas: int = COLUMNAS_POR_DEFECTO,
    ancho_miniatura: int = ANCHO_MINIATURA_POR_DEFECTO,
    guias: bool = False,
) -> list[Path]:
    """Captura fotogramas de `video` en los instantes pedidos (por `cada` segundos o por
    `tiempos` explicitos), los guarda a resolucion completa y arma hojas de contacto.

    Devuelve la lista de PNG generados, con las hojas de contacto primero.
    """
    ruta_video = Path(video)
    ruta_salida = Path(salida)
    ruta_salida.mkdir(parents=True, exist_ok=True)

    rutas_fotogramas: list[Path] = []
    miniaturas: list[Image.Image] = []

    with av.open(str(ruta_video)) as contenedor:
        flujo = contenedor.streams.video[0]
        flujo.thread_type = "AUTO"
        duracion = _duracion_segundos(contenedor, flujo)
        instantes = _generar_tiempos(duracion, cada, tiempos)

        for instante in instantes:
            frame = _decodificar_fotograma(contenedor, flujo, instante)
            if frame is None:
                logger.warning("No se pudo decodificar fotograma en t=%.2fs", instante)
                continue
            imagen = frame.to_image().convert("RGBA")

            ruta_fotograma = ruta_salida / f"f_{instante:05.2f}.png"
            imagen.convert("RGB").save(ruta_fotograma)
            rutas_fotogramas.append(ruta_fotograma)

            miniatura = _redimensionar_miniatura(imagen, ancho_miniatura)
            if guias:
                _dibujar_guias(miniatura)
            _dibujar_etiqueta_tiempo(miniatura, instante)
            miniaturas.append(miniatura)

    rutas_hojas: list[Path] = []
    if miniaturas:
        rutas_hojas = _construir_hojas(miniaturas, columnas, ruta_salida)

    return rutas_hojas + rutas_fotogramas


def _parsear_tiempos(valor: str) -> list[float]:
    return [float(t) for t in valor.split(",") if t.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Captura fotogramas y hojas de contacto de un video para QA visual."
    )
    parser.add_argument("--video", required=True, help="Ruta al archivo de video (mp4).")
    parser.add_argument("--salida", required=True, help="Carpeta de salida (se crea si no existe).")
    parser.add_argument("--cada", type=float, default=None, help="Segundos entre fotogramas (por defecto 2.0).")
    parser.add_argument("--tiempos", type=str, default=None, help="Lista de instantes en segundos separados por coma.")
    parser.add_argument("--columnas", type=int, default=COLUMNAS_POR_DEFECTO, help="Columnas de la hoja de contacto.")
    parser.add_argument("--ancho-miniatura", type=int, default=ANCHO_MINIATURA_POR_DEFECTO, help="Ancho en px de cada miniatura.")
    parser.add_argument("--guias", action="store_true", help="Dibuja ZONA_SEGURA y ZONA_SUBTITULOS sobre las miniaturas.")
    args = parser.parse_args()

    tiempos = _parsear_tiempos(args.tiempos) if args.tiempos else None

    rutas = capturar(
        video=args.video,
        salida=args.salida,
        cada=args.cada,
        tiempos=tiempos,
        columnas=args.columnas,
        ancho_miniatura=args.ancho_miniatura,
        guias=args.guias,
    )
    for ruta in rutas:
        print(ruta)


if __name__ == "__main__":
    main()
