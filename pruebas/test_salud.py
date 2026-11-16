from fastapi.testclient import TestClient

from app.main import app

cliente = TestClient(app)


def test_salud_responde_200_sin_cuerpo():
    r = cliente.head("/api/salud")
    assert r.status_code == 200
    assert r.content == b""


def test_ruta_inexistente_da_404_en_json():
    r = cliente.get("/api/nada")
    assert r.status_code == 404
    assert r.json() == {"error": "Ruta no encontrada."}
