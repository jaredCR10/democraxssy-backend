"""Pruebas de app/almacen.py (Persona 2): máximo de partidas, limpieza y locks."""

import asyncio
import time

import pytest

from app.almacen import Almacen
from app.juego import ErrorJuego, Partida
from pruebas.conftest import auth, crear_iniciada


def test_agregar_y_obtener():
    a = Almacen()
    p = Partida("Ana")
    a.agregar(p)
    assert a.obtener(p.id) is p
    assert a.obtener(p.id.upper()) is None   # solo 32 hex en minúscula
    assert a.obtener("no-es-un-id") is None


def test_obtener_o_404():
    with pytest.raises(ErrorJuego) as e:
        Almacen().obtener_o_404("0" * 32)
    assert e.value.codigo == 404


def test_maximo_de_partidas_da_409():
    a = Almacen(max_partidas=2)
    a.agregar(Partida("Ana"))
    a.agregar(Partida("Beto"))
    with pytest.raises(ErrorJuego) as e:
        a.agregar(Partida("Caro"))
    assert e.value.codigo == 409
    assert len(a) == 2


def test_al_llegar_al_maximo_primero_limpia_las_abandonadas():
    a = Almacen(max_partidas=1, inactividad_maxima=60)
    vieja = Partida("Ana")
    vieja.ultima_actividad = time.time() - 3600
    a.agregar(vieja)
    nueva = Partida("Beto")
    a.agregar(nueva)  # no falla: la vieja se borró
    assert a.obtener(vieja.id) is None and a.obtener(nueva.id) is nueva


def test_limpiar_borra_solo_las_inactivas():
    a = Almacen(inactividad_maxima=2 * 60 * 60)
    activa, inactiva = Partida("Ana"), Partida("Beto")
    inactiva.ultima_actividad = time.time() - 3 * 60 * 60
    a.agregar(activa)
    a.agregar(inactiva)
    assert a.limpiar() == 1
    assert a.obtener(activa.id) is activa and a.obtener(inactiva.id) is None


def test_eliminar_borra_tambien_el_lock():
    a = Almacen()
    p = Partida("Ana")
    a.agregar(p)
    a.eliminar(p.id)
    assert a.obtener(p.id) is None and p.id not in a._locks


def test_bloqueada_serializa_las_acciones_sobre_una_partida():
    a = Almacen()
    p = Partida("Ana")
    a.agregar(p)
    orden = []

    async def accion(nombre):
        async with a.bloqueada(p.id):
            orden.append(f"{nombre}-entra")
            await asyncio.sleep(0.01)  # simula una espera: nadie más debe entrar mientras tanto
            orden.append(f"{nombre}-sale")

    async def principal():
        await asyncio.gather(accion("A"), accion("B"))

    asyncio.run(principal())
    assert orden in (["A-entra", "A-sale", "B-entra", "B-sale"], ["B-entra", "B-sale", "A-entra", "A-sale"])


def test_bloqueada_da_404_si_la_eliminaron_mientras_esperaba():
    a = Almacen()
    p = Partida("Ana")
    a.agregar(p)
    resultado = {}

    async def eliminadora():
        async with a.bloqueada(p.id):
            await asyncio.sleep(0.01)
            a.eliminar(p.id)

    async def rezagada():
        await asyncio.sleep(0)  # llega cuando la otra ya tiene el lock
        try:
            async with a.bloqueada(p.id):
                resultado["entro"] = True
        except ErrorJuego as e:
            resultado["codigo"] = e.codigo

    async def principal():
        await asyncio.gather(eliminadora(), rezagada())

    asyncio.run(principal())
    assert resultado == {"codigo": 404}


def test_limpieza_no_toca_una_partida_con_el_lock_tomado():
    a = Almacen(inactividad_maxima=0)
    p = Partida("Ana")
    p.ultima_actividad = time.time() - 10
    a.agregar(p)

    async def principal():
        async with a.bloqueada(p.id):
            assert a.limpiar() == 0
        assert a.limpiar() == 1

    asyncio.run(principal())


def test_las_acciones_por_http_mantienen_viva_la_partida(cliente):
    pid, tokens = crear_iniciada(cliente)
    from app.almacen import almacen
    partida = almacen.obtener(pid)
    antes = partida.ultima_actividad
    time.sleep(0.01)
    t = tokens[1]
    v = cliente.get(f"/api/partidas/{pid}", headers=auth(t)).json()
    cartas = [c["id"] for c in v["yo"]["mano"][: v["ronda"]["carta_negra"]["elegir"]]]
    cliente.put(f"/api/partidas/{pid}/respuestas", json={"cartas": cartas}, headers=auth(t))
    assert partida.ultima_actividad > antes
