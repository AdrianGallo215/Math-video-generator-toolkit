"""Tests del registro del catálogo del guion (decoradores, modificadores y manifiesto)."""

import json

import pytest

from toolkit.guion import registro
from toolkit.guion.registro import (
    CATALOGO,
    MODIFICADORES,
    Definicion,
    ErrorRegistro,
    Param,
    accion,
    manifiesto,
    objeto,
)


@pytest.fixture
def catalogo_aislado():
    """Deja el catálogo como estaba al terminar (los tests registran piezas falsas)."""
    import toolkit.guion.catalogo  # noqa: F401  (llena el catálogo real)

    copia = dict(CATALOGO)
    yield
    CATALOGO.clear()
    CATALOGO.update(copia)


def test_decorador_objeto_registra_definicion(catalogo_aislado):
    @objeto(
        "prueba_obj",
        "Objeto de prueba.",
        params=[Param("texto", "texto", requerido=True, descripcion="Qué dice")],
        ejemplo={"en": "inicio", "hacer": "mostrar", "id": "p", "tipo": "prueba_obj", "texto": "hola"},
        duracion=0.7,
    )
    def crear(ctx, texto):
        return texto

    definicion = CATALOGO["prueba_obj"]
    assert isinstance(definicion, Definicion)
    assert definicion.clase == "objeto"
    assert definicion.duracion == 0.7
    assert definicion.funcion is crear
    assert [p.nombre for p in definicion.params] == ["texto"]
    assert registro.obtener("prueba_obj", "objeto") is definicion
    assert registro.obtener("prueba_obj", "accion") is None


def test_decorador_accion_con_modificadores_agrega_sus_params(catalogo_aislado):
    @accion(
        "prueba_acc",
        "Acción de prueba.",
        params=[Param("objeto", "objeto", requerido=True)],
        ejemplo={"en": "inicio", "hacer": "prueba_acc", "objeto": "a"},
        modificadores=("escalonado", "rate"),
    )
    def hacer(ctx, objeto, escalonado=0.0):
        return None

    nombres = [p.nombre for p in CATALOGO["prueba_acc"].params]
    assert nombres == ["objeto", "escalonado", "rate"]
    assert CATALOGO["prueba_acc"].modificadores == ("escalonado", "rate")
    assert CATALOGO["prueba_acc"].param("rate") is MODIFICADORES["rate"]


@pytest.mark.parametrize(
    "kwargs, fragmento",
    [
        ({"nombre": "mostrar"}, "ya está registrad"),
        ({"nombre": "Mal Nombre"}, "identificador"),
        ({"params": [Param("x", "decimal")]}, "tipo de parámetro"),
        ({"params": [Param("x", "texto", opciones=("a", "b"), defecto="c")]}, "no está en sus opciones"),
        ({"modificadores": ("volar",)}, "modificador"),
        ({"ejemplo": {"en": "inicio", "hacer": "otro"}}, "ejemplo"),
    ],
)
def test_registro_rechaza_definiciones_mal_formadas(catalogo_aislado, kwargs, fragmento):
    base = {
        "nombre": "prueba_mala",
        "descripcion": "x",
        "params": [],
        "ejemplo": {"en": "inicio", "hacer": kwargs.get("nombre", "prueba_mala")},
    }
    base.update(kwargs)
    with pytest.raises(ErrorRegistro, match=fragmento):
        accion(**base)(lambda ctx: None)


def test_catalogo_minimo_de_g01_esta_registrado():
    import toolkit.guion.catalogo  # noqa: F401

    assert {"texto", "forma", "grupo"} <= set(registro.nombres("objeto"))
    assert {
        "mostrar",
        "quitar",
        "resaltar",
        "pulsar",
        "sonido",
        "personalizado",
        "transformar",
        "camara",
        "detener",
    } <= set(registro.nombres("accion"))


def test_manifiesto_es_serializable_y_describe_params_y_ejemplos():
    import toolkit.guion.catalogo  # noqa: F401

    datos = manifiesto()
    texto = json.dumps(datos, ensure_ascii=False)
    assert json.loads(texto) == datos
    assert set(datos) >= {"version", "objetos", "acciones", "modificadores", "claves_paso"}
    texto_def = datos["objetos"]["texto"]
    assert texto_def["ejemplo"]["tipo"] == "texto"
    params = {p["nombre"]: p for p in texto_def["params"]}
    assert params["texto"]["requerido"] is True
    assert params["zona"]["tipo"] == "zona"
    resaltar = datos["acciones"]["resaltar"]
    modo = {p["nombre"]: p for p in resaltar["params"]}["modo"]
    assert "rodear" in modo["opciones"]
    assert "en" in datos["claves_paso"] and "retraso" in datos["claves_paso"]


def test_resolver_params_rellena_defectos_sin_compartir_mutables(catalogo_aislado):
    @accion(
        "prueba_def",
        "x",
        params=[Param("lista", "lista", defecto=[]), Param("n", "numero", defecto=2)],
        ejemplo={"en": "inicio", "hacer": "prueba_def"},
    )
    def hacer(ctx, lista, n):
        return None

    a = registro.resolver_params(CATALOGO["prueba_def"], {})
    b = registro.resolver_params(CATALOGO["prueba_def"], {"n": 5})
    assert a == {"lista": [], "n": 2}
    assert b == {"lista": [], "n": 5}
    a["lista"].append(1)
    assert registro.resolver_params(CATALOGO["prueba_def"], {})["lista"] == []
