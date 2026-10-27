"""Narración sincronizada: síntesis con edge-tts (caché + fallback offline) y ``narrar()`` en escenas.

Uso en una escena (``PlantillaShort`` / ``PlantillaShort3D`` ya incluyen ``MixinNarracion``)::

    with self.narrar("Fíjate en esta escalera de bloques.") as n:
        n.esperar_hasta("escalera")
        self.play(Create(escalera), run_time=1.2)

Las anclas (``tiempo_de``, ``esperar_hasta``) comparan palabras normalizadas (sin tildes, ni
mayúsculas, ni puntuación). edge-tts puede entregar un número como "100" o como "cien": el guion
debe anclar en PALABRAS, no en cifras.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import hashlib
import json
import logging
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from .medios import RAIZ, convertir_a_wav, duracion_audio, normalizar_texto, silencio_wav

logger = logging.getLogger(__name__)

VOZ_POR_DEFECTO = "es-PE-AlexNeural"
VELOCIDAD_POR_DEFECTO = "+5%"
TONO_POR_DEFECTO = "+0Hz"
VOCES_DISPONIBLES = ("es-PE-AlexNeural", "es-PE-CamilaNeural", "es-MX-JorgeNeural", "es-MX-DaliaNeural")
DIR_CACHE_TTS = RAIZ / "assets" / "cache_tts"
VARIABLE_ENTORNO_OFFLINE = "SHORT_TTS_OFFLINE"
VARIABLE_ENTORNO_CACHE = "SHORT_TTS_CACHE"   # sustituye DIR_CACHE_TTS (tests aislados)

UNIDADES_POR_SEGUNDO_EDGE = 10_000_000  # offset/duration de edge-tts vienen en unidades de 100 ns
PALABRAS_POR_SEGUNDO_SINTETICO = 2.7
ESPERAS_REINTENTO = (1.0, 2.0)  # 3 intentos: espera 1 s y luego 2 s entre ellos
DECIMALES_DURACION = 6  # run_times derivados del reloj: estables frente a ruido de coma flotante (caché)


@dataclass(frozen=True)
class PalabraTemporizada:
    """Palabra con tiempos en segundos relativos al inicio de su segmento."""

    texto: str
    inicio: float
    fin: float


@dataclass
class SegmentoNarrado:
    """Resultado de sintetizar un texto: wav, duración y tiempos por palabra."""

    texto: str
    ruta_wav: Path
    duracion: float
    palabras: list[PalabraTemporizada]
    sintetico: bool

    def _buscar(self, fragmento: str, ocurrencia: int) -> tuple[int, int]:
        """Índices (primera, última) de palabra de la ``ocurrencia``-ésima aparición de ``fragmento``."""
        objetivo = normalizar_texto(fragmento).split()
        # Cada palabra puede normalizarse a 0, 1 o más fichas ("x-y" ⇒ "x y").
        fichas: list[str] = []
        indice_palabra: list[int] = []
        for i, palabra in enumerate(self.palabras):
            for ficha in normalizar_texto(palabra.texto).split():
                fichas.append(ficha)
                indice_palabra.append(i)
        if objetivo and ocurrencia >= 1:
            n = len(objetivo)
            vistas = 0
            for inicio in range(len(fichas) - n + 1):
                if fichas[inicio : inicio + n] == objetivo:
                    vistas += 1
                    if vistas == ocurrencia:
                        return indice_palabra[inicio], indice_palabra[inicio + n - 1]
        disponibles = " ".join(p.texto for p in self.palabras)
        raise KeyError(
            f"No se encontró la ocurrencia {ocurrencia} de {fragmento!r} en la narración. "
            f"Palabras disponibles: {disponibles!r}"
        )

    def tiempo_de(self, fragmento: str, ocurrencia: int = 1) -> float:
        """Inicio (s, relativo al segmento) de la primera palabra de ``fragmento``; ``KeyError`` si no está."""
        primera, _ = self._buscar(fragmento, ocurrencia)
        return self.palabras[primera].inicio

    def fin_de(self, fragmento: str, ocurrencia: int = 1) -> float:
        """Fin (s, relativo al segmento) de la última palabra de ``fragmento``; ``KeyError`` si no está."""
        _, ultima = self._buscar(fragmento, ocurrencia)
        return self.palabras[ultima].fin


def repartir_palabras(texto: str, duracion_habla: float, inicio: float = 0.0) -> list[PalabraTemporizada]:
    """Reparte las palabras de ``texto`` en ``[inicio, inicio + duracion_habla]`` en proporción a len+1."""
    crudas = [p for p in texto.split() if normalizar_texto(p)]
    if not crudas:
        return []
    pesos = [len(p) + 1 for p in crudas]
    total = float(sum(pesos))
    palabras = []
    t = inicio
    for cruda, peso in zip(crudas, pesos):
        hueco = duracion_habla * peso / total
        palabras.append(PalabraTemporizada(cruda, round(t, 4), round(t + 0.85 * hueco, 4)))
        t += hueco
    return palabras


def _ejecutar_corrutina(fabrica: Any) -> Any:
    """``asyncio.run`` de ``fabrica()``; si ya hay un loop corriendo, lo hace en un hilo aparte."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(fabrica())
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ejecutor:
        return ejecutor.submit(lambda: asyncio.run(fabrica())).result()


class MotorNarracion:
    """Sintetiza narración con edge-tts, con caché en disco y fallback sintético (silencio) offline."""

    def __init__(
        self,
        voz: str = VOZ_POR_DEFECTO,
        velocidad: str = VELOCIDAD_POR_DEFECTO,
        tono: str = TONO_POR_DEFECTO,
        dir_cache: Path = DIR_CACHE_TTS,
        permitir_red: bool | None = None,
    ) -> None:
        self.voz = voz
        self.velocidad = velocidad
        self.tono = tono
        if dir_cache == DIR_CACHE_TTS and os.environ.get(VARIABLE_ENTORNO_CACHE):
            dir_cache = Path(os.environ[VARIABLE_ENTORNO_CACHE])
        self.dir_cache = Path(dir_cache)
        if permitir_red is None:
            permitir_red = os.environ.get(VARIABLE_ENTORNO_OFFLINE) != "1"
        self.permitir_red = permitir_red

    def clave(self, texto: str) -> str:
        """Identificador de caché: sha1 de voz, velocidad, tono y texto (16 hex)."""
        base = f"{self.voz}|{self.velocidad}|{self.tono}|{texto}"
        return hashlib.sha1(base.encode("utf-8")).hexdigest()[:16]

    def sintetizar(self, texto: str) -> SegmentoNarrado:
        """Caché ⇒ edge-tts (si hay red, 3 intentos) ⇒ fallback sintético."""
        clave = self.clave(texto)
        ruta_wav = self.dir_cache / f"{clave}.wav"
        ruta_json = self.dir_cache / f"{clave}.json"
        if ruta_wav.exists() and ruta_json.exists():
            try:
                return self._cargar(ruta_wav, ruta_json)
            except (ValueError, KeyError, TypeError) as error:
                logger.warning("Caché TTS corrupta para %s (%s); se regenera", clave, error)
        if self.permitir_red:
            ultimo_error: Exception | None = None
            for intento in range(len(ESPERAS_REINTENTO) + 1):
                try:
                    return self._sintetizar_con_red(texto, ruta_wav, ruta_json)
                except Exception as error:  # red, servicio o ffmpeg: se reintenta y luego fallback
                    ultimo_error = error
                    logger.debug("edge-tts intento %d falló: %s", intento + 1, error)
                    if intento < len(ESPERAS_REINTENTO):
                        time.sleep(ESPERAS_REINTENTO[intento])
            logger.warning("edge-tts no disponible (%s); se usa narración sintética", ultimo_error)
        else:
            logger.warning("Red deshabilitada para TTS; narración sintética para %r", texto)
        return self._sintetico(texto, clave)

    # --- internos -------------------------------------------------------------------

    @staticmethod
    def _cargar(ruta_wav: Path, ruta_json: Path) -> SegmentoNarrado:
        datos = json.loads(ruta_json.read_text(encoding="utf-8"))
        palabras = [PalabraTemporizada(p["texto"], float(p["inicio"]), float(p["fin"])) for p in datos["palabras"]]
        return SegmentoNarrado(
            texto=datos["texto"],
            ruta_wav=ruta_wav,
            duracion=float(datos["duracion"]),
            palabras=palabras,
            sintetico=bool(datos.get("sintetico", False)),
        )

    def _sintetizar_con_red(self, texto: str, ruta_wav: Path, ruta_json: Path) -> SegmentoNarrado:
        import edge_tts

        self.dir_cache.mkdir(parents=True, exist_ok=True)
        ruta_mp3 = ruta_wav.with_suffix(".tmp.mp3")
        crudas: list[tuple[str, float, float]] = []

        async def _descargar() -> int:
            comunicador = edge_tts.Communicate(
                texto, self.voz, rate=self.velocidad, pitch=self.tono, boundary="WordBoundary"
            )
            n_bytes = 0
            with open(ruta_mp3, "wb") as archivo:
                async for trozo in comunicador.stream():
                    if trozo["type"] == "audio":
                        archivo.write(trozo["data"])
                        n_bytes += len(trozo["data"])
                    elif trozo["type"] == "WordBoundary":
                        inicio = trozo["offset"] / UNIDADES_POR_SEGUNDO_EDGE
                        fin = (trozo["offset"] + trozo["duration"]) / UNIDADES_POR_SEGUNDO_EDGE
                        crudas.append((trozo["text"], inicio, fin))
            return n_bytes

        try:
            if _ejecutar_corrutina(_descargar) == 0:
                raise RuntimeError("edge-tts no devolvió audio")
            ruta_wav_tmp = ruta_wav.with_suffix(".tmp.wav")
            convertir_a_wav(ruta_mp3, ruta_wav_tmp)
            duracion = duracion_audio(ruta_wav_tmp)
        finally:
            ruta_mp3.unlink(missing_ok=True)

        if crudas:
            palabras = [
                PalabraTemporizada(t, round(i, 4), round(min(f, duracion), 4)) for t, i, f in crudas
            ]
        else:
            logger.warning("edge-tts no entregó WordBoundary; tiempos de palabra repartidos")
            palabras = repartir_palabras(texto, duracion)
        datos = {
            "texto": texto,
            "voz": self.voz,
            "velocidad": self.velocidad,
            "tono": self.tono,
            "duracion": duracion,
            "sintetico": False,
            "palabras": [{"texto": p.texto, "inicio": p.inicio, "fin": p.fin} for p in palabras],
        }
        # El json se escribe al final: su presencia marca la entrada de caché como completa.
        os.replace(ruta_wav_tmp, ruta_wav)
        ruta_json.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")
        return SegmentoNarrado(texto, ruta_wav, duracion, palabras, sintetico=False)

    def _sintetico(self, texto: str, clave: str) -> SegmentoNarrado:
        n_palabras = len([p for p in texto.split() if normalizar_texto(p)])
        duracion = max(1.0, n_palabras / PALABRAS_POR_SEGUNDO_SINTETICO + 0.3)
        # Fuera de la caché real: un reintento con red debe poder sustituirlo.
        ruta_wav = silencio_wav(self.dir_cache / "sinteticos" / f"{clave}.wav", duracion)
        palabras = repartir_palabras(texto, duracion - 0.3)
        return SegmentoNarrado(texto, ruta_wav, duracion, palabras, sintetico=True)


# --- Escena ---------------------------------------------------------------------------


def _saltando_de_verdad(renderer: Any) -> bool:
    """¿La escena está omitiendo esta parte del video (``-s``, ``-n``, sección saltada)?

    Distinto de ``renderer.skip_animations``, que también queda en True tras una animación
    tomada de la caché de manim aunque el video sí la incluya.
    """
    from manim import config

    if getattr(renderer, "_original_skipping_status", False):
        return True
    secciones = getattr(getattr(renderer, "file_writer", None), "sections", None)
    if secciones and secciones[-1].skip_animations:
        return True
    if config.save_last_frame:
        return True
    n_plays = getattr(renderer, "num_plays", 0)
    return config.from_animation_number > 0 and n_plays < config.from_animation_number


def agregar_sonido(escena: Any, ruta: str | Path, ganancia_db: float | None = None) -> None:
    """``escena.add_sound`` robusto frente a la caché de manim.

    Tras un ``play`` servido desde la caché, ``renderer.skip_animations`` queda en True hasta el
    siguiente ``play`` y ``Scene.add_sound`` descartaría el sonido en silencio: se desactiva el
    salto solo durante la llamada (salvo que la escena esté omitiendo esa parte de verdad).
    """
    renderer = escena.renderer
    if getattr(renderer, "skip_animations", False) and not _saltando_de_verdad(renderer):
        renderer.skip_animations = False
        try:
            escena.add_sound(str(ruta), gain=ganancia_db)
        finally:
            renderer.skip_animations = True
        return
    escena.add_sound(str(ruta), gain=ganancia_db)


def _fotogramas_de_video(ruta: str) -> int | None:
    """Número de fotogramas de un mp4 (cabecera del contenedor), o None si no se puede leer."""
    try:
        import av

        with av.open(ruta) as contenedor:
            n = contenedor.streams.video[0].frames
        return int(n) if n else None
    except Exception as error:  # archivo ausente o ilegible: sin corrección
        logger.debug("No se pudo leer %s: %s", ruta, error)
        return None


def _ajustar_reloj_tras_cache(renderer: Any, antes: float) -> None:
    """Si el último ``play`` salió de la caché, iguala ``renderer.time`` a los fotogramas reales."""
    if not getattr(renderer, "skip_animations", False) or _saltando_de_verdad(renderer):
        return
    archivos = getattr(getattr(renderer, "file_writer", None), "partial_movie_files", None)
    if not archivos or archivos[-1] is None:
        return
    n = _fotogramas_de_video(archivos[-1])
    if n is None:
        return
    renderer.time = antes + n / renderer.camera.frame_rate


class ControlNarracion:
    """Objeto que entrega ``narrar()``: tiempos relativos al segmento en curso."""

    def __init__(self, escena: Any, segmento: SegmentoNarrado, inicio: float) -> None:
        self.escena = escena
        self.segmento = segmento
        self.inicio = inicio

    @property
    def _ahora(self) -> float:
        return self.escena.renderer.time

    @property
    def _un_frame(self) -> float:
        from manim import config

        return 1.0 / config.frame_rate

    @property
    def transcurrido(self) -> float:
        """Segundos desde que empezó el audio del segmento."""
        return self._ahora - self.inicio

    @property
    def restante(self) -> float:
        """Segundos que le quedan al audio (negativo si ya terminó)."""
        return self.inicio + self.segmento.duracion - self._ahora

    def tiempo_hasta(self, fragmento: str, ocurrencia: int = 1) -> float:
        """Segundos hasta que se pronuncie ``fragmento`` (0 si ya pasó)."""
        return max(0.0, self.inicio + self.segmento.tiempo_de(fragmento, ocurrencia) - self._ahora)

    def esperar_hasta(self, fragmento: str, ocurrencia: int = 1) -> None:
        """``wait`` hasta que empiece ``fragmento`` (no hace nada si falta menos de un frame)."""
        espera = round(self.tiempo_hasta(fragmento, ocurrencia), DECIMALES_DURACION)
        if espera > self._un_frame:
            self.escena.wait(espera)

    def hasta_el_final(self, margen: float = 0.0) -> float:
        """``run_time`` para que una animación llene lo que queda del audio (mínimo un frame)."""
        return max(self._un_frame, round(self.restante - margen, DECIMALES_DURACION))

    def hasta_ultima_palabra(self, margen: float = 0.0) -> float:
        """Como ``hasta_el_final`` pero termina en la última palabra (ignora el silencio final de edge-tts).
        Úsalo con ``RECORTAR_SILENCIO_FINAL = True``."""
        fin = self.segmento.palabras[-1].fin if self.segmento.palabras else self.segmento.duracion
        return max(self._un_frame, round(self.inicio + fin - self._ahora - margen, DECIMALES_DURACION))


class MixinNarracion:
    """Añade ``narrar()`` a una escena de manim. ``VOZ``/``VELOCIDAD``/``TONO`` sobreescribibles por video."""

    VOZ: str = VOZ_POR_DEFECTO
    VELOCIDAD: str = VELOCIDAD_POR_DEFECTO
    TONO: str = TONO_POR_DEFECTO

    @property
    def motor_narracion(self) -> MotorNarracion:
        """Motor TTS de la escena (perezoso; se puede sustituir asignando ``_motor_narracion``)."""
        motor = getattr(self, "_motor_narracion", None)
        if motor is None:
            motor = MotorNarracion(voz=self.VOZ, velocidad=self.VELOCIDAD, tono=self.TONO)
            self._motor_narracion = motor
        return motor

    @property
    def segmentos_narrados(self) -> list[tuple[float, SegmentoNarrado]]:
        """``(inicio_en_escena, segmento)`` de cada ``narrar`` (estadísticas, subtítulos)."""
        segmentos = getattr(self, "_segmentos_narrados", None)
        if segmentos is None:
            segmentos = []
            self._segmentos_narrados = segmentos
        return segmentos

    def play(self, *args: Any, **kwargs: Any) -> None:
        """``Scene.play`` + corrección del reloj cuando la animación sale de la caché de manim.

        Renderizando, ``renderer.time`` avanza por fotogramas reales (``ceil(d·fps)`` en animaciones,
        ``int(d·fps)`` en esperas congeladas); desde la caché avanza ``d`` exacto. Sin corregir, el
        reloj de un re-render se desfasa del video (hasta un fotograma por animación) y la narración
        y los subtítulos quedan corridos.
        """
        renderer = self.renderer
        antes = getattr(renderer, "time", None)
        super().play(*args, **kwargs)  # type: ignore[misc]
        if antes is not None:
            _ajustar_reloj_tras_cache(renderer, antes)

    RECORTAR_SILENCIO_FINAL: bool = False   # True: la espera final termina en la ultima palabra, no en el fin del wav

    def _al_narrar(self, segmento: SegmentoNarrado, inicio: float) -> None:
        """Gancho llamado al empezar cada segmento (T09: subtítulos)."""

    @contextmanager
    def narrar(self, texto: str, pausa_final: float = 0.15) -> Iterator[ControlNarracion]:
        """Reproduce la voz de ``texto`` desde ahora; al salir del bloque espera a que termine.

        Si las animaciones del bloque duran más que el audio, la escena simplemente se alarga.
        """
        from manim import config

        segmento = self.motor_narracion.sintetizar(texto)
        inicio = self.renderer.time
        agregar_sonido(self, segmento.ruta_wav)
        self.segmentos_narrados.append((inicio, segmento))
        self._al_narrar(segmento, inicio)
        control = ControlNarracion(self, segmento, inicio)
        yield control
        fin_audio = segmento.duracion
        if getattr(self, "RECORTAR_SILENCIO_FINAL", False) and segmento.palabras:
            # edge-tts deja ~0.9 s de silencio tras la ultima palabra: la siguiente frase puede arrancar antes
            # (el audio se solapa solo con silencio).
            fin_audio = min(segmento.duracion, segmento.palabras[-1].fin)
        restante = round(inicio + fin_audio + pausa_final - self.renderer.time, DECIMALES_DURACION)
        if restante > 1.0 / config.frame_rate:
            self.wait(restante)
        elif restante < -1.0 / config.frame_rate:
            logger.debug(
                "Las animaciones de %r exceden su audio en %.2f s (la escena se alarga)",
                texto[:40],
                -restante,
            )
