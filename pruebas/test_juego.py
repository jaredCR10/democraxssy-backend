"""Pruebas de la fase "sala" de app/juego.py (Persona 1)."""

import json
import re

import pytest

from app.juego import MAX_JUGADORES, ErrorJuego, Partida

HEX = lambda n: re.compile(rf"^[0-9a-f]{{{n}}}$")


def codigo(excinfo) -> int:
    return excinfo.value.codigo


# ---------------------------------------------------------------- crear

def test_crear_partida_con_valores_por_defecto():
    p = Partida("Ana")
    assert HEX(32).match(p.id)
    assert p.fase == "sala"
    assert p.puntos_para_ganar == 5
    assert p.anfitrion.nombre == "Ana"
    assert HEX(16).match(p.anfitrion.id)
    assert HEX(64).match(p.anfitrion.token)
    assert len(p.jugadores) == 1


def test_crear_con_puntos_y_nombre_recortado():
    p = Partida("  Ana  ", 3)
    assert p.anfitrion.nombre == "Ana"
    assert p.puntos_para_ganar == 3


@pytest.mark.parametrize("nombre", ["", "   ", "x" * 25, "Ana\nBeto", "Ana\x00", 5])
def test_nombre_invalido_da_400(nombre):
    with pytest.raises(ErrorJuego) as e:
        Partida(nombre)
    assert codigo(e) == 400


def test_nombre_de_24_caracteres_y_con_etiquetas_se_acepta():
    assert Partida("x" * 24).anfitrion.nombre == "x" * 24
    # Se guarda tal cual: el frontend lo muestra como texto plano.
    assert Partida("<svg onload=alert(1)>").anfitrion.nombre == "<svg onload=alert(1)>"


@pytest.mark.parametrize("puntos", [0, 21, -1, True, False, 2.5, "5"])
def test_puntos_invalidos_dan_400(puntos):
    with pytest.raises(ErrorJuego) as e:
        Partida("Ana", puntos)
    assert codigo(e) == 400


@pytest.mark.parametrize("puntos", [1, 20])
def test_puntos_en_los_limites(puntos):
    assert Partida("Ana", puntos).puntos_para_ganar == puntos


def test_ids_y_tokens_distintos_entre_partidas():
    a, b = Partida("Ana"), Partida("Ana")
    assert a.id != b.id
    assert a.anfitrion.token != b.anfitrion.token


# ---------------------------------------------------------------- unirse

def test_unirse_agrega_en_orden():
    p = Partida("Ana")
    beto = p.unirse("Beto")
    assert [j.nombre for j in p.jugadores] == ["Ana", "Beto"]
    assert HEX(16).match(beto.id) and HEX(64).match(beto.token)
    assert beto.token != p.anfitrion.token


@pytest.mark.parametrize("repetido", ["Ana", "ana", "ANA", "  aNa "])
def test_nombre_repetido_sin_distinguir_mayusculas_da_409(repetido):
    p = Partida("Ana")
    with pytest.raises(ErrorJuego) as e:
        p.unirse(repetido)
    assert codigo(e) == 409


def test_unirse_con_nombre_invalido_da_400():
    p = Partida("Ana")
    with pytest.raises(ErrorJuego) as e:
        p.unirse("x" * 25)
    assert codigo(e) == 400


def test_partida_llena_da_409():
    p = Partida("J0")
    for i in range(1, MAX_JUGADORES):
        p.unirse(f"J{i}")
    assert len(p.jugadores) == MAX_JUGADORES
    with pytest.raises(ErrorJuego) as e:
        p.unirse("Otro")
    assert codigo(e) == 409


def test_unirse_fuera_de_la_sala_da_409():
    p = Partida("Ana")
    p.fase = "respuestas"
    with pytest.raises(ErrorJuego) as e:
        p.unirse("Beto")
    assert codigo(e) == 409


def test_unirse_actualiza_la_actividad():
    p = Partida("Ana")
    p.ultima_actividad = 0
    p.unirse("Beto")
    assert p.ultima_actividad > 0


# ---------------------------------------------------------------- tokens

def test_jugador_por_token():
    p = Partida("Ana")
    beto = p.unirse("Beto")
    assert p.jugador_por_token(beto.token) is beto
    assert p.jugador_por_token(p.anfitrion.token) is p.anfitrion
    assert p.jugador_por_token("0" * 64) is None


def test_token_de_otra_partida_no_sirve():
    a, b = Partida("Ana"), Partida("Beto")
    assert a.jugador_por_token(b.anfitrion.token) is None


# ---------------------------------------------------------------- vista

CLAVES_VISTA = {"id", "fase", "anfitrion_id", "puntos_para_ganar", "jugadores",
                "ronda", "yo", "historial", "ganador_id"}
CLAVES_JUGADOR = {"id", "nombre", "puntos", "es_anfitrion", "es_soberano", "ya_respondio", "ya_voto"}


def test_vista_publica_de_la_sala():
    p = Partida("Ana", 7)
    p.unirse("Beto")
    v = p.vista(None)
    assert set(v) == CLAVES_VISTA
    assert v["id"] == p.id and v["fase"] == "sala"
    assert v["anfitrion_id"] == p.anfitrion.id
    assert v["puntos_para_ganar"] == 7
    assert v["ronda"] is None and v["yo"] is None
    assert v["historial"] == [] and v["ganador_id"] is None
    assert [j["nombre"] for j in v["jugadores"]] == ["Ana", "Beto"]
    for j in v["jugadores"]:
        assert set(j) == CLAVES_JUGADOR
        assert j["puntos"] == 0 and not j["es_soberano"]
        assert not j["ya_respondio"] and not j["ya_voto"]
    assert v["jugadores"][0]["es_anfitrion"] and not v["jugadores"][1]["es_anfitrion"]


def test_vista_con_jugador_incluye_yo():
    p = Partida("Ana")
    beto = p.unirse("Beto")
    yo_anfitrion = p.vista(p.anfitrion.id)["yo"]
    yo_beto = p.vista(beto.id)["yo"]
    assert set(yo_beto) == {"id", "nombre", "mano", "mi_voto", "puede_avanzar"}
    assert yo_beto["id"] == beto.id and yo_beto["nombre"] == "Beto"
    assert yo_beto["mano"] == [] and yo_beto["mi_voto"] is None
    assert yo_anfitrion["puede_avanzar"] is True
    assert yo_beto["puede_avanzar"] is False


def test_la_vista_nunca_expone_tokens_y_es_json():
    p = Partida("Ana")
    beto = p.unirse("Beto")
    for jugador_id in (None, p.anfitrion.id, beto.id):
        texto = json.dumps(p.vista(jugador_id))   # debe poder convertirse a JSON
        assert p.anfitrion.token not in texto
        assert beto.token not in texto
