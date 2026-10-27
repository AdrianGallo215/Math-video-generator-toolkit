"""Tests del runtime del guion: agrupación de pasos, semántica de dur/anclas, carga desde escena.py y humo."""

import importlib.util
import sys
from pathlib import Path

import pytest
import yaml
from manim import ScaleInPlace, Succession, tempconfig

from toolkit.guion.esquema import (
    DUR_MINIMA_RELATIVA,
    ErrorGuion,
    agrupar_pasos,
    cargar_texto,
    duracion_base,
    parsear_ancla,
    resolver_dur,
    tiempo_de_ancla,
)
from toolkit.narracion import MotorNarracion, PalabraTemporizada, SegmentoNarrado

RAIZ = Path(__file__).resolve().parents[2]
EJEMPLO = RAIZ / "ejemplos" / "guion_minimo"
TRES_LINEAS = (
    "from toolkit.guion.runtime import escena_desde_yaml\n\n\n"
    "class {clase}(escena_desde_yaml(\"guion_tecnico.yaml\")):\n    pass\n"
)


def _segmento(palabras: list[str], paso: float = 0.5) -> SegmentoNarrado:
    tiempos = [PalabraTemporizada(p, i * paso, i * paso + 0.4) for i, p in enumerate(palabras)]
    return SegmentoNarrado(" ".join(palabras), Path("x.wav"), len(palabras) * paso + 0.9, tiempos, False)


# --- funciones puras -----------------------------------------------------------------------------------


def test_agrupar_pasos_consecutivos_con_la_misma_ancla():
    guion = cargar_texto("""
version: 1
meta: {slug: a, titulo: A, clase: A}
segmentos:
  - narracion: "uno dos tres dos"
    pasos:
      - {en: inicio, hacer: mostrar, id: a, tipo: texto, texto: a}
      - {en: inicio, hacer: mostrar, id: b, tipo: texto, texto: b}
      - {en: "Dos", hacer: resaltar, objeto: a}
      - {en: [dos, 1], hacer: resaltar, objeto: b}
      - {en: tres, hacer: pulsar, objeto: a}
      - {en: [dos, 2], hacer: pulsar, objeto: b}
      - {en: {ancla: dos, ocurrencia: 2, mas: 0.2}, hacer: quitar, objeto: a}
""")
    grupos = agrupar_pasos(guion.segmentos[0].pasos)
    assert [[p.indice for p in g] for g in grupos] == [[1, 2], [3, 4], [5], [6], [7]]


def test_tiempo_de_ancla_y_resolver_dur():
    seg = _segmento(["uno", "dos", "tres", "cuatro"])
    assert tiempo_de_ancla(parsear_ancla("inicio"), seg) == 0.0
    assert tiempo_de_ancla(parsear_ancla("tres"), seg) == pytest.approx(1.0)
    assert tiempo_de_ancla(parsear_ancla({"ancla": "tres", "mas": 0.3}), seg) == pytest.approx(1.3)
    assert tiempo_de_ancla(parsear_ancla("fin"), seg) == pytest.approx(1.9)  # fin de la última palabra
    assert resolver_dur(1.2, 0.0, seg) == (1.2, None)
    assert resolver_dur("resto", 0.4, seg) == (pytest.approx(1.5), None)
    assert resolver_dur(parsear_ancla("cuatro"), 0.5, seg) == (pytest.approx(1.0), None)
    dur, aviso = resolver_dur(parsear_ancla("dos"), 0.45, seg)
    assert dur == DUR_MINIMA_RELATIVA and "tarde" in aviso


def test_duracion_base_usa_la_del_tipo_en_mostrar():
    import toolkit.guion.catalogo  # noqa: F401

    guion = cargar_texto("""
version: 1
meta: {slug: a, titulo: A, clase: A}
segmentos:
  - narracion: "uno dos"
    pasos:
      - {en: inicio, hacer: mostrar, id: a, tipo: texto, texto: a}
      - {en: inicio, hacer: sonido, nombre: pop}
      - {en: dos, hacer: quitar, objeto: a, dur: resto}
""")
    mostrar, sonido, quitar = guion.segmentos[0].pasos
    assert duracion_base(mostrar) == 1.0
    assert duracion_base(sonido) == 0.0
    assert duracion_base(quitar) == "resto"


# --- escena_desde_yaml ----------------------------------------------------------------------------------


def _importar(ruta: Path, nombre: str):
    spec = importlib.util.spec_from_file_location(nombre, ruta)
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[nombre] = modulo
    spec.loader.exec_module(modulo)
    return modulo


GUION_CORTO = {
    "version": 1,
    "meta": {"slug": "corto", "titulo": "Corto", "clase": "Corto", "voz": "es-MX-JorgeNeural"},
    "subtitulos": {"cuadrado": "azul"},
    "segmentos": [
        {
            "narracion": "Fíjate en este cuadrado azul que aparece ahora. Luego se va.",
            "pasos": [
                {"en": "inicio", "hacer": "mostrar", "id": "c", "tipo": "forma", "figura": "rect"},
                {"en": "inicio", "hacer": "mostrar", "id": "t", "tipo": "texto", "texto": "Un cuadrado", "zona": "titulo"},
                {"en": "cuadrado", "hacer": "resaltar", "objeto": "c", "modo": "rodear"},
                {"en": "cuadrado", "hacer": "sonido", "nombre": "pop"},
                {"en": "Luego", "hacer": "transformar", "objeto": "t",
                 "a": {"tipo": "texto", "texto": "Se va", "zona": "titulo"}},
                {"en": "va", "hacer": "quitar", "objeto": ["c", "t"], "retraso": 0.2},
            ],
        }
    ],
}


def _preparar(tmp_path: Path, datos: dict, clase: str = "Corto") -> Path:
    (tmp_path / "guion_tecnico.yaml").write_text(yaml.safe_dump(datos, allow_unicode=True), encoding="utf-8")
    ruta = tmp_path / "escena.py"
    ruta.write_text(TRES_LINEAS.format(clase=clase), encoding="utf-8")
    return ruta


def test_escena_de_tres_lineas_carga_el_yaml_relativo(tmp_path):
    from toolkit.base_scene import PlantillaShort
    from toolkit.estilos import AZUL

    ruta = _preparar(tmp_path, GUION_CORTO)
    modulo = _importar(ruta, "escena_guion_prueba")
    clase = modulo.Corto
    assert issubclass(clase, PlantillaShort)
    assert clase.GUION.meta.slug == "corto"
    assert clase.VOZ == "es-MX-JorgeNeural"
    assert clase.RECORTAR_SILENCIO_FINAL is True and clase.SUBTITULOS is True
    assert clase.COLORES_SUBTITULOS == {"cuadrado": AZUL}
    # manim descubre la clase del escena.py (módulo) y no la generada.
    from manim.utils.module_ops import get_scene_classes_from_module

    assert [c.__name__ for c in get_scene_classes_from_module(modulo)] == ["Corto"]


def test_escena_desde_yaml_invalido_falla_con_lo_que_hay_que_corregir(tmp_path):
    datos = yaml.safe_load(yaml.safe_dump(GUION_CORTO))
    datos["segmentos"][0]["pasos"][2]["hacer"] = "resaltr"
    ruta = _preparar(tmp_path, datos)
    with pytest.raises(ErrorGuion, match="resaltar"):
        _importar(ruta, "escena_guion_invalida")


def test_producir_video_acepta_la_escena_de_tres_lineas(tmp_path):
    from scripts.producir_video import cargar_configuracion

    _preparar(tmp_path, GUION_CORTO)
    (tmp_path / "video.yaml").write_text("slug: corto\nescenas:\n  - {archivo: escena.py, clase: Corto}\n",
                                         encoding="utf-8")
    cfg = cargar_configuracion(tmp_path / "video.yaml")
    assert cfg.escenas[0].clase == "Corto"


# --- humo (construyen escenas) ---------------------------------------------------------------------------


def _config(tmp_path) -> dict:
    return {"quality": "low_quality", "dry_run": True, "media_dir": str(tmp_path / "media"), "disable_caching": True}


def _escena_con_registro(tmp_path, datos: dict, nombre: str):
    """Clase de escena del guion con TTS offline en tmp y un registro de cada play (tiempo, animación)."""
    modulo = _importar(_preparar(tmp_path, datos, datos["meta"]["clase"]), nombre)
    base = getattr(modulo, datos["meta"]["clase"])

    class ConRegistro(base):
        def setup(self):
            super().setup()
            self._motor_narracion = MotorNarracion(dir_cache=tmp_path / "tts", permitir_red=False)
            self.registro_plays = []

        def play(self, *animaciones, **kwargs):
            self.registro_plays.append((self.renderer.time, animaciones))
            super().play(*animaciones, **kwargs)

    return ConRegistro


@pytest.mark.render
def test_runtime_agrupa_espera_anclas_y_limpia(tmp_path):
    clase = _escena_con_registro(tmp_path, GUION_CORTO, "escena_guion_humo")
    with tempconfig(_config(tmp_path)):
        escena = clase()
        escena.render()
    ctx = escena.contexto_guion
    assert ctx.objetos == {}  # todo se quitó
    inicio, segmento = escena.segmentos_narrados[0]
    reales = [p for p in escena.registro_plays if not _es_espera(p[1])]
    # 1 play por grupo: inicio(2 pasos) · cuadrado(resaltar + sonido) · Luego · va  (+ relleno ambiental)
    grupos = [r for r in reales if not _es_relleno(r[1])]
    assert len(grupos) == 4
    t_cuadrado = inicio + segmento.tiempo_de("cuadrado")
    assert grupos[1][0] == pytest.approx(t_cuadrado, abs=1 / 15 + 1e-6)
    # sin restos visibles en escena del cuadrado/texto quitados (fuera del HUD de subtítulos)
    restos = [m for m in escena.get_mobject_family_members()
              if m.get_num_points() > 0 and not _es_hud(escena, m) and m is not escena.camera.frame]
    assert not restos


def _es_espera(animaciones) -> bool:
    from manim import Wait

    return len(animaciones) == 1 and isinstance(animaciones[0], Wait)


def _es_relleno(animaciones) -> bool:
    a = animaciones[0]
    return isinstance(a, ScaleInPlace) or (isinstance(a, Succession) and all(isinstance(x, ScaleInPlace) for x in a.animations))


def _es_hud(escena, mob) -> bool:
    return mob in escena.capa_hud.get_family()


@pytest.mark.render
def test_relleno_ambiental_llena_huecos_largos(tmp_path):
    datos = {
        "version": 1,
        "meta": {"slug": "relleno", "titulo": "Relleno", "clase": "Relleno"},
        "segmentos": [{
            "narracion": "Mira este cuadrado. Ahora espera un buen rato con calma, sin prisa y sin ruido. Adiós.",
            "pasos": [
                {"en": "inicio", "hacer": "mostrar", "id": "c", "tipo": "forma", "figura": "circulo"},
                {"en": "Adiós", "hacer": "quitar", "objeto": "c"},
            ],
        }],
    }
    clase = _escena_con_registro(tmp_path, datos, "escena_guion_relleno")
    with tempconfig(_config(tmp_path)):
        escena = clase()
        escena.render()
    rellenos = [p for p in escena.registro_plays if _es_relleno(p[1])]
    assert rellenos, "debió respirar el círculo en el hueco largo"
    esperas_largas = [p for p in escena.registro_plays if _es_espera(p[1]) and p[1][0].run_time > 1.0]
    assert not esperas_largas


@pytest.mark.render
def test_camara_persistente_entre_segmentos_y_detener(tmp_path):
    datos = {
        "version": 1,
        "meta": {"slug": "cam", "titulo": "Cam", "clase": "Cam"},
        "segmentos": [
            {"narracion": "Acércate al círculo.", "pasos": [
                {"en": "inicio", "hacer": "mostrar", "id": "c", "tipo": "forma", "figura": "circulo", "proporcion": 0.3},
                {"en": "círculo", "hacer": "camara", "id": "cam", "modo": "zoom", "objeto": "c", "factor": 1.5},
            ]},
            {"narracion": "Y vuelve.", "pasos": [
                {"en": "inicio", "hacer": "detener", "objeto": "cam"},
                {"en": "vuelve", "hacer": "quitar", "objeto": "c"},
            ]},
        ],
    }
    anchos = []
    clase = _escena_con_registro(tmp_path, datos, "escena_guion_camara")

    class Medir(clase):
        def _al_narrar(self, segmento, inicio):
            anchos.append(self.camera.frame.width)
            super()._al_narrar(segmento, inicio)

    with tempconfig(_config(tmp_path)):
        escena = Medir()
        ancho_inicial = escena.camera.frame.width
        escena.render()
    assert anchos[1] == pytest.approx(ancho_inicial / 1.5)
    assert escena.camera.frame.width == pytest.approx(ancho_inicial)
    assert escena.contexto_guion.efectos == {}


@pytest.mark.render
def test_escenario_grupo_personalizado_y_retraso(tmp_path):
    (tmp_path / "momentos.py").write_text(
        "from manim import FadeIn\n"
        "from toolkit.guion.catalogo.texto_formas import crear_texto\n\n"
        "def destello(ctx, texto):\n"
        "    mob = ctx.crear('texto', texto=texto, zona={'de': 'a', 'lado': 'abajo', 'espacio': 0.4})\n"
        "    ctx.registrar('extra', mob)\n"
        "    ctx.estado['llamado'] = True\n"
        "    return FadeIn(mob)\n",
        encoding="utf-8",
    )
    datos = {
        "version": 1,
        "meta": {"slug": "esc", "titulo": "Esc", "clase": "Esc"},
        "escenario": {"objetos": [{"id": "a", "tipo": "texto", "texto": "Primero"},
                                  {"id": "b", "tipo": "texto", "texto": "Segundo"}],
                      "disposicion": [{"apilar": ["a", "b"], "espacio": 0.6}]},
        "segmentos": [{"narracion": "Primero uno, luego otro, y al final todo junto.", "pasos": [
            {"en": "inicio", "hacer": "mostrar", "id": "a"},
            {"en": "luego", "hacer": "mostrar", "id": "b", "entrada": "desde_abajo"},
            {"en": "final", "hacer": "mostrar", "id": "g", "tipo": "grupo", "de": ["a", "b"]},
            {"en": "final", "hacer": "personalizado", "archivo": "momentos.py", "funcion": "destello",
             "args": {"texto": "¡Listo!"}, "crea": ["extra"], "retraso": 0.3, "dur": 0.5},
            {"en": "junto", "hacer": "pulsar", "objeto": ["g", "extra"], "dur": "resto"},
        ]}],
    }
    clase = _escena_con_registro(tmp_path, datos, "escena_guion_escenario")
    with tempconfig(_config(tmp_path)):
        escena = clase()
        escena.render()
    ctx = escena.contexto_guion
    a, b = ctx.objetos["a"], ctx.objetos["b"]
    assert a.get_bottom()[1] - b.get_top()[1] == pytest.approx(0.6, abs=0.05)
    assert ctx.estado["llamado"] is True
    assert set(ctx.objetos) == {"a", "b", "g", "extra"} and not ctx.reservados
    assert ctx.objetos["g"] in escena.get_mobject_family_members()
    retrasado = [anims for _, anims in escena.registro_plays if any(isinstance(x, Succession) for x in _hojas(anims))]
    assert retrasado


def _hojas(animaciones):
    for a in animaciones:
        yield a
        yield from _hojas(getattr(a, "animations", []))


@pytest.mark.render
def test_humo_ejemplo_guion_minimo(tmp_path, monkeypatch):
    """El ejemplo del repo construye en borrador (voz de la caché si existe; si no, sintética offline)."""
    monkeypatch.setenv("SHORT_TTS_OFFLINE", "1")
    modulo = _importar(EJEMPLO / "escena.py", "escena_ejemplo_guion_minimo")
    clase = modulo.GuionMinimo
    with tempconfig(_config(tmp_path)):
        escena = clase()
        escena.render()
    assert escena.renderer.time > 10
    assert escena.contexto_guion.efectos == {}
