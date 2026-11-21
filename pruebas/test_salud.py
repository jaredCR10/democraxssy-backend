from fastapi.testclient import TestClient

from app.main import app

cliente = TestClient(app)


def test_salud_responde_200_sin_cuerpo():
    r = cliente.head("/api/salud")
    assert r.status_code == 200
    assert r.content == b""


def test_cors_en_respuestas():
    r = cliente.head("/api/salud", headers={"Origin": "https://democraxssy-anj.duckdns.org"})
    assert r.headers["access-control-allow-origin"] == "*"


def test_cors_verificacion_previa():
    r = cliente.options(
        "/api/partidas",
        headers={
            "Origin": "https://democraxssy-anj.duckdns.org",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "*"
    assert "POST" in r.headers["access-control-allow-methods"]


def test_ruta_inexistente_da_404_en_json():
    r = cliente.get("/api/nada")
    assert r.status_code == 404
    assert r.json() == {"error": "Ruta no encontrada."}
