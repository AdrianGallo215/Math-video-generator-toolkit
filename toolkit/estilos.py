"""
Módulo puramente declarativo. Contiene constantes de diseño visual
(paleta de colores, tipografía, trazos, opacidades y tiempos de animación).
Sin dependencias complejas para evitar cargas lentas.
"""

# Paleta base (hex exactos de la guía de estilo 3B1B §3)
AZUL = "#58C4DD"
AMARILLO = "#F7D96F"
VERDE = "#83C167"
ROJO = "#FC6255"
NARANJA = "#F0AC5F"
MORADO = "#9A72AC"
TURQUESA = "#5CD0B3"
GRIS = "#BBBBBB"
GRIS_OSCURO = "#444444"
BLANCO = "#FFFFFF"
FONDO = "#0E0E10"

# Paleta para regiones/categorías; orden fijo (determinismo visual).
PALETA_SECUENCIAL = [AZUL, VERDE, AMARILLO, NARANJA, ROJO, MORADO, TURQUESA]

COLORES_MARCA = {
    "PRIMARIO": AZUL,
    "SECUNDARIO": ROJO,
    "TEXTO_PRINCIPAL": BLANCO,
    "TEXTO_SECUNDARIO": GRIS,
    "RESALTE": AMARILLO,
    "GUIA_ERROR": "#FF0000",
    "EXITO": VERDE,
    "AUXILIAR": MORADO,
    "VECTOR": TURQUESA,
}

# Color semántico: token LaTeX exacto -> color. Solo símbolos de UNA letra o
# comandos completos (empiezan por "\").
COLOR_SEMANTICO = {
    "x": AZUL,
    "n": AZUL,
    "y": VERDE,
    "z": MORADO,
    "t": TURQUESA,
    "k": NARANJA,
    r"\theta": AMARILLO,
    r"\alpha": AMARILLO,
    "v": TURQUESA,
    "g": ROJO,
}
MAPA_COLORES_MATEMATICOS = COLOR_SEMANTICO  # alias de compatibilidad

# Tipografía (tamaños base)
FUENTE_TITULO = 68
FUENTE_SUBTITULO = 56
FUENTE_CUERPO = 48
FUENTE_MATEMATICA = 56
FUENTE_ETIQUETA = 40
FUENTE_MINIMA = 36
FUENTE_SUBTITULOS = 46

# Grosores de geometría
GROSOR_LINEA_FINA = 3
GROSOR_LINEA_MEDIA = 5
GROSOR_LINEA_GRUESA = 8

# Opacidades
OPACIDAD_RELLENO = 0.65
OPACIDAD_ATENUADO = 0.3

# Tiempos de animación (segundos)
TIEMPO_CREAR = 1.0
TIEMPO_TRANSFORMAR = 1.2
TIEMPO_ENFASIS = 0.8
TIEMPO_TRANSICION = 0.4
PAUSA_CORTA = 0.3
