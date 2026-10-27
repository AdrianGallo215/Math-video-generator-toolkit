"""Tests de toolkit/motor_algebra.py (puro: sympy, sin manim)."""

from fractions import Fraction

import pytest

from toolkit.motor_algebra import (
    Paso,
    completar_cuadrado,
    emparejar_tokens,
    formatear_polinomio,
    normalizar_token,
    resolver_cuadratica_formula,
    resolver_ecuacion_cuadratica,
    resolver_lineal,
    tokenizar_latex,
    verificar_solucion,
)


def _latex(paso: Paso) -> str:
    return " ".join(paso.tokens)


# ---------------------------------------------------------------- formatear_polinomio


@pytest.mark.parametrize(
    "coefs, esperado",
    [
        ([1, -5, 6], "x^2 - 5x + 6"),
        ([2, 0, -8], "2x^2 - 8"),
        ([-1, 1, 0], "-x^2 + x"),
        ([0, 0, 0], "0"),
        ([0, 3, 0], "3x"),
        ([1, 0, 0, -1], "x^3 - 1"),
        ([Fraction(1, 2), -1], r"\frac{1}{2}x - 1"),
        ([Fraction(-3, 4)], r"-\frac{3}{4}"),
    ],
)
def test_formatear_polinomio(coefs, esperado):
    assert formatear_polinomio(coefs) == esperado


def test_formatear_polinomio_otra_variable():
    assert formatear_polinomio([1, 2], variable="n") == "n + 2"


def test_formatear_polinomio_exponente_de_dos_cifras_con_llaves():
    assert formatear_polinomio([1] + [0] * 10) == "x^{10}"


# ---------------------------------------------------------------- tokenizar_latex


def test_tokenizar_cuadratica_basica():
    assert tokenizar_latex(r"x^2 - 5x + 6 = 0") == ("x^2", "-", "5", "x", "+", "6", "=", "0")


def test_tokenizar_coeficiente_pegado_se_parte_en_numero_y_variable():
    # "5x" son DOS tokens para que la x se empareje entre pasos.
    assert tokenizar_latex("5x") == ("5", "x")
    assert tokenizar_latex("6x") == ("6", "x")


def test_tokenizar_no_parte_frac_ni_sqrt():
    toks = tokenizar_latex(r"x = \frac{-b \pm \sqrt{b^2 - 4ac}}{2a}")
    assert toks == ("x", "=", r"\frac{-b\pm\sqrt{b^2-4ac}}{2a}")


def test_tokenizar_sqrt_con_indice():
    assert tokenizar_latex(r"\sqrt[3]{8} = 2") == (r"\sqrt[3]{8}", "=", "2")


def test_tokenizar_parentesis_balanceados_con_exponente_como_un_token():
    assert tokenizar_latex("(x + 3)^2 = 25") == ("(x+3)^2", "=", "25")
    assert tokenizar_latex("2(x + (1 - y)) = 4") == ("2", "(x+(1-y))", "=", "4")


def test_tokenizar_left_right():
    assert tokenizar_latex(r"\left(x + \frac{3}{2}\right)^2 = 1") == (
        r"\left(x+\frac{3}{2}\right)^2",
        "=",
        "1",
    )


def test_tokenizar_operadores_comando():
    assert tokenizar_latex(r"x + 3 = \pm 5") == ("x", "+", "3", "=", r"\pm", "5")
    assert tokenizar_latex(r"x = 2 \quad x = -8") == ("x", "=", "2", r"\quad", "x", "=", "-", "8")
    assert tokenizar_latex(r"2 \cdot 3") == ("2", r"\cdot", "3")


def test_tokenizar_subindices_y_exponentes_con_llaves():
    assert tokenizar_latex("x_1 + x_{2} = y^{10}") == ("x_1", "+", "x_{2}", "=", "y^{10}")


def test_tokenizar_letras_no_variables_se_agrupan():
    # 'a','c' no son variables: "4ac" => "4", "ac"; la x siempre va sola.
    assert tokenizar_latex("b^2 - 4ac") == ("b^2", "-", "4", "ac")
    assert tokenizar_latex("ax^2") == ("a", "x^2")
    assert tokenizar_latex("xy") == ("x", "y")


def test_tokenizar_variables_personalizadas():
    assert tokenizar_latex("vt", variables=("v", "t")) == ("v", "t")
    assert tokenizar_latex("vt", variables=("x",)) == ("vt",)


def test_tokenizar_text_preserva_espacios():
    assert tokenizar_latex(r"\text{sin soluciones reales}") == (r"\text{sin soluciones reales}",)


def test_tokenizar_decimales_y_comandos_griegos():
    assert tokenizar_latex(r"3.5\theta^2") == ("3.5", r"\theta^2")


def test_tokenizar_nunca_parte_dentro_de_llaves():
    for tok in tokenizar_latex(r"x^{2} + \frac{1}{2}x + {a+b} = 0"):
        assert tok.count("{") == tok.count("}")


def test_normalizar_token_quita_espacios_salvo_los_necesarios():
    assert normalizar_token("(x + 3)^2") == "(x+3)^2"
    assert normalizar_token(r"\cdot x") == r"\cdot x"
    assert normalizar_token(r"\pm 5") == r"\pm5"
    assert normalizar_token(r"\text{a  b}") == r"\text{a  b}"
    assert normalizar_token(r"a\ b") == r"a\ b"


# ---------------------------------------------------------------- Paso


def test_paso_convierte_lista_a_tupla_y_es_inmutable():
    p = Paso(["x", "=", "1"], "Resultado")
    assert p.tokens == ("x", "=", "1")
    with pytest.raises(Exception):
        p.explicacion = "otra"  # type: ignore[misc]


def test_paso_manual_desde_tokenizar():
    p = Paso(tokenizar_latex("x^2 + 6x + 9 = 16 + 9"), "Sumamos 9")
    assert p.tokens.count("9") == 2 and p.resaltar == ()


# ---------------------------------------------------------------- resolver_lineal


def test_resolver_lineal_pasos_y_resultado():
    pasos = resolver_lineal(2, 5, 11)
    assert _latex(pasos[0]) == "2 x + 5 = 11"
    assert pasos[-1].tokens == ("x", "=", "3")
    assert all(isinstance(p, Paso) and p.explicacion for p in pasos)
    assert any("Restamos 5" in p.explicacion for p in pasos)
    assert any("Dividimos" in p.explicacion for p in pasos)


def test_resolver_lineal_fraccion_y_b_negativo():
    pasos = resolver_lineal(2, -1, 2)
    assert any("Sumamos 1" in p.explicacion for p in pasos)
    assert pasos[-1].tokens == ("x", "=", r"\frac{3}{2}")


def test_resolver_lineal_a_cero_falla():
    with pytest.raises(ValueError):
        resolver_lineal(0, 1, 2)


# ---------------------------------------------------------------- formula general


def test_resolver_cuadratica_formula_raices_enteras():
    pasos = resolver_cuadratica_formula(1, -5, 6)
    assert pasos[0].tokens == ("x^2", "-", "5", "x", "+", "6", "=", "0")
    final = _latex(pasos[-1])
    assert "3" in pasos[-1].tokens and "2" in pasos[-1].tokens
    assert r"\quad" in final
    assert len(pasos) >= 4


def test_resolver_cuadratica_formula_sin_soluciones_reales():
    pasos = resolver_cuadratica_formula(1, 2, 5)
    assert "sin soluciones reales" in _latex(pasos[-1])
    assert "sin soluciones reales" in pasos[-1].explicacion


def test_resolver_cuadratica_formula_raiz_doble():
    pasos = resolver_cuadratica_formula(1, -4, 4)
    assert pasos[-1].tokens == ("x", "=", "2")


def test_resolver_cuadratica_formula_a_cero_falla():
    with pytest.raises(ValueError):
        resolver_cuadratica_formula(0, 2, 1)


def test_compat_resolver_ecuacion_cuadratica():
    pasos = resolver_ecuacion_cuadratica(1, -5, 6)
    assert len(pasos) == 4 and all(isinstance(p, str) for p in pasos)
    assert all("1x" not in p for p in pasos)
    assert r"\sqrt" in pasos[1]
    # Sin soluciones reales tambien devuelve 4 strings.
    assert len(resolver_ecuacion_cuadratica(1, 2, 5)) == 4


# ---------------------------------------------------------------- completar_cuadrado


def test_completar_cuadrado_caso_del_guion_v02():
    pasos = completar_cuadrado(1, 6, -16)
    latex = [_latex(p) for p in pasos]
    assert pasos[0].tokens == ("x^2", "+", "6", "x", "=", "16")
    assert pasos[1].tokens == ("x^2", "+", "6", "x", "+", "9", "=", "16", "+", "9")
    assert pasos[2].tokens == ("(x+3)^2", "=", "16", "+", "9")
    assert pasos[3].tokens == ("(x+3)^2", "=", "25")
    assert pasos[4].tokens == ("x", "+", "3", "=", r"\pm", "5")
    assert pasos[5].tokens == ("x", "=", "2", r"\quad", "x", "=", "-", "8")
    assert "2" in pasos[-1].tokens and "8" in pasos[-1].tokens
    assert len(latex) == 6


def test_completar_cuadrado_resalta_lo_sumado():
    pasos = completar_cuadrado(1, 6, -16)
    resaltados = {pasos[1].tokens[i] for i in pasos[1].resaltar}
    assert resaltados == {"9"}


def test_completar_cuadrado_con_a_distinto_de_uno_y_fracciones():
    pasos = completar_cuadrado(2, 6, -8)  # 2x^2+6x-8=0 => x^2+3x=4 => (x+3/2)^2=25/4 => x=1, x=-4
    assert any("Dividimos" in p.explicacion for p in pasos)
    final = pasos[-1].tokens
    assert "1" in final and "4" in final


def test_completar_cuadrado_sin_soluciones_reales():
    pasos = completar_cuadrado(1, 2, 5)
    assert "sin soluciones reales" in _latex(pasos[-1])


def test_completar_cuadrado_b_cero():
    pasos = completar_cuadrado(1, 0, -9)
    assert pasos[-1].tokens == ("x", "=", "3", r"\quad", "x", "=", "-", "3")


def test_completar_cuadrado_raiz_irracional():
    pasos = completar_cuadrado(1, 2, -1)  # (x+1)^2 = 2
    assert any(r"\sqrt{2}" in t for t in pasos[-1].tokens)


# ---------------------------------------------------------------- verificar_solucion


def test_verificar_solucion():
    assert verificar_solucion("x**2 + 6*x = 16", "x", [2, -8])
    assert verificar_solucion("x**2 + 6*x - 16", "x", 2)
    assert not verificar_solucion("x**2 + 6*x = 16", "x", [3])


# ---------------------------------------------------------------- emparejar_tokens


def test_emparejar_tokens_numero_unico_del_mismo_lado():
    origen = ("(x+3)^2", "=", "25")
    destino = ("x", "+", "3", "=", r"\pm", "5")
    assert emparejar_tokens(origen, destino) == {"25": "5"}


def test_emparejar_tokens_misma_base_y_mismo_tipo():
    assert emparejar_tokens(("x_1", "=", "2"), ("x", "=", "2")) == {"x_1": "x"}
    km = emparejar_tokens(("x", "=", r"\frac{5\pm\sqrt{1}}{2}"), ("x", "=", r"\frac{5\pm1}{2}"))
    assert km == {r"\frac{5\pm\sqrt{1}}{2}": r"\frac{5\pm1}{2}"}


def test_emparejar_tokens_no_toca_tokens_ya_emparejados():
    assert emparejar_tokens(("x", "=", "16"), ("x", "=", "16")) == {}
    # Dos numeros sin pareja en el mismo lado => ambiguo => no se emparejan.
    assert emparejar_tokens(("y", "=", "16", "+", "9"), ("y", "=", "25")) == {}
