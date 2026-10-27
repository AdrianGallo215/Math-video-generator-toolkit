"""Tests de la familia ``contadores`` del catálogo del guion (odometro, contar, barra, llenar, partir, tabla)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest
import yaml

from toolkit.guion import registro
from toolkit.guion.catalogo.contadores import mitades_de_barra, valor_contado
from toolkit.guion.validar import validar

# --- funciones puras ------------------------------------------------------------------------------------------


def test_valor_contado_continuo():
    assert valor_contado(0, 10, 0.0) == 0
    assert valor_contado(0, 10, 0.5) == pytest.approx(5)
    assert valor_contado(0, 10, 1.0) == 10
    assert valor_contado(1_000_000, 500_000, 0.5) == pytest.approx(750_000)


def test_valor_contado_por_pasos_escalon_exacto():
    # 0 -> 3 en 3 pasos: arranca en 0, salta a 1 apenas empieza, 2 en el segundo tercio, 3 en el último.
    assert valor_contado(0, 3, 0.0, pasos=3) == 0
    assert valor_contado(0, 3, 0.01, pasos=3) == 1
    assert valor_contado(0, 3, 0.34, pasos=3) == 2
    assert valor_contado(0, 3, 0.9, pasos=3) == 3
    assert valor_contado(0, 3, 1.0, pasos=3) == 3
    # solo toma valores del escalón
    valores = {valor_contado(10, 50, a / 100, pasos=4) for a in range(101)}
    assert valores == {10, 20, 30, 40, 50}


def test_valor_contado_alfa_fuera_de_rango_se_recorta():
    assert valor_contado(0, 8, -0.2, pasos=8) == 0
    assert valor_contado(0, 8, 1.3) == 8


def test_mitades_de_barra():
    # (ancho_inicial, veces, reescalar) -> anchos tras cada corte
    assert mitades_de_barra(4.0, 3, reescalar=False) == [2.0, 1.0, 0.5]
    assert mitades_de_barra(4.0, 3, reescalar=True) == [4.0, 4.0, 4.0]


def test_geometria_corte_fases():
    from toolkit.guion.catalogo.contadores import TIEMPOS_FASE, geometria_corte

    inicio = geometria_corte(4.0, 4.0, "izquierda", 0.0)
    assert inicio["relleno"] == (0.0, 4.0) and inicio["opacidad_descarte"] == 0 and inicio["corte"] == 0
    separado = geometria_corte(4.0, 4.0, "izquierda", TIEMPOS_FASE[0] + TIEMPOS_FASE[1])
    assert separado["relleno"][1] < 2.0 < separado["descarte"][0]  # hay hueco entre las mitades
    assert separado["opacidad_descarte"] == pytest.approx(1.0) and separado["corte"] == pytest.approx(1.0)
    fin = geometria_corte(4.0, 2.0, "izquierda", 1.0)
    assert fin["relleno"] == pytest.approx((0.0, 2.0))  # sin reescalar: se queda la mitad
    assert fin["opacidad_descarte"] == 0 and fin["opacidad_corte"] == 0
    assert fin["descarte"][0] > 2.0  # salió hacia la derecha
    espejo = geometria_corte(4.0, 4.0, "derecha", TIEMPOS_FASE[0] + TIEMPOS_FASE[1])
    assert espejo["descarte"][1] < 2.0 < espejo["relleno"][0]  # sale la izquierda
    assert geometria_corte(4.0, 4.0, "derecha", 1.0)["relleno"] == pytest.approx((0.0, 4.0))


# --- validación ------------------------------------------------------------------------------------------------

PIEZAS = ("odometro", "contar", "barra", "llenar", "partir", "tabla")
NARRACION = ("Un millón de datos. Pregunta uno, dos y tres: la barra se parte, "
             "y el tiempo se compara.")


def _guion(pasos: list[dict], narracion: str = NARRACION) -> dict:
    return {
        "version": 1,
        "meta": {"slug": "contadores", "titulo": "Contadores", "clase": "Contadores"},
        "segmentos": [{"narracion": narracion, "pasos": pasos}],
    }


def _validar(tmp_path, datos: dict):
    ruta = tmp_path / "guion_tecnico.yaml"
    ruta.write_text(yaml.safe_dump(datos, allow_unicode=True), encoding="utf-8")
    return validar(ruta)


def _paso(nombre: str, **cambios) -> dict:
    import toolkit.guion.catalogo  # noqa: F401

    paso = dict(registro.CATALOGO[nombre].ejemplo)
    paso["en"] = "inicio"
    paso.update(cambios)
    return paso


def _cadena() -> list[dict]:
    """Todas las piezas en un guion realista: odómetros encadenados, barra que se parte y tabla que se llena."""
    return [
        _paso("odometro"),
        {"en": "millón", "hacer": "contar", "objeto": "odo", "a": 1000000, "dur": 1.0},
        {"en": "datos", "hacer": "mostrar", "id": "preg", "tipo": "odometro", "rotulo": "Preguntas",
         "zona": "titulo", "tamano": 48},
        _paso("barra", en="datos", zona={"de": "odo", "lado": "abajo", "espacio": 0.5}),
        _paso("partir", en="uno", veces=1, dur=0.8),
        {"en": "uno", "hacer": "contar", "objeto": "odo", "a": 500000, "dur": 0.8},
        {"en": "uno", "hacer": "contar", "objeto": "preg", "a": 1, "pasos": 1, "dur": 0.8},
        _paso("partir", en="dos", veces=1, dur=1.0),
        {"en": "dos", "hacer": "contar", "objeto": "odo", "a": 250000, "dur": 0.4},
        {"en": "dos", "hacer": "contar", "objeto": "odo", "a": 125000, "dur": 0.4, "retraso": 0.5},
        {"en": "tres", "hacer": "partir", "objeto": "barra", "reescalar": False, "dur": 0.8},
        {"en": "tres", "hacer": "contar", "objeto": "preg", "desde": 1, "a": 3, "pasos": 2, "dur": 0.8},
        {"en": "tres", "hacer": "quitar", "objeto": ["odo", "preg"], "retraso": 0.8},
        _paso("tabla", en="tiempo", zona="principal"),
        {"en": "compara", "hacer": "llenar", "objeto": "tiempos", "escalonado": 0.3, "dur": 1.2},
        {"en": "fin", "hacer": "llenar", "objeto": "barra", "a": 1},
        {"en": "fin", "hacer": "quitar", "objeto": ["barra", "tiempos"], "retraso": 1.0},
    ]


def test_todas_las_piezas_de_la_familia_estan_registradas_con_descripciones():
    import toolkit.guion.catalogo  # noqa: F401

    for nombre in PIEZAS:
        d = registro.CATALOGO[nombre]
        assert d.descripcion
        assert all(p.descripcion for p in d.params), nombre


def test_cadena_realista_valida_sin_errores_ni_avisos_de_ciclo(tmp_path):
    reporte = _validar(tmp_path, _guion(_cadena()))
    assert reporte.ok, reporte.texto()
    assert not [a for a in reporte.avisos if a.codigo in ("A4", "A8")], reporte.texto()


@pytest.mark.parametrize(
    "paso, codigo",
    [
        ({"en": "inicio", "hacer": "mostrar", "id": "o", "tipo": "odometro", "tamano": 20}, "E8"),
        ({"en": "inicio", "hacer": "mostrar", "id": "o", "tipo": "odometro", "separador": "punto"}, "E3"),
        ({"en": "inicio", "hacer": "mostrar", "id": "b", "tipo": "barra", "maximo": 0}, "E3"),
        ({"en": "inicio", "hacer": "mostrar", "id": "t", "tipo": "tabla", "filas": [{"valor": 1}]}, "E3"),
        ({"en": "inicio", "hacer": "mostrar", "id": "t", "tipo": "tabla",
          "filas": [{"rotulo": "n", "valor": 1, "color": "fucsia"}]}, "E6"),
        ({"en": "inicio", "hacer": "mostrar", "id": "t", "tipo": "tabla",
          "filas": [{"rotulo": "n", "valor": 1, "colour": "rojo"}]}, "E1"),
    ],
)
def test_parametros_invalidos(tmp_path, paso, codigo):
    reporte = _validar(tmp_path, _guion([paso]))
    assert any(h.codigo == codigo for h in reporte.errores), reporte.texto()


def test_contar_valida_tamano_y_referencia(tmp_path):
    base = [_paso("odometro")]
    chico = base + [{"en": "inicio", "hacer": "contar", "objeto": "odo", "a": 5, "tamano": 12}]
    assert any(h.codigo == "E8" for h in _validar(tmp_path, _guion(chico)).errores)
    fantasma = base + [{"en": "inicio", "hacer": "contar", "objeto": "otro", "a": 5}]
    assert any(h.codigo == "E4" for h in _validar(tmp_path, _guion(fantasma)).errores)


# --- NumeroOdometro --------------------------------------------------------------------------------------------


def _colores_visibles(numero) -> set[str]:
    from manim import VectorizedPoint

    return {h.get_fill_color().to_hex().upper() for s in numero.submobjects if not isinstance(s, VectorizedPoint)
            for h in s.family_members_with_points()}


def test_numero_odometro_separadores():
    from manim import VectorizedPoint

    from toolkit.guion.catalogo.contadores import NumeroOdometro

    espacio = NumeroOdometro(1234567, separador="espacio")
    assert sum(isinstance(s, VectorizedPoint) for s in espacio.submobjects) == 2  # 1 234 567
    assert len(espacio.submobjects) == 9
    coma = NumeroOdometro(1234567, separador="coma")
    assert not any(isinstance(s, VectorizedPoint) for s in coma.submobjects) and len(coma.submobjects) == 9
    nada = NumeroOdometro(1234567, separador="ninguno")
    assert len(nada.submobjects) == 7


def test_numero_odometro_color_estable_y_anclaje():
    from manim import LEFT

    from toolkit.estilos import ROJO
    from toolkit.guion.catalogo.contadores import NumeroOdometro

    numero = NumeroOdometro(7, color="#FFFFFF", ancla=LEFT)
    izquierda = numero.get_left()[0]
    numero.set_color(ROJO)
    numero.set_value(1000000)  # crece: más glifos que al construirse
    assert _colores_visibles(numero) == {ROJO.upper()}
    assert numero.get_left()[0] == pytest.approx(izquierda, abs=1e-6)
    tamano = numero.font_size
    numero.set_value(3)
    assert numero.font_size == pytest.approx(tamano, rel=1e-3)
    numero.set_opacity(0.3)
    numero.set_value(42)
    assert all(h.get_fill_opacity() == pytest.approx(0.3) for h in numero.family_members_with_points())


def test_contar_en_cadena_lee_el_valor_al_empezar_sin_parpadeo():
    from toolkit.guion.catalogo.contadores import ContarDiferido, NumeroOdometro

    numero = NumeroOdometro(0)
    # Construidas ANTES de reproducir la primera (como en un grupo del runtime o una Succession).
    primera = ContarDiferido(numero, 1000)
    segunda = ContarDiferido(numero, 500)
    primera.begin()
    primera.interpolate(0.5)
    primera.finish()
    assert numero.get_value() == 1000
    segunda.begin()  # interpola en 0: debe seguir mostrando 1000, no volver a 0
    assert numero.get_value() == 1000
    segunda.interpolate(0.5)
    assert 500 < numero.get_value() < 1000
    segunda.finish()
    assert numero.get_value() == 500


def test_contar_por_pasos_y_desde_y_tamano():
    from manim.utils.rate_functions import linear

    from toolkit.guion.catalogo.contadores import ContarDiferido, NumeroOdometro

    numero = NumeroOdometro(99, tamano=48)
    anim = ContarDiferido(numero, 3, desde=0, pasos=3, tamano=72, rate_func=linear)
    vistos = []
    anim.begin()
    for k in range(11):
        anim.interpolate(k / 10)
        vistos.append(numero.get_value())
    anim.finish()
    assert vistos[0] == 0 and set(vistos) == {0, 1, 2, 3}
    assert numero.font_size == pytest.approx(72, rel=1e-3)


# --- objetos (sin escena) ----------------------------------------------------------------------------------------


@pytest.fixture()
def ctx():
    import toolkit.guion.catalogo  # noqa: F401
    from toolkit.guion.contexto import ContextoGuion

    return ContextoGuion(None)


def _crear(ctx, id: str, tipo: str, **params):
    mob = ctx.crear(tipo, **params)
    ctx.registrar(id, mob)
    return mob


def _segura():
    from toolkit.layout import ZONA_SEGURA

    return ZONA_SEGURA


def test_odometro_reserva_su_maximo_dentro_de_la_zona(ctx):
    odo = _crear(ctx, "odo", "odometro", valor=0, rotulo="Datos", maximo=1000000)
    numero = ctx.parte(odo, "numero")
    assert numero.get_value() == 0
    numero.set_value(1000000)
    assert _segura().contiene(odo, tolerancia=0.02)
    arriba = _crear(ctx, "o2", "odometro", valor=5, rotulo="Pasos", lado_rotulo="arriba", zona="titulo", tamano=48)
    assert ctx.parte(arriba, "rotulo").get_center()[1] > ctx.parte(arriba, "numero").get_center()[1]


def test_contar_devuelve_animacion_diferida_y_lineal_con_pasos(ctx):
    from manim.utils.rate_functions import linear

    from toolkit.guion.catalogo.contadores import ContarDiferido

    _crear(ctx, "odo", "odometro", valor=0)
    definicion = registro.CATALOGO["contar"]
    params = registro.resolver_params(definicion, {"objeto": "odo", "a": 8, "pasos": 8})
    params.pop("rate")
    anim = definicion.funcion(ctx, **params)
    assert isinstance(anim, ContarDiferido) and anim.rate_func is linear


def test_barra_llenar_en_cadena_y_segmentos(ctx):
    from toolkit.guion.catalogo.contadores import LlenarDiferido

    barra = _crear(ctx, "b", "barra", valor=0.25, segmentos=4)
    estado = barra.barra_guion
    assert estado.fraccion() == pytest.approx(0.25)
    assert len(ctx.parte(barra, "divisiones").submobjects) == 3
    assert _segura().contiene(barra)
    izquierda = estado.relleno.get_left()[0]
    a, b = LlenarDiferido(barra, 1.0), LlenarDiferido(barra, 0.5)
    a.begin()
    a.finish()
    b.begin()
    assert estado.fraccion() == pytest.approx(1.0)
    b.finish()
    assert estado.fraccion() == pytest.approx(0.5)
    assert estado.relleno.get_left()[0] == pytest.approx(izquierda, abs=1e-6)  # anclada a la izquierda


def test_tabla_misma_escala_desborde_y_vacia(ctx):
    filas = [
        {"rotulo": "n", "valor": 1, "texto": "1 s", "color": "verde", "nombre": "lineal"},
        {"tex": "n^2", "valor": 4, "texto": "4 s", "color": "rojo", "nombre": "cuadratica"},
    ]
    tabla = _crear(ctx, "t", "tabla", filas=filas)
    assert _segura().contiene(tabla, tolerancia=0.02)
    lineal = ctx.parte(tabla, "lineal.barra").barra_guion
    cuadratica = ctx.parte(tabla, "cuadratica.barra").barra_guion
    assert cuadratica.relleno.width == pytest.approx(4 * lineal.relleno.width, rel=1e-3)
    assert ctx.parte(tabla, "0") is ctx.parte(tabla, "lineal")
    # escala pequeña: la fila grande se sale de la zona (¡ajá!), su cifra queda dentro
    desborda = _crear(ctx, "t2", "tabla", filas=filas, escala=2)
    barra = ctx.parte(desborda, "cuadratica.barra")
    assert barra.get_right()[0] > _segura().x_max
    assert _segura().contiene(ctx.parte(desborda, "cuadratica.valor"), tolerancia=0.02)
    # vacía: barras en 0 y cifras fuera de la escena hasta 'llenar'
    vacia = _crear(ctx, "t3", "tabla", filas=filas, vacia=True)
    assert ctx.parte(vacia, "lineal.barra").barra_guion.fraccion() == 0
    assert ctx.parte(vacia, "lineal.valor") not in vacia.get_family()
    assert _segura().contiene(vacia, tolerancia=0.02)


# --- humo: el guion completo se ejecuta en una escena (dry_run) ----------------------------------------------------

TRES_LINEAS = (
    "from toolkit.guion.runtime import escena_desde_yaml\n\n\n"
    "class {clase}(escena_desde_yaml(\"guion_tecnico.yaml\")):\n    pass\n"
)


def _escena(tmp_path, datos: dict, nombre: str):
    from toolkit.narracion import MotorNarracion

    (tmp_path / "guion_tecnico.yaml").write_text(yaml.safe_dump(datos, allow_unicode=True), encoding="utf-8")
    ruta = tmp_path / "escena.py"
    ruta.write_text(TRES_LINEAS.format(clase=datos["meta"]["clase"]), encoding="utf-8")
    spec = importlib.util.spec_from_file_location(nombre, ruta)
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[nombre] = modulo
    spec.loader.exec_module(modulo)
    base = getattr(modulo, datos["meta"]["clase"])

    class Offline(base):
        def setup(self):
            super().setup()
            self._motor_narracion = MotorNarracion(dir_cache=tmp_path / "tts", permitir_red=False)

    return Offline


@pytest.mark.render
def test_humo_familia_contadores_en_escena_sin_parpadeo(tmp_path, monkeypatch):
    from manim import tempconfig

    from toolkit.guion.catalogo import contadores

    valores: list[float] = []
    original = contadores.NumeroOdometro.set_value

    def registrar(self, numero):
        if getattr(self, "font_size", 0) > 60:  # solo el odómetro grande ("odo")
            valores.append(float(numero))
        return original(self, numero)

    monkeypatch.setattr(contadores.NumeroOdometro, "set_value", registrar)
    clase = _escena(tmp_path, _guion(_cadena()), "escena_humo_contadores")
    config = {"quality": "low_quality", "dry_run": True, "media_dir": str(Path(tmp_path) / "media"),
              "disable_caching": True}
    with tempconfig(config):
        escena = clase()
        escena.render()
    ctx = escena.contexto_guion
    assert ctx.objetos == {}
    restos = [m for m in escena.get_mobject_family_members()
              if m.get_num_points() > 0 and m not in escena.capa_hud.get_family() and m is not escena.camera.frame]
    assert not restos
    # Tras llegar al millón, el odómetro solo baja (500 000 → 250 000 → 125 000): nunca vuelve a 0 ni sube.
    desde_millon = valores[valores.index(1000000):]
    assert desde_millon[-1] == 125000
    assert all(b <= a for a, b in zip(desde_millon, desde_millon[1:])), desde_millon
    assert min(desde_millon) == 125000


@pytest.mark.render
def test_humo_partir_con_contar_en_el_mismo_grupo_conserva_la_barra_entera(tmp_path):
    """Un AnimationGroup sobre partes (relleno, número) no debe dejar el relleno pintado encima de las divisiones."""
    from manim import tempconfig

    pasos = [
        _paso("odometro", valor=16),
        _paso("barra", en="datos", zona={"de": "odo", "lado": "abajo", "espacio": 0.5}),
        _paso("partir", en="uno", veces=1, dur=0.8),
        {"en": "uno", "hacer": "contar", "objeto": "odo", "a": 8, "dur": 0.8},
        {"en": "dos", "hacer": "partir", "objeto": "barra", "veces": 2, "reescalar": False, "dur": 1.2},
        {"en": "dos", "hacer": "contar", "objeto": "odo", "a": 2, "pasos": 2, "dur": 1.2},
    ]
    clase = _escena(tmp_path, _guion(pasos), "escena_humo_partir")
    config = {"quality": "low_quality", "dry_run": True, "media_dir": str(Path(tmp_path) / "media"),
              "disable_caching": True}
    with tempconfig(config):
        escena = clase()
        escena.render()
    ctx = escena.contexto_guion
    barra, odo = ctx.objetos["barra"], ctx.objetos["odo"]
    for registrado in (barra, odo):
        hoja = registrado.family_members_with_points()[0]
        contenedores = [m for m in escena.mobjects if hoja in m.get_family()]
        # Lo último que se pinta contiene el objeto ENTERO (sus partes en su orden: divisiones sobre el relleno).
        assert contenedores and registrado in contenedores[-1].get_family()
    estado = barra.barra_guion
    assert estado.fraccion() == pytest.approx(0.25, abs=1e-3)  # 2 cortes sin reescalar
    assert ctx.parte(odo, "numero").get_value() == 2
    divisiones = ctx.parte(barra, "divisiones")
    familia = barra.get_family()
    assert familia.index(divisiones) > familia.index(estado.relleno)
    assert len(barra.submobjects) == 5  # ancla, tope, marco, relleno, divisiones: el corte y el descarte se fueron
