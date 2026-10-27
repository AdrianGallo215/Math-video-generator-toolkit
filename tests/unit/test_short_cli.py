"""Tests del CLI ``scripts/short.py`` (sin renders reales)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from scripts import short  # noqa: E402


def test_nuevo_crea_y_no_sobrescribe(tmp_path: Path) -> None:
    carpeta, creados, existentes = short.crear_video("v99_prueba", "Prueba", base=tmp_path)
    assert sorted(creados) == ["escena.py", "guion_conceptual.md", "guion_tecnico.yaml", "video.yaml"]
    assert not existentes
    escena = carpeta / "escena.py"
    assert "escena_desde_yaml" in escena.read_text(encoding="utf-8")
    escena.write_text("# editado a mano", encoding="utf-8")
    (carpeta / "video.yaml").unlink()
    _, creados2, existentes2 = short.crear_video("v99_prueba", "Prueba", base=tmp_path)
    assert creados2 == ["video.yaml"]
    assert "escena.py" in existentes2
    assert escena.read_text(encoding="utf-8") == "# editado a mano"
    with pytest.raises(short.ErrorCLI, match="no se sobrescribió"):
        short.crear_video("v99_prueba", "Prueba", base=tmp_path)


def test_nuevo_slug_invalido(tmp_path: Path) -> None:
    with pytest.raises(short.ErrorCLI, match="slug inválido"):
        short.crear_video("Mi Video", "x", base=tmp_path)


def test_plantilla_tecnica_es_valida(tmp_path: Path) -> None:
    from toolkit.guion.validar import validar

    carpeta, _, _ = short.crear_video("v98_plantilla", "Plantilla", base=tmp_path)
    reporte = validar(carpeta / "guion_tecnico.yaml")
    assert reporte.ok, reporte.texto()


def test_validar_detecta_yaml_roto(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    roto = tmp_path / "guion_tecnico.yaml"
    roto.write_text("version: 1\nmeta: [esto, no, es, un, mapa\nsegmentos:\n", encoding="utf-8")
    codigo = short.main(["validar", str(roto), "--json"])
    datos = json.loads(capsys.readouterr().out)
    assert codigo == 1
    assert datos["ok"] is False and datos["errores"]
    assert datos["errores"][0]["mensaje"]


def test_validar_guion_inexistente(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    assert short.main(["validar", str(tmp_path / "no_existe.yaml")]) == 1
    assert "no existe" in capsys.readouterr().out


def test_validar_ejemplo_ok(capsys: pytest.CaptureFixture) -> None:
    assert short.main(["validar", str(RAIZ / "ejemplos" / "guion_minimo")]) == 0


def test_catalogo_json_valido(capsys: pytest.CaptureFixture) -> None:
    assert short.main(["catalogo", "--json"]) == 0
    datos = json.loads(capsys.readouterr().out)
    assert {"objetos", "acciones"} <= set(datos)
    assert "mostrar" in datos["acciones"]


def test_catalogo_detalle_y_desconocido(capsys: pytest.CaptureFixture) -> None:
    assert short.main(["catalogo", "mostrar"]) == 0
    assert "ejemplo" in capsys.readouterr().out
    assert short.main(["catalogo", "no_existe_xyz", "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["ok"] is False


def test_estado(tmp_path: Path) -> None:
    carpeta, _, _ = short.crear_video("v97_estado", "Estado", base=tmp_path)
    info = short.estado_de("v97_estado", base=tmp_path, salidas=tmp_path / "salidas")
    assert info["artefactos"]["guion_tecnico.yaml"] is True
    assert info["artefactos"]["qa/"] is False
    assert info["puertas"]["validado"] is True
    assert info["puertas"]["produccion"] is False
    with pytest.raises(short.ErrorCLI, match="no existe"):
        short.estado_de("nada", base=tmp_path)


def test_estado_reconoce_el_borrador_de_media(tmp_path: Path) -> None:
    """`render`/`qa` dejan el video en media/videos/escena/<alto>p<fps>/<Clase>.mp4, no en salidas/."""
    from toolkit.configuracion import PERFILES
    from toolkit.guion.esquema import cargar

    carpeta, _, _ = short.crear_video("v96_media", "Media", base=tmp_path)
    clase = cargar(carpeta / short.NOMBRE_GUION).meta.clase
    salidas, media = tmp_path / "salidas", tmp_path / "media"
    info = short.estado_de("v96_media", base=tmp_path, salidas=salidas, media=media)
    assert info["puertas"]["borrador"] is False and info["ultimo_borrador"] is None
    perfil = PERFILES["borrador"]
    video = media / "videos" / "escena" / f"{perfil.alto_px}p{perfil.fps}" / f"{clase}.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"x")
    info = short.estado_de("v96_media", base=tmp_path, salidas=salidas, media=media)
    assert info["puertas"]["borrador"] is True and info["ultimo_borrador"] == str(video)


def _video_sintetico(ruta: Path) -> None:
    """6 s a 10 fps, 90x160: movimiento 0-2 s, quieto 2-4.5 s, movimiento 4.5-6 s."""
    import av
    import numpy as np

    with av.open(str(ruta), "w") as cont:
        flujo = cont.add_stream("libx264", rate=10)
        flujo.width, flujo.height, flujo.pix_fmt = 90, 160, "yuv420p"
        flujo.options = {"crf": "10"}
        for i in range(60):
            img = np.zeros((160, 90, 3), dtype=np.uint8)
            t = i / 10
            if t < 2.0 or t >= 4.5:
                x = (i * 7) % 60
                img[40:80, x : x + 25] = 255
            else:
                img[40:80, 10:35] = 255
            for paquete in flujo.encode(av.VideoFrame.from_ndarray(img, format="rgb24")):
                cont.mux(paquete)
        for paquete in flujo.encode():
            cont.mux(paquete)


def test_qa_detecta_tramo_quieto(tmp_path: Path) -> None:
    video = tmp_path / "sintetico.mp4"
    _video_sintetico(video)
    tramos, duracion = short.detectar_tramos_quietos(video)
    assert duracion == pytest.approx(5.9, abs=0.3)
    assert len(tramos) == 1
    t = tramos[0]
    assert t["inicio"] == pytest.approx(2.0, abs=0.35)
    assert t["fin"] == pytest.approx(4.5, abs=0.35)
