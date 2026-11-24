"""Ayudantes compartidos por las pruebas de la capa HTTP (Persona 2)."""

import pytest
from fastapi.testclient import TestClient

from app.almacen import almacen
from app.main import app

NOMBRES = ["Ana", "Beto", "Caro", "Dani", "Eva", "Fede"]


@pytest.fixture(autouse=True)
def almacen_vacio():
    """Cada prueba empieza sin partidas (el almacén es global)."""
    almacen._partidas.clear()
    almacen._locks.clear()
    yield
    almacen._partidas.clear()
    almacen._locks.clear()


@pytest.fixture
def cliente():
    return TestClient(app)


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def crear_sala(cliente, n=4, puntos=5):
    """Crea una partida con n jugadores. Devuelve (partida_id, [tokens]); el 0 es el anfitrión."""
    r = cliente.post("/api/partidas", json={"nombre": NOMBRES[0], "puntos_para_ganar": puntos})
    assert r.status_code == 201, r.text
    pid, tokens = r.json()["partida_id"], [r.json()["token"]]
    for nombre in NOMBRES[1:n]:
        r = cliente.post(f"/api/partidas/{pid}/jugadores", json={"nombre": nombre})
        assert r.status_code == 201, r.text
        tokens.append(r.json()["token"])
    return pid, tokens


def crear_iniciada(cliente, n=4, puntos=5):
    pid, tokens = crear_sala(cliente, n, puntos)
    assert cliente.post(f"/api/partidas/{pid}/iniciar", headers=auth(tokens[0])).status_code == 200
    return pid, tokens


def vista(cliente, pid, token=None):
    r = cliente.get(f"/api/partidas/{pid}", headers=auth(token) if token else {})
    assert r.status_code == 200, r.text
    return r.json()


def cartas_para(cliente, pid, token):
    """Las primeras cartas de la mano, tantas como pide la carta negra."""
    v = vista(cliente, pid, token)
    elegir = v["ronda"]["carta_negra"]["elegir"]
    return [c["id"] for c in v["yo"]["mano"][:elegir]]
