"""Tests de toolkit/algebra_visual.py: color por token, Ecuacion tokenizada y DerivacionVisual."""

import pytest

from toolkit.algebra_visual import color_de_token, patron_seguro
from toolkit.estilos import AMARILLO, AZUL, BLANCO, COLOR_SEMANTICO, NARANJA, TURQUESA, VERDE

MAPA_V02 = {**COLOR_SEMANTICO, "3": NARANJA, "6": NARANJA, "9": NARANJA, "25": AMARILLO}


def _hex(mob) -> str:
    return mob.get_color().to_hex().upper()


# ---------------------------------------------------------------- puras


@pytest.mark.parametrize(
    "token, esperado",
    [
        ("x", AZUL),
        ("x^2", AZUL),
        ("x_1", AZUL),
        ("y^{10}", VERDE),
        (r"\theta", AMARILLO),
        (r"\theta^2", AMARILLO),
        ("5", None),
        ("+", None),
        (r"\sqrt{x}", None),
        ("ac", None),
        ("xy", None),
    ],
)
def test_color_de_token(token, esperado):
    assert color_de_token(token) == esperado


def test_color_de_token_numeros_exactos_con_mapa():
    assert color_de_token("3", MAPA_V02) == NARANJA
    assert color_de_token("25", MAPA_V02) == AMARILLO
    assert color_de_token("16", MAPA_V02) is None  # "6" no colorea "16"
    assert color_de_token("3^2", MAPA_V02) == NARANJA


@pytest.mark.parametrize(
    "clave, texto, coincidencias",
    [
        ("t", r"\sqrt{t}", ["t"]),  # la t de \sqrt NO, la variable si
        ("t", r"\text{t}", ["t"]),  # (la exclusion de \text se hace aparte)
        ("x", r"(x+3)^2", ["x"]),
        ("x", r"\frac{x^2}{2}", ["x^2"]),  # se aisla con su exponente, nunca "x" antes de "^"
        ("x", r"e^x", []),  # tras ^ no se puede envolver
        ("x", r"x^2y", []),
        ("n", r"\pm n", ["n"]),
        ("6", "16 + 6", ["6"]),
        ("3", "(x+3)^2", ["3"]),
        ("3", "x^3", []),
        ("3", "3.5", []),
    ],
)
def test_patron_seguro(clave, texto, coincidencias):
    assert [m.group(0) for m in patron_seguro(clave).finditer(texto)] == coincidencias


# ---------------------------------------------------------------- render (LaTeX real)


@pytest.mark.render
def test_ecuacion_colorea_x_en_azul_y_cada_token_es_submobject():
    from toolkit.algebra_visual import Ecuacion

    eq = Ecuacion("x^2", "+", "6", "x", "=", "16")
    assert [p.tex_string for p in eq.submobjects] == ["x^2", "+", "6", "x", "=", "16"]
    assert _hex(eq.parte("x")) == AZUL.upper()
    assert _hex(eq.parte("x^2")) == AZUL.upper()
    assert _hex(eq.parte("16")) == BLANCO.upper()


@pytest.mark.render
def test_ecuacion_mapa_con_numeros_y_color_interno_de_compuestos():
    from toolkit.algebra_visual import Ecuacion

    eq = Ecuacion("(x+3)^2", "=", "16", "+", "9", mapa=MAPA_V02)
    assert _hex(eq.parte("9")) == NARANJA.upper()
    assert _hex(eq.parte("16")) == BLANCO.upper()
    colores = [_hex(m) for m in eq.parte("(x+3)^2").submobjects]
    assert AZUL.upper() in colores and NARANJA.upper() in colores and BLANCO.upper() in colores


@pytest.mark.render
def test_ecuacion_coloreada_no_rompe_sqrt_ni_text():
    from toolkit.algebra_visual import EcuacionColoreada
    from toolkit.motor_algebra import resolver_ecuacion_cuadratica

    for paso in resolver_ecuacion_cuadratica(1, -5, 6) + resolver_ecuacion_cuadratica(1, 2, 5):
        eq = EcuacionColoreada(paso)
        assert len(eq.submobjects) >= 1
    vt = EcuacionColoreada(r"d = vt + \sqrt{t}")
    assert _hex(vt.parte("v")) == TURQUESA.upper()


@pytest.mark.render
def test_transformar_tokens_no_falla_con_desiguales():
    from toolkit.algebra_visual import Ecuacion, TransformarTokens
    from toolkit.motor_algebra import completar_cuadrado

    pasos = completar_cuadrado(1, 6, -16)
    ecs = [Ecuacion.desde_paso(p) for p in pasos]
    for a, b in zip(ecs, ecs[1:]):
        anim = TransformarTokens(a.copy(), b.copy())
        anim.begin()
        anim.interpolate(0.5)
        anim.finish()


def _escena_derivacion(modo, pasos, **kw):
    from manim import Scene

    from toolkit.algebra_visual import DerivacionVisual

    resultado = {}

    class _Escena(Scene):
        def construct(self):
            deriv = DerivacionVisual(self, pasos, modo=modo, **kw)
            deriv.mostrar_inicial()
            resultado["en_zona"] = [deriv.zona.contiene(deriv.actual)]
            while deriv.quedan_pasos:
                deriv.siguiente()
                resultado["en_zona"].append(all(deriv.zona.contiene(m) for m in deriv.visibles))
                if modo == "acumular":
                    xs = [m.parte("=").get_center()[0] for m in deriv.visibles if m.tiene("=")]
                    resultado.setdefault("xs_igual", []).append(xs)
                    resultado.setdefault("n_visibles", []).append(len(deriv.visibles))
            deriv.resultado_final()
            resultado["ultimo"] = deriv.actual

    return _Escena, resultado


@pytest.mark.render
@pytest.mark.parametrize("modo", ["acumular", "reemplazar"])
def test_derivacion_visual_recorre_completar_cuadrado_y_cabe_en_zona(modo):
    from manim import tempconfig

    from toolkit.motor_algebra import completar_cuadrado

    pasos = completar_cuadrado(1, 6, -16)
    Escena, resultado = _escena_derivacion(modo, pasos, max_visibles=4)
    with tempconfig({"quality": "low_quality", "dry_run": True}):
        Escena().render()
    assert all(resultado["en_zona"])
    assert resultado["ultimo"].tokens == pasos[-1].tokens
    if modo == "acumular":
        for xs in resultado["xs_igual"]:
            assert max(xs) - min(xs) < 0.02  # los "=" alineados en la misma x
        assert max(resultado["n_visibles"]) <= 4


@pytest.mark.render
def test_derivacion_acumular_respeta_max_visibles_y_animaciones_extra():
    from manim import Circle, FadeIn, Scene, tempconfig

    from toolkit.algebra_visual import DerivacionVisual
    from toolkit.layout import ZONA_PRINCIPAL, dividir_vertical
    from toolkit.motor_algebra import completar_cuadrado

    _, zona_alg = dividir_vertical(ZONA_PRINCIPAL, [0.55, 0.45])
    visto = {}

    class _Escena(Scene):
        def construct(self):
            deriv = DerivacionVisual(
                self, completar_cuadrado(1, 6, -16), zona=zona_alg, modo="acumular",
                max_visibles=3, mostrar_explicacion=False,
            )
            deriv.mostrar_inicial()
            circulo = Circle()
            maximo = 0
            while deriv.quedan_pasos:
                deriv.siguiente(animaciones_extra=[FadeIn(circulo)])
                maximo = max(maximo, len(deriv.visibles))
                assert all(zona_alg.contiene(m) for m in deriv.visibles)
            visto["maximo"] = maximo
            visto["circulo_en_escena"] = circulo in self.mobjects

    with tempconfig({"quality": "low_quality", "dry_run": True}):
        _Escena().render()
    assert visto["maximo"] == 3
    assert visto["circulo_en_escena"]


@pytest.mark.render
def test_mostrar_inicial_desde_transforma_una_copia_grande_en_la_fila():
    from manim import Scene, tempconfig

    from toolkit.algebra_visual import DerivacionVisual, Ecuacion
    from toolkit.layout import ZONA_PRINCIPAL, dividir_vertical
    from toolkit.motor_algebra import completar_cuadrado

    zona_geo, zona_alg = dividir_vertical(ZONA_PRINCIPAL, [0.6, 0.4])
    visto = {}

    class _Escena(Scene):
        def construct(self):
            pasos = completar_cuadrado(1, 6, -16)
            grande = Ecuacion.desde_paso(pasos[0]).scale(1.5).move_to(zona_geo.centro)
            self.add(grande)
            deriv = DerivacionVisual(self, pasos, zona=zona_alg, modo="acumular", mostrar_explicacion=False)
            deriv.mostrar_inicial(run_time=0.5, desde=grande)
            visto["grande_fuera"] = grande not in self.mobjects
            visto["actual_en_escena"] = deriv.actual in self.mobjects
            visto["en_zona"] = zona_alg.contiene(deriv.actual)
            visto["ancho"] = deriv.actual.width

    with tempconfig({"quality": "low_quality", "dry_run": True}):
        _Escena().render()
    assert visto["grande_fuera"]
    assert visto["actual_en_escena"]
    assert visto["en_zona"]


@pytest.mark.render
def test_acumular_siguiente_en_dos_fases_sin_tres_capas():
    """Fase 1 sube/atenúa las filas previas; fase 2 transforma la copia (con animaciones_extra)."""
    from manim import Circle, FadeIn, Scene, tempconfig

    from toolkit.algebra_visual import DerivacionVisual
    from toolkit.layout import ZONA_PRINCIPAL, dividir_vertical
    from toolkit.motor_algebra import completar_cuadrado

    _, zona_alg = dividir_vertical(ZONA_PRINCIPAL, [0.6, 0.4])
    visto = {"plays": [], "extra_en_fase": []}

    class _Escena(Scene):
        def play(self, *anims, **kw):
            circ = visto.get("circulo")
            visto["plays"].append(len(anims))
            if circ is not None:
                visto["extra_en_fase"].append(any(getattr(a, "mobject", None) is circ for a in anims))
            super().play(*anims, **kw)

        def construct(self):
            deriv = DerivacionVisual(
                self, completar_cuadrado(1, 6, -16), zona=zona_alg, modo="acumular",
                max_visibles=2, mostrar_explicacion=False,
            )
            deriv.mostrar_inicial()
            deriv.siguiente(indicar=False)
            circulo = Circle()
            visto["circulo"] = circulo
            n0 = len(visto["plays"])
            visto["extra_en_fase"].clear()
            deriv.siguiente(indicar=False, animaciones_extra=[FadeIn(circulo)])
            visto["plays_por_paso"] = len(visto["plays"]) - n0

    with tempconfig({"quality": "low_quality", "dry_run": True}):
        _Escena().render()
    assert visto["plays_por_paso"] == 2
    assert visto["extra_en_fase"] == [False, True]
