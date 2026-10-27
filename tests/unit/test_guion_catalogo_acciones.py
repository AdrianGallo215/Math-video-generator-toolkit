"""Tests de la familia ``acciones`` del catálogo del guion: enfocar, restaurar, mover, titulo, llave, flecha y los
modificadores comunes (caja, tachar, ola, entrada crecer_izq, escala, rate)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
import yaml
from manim import tempconfig

import toolkit.guion.catalogo  # noqa: F401  (registra las piezas)
from toolkit.guion import registro
from toolkit.guion.catalogo.modificadores import es_marca_de, id_derivado
from toolkit.guion.validar import guion_de_ejemplo, validar
from toolkit.layout import ZONA_SEGURA
from toolkit.narracion import MotorNarracion

RAIZ = Path(__file__).resolve().parents[2]
EJEMPLO = RAIZ / "ejemplos" / "guion_catalogo_acciones"
PIEZAS = ("enfocar", "restaurar", "mover", "titulo", "llave", "flecha")
NARRACION = "Mira este texto y este otro, que luego cambian de lugar."
TOLERANCIA = 0.02


def _paso(en, hacer, **params):
    return {"en": en, "hacer": hacer, **params}


def _guion(pasos, narracion=NARRACION) -> dict:
    return {
        "version": 1,
        "meta": {"slug": "acciones", "titulo": "Acciones", "clase": "Acciones"},
        "segmentos": [{"narracion": narracion, "pasos": pasos}],
    }


def _validar(tmp_path: Path, datos: dict):
    ruta = tmp_path / "guion_tecnico.yaml"
    ruta.write_text(yaml.safe_dump(datos, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return validar(ruta)


def _codigos(hallazgos) -> list[str]:
    return [h.codigo for h in hallazgos]


def _texto(id: str, texto: str = "Texto", **extra) -> dict:
    return _paso("inicio", "mostrar", id=id, tipo="texto", texto=texto, **extra)


# --- registro y ejemplos ---------------------------------------------------------------------------------------


def test_piezas_registradas_con_parametros_descritos():
    for nombre in PIEZAS:
        definicion = registro.CATALOGO[nombre]
        assert definicion.descripcion
        for p in definicion.params:
            assert p.descripcion, f"{nombre}.{p.nombre} sin descripción"


@pytest.mark.parametrize("nombre", PIEZAS)
def test_ejemplo_de_cada_pieza_valida(tmp_path, nombre):
    reporte = _validar(tmp_path, guion_de_ejemplo(nombre))
    assert reporte.ok, reporte.texto()


def test_ejemplo_yaml_del_catalogo_valida_sin_errores():
    reporte = validar(EJEMPLO / "guion_tecnico.yaml")
    assert reporte.ok, reporte.texto()
    usados = {p.hacer for s in reporte.guion.segmentos for p in s.pasos}
    tipos = {p.params.get("tipo") for s in reporte.guion.segmentos for p in s.pasos}
    assert {"enfocar", "restaurar", "mover", "titulo"} <= usados
    assert {"llave", "flecha"} <= tipos


def test_manifiesto_incluye_los_modificadores_nuevos():
    manifiesto = registro.manifiesto()
    assert "crecer_izq" in manifiesto["modificadores"]["entrada"]["opciones"]
    assert "ola" in manifiesto["acciones"]["resaltar"]["params"][2]["opciones"]
    for verbo in ("resaltar", "mostrar"):
        assert {"caja", "tachar"} <= set(manifiesto["acciones"][verbo]["modificadores"])


# --- funciones puras ---------------------------------------------------------------------------------------------


def test_id_derivado_y_es_marca_de():
    assert id_derivado("eq", None, "caja") == "eq_caja"
    assert id_derivado("eq", "16", "tachado") == "eq_16_tachado"
    assert id_derivado("eq", "Lado Ñ", "caja") == "eq_lado___caja"
    assert es_marca_de("eq_caja", "eq") and es_marca_de("eq_16_tachado", "eq")
    assert not es_marca_de("eq2_caja", "eq") and not es_marca_de("eq", "eq") and not es_marca_de("otro_caja", "eq")


# --- ciclo de vida de ids -----------------------------------------------------------------------------------------


def test_titulo_consume_sale_y_crea_su_id(tmp_path):
    pasos = [_texto("a"), _paso("Mira", "titulo", id="sec", texto="Sección", sale=["a"]),
             _paso("otro", "resaltar", objeto="a")]
    reporte = _validar(tmp_path, _guion(pasos))
    assert any(h.codigo == "E4" and "'a'" in h.mensaje for h in reporte.errores), reporte.texto()
    ok = _validar(tmp_path, _guion([_texto("a"), _paso("Mira", "titulo", id="sec", texto="S", sale="a"),
                                    _paso("otro", "quitar", objeto="sec")]))
    assert ok.ok, ok.texto()


def test_titulo_no_admite_partes_ni_id_repetido(tmp_path):
    reporte = _validar(tmp_path, _guion([_texto("a"), _paso("Mira", "titulo", id="a", texto="S", sale="a.0")]))
    assert "E3" in _codigos(reporte.errores)
    assert "E4" in _codigos(reporte.errores)


def test_enfocar_y_restaurar_exigen_objetos_vivos(tmp_path):
    reporte = _validar(tmp_path, _guion([_texto("a"), _paso("Mira", "enfocar", objeto="zz"),
                                         _paso("otro", "restaurar", objeto="yy")]))
    assert _codigos(reporte.errores) == ["E4", "E4"]
    reporte = _validar(tmp_path, _guion([_texto("a"), _paso("Mira", "enfocar", objeto="a", resto="casi")]))
    assert _codigos(reporte.errores) == ["E3"], reporte.texto()
    reporte = _validar(tmp_path, _guion([_texto("a"), _texto("b"), _paso("Mira", "enfocar", objeto=["a"], resto=["b"]),
                                         _paso("otro", "restaurar")]))
    assert reporte.ok, reporte.texto()


def test_mover_valida_extremos(tmp_path):
    reporte = _validar(tmp_path, _guion([_texto("a"), _paso("Mira", "mover", objeto="a",
                                                            a={"de": "a", "lado": "abajo"})]))
    assert "E4" in _codigos(reporte.errores)
    reporte = _validar(tmp_path, _guion([_texto("a"), _paso("Mira", "mover", objeto=["a"], a="principal")]))
    assert "E3" in _codigos(reporte.errores)
    reporte = _validar(tmp_path, _guion([_texto("a"), _paso("Mira", "mover", objeto="a", a="principal", escala=-1)]))
    assert "E3" in _codigos(reporte.errores)
    reporte = _validar(tmp_path, _guion([_texto("a"), _paso("Mira", "mover", objeto="a", a="zona_falsa")]))
    assert "E5" in _codigos(reporte.errores)


def test_llave_y_flecha_validan_extremos_y_tamano(tmp_path):
    reporte = _validar(tmp_path, _guion([_paso("Mira", "mostrar", id="ll", tipo="llave", objeto="zz", etiqueta="x")]))
    assert "E4" in _codigos(reporte.errores)
    reporte = _validar(tmp_path, _guion([_texto("a"), _paso("Mira", "mostrar", id="ll", tipo="llave", objeto="a",
                                                            etiqueta="x", tamano=20)]))
    assert "E8" in _codigos(reporte.errores)
    reporte = _validar(tmp_path, _guion([_texto("a"), _paso("Mira", "mostrar", id="f", tipo="flecha", de="a", a="a")]))
    assert "E4" in _codigos(reporte.errores)
    reporte = _validar(tmp_path, _guion([_texto("a"), _texto("b"),
                                         _paso("Mira", "mostrar", id="f", tipo="flecha", de="a", a="b",
                                               color="fucsia")]))
    assert "E6" in _codigos(reporte.errores)


def test_caja_y_tachar_crean_ids_derivados(tmp_path):
    pasos = [_texto("a", caja=True), _paso("Mira", "resaltar", objeto="a", tachar=True),
             _paso("otro", "quitar", objeto=["a", "a_caja", "a_tachado"])]
    reporte = _validar(tmp_path, _guion(pasos))
    assert reporte.ok, reporte.texto()
    assert "A4" not in _codigos(reporte.avisos)  # las marcas no avisan de "creado y sin usar"


def test_marcas_con_parte_usan_id_con_parte_y_no_se_duplican(tmp_path):
    pasos = [_texto("a"), _paso("Mira", "resaltar", objeto="a", parte="0", caja=True),
             _paso("otro", "resaltar", objeto="a.0", caja=True)]
    reporte = _validar(tmp_path, _guion(pasos))
    assert _codigos(reporte.errores) == ["E4"] and "a_0_caja" in reporte.errores[0].mensaje
    reporte = _validar(tmp_path, _guion([_texto("a"), _paso("Mira", "resaltar", objeto="a", parte="0", caja=True),
                                         _paso("otro", "quitar", objeto="a_0_caja")]))
    assert reporte.ok, reporte.texto()


def test_caja_de_resaltar_pide_un_solo_objeto(tmp_path):
    reporte = _validar(tmp_path, _guion([_texto("a"), _texto("b"),
                                         _paso("Mira", "resaltar", objeto=["a", "b"], caja=True)]))
    assert _codigos(reporte.errores) == ["E3"]


def test_caja_repetida_sobre_el_mismo_objeto_es_error_de_id(tmp_path):
    reporte = _validar(tmp_path, _guion([_texto("a", caja=True), _paso("Mira", "resaltar", objeto="a", caja=True)]))
    assert _codigos(reporte.errores) == ["E4"]


def test_modos_y_entradas_nuevas_son_validos(tmp_path):
    pasos = [_texto("a", entrada="crecer_izq"), _paso("Mira", "resaltar", objeto="a", modo="ola", escalonado=0.3,
                                                        escala=1.3),
             _paso("otro", "mostrar", id="b", tipo="forma", figura="rect", entrada="crecer_izq", rate="rush_from")]
    assert _validar(tmp_path, _guion(pasos)).ok


# --- ejecución de humo (construyen escenas en dry_run) -----------------------------------------------------------


def _importar(ruta: Path, nombre: str):
    spec = importlib.util.spec_from_file_location(nombre, ruta)
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[nombre] = modulo
    spec.loader.exec_module(modulo)
    return modulo


def _ejecutar(tmp_path: Path, datos: dict, nombre: str):
    (tmp_path / "guion_tecnico.yaml").write_text(yaml.safe_dump(datos, allow_unicode=True), encoding="utf-8")
    (tmp_path / "escena.py").write_text(
        'from toolkit.guion.runtime import escena_desde_yaml\n\n\n'
        f'class {datos["meta"]["clase"]}(escena_desde_yaml("guion_tecnico.yaml")):\n    pass\n', encoding="utf-8")
    base = getattr(_importar(tmp_path / "escena.py", nombre), datos["meta"]["clase"])

    class Offline(base):
        def setup(self):
            super().setup()
            self._motor_narracion = MotorNarracion(dir_cache=tmp_path / "tts", permitir_red=False)

    config = {"quality": "low_quality", "dry_run": True, "media_dir": str(tmp_path / "media"), "disable_caching": True}
    with tempconfig(config):
        escena = Offline()
        escena.render()
    return escena


def _dentro_de_zona_segura(ctx) -> list[str]:
    fuera = []
    for id, mob in ctx.objetos.items():
        if (mob.get_left()[0] < ZONA_SEGURA.x_min - TOLERANCIA or mob.get_right()[0] > ZONA_SEGURA.x_max + TOLERANCIA
                or mob.get_bottom()[1] < ZONA_SEGURA.y_min - TOLERANCIA
                or mob.get_top()[1] > ZONA_SEGURA.y_max + TOLERANCIA):
            fuera.append(id)
    return fuera


@pytest.mark.render
@pytest.mark.parametrize("nombre", PIEZAS)
def test_humo_de_cada_pieza_dentro_de_la_zona_segura(tmp_path, nombre):
    previos = [_texto("a")] if nombre == "restaurar" else None  # (el ejemplo de restaurar no referencia ids)
    escena = _ejecutar(tmp_path, guion_de_ejemplo(nombre, previos), f"escena_acciones_{nombre}")
    ctx = escena.contexto_guion
    assert ctx.objetos, "el ejemplo debe dejar algo en escena"
    assert not _dentro_de_zona_segura(ctx), _dentro_de_zona_segura(ctx)


COREOGRAFIA = {
    "version": 1,
    "meta": {"slug": "coreo", "titulo": "Coreo", "clase": "Coreo"},
    "zonas": {"arriba": {"de": "principal", "filas": [0.5, 0.5], "fila": 0},
              "abajo": {"de": "principal", "filas": [0.5, 0.5], "fila": 1}},
    "segmentos": [
        {"narracion": "Mira este texto y este otro, que luego cambian de lugar.", "pasos": [
            _texto("a", "Tres más cuatro", zona="arriba", entrada="crecer_izq"),
            _paso("este", "mostrar", id="b", tipo="texto", texto="Siete", zona={"de": "a", "lado": "abajo", "espacio": 1.4}),
            _paso("otro", "mostrar", id="f", tipo="flecha", de="a", a="b", etiqueta="suma", curvatura=0.4),
            _paso("luego", "mostrar", id="ll", tipo="llave", objeto="a", etiqueta="$3+4$", lado="arriba",
                  color_etiqueta="amarillo"),
        ]},
        {"narracion": "Ahora fíjate solo en uno y después vuelve todo a su lugar.", "pasos": [
            _paso("Ahora", "enfocar", objeto="b"),
            _paso("después", "restaurar"),
            _paso("lugar", "resaltar", objeto="a", modo="ola", escalonado=0.2),
        ]},
        {"narracion": "Marcamos el resultado con una caja y tachamos el otro texto.", "pasos": [
            _paso("Marcamos", "resaltar", objeto="b", caja=True),
            _paso("tachamos", "resaltar", objeto="a", tachar=True, escala=1.1),
            _paso("texto", "mover", objeto="b", a="abajo", alineacion="abajo", escala=0.8, arco=0.5),
        ]},
    ],
}


@pytest.mark.render
def test_coreografia_completa_en_dry_run(tmp_path):
    escena = _ejecutar(tmp_path, COREOGRAFIA, "escena_acciones_coreo")
    ctx = escena.contexto_guion
    assert {"a", "b", "f", "ll", "b_caja", "a_tachado"} <= set(ctx.objetos)
    assert not _dentro_de_zona_segura(ctx), _dentro_de_zona_segura(ctx)
    a, b, caja, tachado = (ctx.objetos[i] for i in ("a", "b", "b_caja", "a_tachado"))
    # la caja viajó con b y lo rodea; el tachado cruza a
    assert caja.get_left()[0] < b.get_left()[0] and caja.get_right()[0] > b.get_right()[0]
    assert abs(caja.get_center()[1] - b.get_center()[1]) < 0.05
    assert tachado.get_width() == pytest.approx(a.width, rel=0.05)
    # b bajó a la zona "abajo" (mitad inferior de la principal)
    assert b.get_center()[1] < ctx.zonas["abajo"].y_max
    # nada quedó atenuado tras restaurar (enfocar/restaurar), ni con atributos residuales
    from toolkit.animaciones import ATRIBUTO_OPACIDAD

    assert not [m for m in ctx.objetos["a"].get_family() if hasattr(m, ATRIBUTO_OPACIDAD)]
    assert ctx.objetos["a"].get_fill_opacity() > 0.9 or ctx.objetos["a"].get_family()[1].get_fill_opacity() > 0.9


@pytest.mark.render
def test_enfocar_atenua_el_resto_y_deja_el_foco(tmp_path):
    from toolkit.animaciones import ATRIBUTO_OPACIDAD

    datos = {
        "version": 1,
        "meta": {"slug": "foco", "titulo": "Foco", "clase": "Foco"},
        "segmentos": [{"narracion": "Mira este texto y este otro, atento.", "pasos": [
            _texto("a", "Uno"),
            _paso("este", "mostrar", id="b", tipo="texto", texto="Dos", zona={"de": "a", "lado": "abajo"}),
            _paso("atento", "enfocar", objeto="b"),
        ]}],
    }
    escena = _ejecutar(tmp_path, datos, "escena_acciones_foco")
    ctx = escena.contexto_guion
    atenuado = [m for m in ctx.objetos["a"].get_family() if hasattr(m, ATRIBUTO_OPACIDAD)]
    assert atenuado, "'a' debió quedar atenuado"
    assert not [m for m in ctx.objetos["b"].get_family() if hasattr(m, ATRIBUTO_OPACIDAD)]
    hojas_a = [m for m in ctx.objetos["a"].get_family() if m.get_num_points() > 0]
    hojas_b = [m for m in ctx.objetos["b"].get_family() if m.get_num_points() > 0]
    assert max(m.get_fill_opacity() for m in hojas_a) < 0.5 < min(m.get_fill_opacity() for m in hojas_b)


@pytest.mark.render
def test_humo_del_ejemplo_yaml(tmp_path):
    from toolkit.guion.runtime import ejecutar_guion  # noqa: F401  (import de humo)

    clase = _importar(EJEMPLO / "escena.py", "escena_ejemplo_acciones").CatalogoAcciones

    class Offline(clase):
        def setup(self):
            super().setup()
            self._motor_narracion = MotorNarracion(dir_cache=tmp_path / "tts", permitir_red=False)

    config = {"quality": "low_quality", "dry_run": True, "media_dir": str(tmp_path / "media"), "disable_caching": True}
    with tempconfig(config):
        escena = Offline()
        escena.render()
    assert escena.contexto_guion.objetos == {}  # el ejemplo lo quita todo al final
