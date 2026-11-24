"""Pruebas de las rutas de app/main.py (Persona 2): códigos de éxito, 404, 401 y una partida
completa por HTTP, como la jugaría el frontend."""

import re

import pytest

from pruebas.conftest import auth, cartas_para, crear_iniciada, crear_sala, vista

HEX = lambda n: re.compile(rf"^[0-9a-f]{{{n}}}$")  # noqa: E731


# ---------------------------------------------------------------- crear y unirse

def test_crear_partida_devuelve_sesion(cliente):
    r = cliente.post("/api/partidas", json={"nombre": "  Ana  "})
    assert r.status_code == 201
    s = r.json()
    assert set(s) == {"partida_id", "jugador_id", "token", "partida"}
    assert HEX(32).match(s["partida_id"]) and HEX(16).match(s["jugador_id"]) and HEX(64).match(s["token"])
    v = s["partida"]
    assert v["fase"] == "sala" and v["anfitrion_id"] == s["jugador_id"] and v["puntos_para_ganar"] == 5
    assert v["yo"]["nombre"] == "Ana"  # sin los espacios
    assert v["ronda"] is None and v["ganador_id"] is None


def test_unirse_devuelve_sesion_propia(cliente):
    pid, tokens = crear_sala(cliente, n=1)
    r = cliente.post(f"/api/partidas/{pid}/jugadores", json={"nombre": "Beto"})
    assert r.status_code == 201
    assert r.json()["partida"]["yo"]["nombre"] == "Beto"
    assert r.json()["token"] != tokens[0]


def test_nombre_repetido_sin_distinguir_mayusculas_da_409(cliente):
    pid, _ = crear_sala(cliente, n=1)
    assert cliente.post(f"/api/partidas/{pid}/jugadores", json={"nombre": "ANA"}).status_code == 409


def test_unirse_a_partida_iniciada_da_409(cliente):
    pid, _ = crear_iniciada(cliente)
    assert cliente.post(f"/api/partidas/{pid}/jugadores", json={"nombre": "Zoe"}).status_code == 409


def test_nombre_con_html_se_guarda_tal_cual(cliente):
    # Es parte del juego: el backend lo devuelve como texto y el frontend lo muestra como texto.
    r = cliente.post("/api/partidas", json={"nombre": "<svg onload=alert(1)>"})
    assert r.json()["partida"]["yo"]["nombre"] == "<svg onload=alert(1)>"


# ---------------------------------------------------------------- 404

@pytest.mark.parametrize("pid", [
    "0" * 32,                                    # bien formado pero no existe
    "A" * 32,                                    # mayúsculas
    "abc",                                       # corto
    "g" * 32,                                    # no hexadecimal
])
def test_partida_inexistente_o_id_invalido_da_404(cliente, pid):
    r = cliente.get(f"/api/partidas/{pid}")
    assert r.status_code == 404
    assert r.json() == {"error": "Partida no encontrada."}


def test_id_en_mayusculas_de_una_partida_que_existe_da_404(cliente):
    pid, _ = crear_sala(cliente)
    assert cliente.get(f"/api/partidas/{pid.upper()}").status_code == 404


@pytest.mark.parametrize("metodo, ruta", [
    ("GET", "/api/nada"),
    ("GET", "/api/salud"),           # la ruta existe, pero solo con HEAD
    ("POST", "/api/salud"),
    ("PATCH", "/api/partidas"),
    ("GET", "/api/partidas"),
    ("GET", "/api/partidas/"),
    ("GET", "/"),
])
def test_rutas_o_metodos_inexistentes_dan_404(cliente, metodo, ruta):
    r = cliente.request(metodo, ruta)
    assert r.status_code == 404
    assert r.json() == {"error": "Ruta no encontrada."}


def test_404_de_partida_antes_que_401(cliente):
    assert cliente.post(f"/api/partidas/{'0' * 32}/iniciar").status_code == 404


# ---------------------------------------------------------------- vista pública y privada

def test_get_sin_token_da_vista_publica(cliente):
    pid, _ = crear_iniciada(cliente)
    v = vista(cliente, pid)
    assert v["yo"] is None


def test_get_con_token_incluye_mano(cliente):
    pid, tokens = crear_iniciada(cliente)
    v = vista(cliente, pid, tokens[1])
    assert len(v["yo"]["mano"]) == 7


def test_token_de_otra_partida_da_401(cliente):
    pid1, _ = crear_sala(cliente)
    _, tokens2 = crear_sala(cliente)
    assert cliente.get(f"/api/partidas/{pid1}", headers=auth(tokens2[0])).status_code == 401


def test_la_respuesta_nunca_incluye_tokens_ajenos(cliente):
    pid, tokens = crear_iniciada(cliente)
    texto = cliente.get(f"/api/partidas/{pid}", headers=auth(tokens[0])).text
    for t in tokens:
        assert t not in texto


# ---------------------------------------------------------------- errores de la lógica pasan tal cual

def test_errores_de_la_logica_llegan_con_su_codigo(cliente):
    pid, tokens = crear_sala(cliente, n=3)
    assert cliente.post(f"/api/partidas/{pid}/iniciar", headers=auth(tokens[1])).status_code == 403
    assert cliente.post(f"/api/partidas/{pid}/iniciar", headers=auth(tokens[0])).status_code == 409  # 3 jugadores
    r = cliente.put(f"/api/partidas/{pid}/votos", json={"respuesta_id": "XYZ"}, headers=auth(tokens[1]))
    assert r.status_code == 409  # fuera de fase


def test_respuesta_id_que_no_existe_da_404(cliente):
    pid, tokens = crear_iniciada(cliente)
    for t in tokens[1:]:
        cliente.put(f"/api/partidas/{pid}/respuestas", json={"cartas": cartas_para(cliente, pid, t)}, headers=auth(t))
    r = cliente.put(f"/api/partidas/{pid}/votos", json={"respuesta_id": "XYZ"}, headers=auth(tokens[1]))
    assert r.status_code == 404


def test_eliminar_antes_de_terminar_da_409_y_no_anfitrion_403(cliente):
    pid, tokens = crear_iniciada(cliente)
    assert cliente.delete(f"/api/partidas/{pid}", headers=auth(tokens[1])).status_code == 403
    assert cliente.delete(f"/api/partidas/{pid}", headers=auth(tokens[0])).status_code == 409


# ---------------------------------------------------------------- partida completa

def jugar_ronda(cliente, pid, tokens):
    """Todos responden y votan por la primera respuesta; el soberano la elige. Devuelve la vista."""
    v = vista(cliente, pid, tokens[0])
    soberano = v["ronda"]["soberano_id"]
    ids = {vista(cliente, pid, t)["yo"]["id"]: t for t in tokens}
    votantes = [t for jid, t in ids.items() if jid != soberano]
    for t in votantes:
        r = cliente.put(f"/api/partidas/{pid}/respuestas", json={"cartas": cartas_para(cliente, pid, t)},
                        headers=auth(t))
        assert r.status_code == 200, r.text
    assert vista(cliente, pid)["fase"] == "votacion"
    rid = vista(cliente, pid, votantes[0])["ronda"]["respuestas"][0]["id"]
    for t in votantes:
        assert cliente.put(f"/api/partidas/{pid}/votos", json={"respuesta_id": rid}, headers=auth(t)).status_code == 200
    assert vista(cliente, pid)["fase"] == "decision"
    r = cliente.post(f"/api/partidas/{pid}/decision", json={"respuesta_id": rid}, headers=auth(ids[soberano]))
    assert r.status_code == 200, r.text
    return r.json()


def test_partida_completa_por_http(cliente):
    pid, tokens = crear_iniciada(cliente, n=4, puntos=2)
    rondas = 0
    while True:
        v = jugar_ronda(cliente, pid, tokens)
        rondas += 1
        assert v["historial"][-1]["respeto_al_pueblo"] is True
        if v["fase"] == "terminada":
            break
        assert v["fase"] == "resultado"
        r = cliente.post(f"/api/partidas/{pid}/avanzar", headers=auth(tokens[0]))
        assert r.status_code == 200 and r.json()["fase"] == "respuestas"
        assert rondas < 20
    assert v["ganador_id"] is not None
    assert cliente.post(f"/api/partidas/{pid}/avanzar", headers=auth(tokens[0])).status_code == 409
    r = cliente.delete(f"/api/partidas/{pid}", headers=auth(tokens[0]))
    assert r.status_code == 204 and r.content == b""
    assert cliente.get(f"/api/partidas/{pid}").status_code == 404


def test_avanzar_abre_votacion_y_cierra_votacion(cliente):
    pid, tokens = crear_iniciada(cliente, n=6)
    for t in tokens[1:3]:
        cliente.put(f"/api/partidas/{pid}/respuestas", json={"cartas": cartas_para(cliente, pid, t)}, headers=auth(t))
    assert cliente.post(f"/api/partidas/{pid}/avanzar", headers=auth(tokens[0])).json()["fase"] == "votacion"
    assert cliente.post(f"/api/partidas/{pid}/avanzar", headers=auth(tokens[0])).json()["fase"] == "decision"
