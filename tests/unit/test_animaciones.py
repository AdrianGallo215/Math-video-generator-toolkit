"""Tests de toolkit/animaciones.py: vocabulario de animacion estilo 3B1B."""

import numpy as np
import pytest
from manim import (
    DOWN,
    RIGHT,
    UP,
    Animation,
    AnimationGroup,
    ChangeDecimalToValue,
    Circle,
    Create,
    DecimalNumber,
    DrawBorderThenFill,
    FadeIn,
    FadeOut,
    Integer,
    LaggedStart,
    MathTex,
    Mobject,
    Square,
    SurroundingRectangle,
    Transform,
    VGroup,
    Write,
)

from toolkit.animaciones import (
    aparecer,
    aparecer_escalonado,
    caja_resultado,
    contar,
    desaparecer,
    enfocar,
    flecha_etiquetada,
    llave_con_etiqueta,
    mover_a_zona,
    pulso,
    resaltar,
    restaurar,
    titulo_seccion,
    transicion_seccion,
)
from toolkit.estilos import OPACIDAD_ATENUADO
from toolkit.layout import ZONA_PRINCIPAL, ZONA_TITULO
from toolkit.tipografia import Texto


def _aplicar(anim: Animation) -> None:
    anim.begin()
    anim.interpolate(1)
    anim.finish()


def _opacidades(mob: Mobject) -> list[tuple[float, float]]:
    return [
        (float(sm.get_fill_opacity()), float(sm.get_stroke_opacity()))
        for sm in mob.get_family()
        if len(sm.points) > 0
    ]


# --- aparecer ---------------------------------------------------------------------------


def test_aparecer_trazo_sin_relleno_usa_create():
    anim = aparecer(Circle())
    assert isinstance(anim, Create)


def test_aparecer_con_relleno_usa_draw_border_then_fill():
    anim = aparecer(Square().set_fill(opacity=0.6))
    assert isinstance(anim, DrawBorderThenFill)


def test_aparecer_texto_usa_write_con_run_time_acotado():
    anim = aparecer(Texto("Hola"), run_time=3.0)
    assert isinstance(anim, Write)
    assert anim.run_time <= 1.5


def test_aparecer_con_direccion_usa_fade_in():
    anim = aparecer(Circle(), direccion=UP)
    assert isinstance(anim, FadeIn)


def test_aparecer_grupo_mixto_devuelve_animation_group():
    anim = aparecer(VGroup(Texto("a"), Circle()))
    assert isinstance(anim, AnimationGroup)


def test_aparecer_escalonado_es_lagged_start_con_run_time_acotado():
    mobs = [Circle() for _ in range(3)]
    anim = aparecer_escalonado(mobs)
    assert isinstance(anim, LaggedStart)
    assert anim.run_time == pytest.approx(0.6 + 0.12 * 3)
    muchos = aparecer_escalonado([Circle() for _ in range(40)])
    assert muchos.run_time == pytest.approx(2.5)


def test_aparecer_escalonado_vacio_lanza():
    with pytest.raises(ValueError):
        aparecer_escalonado([])


# --- desaparecer ------------------------------------------------------------------------


def test_desaparecer_devuelve_fade_out():
    anim = desaparecer(Circle(), Square(), direccion=DOWN)
    assert isinstance(anim, FadeOut)


# --- enfocar / restaurar ----------------------------------------------------------------


def test_enfocar_atenua_resto_preservando_relacion_y_restaurar_recupera():
    foco = Texto("foco")
    relleno = Square().set_fill(opacity=0.6).set_stroke(opacity=1.0)
    solo_trazo = Circle()  # relleno 0
    originales_relleno = _opacidades(relleno)
    originales_trazo = _opacidades(solo_trazo)

    anim = enfocar(foco, [relleno, solo_trazo])
    assert isinstance(anim, Animation)
    _aplicar(anim)

    for (f, s), (f0, s0) in zip(_opacidades(relleno), originales_relleno):
        assert f == pytest.approx(f0 * OPACIDAD_ATENUADO)
        assert s == pytest.approx(s0 * OPACIDAD_ATENUADO)
    for (f, s), (f0, s0) in zip(_opacidades(solo_trazo), originales_trazo):
        assert f == pytest.approx(0.0)  # nunca se le pone relleno
        assert s == pytest.approx(s0 * OPACIDAD_ATENUADO)
    for f, s in _opacidades(foco):
        assert f == pytest.approx(1.0)

    assert hasattr(relleno, "opacidad_original")

    _aplicar(restaurar([relleno, solo_trazo]))
    assert _opacidades(relleno) == pytest.approx(originales_relleno)
    assert _opacidades(solo_trazo) == pytest.approx(originales_trazo)


def test_enfocar_dos_veces_no_pierde_la_opacidad_original():
    a, b = Square().set_fill(opacity=0.8), Circle()
    originales = _opacidades(a)
    _aplicar(enfocar(b, a))
    _aplicar(enfocar(b, a))  # repetir no debe atenuar sobre lo ya atenuado
    assert _opacidades(a)[0][0] == pytest.approx(0.8 * OPACIDAD_ATENUADO)
    _aplicar(restaurar(a))
    assert _opacidades(a) == pytest.approx(originales)


def test_enfocar_en_un_mob_atenuado_lo_devuelve_a_su_original():
    a, b = Square().set_fill(opacity=0.5), Circle()
    _aplicar(enfocar(b, a))
    _aplicar(enfocar(a, b))
    assert _opacidades(a)[0][0] == pytest.approx(0.5)
    assert _opacidades(b)[0][1] == pytest.approx(OPACIDAD_ATENUADO)


def test_restaurar_sin_enfocar_no_cambia_nada():
    a = Square().set_fill(opacity=0.4)
    antes = _opacidades(a)
    _aplicar(restaurar(a))
    assert _opacidades(a) == pytest.approx(antes)


# --- resaltar ---------------------------------------------------------------------------


@pytest.mark.parametrize("modo", ["indicar", "rodear", "destello", "subrayar"])
def test_resaltar_modos_devuelven_animacion(modo):
    anim = resaltar(Texto("x"), modo=modo)
    assert isinstance(anim, Animation)


def test_resaltar_modo_desconocido_lanza():
    with pytest.raises(ValueError):
        resaltar(Circle(), modo="bailar")


# --- caja, llave, flecha ----------------------------------------------------------------


def test_caja_resultado_rodea_completamente_el_mob():
    mob = MathTex("x = 3").shift(RIGHT)
    caja, anim = caja_resultado(mob, buff=0.25)
    assert isinstance(caja, SurroundingRectangle)
    assert isinstance(anim, Create)
    assert caja.get_left()[0] < mob.get_left()[0]
    assert caja.get_right()[0] > mob.get_right()[0]
    assert caja.get_top()[1] > mob.get_top()[1]
    assert caja.get_bottom()[1] < mob.get_bottom()[1]


def test_llave_con_etiqueta_texto_y_tex():
    mob = Square()
    grupo, anim = llave_con_etiqueta(mob, "lado")
    assert isinstance(grupo, VGroup) and len(grupo) == 2
    assert isinstance(anim, Animation)
    assert grupo[1].get_top()[1] < mob.get_bottom()[1]  # etiqueta debajo

    grupo_tex, _ = llave_con_etiqueta(mob, r"\frac{a}{2}", direccion=UP)
    assert isinstance(grupo_tex[1], MathTex)
    grupo_dolar, _ = llave_con_etiqueta(mob, "$n^2$")
    assert isinstance(grupo_dolar[1], MathTex)


def test_flecha_etiquetada_recta_y_curva():
    grupo, anim = flecha_etiquetada(np.array([-1, 0, 0]), np.array([1, 0, 0]), "paso")
    assert isinstance(grupo, VGroup) and len(grupo) == 2
    assert isinstance(anim, Animation)
    # la etiqueta queda desplazada respecto de la flecha (no encima)
    assert grupo[1].get_bottom()[1] > 0

    a, b = Circle(radius=0.3).shift(2 * DOWN), Square(0.5).shift(2 * UP)
    grupo_curvo, _ = flecha_etiquetada(a, b, "sube", curvatura=1.0)
    flecha = grupo_curvo[0]
    assert np.linalg.norm(flecha.get_start() - a.get_center()) > 0.25  # nace en el borde


# --- contar, pulso ----------------------------------------------------------------------


def test_contar_usa_change_decimal_to_value():
    numero = DecimalNumber(0)
    anim = contar(numero, 10)
    assert isinstance(anim, ChangeDecimalToValue)
    _aplicar(anim)
    assert numero.get_value() == pytest.approx(10)
    assert isinstance(contar(Integer(3), 7), ChangeDecimalToValue)


def test_contar_rechaza_no_numericos():
    with pytest.raises(TypeError):
        contar(Circle(), 3)


def test_pulso_vuelve_al_tamano_original():
    mob = Square()
    ancho = mob.width
    anim = pulso(mob)
    assert isinstance(anim, Animation)
    _aplicar(anim)
    assert mob.width == pytest.approx(ancho)


# --- titulo, mover, transicion ----------------------------------------------------------


def test_titulo_seccion_queda_en_zona():
    titulo = titulo_seccion("Sección uno")
    assert isinstance(titulo, Mobject)
    assert ZONA_TITULO.contiene(titulo)


def test_mover_a_zona_usa_transform_y_termina_dentro():
    mob = Square(side_length=8)
    anim = mover_a_zona(mob, ZONA_TITULO)
    assert isinstance(anim, Transform)
    _aplicar(anim)
    assert ZONA_TITULO.contiene(mob)


def test_transicion_seccion_llama_play_y_sfx():
    class EscenaFalsa:
        def __init__(self):
            self.jugadas = []
            self.sonidos = []

        def play(self, *anims, **kw):
            self.jugadas.append((anims, kw))

        def sfx(self, nombre):
            self.sonidos.append(nombre)

    escena = EscenaFalsa()
    transicion_seccion(escena, [Circle(), Square()])
    assert escena.sonidos == ["whoosh"]
    assert len(escena.jugadas) == 1
    assert isinstance(escena.jugadas[0][0][0], FadeOut)

    vacia = EscenaFalsa()
    transicion_seccion(vacia, [])
    assert vacia.jugadas == []


# --- humo de render ---------------------------------------------------------------------


@pytest.mark.render
def test_escena_con_todas_las_funciones_construye():
    from manim import tempconfig

    from toolkit.base_scene import PlantillaShort

    class EscenaHumo(PlantillaShort):
        def construct(self):
            titulo = titulo_seccion("Prueba")
            circulo, cuadro = Circle(radius=0.5), Square(1).set_fill(opacity=0.6)
            VGroup(circulo, cuadro).arrange(RIGHT, buff=1)
            numero = DecimalNumber(0).next_to(cuadro, DOWN)
            self.play(aparecer(titulo))
            self.play(aparecer_escalonado([circulo, cuadro, numero]))
            self.play(resaltar(circulo, modo="rodear"), resaltar(cuadro, modo="subrayar"))
            self.play(resaltar(cuadro, modo="destello"), resaltar(numero))
            self.play(enfocar(cuadro, [circulo, numero]))
            caja, anim = caja_resultado(cuadro)
            self.play(anim)
            self.play(restaurar([circulo, numero]))
            llave, anim_llave = llave_con_etiqueta(circulo, "radio")
            flecha, anim_flecha = flecha_etiquetada(circulo, cuadro, "a", curvatura=0.8)
            self.play(anim_llave, anim_flecha)
            self.play(contar(numero, 5, run_time=0.3), pulso(circulo))
            self.play(mover_a_zona(cuadro, ZONA_PRINCIPAL))
            self.play(desaparecer(caja, llave, direccion=DOWN))
            transicion_seccion(self, [titulo, circulo, cuadro, numero, flecha])

    with tempconfig({"quality": "low_quality", "dry_run": True}):
        EscenaHumo().render()
