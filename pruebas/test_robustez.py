"""Pruebas de robustez de la capa HTTP (Persona 2): errores inesperados, acciones simultáneas,
limpieza al arrancar y casos de cuerpo que un cliente real puede mandar."""

import asyncio
import time

import httpx
from fastapi.testclient import TestClient

from app import main
from app.almacen import almacen
from app.juego import Partida
from pruebas.conftest import auth, cartas_para, crear_iniciada, crear_sala, vista


def test_error_inesperado_da_500_en_json_con_cabeceras(cliente, monkeypatch):
    pid, _ = crear_sala(cliente)

    def falla(self, jugador_id):
        raise RuntimeError("detalle interno que no debe verse")

    monkeypatch.setattr(Partida, "vista", falla)
    r = TestClient(main.app, raise_server_exceptions=False).get(f"/api/partidas/{pid}")
    assert r.status_code == 500
    assert r.json() == {"error": "Error interno del servidor."}
    assert "detalle interno" not in r.text
    assert r.headers["access-control-allow-origin"] == "*"
    assert r.headers["content-type"] == "application/json; charset=utf-8"


def test_respuestas_simultaneas_no_dejan_la_partida_inconsistente(cliente):
    """Los 3 votantes responden al mismo tiempo: las 3 se guardan y la partida pasa sola a votación."""
    pid, tokens = crear_iniciada(cliente)
    cuerpos = {t: {"cartas": cartas_para(cliente, pid, t)} for t in tokens[1:]}

    async def todos_a_la_vez():
        transporte = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(transport=transporte, base_url="http://prueba") as c:
            return await asyncio.gather(*(
                c.put(f"/api/partidas/{pid}/respuestas", json=cuerpo, headers=auth(t))
                for t, cuerpo in cuerpos.items()
            ))

    respuestas = asyncio.run(todos_a_la_vez())
    assert [r.status_code for r in respuestas] == [200, 200, 200]
    v = vista(cliente, pid)
    assert v["fase"] == "votacion" and len(v["ronda"]["respuestas"]) == 3


def test_union_simultanea_con_el_mismo_nombre_solo_entra_uno(cliente):
    pid, _ = crear_sala(cliente, n=1)

    async def dos_a_la_vez():
        transporte = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(transport=transporte, base_url="http://prueba") as c:
            return await asyncio.gather(*(
                c.post(f"/api/partidas/{pid}/jugadores", json={"nombre": "Beto"}) for _ in range(2)
            ))

    codigos = sorted(r.status_code for r in asyncio.run(dos_a_la_vez()))
    assert codigos == [201, 409]
    assert len(vista(cliente, pid)["jugadores"]) == 2


def test_la_consulta_periodica_mantiene_viva_la_partida(cliente):
    pid, _ = crear_sala(cliente)
    partida = almacen.obtener(pid)
    partida.ultima_actividad = time.time() - 3600
    vista(cliente, pid)  # GET sin token, como el espectador
    assert time.time() - partida.ultima_actividad < 5


def test_la_limpieza_periodica_arranca_y_se_detiene_con_la_app():
    with TestClient(main.app) as c:  # el "with" ejecuta el ciclo de vida (lifespan)
        assert c.head("/api/salud").status_code == 200
        tareas = [t for t in asyncio.all_tasks(c.portal.call(asyncio.get_running_loop))
                  if "limpiar_periodicamente" in repr(t.get_coro())]
        assert len(tareas) == 1


def test_content_length_mayor_al_limite_da_413_sin_leer_el_cuerpo(cliente):
    r = cliente.post("/api/partidas", content=b'{"nombre":"Ana"}',
                     headers={"Content-Type": "application/json", "Content-Length": "999999"})
    assert r.status_code == 413


def test_content_length_cero_en_get_se_acepta(cliente):
    pid, _ = crear_sala(cliente)
    assert cliente.get(f"/api/partidas/{pid}", headers={"Content-Length": "0"}).status_code == 200


def test_json_con_miles_de_niveles_da_409_y_no_tumba_el_servidor(cliente):
    cuerpo = b"[" * 2000 + b"]" * 2000
    r = cliente.post("/api/partidas", content=cuerpo, headers={"Content-Type": "application/json"})
    assert r.status_code == 409
    assert cliente.head("/api/salud").status_code == 200


def test_bom_utf8_da_409(cliente):
    r = cliente.post("/api/partidas", content=b'\xef\xbb\xbf{"nombre":"Ana"}',
                     headers={"Content-Type": "application/json"})
    assert r.status_code == 409


def test_nombres_con_tildes_y_emoji_llegan_intactos(cliente):
    r = cliente.post("/api/partidas", json={"nombre": "Doña Chepa 🗳️"})
    assert r.status_code == 201
    assert r.json()["partida"]["yo"]["nombre"] == "Doña Chepa 🗳️"
