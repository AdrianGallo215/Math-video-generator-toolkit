"""Motor algebraico puro (sympy, sin manim): derivaciones paso a paso tokenizadas.

Cada derivacion es una lista de ``Paso``: tokens LaTeX + explicacion en espanol.
Los tokens iguales entre pasos consecutivos son los que ``TransformMatchingTex``
empareja (vuelan) en ``toolkit.algebra_visual``.

Especificacion de la tokenizacion (``tokenizar_latex``)
-------------------------------------------------------
Se recorre el LaTeX de izquierda a derecha ignorando espacios; cada token es:

* Numero: ``\\d+(\\.\\d+)?`` ("16", "3.5"). Un coeficiente pegado se separa: "5x" => "5", "x".
* Variable (letra de ``variables``): siempre sola, con su exponente/subindice pegado:
  "x", "x^2", "x_1", "y^{10}". "xy" => "x", "y".
* Otras letras seguidas (no variables) forman un token: "4ac" => "4", "ac"; "b^2" => "b^2".
* Comando con argumentos, completo: ``\\frac{..}{..}`` (y ``\\dfrac``, ``\\tfrac``, ``\\binom``),
  ``\\sqrt[..]{..}``, ``\\text{..}``, ``\\mathrm{..}``, ``\\overline{..}``, ``\\vec{..}``...
* ``\\left<d> ... \\right<d>`` balanceado, completo.
* Grupo entre parentesis/corchetes balanceados, completo: "(x + 3)^2" es UN token.
* Grupo entre llaves ``{...}``, completo. Nunca se parte dentro de llaves.
* Cualquier otro comando (``\\pm``, ``\\cdot``, ``\\quad``, ``\\theta``) o caracter (+ - = < > ,) es un token.
* Exponentes/subindices (``^2``, ``^{..}``, ``_1``) se pegan al token anterior.

Cada token se normaliza con ``normalizar_token``: se quitan los espacios (el modo
matematico los ignora) salvo dentro de ``\\text{..}`` y los necesarios tras un comando
seguido de letra (``\\cdot x``). Asi "(x+3)^2" y "(x + 3)^2" son el mismo token y se
emparejan aunque uno venga del motor y otro se escriba a mano.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from fractions import Fraction
from typing import Iterable, Sequence

import sympy as sp

logger = logging.getLogger(__name__)

__all__ = [
    "Paso",
    "tokenizar_latex",
    "normalizar_token",
    "formatear_polinomio",
    "resolver_lineal",
    "resolver_cuadratica_formula",
    "completar_cuadrado",
    "resolver_ecuacion_cuadratica",
    "verificar_solucion",
    "emparejar_tokens",
    "formatear_latex_sympy",
    "RELACIONES",
]

# Comandos que consumen argumentos entre llaves (numero de argumentos obligatorios).
_COMANDOS_CON_ARGUMENTOS = {
    "frac": 2, "dfrac": 2, "tfrac": 2, "binom": 2, "sqrt": 1,
    "text": 1, "textrm": 1, "textbf": 1, "textit": 1, "mbox": 1,
    "mathrm": 1, "mathbf": 1, "mathit": 1, "operatorname": 1,
    "overline": 1, "underline": 1, "vec": 1, "hat": 1, "bar": 1, "tilde": 1, "boxed": 1,
}
# Comandos en modo texto: sus espacios internos importan.
_COMANDOS_TEXTO = {"text", "textrm", "textbf", "textit", "mbox"}

# Tokens de relacion (alineacion por "=" y lados de una ecuacion).
RELACIONES = frozenset({"=", "<", ">", r"\le", r"\ge", r"\leq", r"\geq", r"\neq", r"\approx"})

_RE_NUMERO = re.compile(r"\d+(?:\.\d+)?$")


@dataclass(frozen=True)
class Paso:
    """Un paso de una derivacion."""

    tokens: tuple[str, ...]  # piezas LaTeX; tokens iguales entre pasos => se emparejan en la animacion
    explicacion: str  # texto corto en espanol para narracion/etiqueta
    resaltar: tuple[int, ...] = ()  # indices de tokens nuevos/importantes en este paso

    def __post_init__(self) -> None:
        object.__setattr__(self, "tokens", tuple(self.tokens))
        object.__setattr__(self, "resaltar", tuple(self.resaltar))
        for i in self.resaltar:
            if not 0 <= i < len(self.tokens):
                raise ValueError(f"indice de resaltar fuera de rango: {i}")

    @property
    def latex(self) -> str:
        """LaTeX completo del paso (tokens unidos por espacio)."""
        return " ".join(self.tokens)


# ============================================================ tokenizacion


def _fin_llaves(s: str, i: int) -> int:
    """``s[i] == "{"``: indice justo despues de la llave que la cierra."""
    profundidad = 0
    n = len(s)
    while i < n:
        c = s[i]
        if c == "\\":
            i += 2
            continue
        if c == "{":
            profundidad += 1
        elif c == "}":
            profundidad -= 1
            if profundidad == 0:
                return i + 1
        i += 1
    raise ValueError(f"llaves desbalanceadas en {s!r}")


def _fin_delimitado(s: str, i: int, abre: str, cierra: str) -> int | None:
    """``s[i] == abre``: indice tras el ``cierra`` que lo balancea (saltando llaves), o None."""
    profundidad = 0
    n = len(s)
    while i < n:
        c = s[i]
        if c == "\\":
            i += 2
            continue
        if c == "{":
            i = _fin_llaves(s, i)
            continue
        if c == abre:
            profundidad += 1
        elif c == cierra:
            profundidad -= 1
            if profundidad == 0:
                return i + 1
        i += 1
    return None


def _saltar_espacios(s: str, i: int) -> int:
    while i < len(s) and s[i].isspace():
        i += 1
    return i


def _fin_comando(s: str, i: int) -> int:
    """``s[i] == "\\"``: indice tras el nombre del comando (palabra o simbolo)."""
    j = i + 1
    if j < len(s) and s[j].isalpha():
        while j < len(s) and s[j].isalpha():
            j += 1
        return j
    return min(j + 1, len(s))


def _fin_argumento(s: str, i: int) -> int:
    """Consume un argumento: ``{..}``, un comando o un caracter."""
    i = _saltar_espacios(s, i)
    if i >= len(s):
        return i
    if s[i] == "{":
        return _fin_llaves(s, i)
    if s[i] == "\\":
        return _fin_comando(s, i)
    return i + 1


def _fin_adjuntos(s: str, i: int) -> int:
    """Consume exponentes/subindices pegados (``^2``, ``_{12}``, ``^\\prime``)."""
    while True:
        j = _saltar_espacios(s, i)
        if j < len(s) and s[j] in "^_":
            i = _fin_argumento(s, j + 1)
        else:
            return i


def _fin_left(s: str, i: int) -> int:
    """``s[i:]`` empieza por ``\\left``: indice tras su ``\\right<delim>`` balanceado."""
    profundidad = 0
    n = len(s)
    while i < n:
        if s.startswith(r"\left", i) and not (i + 5 < n and s[i + 5].isalpha()):
            profundidad += 1
            i += 5
        elif s.startswith(r"\right", i) and not (i + 6 < n and s[i + 6].isalpha()):
            profundidad -= 1
            i += 6
            if profundidad == 0:
                i = _saltar_espacios(s, i)
                if i < n and s[i] == "\\":
                    return _fin_comando(s, i)
                return min(i + 1, n)
        elif s[i] == "\\":
            i += 2
        else:
            i += 1
    raise ValueError(rf"\left sin \right en {s!r}")


def normalizar_token(token: str) -> str:
    """Forma canonica de un token: sin espacios salvo en modo texto y tras comandos antes de letra."""
    salida: list[str] = []
    i, n = 0, len(token)
    while i < n:
        c = token[i]
        if c == "\\":
            if i + 1 < n and token[i + 1].isalpha():
                j = _fin_comando(token, i)
                nombre = token[i + 1 : j]
                salida.append(token[i:j])
                i = j
                if nombre in _COMANDOS_TEXTO:
                    k = _saltar_espacios(token, i)
                    if k < n and token[k] == "{":
                        fin = _fin_llaves(token, k)
                        salida.append(token[k:fin])
                        i = fin
                continue
            salida.append(token[i : i + 2])
            i += 2
            continue
        if c.isspace():
            j = _saltar_espacios(token, i)
            previo = "".join(salida)
            if j < n and token[j].isalpha() and re.search(r"\\[A-Za-z]+$", previo):
                salida.append(" ")
            i = j
            continue
        salida.append(c)
        i += 1
    return "".join(salida).strip()


def tokenizar_latex(latex: str, variables: Iterable[str] = ("x", "y", "n")) -> tuple[str, ...]:
    """Parte ``latex`` en tokens emparejables (ver especificacion en el docstring del modulo)."""
    variables = set(variables)
    s = latex
    n = len(s)
    tokens: list[str] = []
    i = 0
    while i < n:
        c = s[i]
        if c.isspace():
            i += 1
            continue
        inicio = i
        if c.isdigit() or (c == "." and i + 1 < n and s[i + 1].isdigit()):
            m = re.compile(r"\d*\.?\d+|\d+").match(s, i)
            i = m.end() if m else i + 1
            i = _fin_adjuntos(s, i)
        elif c.isalpha():
            if c in variables:
                i += 1
            else:
                while i < n and s[i].isalpha() and s[i] not in variables:
                    i += 1
            i = _fin_adjuntos(s, i)
        elif c == "\\":
            j = _fin_comando(s, i)
            nombre = s[i + 1 : j]
            if nombre == "left":
                i = _fin_left(s, i)
            elif nombre in _COMANDOS_CON_ARGUMENTOS:
                i = j
                if nombre == "sqrt":
                    k = _saltar_espacios(s, i)
                    if k < n and s[k] == "[":
                        fin = _fin_delimitado(s, k, "[", "]")
                        i = fin if fin is not None else k + 1
                for _ in range(_COMANDOS_CON_ARGUMENTOS[nombre]):
                    i = _fin_argumento(s, i)
            else:
                i = j
            i = _fin_adjuntos(s, i)
        elif c == "{":
            i = _fin_adjuntos(s, _fin_llaves(s, i))
        elif c in "([":
            fin = _fin_delimitado(s, i, c, ")" if c == "(" else "]")
            i = _fin_adjuntos(s, fin) if fin is not None else i + 1
        elif c in "^_":
            i = _fin_adjuntos(s, i)
        else:
            i += 1
        token = normalizar_token(s[inicio:i])
        if token:
            tokens.append(token)
    return tuple(tokens)


# ============================================================ formato de numeros


def _q(valor) -> Fraction:
    """Convierte int/Fraction/sympy.Rational/float a Fraction exacta."""
    if isinstance(valor, bool):
        raise TypeError("booleano no es un coeficiente")
    if isinstance(valor, Fraction):
        return valor
    if isinstance(valor, int):
        return Fraction(valor)
    if isinstance(valor, sp.Rational):
        return Fraction(int(valor.p), int(valor.q))
    if isinstance(valor, float):
        return Fraction(valor).limit_denominator(10**6)
    if isinstance(valor, sp.Basic) and valor.is_number:
        r = sp.nsimplify(valor)
        if isinstance(r, sp.Rational):
            return Fraction(int(r.p), int(r.q))
    raise TypeError(f"coeficiente no racional: {valor!r}")


def _lq(q: Fraction) -> str:
    """LaTeX de un racional: "3", "-3", "\\frac{3}{2}", "-\\frac{3}{2}"."""
    q = _q(q)
    if q.denominator == 1:
        return str(q.numerator)
    signo = "-" if q < 0 else ""
    return rf"{signo}\frac{{{abs(q.numerator)}}}{{{q.denominator}}}"


def _tq(q: Fraction) -> str:
    """Texto plano de un racional para explicaciones ("9", "9/4")."""
    return str(_q(q))


def _paren(q: Fraction) -> str:
    """Racional entre parentesis si es negativo."""
    q = _q(q)
    return f"({_lq(q)})" if q < 0 else _lq(q)


def formatear_latex_sympy(expresion_sympy) -> str:
    """Compat: LaTeX de un objeto sympy."""
    return sp.latex(expresion_sympy)


def formatear_polinomio(coefs: Sequence, variable: str = "x") -> str:
    """Coeficientes de mayor a menor grado => LaTeX limpio ([1,-5,6] => "x^2 - 5x + 6")."""
    coefs = [_q(c) for c in coefs]
    grado = len(coefs) - 1
    partes: list[str] = []
    for k, c in enumerate(coefs):
        potencia = grado - k
        if c == 0:
            continue
        if potencia == 0:
            var = ""
        elif potencia == 1:
            var = variable
        elif potencia < 10:
            var = f"{variable}^{potencia}"
        else:
            var = f"{variable}^{{{potencia}}}"
        magnitud = abs(c)
        cuerpo = var if (magnitud == 1 and var) else f"{_lq(magnitud)}{var}"
        if not partes:
            partes.append(("-" if c < 0 else "") + cuerpo)
        else:
            partes.append(("- " if c < 0 else "+ ") + cuerpo)
    return " ".join(partes) if partes else "0"


# ============================================================ verificacion


def _parsear(ecuacion: str) -> sp.Expr:
    if "=" in ecuacion and "==" not in ecuacion:
        izq, der = ecuacion.split("=", 1)
        return sp.sympify(izq) - sp.sympify(der)
    return sp.sympify(ecuacion)


def verificar_solucion(ecuacion_sympy_str: str, variable: str, valores) -> bool:
    """True si todos los ``valores`` satisfacen la ecuacion ("x**2 + 6*x = 16" o expresion = 0)."""
    expr = _parsear(ecuacion_sympy_str)
    x = sp.Symbol(variable)
    if isinstance(valores, (str, sp.Basic)) or not isinstance(valores, Iterable):
        valores = [valores]
    for v in valores:
        valor = sp.nsimplify(v) if not isinstance(v, sp.Basic) else v
        if sp.simplify(expr.subs(x, valor)) != 0:
            return False
    return True


def _comprobar(a, b, c, soluciones: list, variable: str) -> None:
    """Contrasta las soluciones calculadas con sympy; ValueError si no coinciden."""
    x = sp.Symbol(variable)
    esperadas = [s for s in sp.solve(sp.Rational(a) * x**2 + sp.Rational(b) * x + sp.Rational(c), x) if s.is_real]
    ok = len(esperadas) == len(soluciones) and all(
        any(sp.simplify(e - s) == 0 for s in soluciones) for e in esperadas
    )
    if not ok:
        raise ValueError(f"inconsistencia: calculadas {soluciones}, sympy {esperadas}")


def _t(latex: str, variable: str) -> tuple[str, ...]:
    return tokenizar_latex(latex, variables=("x", "y", "n", variable))


def _indices_finales(tokens: tuple[str, ...], n: int) -> tuple[int, ...]:
    return tuple(range(len(tokens) - n, len(tokens)))


# ============================================================ derivaciones


def resolver_lineal(a, b, c, variable: str = "x") -> list[Paso]:
    """a·x + b = c => restar b, dividir entre a, resultado."""
    a, b, c = _q(a), _q(b), _q(c)
    if a == 0:
        raise ValueError("a no puede ser 0 en una ecuacion lineal")
    v = variable
    pasos = [Paso(_t(f"{formatear_polinomio([a, b], v)} = {_lq(c)}", v), f"Queremos despejar {v}")]
    lado = formatear_polinomio([a, 0], v)
    d = c - b
    if b != 0:
        op = "-" if b > 0 else "+"
        verbo = "Restamos" if b > 0 else "Sumamos"
        numero = _t(_lq(abs(b)), v)
        toks = _t(f"{lado} = {_lq(c)} {op} {_lq(abs(b))}", v)
        pasos.append(Paso(toks, f"{verbo} {_tq(abs(b))} a ambos lados", _indices_finales(toks, len(numero) + 1)))
        pasos.append(Paso(_t(f"{lado} = {_lq(d)}", v), "Operamos"))
    if a != 1:
        pasos.append(
            Paso(_t(rf"{v} = \frac{{{_lq(d)}}}{{{_lq(a)}}}", v), f"Dividimos entre {_tq(a)} ambos lados")
        )
    sol = d / a
    final = _t(f"{v} = {_lq(sol)}", v)
    if final != pasos[-1].tokens:
        pasos.append(Paso(final, f"Resultado: {v} = {_tq(sol)}", tuple(range(2, len(final)))))
    if sp.simplify(sp.Rational(a.numerator, a.denominator) * sp.Rational(sol.numerator, sol.denominator)
                   + sp.Rational(b.numerator, b.denominator) - sp.Rational(c.numerator, c.denominator)) != 0:
        raise ValueError("inconsistencia en resolver_lineal")
    return pasos


def _r(q: Fraction) -> sp.Rational:
    return sp.Rational(q.numerator, q.denominator)


def resolver_cuadratica_formula(a, b, c, variable: str = "x") -> list[Paso]:
    """ax^2+bx+c=0 por formula general: planteamiento, sustitucion, discriminante, raiz, soluciones."""
    a, b, c = _q(a), _q(b), _q(c)
    if a == 0:
        raise ValueError("a no puede ser 0 en una ecuacion cuadratica")
    v = variable
    pasos = [Paso(_t(f"{formatear_polinomio([a, b, c], v)} = 0", v), "Planteamos la ecuación")]

    lb = _lq(b)
    menos_b = "" if b == 0 else (f"-({lb})" if b < 0 else f"-{lb}")
    b2 = f"({lb})^2" if (b < 0 or b.denominator != 1) else f"{lb}^2"
    sustituida = (
        rf"{v} = \frac{{{menos_b} \pm \sqrt{{{b2} - 4 \cdot {_paren(a)} \cdot {_paren(c)}}}}}"
        rf"{{2 \cdot {_paren(a)}}}"
    )
    pasos.append(Paso(_t(sustituida, v), "Sustituimos en la fórmula"))

    disc = b * b - 4 * a * c
    num_b = "" if b == 0 else _lq(-b)
    pasos.append(
        Paso(
            _t(rf"{v} = \frac{{{num_b} \pm \sqrt{{{_lq(disc)}}}}}{{{_lq(2 * a)}}}", v),
            f"El discriminante vale {_tq(disc)}",
        )
    )
    if disc < 0:
        _comprobar(a, b, c, [], v)
        pasos.append(
            Paso(_t(r"\text{sin soluciones reales}", v), "El discriminante es negativo: sin soluciones reales")
        )
        return pasos

    raiz = sp.sqrt(_r(disc))
    if disc == 0:
        sol = sp.nsimplify(-_r(b) / (2 * _r(a)))
        _comprobar(a, b, c, [sol], v)
        final = _t(f"{v} = {sp.latex(sol)}", v)
        pasos.append(Paso(final, "Discriminante cero: una sola solución", tuple(range(2, len(final)))))
        return pasos

    if sp.latex(raiz) != rf"\sqrt{{{_lq(disc)}}}":
        pasos.append(
            Paso(
                _t(rf"{v} = \frac{{{num_b} \pm {sp.latex(raiz)}}}{{{_lq(2 * a)}}}", v),
                "Simplificamos la raíz",
            )
        )
    r1 = sp.radsimp(sp.simplify((-_r(b) + raiz) / (2 * _r(a))))
    r2 = sp.radsimp(sp.simplify((-_r(b) - raiz) / (2 * _r(a))))
    _comprobar(a, b, c, [r1, r2], v)
    pasos.append(
        Paso(_t(rf"{v} = {sp.latex(r1)} \quad {v} = {sp.latex(r2)}", v), "Las dos soluciones")
    )
    return pasos


def completar_cuadrado(a, b, c, variable: str = "x") -> list[Paso]:
    """ax^2+bx+c=0 completando el cuadrado.

    (1, 6, -16): x^2+6x=16 ⇒ x^2+6x+9=16+9 ⇒ (x+3)^2=16+9 ⇒ (x+3)^2=25 ⇒ x+3=±5 ⇒ x=2 \\quad x=-8.
    """
    a, b, c = _q(a), _q(b), _q(c)
    if a == 0:
        raise ValueError("a no puede ser 0 en una ecuacion cuadratica")
    v = variable
    k0 = -c
    pasos = [
        Paso(
            _t(f"{formatear_polinomio([a, b, 0], v)} = {_lq(k0)}", v),
            f"Dejamos las {v} a un lado" if c != 0 else "Partimos de la ecuación",
        )
    ]
    bb, k = b / a, k0 / a
    if a != 1:
        pasos.append(
            Paso(_t(f"{formatear_polinomio([1, bb, 0], v)} = {_lq(k)}", v), f"Dividimos entre {_tq(a)} ambos lados")
        )
    h = bb / 2
    h2 = h * h
    if h != 0:
        izq = formatear_polinomio([1, bb, 0], v)
        der = f"{_lq(k)} + {_lq(h2)}" if k != 0 else _lq(h2)
        toks = _t(f"{izq} + {_lq(h2)} = {der}", v)
        n_izq, n_h2 = len(_t(izq, v)), len(_t(_lq(h2), v))
        resaltar = tuple(range(n_izq + 1, n_izq + 1 + n_h2)) + _indices_finales(toks, n_h2)
        pasos.append(Paso(toks, f"Sumamos {_tq(h2)} a ambos lados", resaltar))
        signo = "+" if h > 0 else "-"
        base = f"{v} {signo} {_lq(abs(h))}"
        cuadrado = f"({base})^2" if h.denominator == 1 else rf"\left({base}\right)^2"
        pasos.append(Paso(_t(f"{cuadrado} = {der}", v), "¡Un cuadrado perfecto!", (0,)))
        r = k + h2
        if k != 0:
            toks = _t(f"{cuadrado} = {_lq(r)}", v)
            pasos.append(Paso(toks, f"Sumamos: {_tq(k)} + {_tq(h2)} = {_tq(r)}", tuple(range(2, len(toks)))))
    else:
        base = v
        r = k

    if r < 0:
        _comprobar(a, b, c, [], v)
        pasos.append(
            Paso(_t(r"\text{sin soluciones reales}", v), "Cuadrado negativo: sin soluciones reales")
        )
        return pasos
    if r == 0:
        sol = -_r(h)
        _comprobar(a, b, c, [sol], v)
        if h != 0:
            pasos.append(Paso(_t(f"{base} = 0", v), "Sacamos raíz cuadrada"))
        final = _t(f"{v} = {sp.latex(sol)}", v)
        if final != pasos[-1].tokens:
            pasos.append(Paso(final, "Una sola solución", tuple(range(2, len(final)))))
        return pasos

    s = sp.sqrt(_r(r))
    pasos.append(Paso(_t(rf"{base} = \pm {sp.latex(s)}", v), "Raíz cuadrada a ambos lados"))
    r1 = sp.radsimp(-_r(h) + s)
    r2 = sp.radsimp(-_r(h) - s)
    _comprobar(a, b, c, [r1, r2], v)
    pasos.append(Paso(_t(rf"{v} = {sp.latex(r1)} \quad {v} = {sp.latex(r2)}", v), f"Despejamos {v}: dos soluciones"))
    return pasos


def resolver_ecuacion_cuadratica(a, b, c, variable: str = "x") -> list[str]:
    """Compat: 4 strings LaTeX (planteamiento, sustitucion, discriminante, soluciones).

    Los tokens se unen con espacio (no con "" como decia el plan: "\\quad" + "x" daria "\\quadx").
    """
    pasos = resolver_cuadratica_formula(a, b, c, variable)
    elegidos = [pasos[0], pasos[1], pasos[2], pasos[-1]]
    return [p.latex for p in elegidos]


# ============================================================ emparejamiento automatico


def _base_token(token: str) -> str:
    """Token sin exponentes/subindices finales ("x^2" => "x", "(x+3)^2" => "(x+3)")."""
    base = token
    while True:
        m = re.search(r"[\^_](\{[^{}]*\}|\\[A-Za-z]+|[^{}\\])$", base)
        if not m or m.start() == 0:
            return base
        base = base[: m.start()]


def _tipo_token(token: str) -> str | None:
    if _RE_NUMERO.match(token):
        return "numero"
    for prefijo, tipo in ((r"\frac", "frac"), (r"\dfrac", "frac"), (r"\tfrac", "frac"),
                          (r"\sqrt", "raiz"), (r"\left", "grupo"), ("(", "grupo"), (r"\text", "texto")):
        if token.startswith(prefijo):
            return tipo
    return None


def _unicos(tokens: Sequence[str]) -> list[str]:
    vistos: list[str] = []
    for t in tokens:
        if t not in vistos:
            vistos.append(t)
    return vistos


def _lado(tokens: Sequence[str], token: str) -> int:
    """0 si la primera aparicion de ``token`` esta antes de la primera relacion, si no 1."""
    for t in tokens:
        if t == token:
            return 0
        if t in RELACIONES:
            return 1
    return 0


def emparejar_tokens(origen: Sequence[str], destino: Sequence[str]) -> dict[str, str]:
    """``key_map`` automatico entre tokens SIN pareja exacta (para transformarlos en vez de fundirlos).

    Reglas, en orden y uno a uno: (1) misma base ("x_1" -> "x"); (2) mismo tipo compuesto
    (\\frac, \\sqrt, grupo, \\text) si es el unico sin pareja de ese tipo en ambos lados;
    (3) numeros: si en un lado de la relacion queda exactamente un numero sin pareja en origen
    y uno en destino ("25" -> "5").
    """
    en_destino, en_origen = set(destino), set(origen)
    libres_o = [t for t in _unicos(origen) if t not in en_destino]
    libres_d = [t for t in _unicos(destino) if t not in en_origen]
    mapa: dict[str, str] = {}

    def disponibles_d() -> list[str]:
        return [d for d in libres_d if d not in mapa.values()]

    for o in libres_o:
        if _tipo_token(o) == "numero":
            continue
        for d in disponibles_d():
            if _base_token(o) == _base_token(d) and _tipo_token(d) != "numero":
                mapa[o] = d
                break

    for tipo in ("frac", "raiz", "grupo", "texto"):
        so = [o for o in libres_o if o not in mapa and _tipo_token(o) == tipo]
        sd = [d for d in disponibles_d() if _tipo_token(d) == tipo]
        if len(so) == 1 and len(sd) == 1:
            mapa[so[0]] = sd[0]

    for lado in (0, 1):
        so = [o for o in libres_o if o not in mapa and _tipo_token(o) == "numero" and _lado(origen, o) == lado]
        sd = [d for d in disponibles_d() if _tipo_token(d) == "numero" and _lado(destino, d) == lado]
        if len(so) == 1 and len(sd) == 1:
            mapa[so[0]] = sd[0]
    return mapa
