"""Pruebas de app/validacion.py (Persona 2): una por cada regla de forma del openapi.yaml.

Todas pasan por HTTP (TestClient), como llegaría una solicitud real.
"""

import pytest

from app.main import app
from app.validacion import LIMITE_CUERPO, MSG_CONSULTA, MSG_DEMASIADO_GRANDE, REGLAS, buscar_regla
from pruebas.conftest import auth, crear_iniciada, crear_sala

TOKEN_FALSO = "a" * 64
ID_FALSO = "0" * 32


def es_409(r):
    assert r.status_code == 409, r.text
    assert set(r.json()) == {"error"}
    return r.json()["error"]


# ---------------------------------------------------------------- 1. parámetros de consulta

@pytest.mark.parametrize("metodo, ruta", [
    ("HEAD", "/api/salud"),
    ("GET", f"/api/partidas/{ID_FALSO}"),
    ("POST", "/api/partidas"),
])
def test_parametros_de_consulta_dan_409(cliente, metodo, ruta):
    r = cliente.request(metodo, ruta + "?x=1")
    assert r.status_code == 409
    if metodo != "HEAD":
        assert r.json() == {"error": MSG_CONSULTA}


def test_consulta_se_revisa_antes_que_la_partida(cliente):
    # La partida no existe, pero la forma se revisa primero: 409, no 404.
    es_409(cliente.get(f"/api/partidas/{ID_FALSO}?a=b"))


# ---------------------------------------------------------------- 2. override de método

@pytest.mark.parametrize("cabecera", ["X-HTTP-Method-Override", "X-HTTP-Method", "X-Method-Override"])
def test_cabeceras_de_override_dan_409(cliente, cabecera):
    es_409(cliente.post("/api/partidas", json={"nombre": "Ana"}, headers={cabecera: "DELETE"}))


# ---------------------------------------------------------------- 3. Authorization

@pytest.mark.parametrize("valor", [
    "Bearer " + "A" * 64,          # mayúsculas
    "Bearer " + "a" * 63,          # corto
    "Bearer " + "a" * 65,          # largo
    "bearer " + "a" * 64,          # esquema en minúscula
    "Basic " + "a" * 64,
    "Bearer  " + "a" * 64,         # dos espacios
    "a" * 64,                      # sin esquema
    "Bearer " + "g" * 64,          # no hexadecimal
])
def test_authorization_mal_formada_da_409(cliente, valor):
    pid, _ = crear_sala(cliente)
    es_409(cliente.get(f"/api/partidas/{pid}", headers={"Authorization": valor}))


def test_authorization_repetida_da_409(cliente):
    pid, tokens = crear_sala(cliente)
    r = cliente.get(f"/api/partidas/{pid}", headers=[("Authorization", f"Bearer {tokens[0]}")] * 2)
    es_409(r)


@pytest.mark.parametrize("metodo, ruta, cuerpo", [
    ("HEAD", "/api/salud", None),
    ("POST", "/api/partidas", {"nombre": "Ana"}),
    ("POST", f"/api/partidas/{ID_FALSO}/jugadores", {"nombre": "Beto"}),
])
def test_authorization_en_rutas_publicas_da_409(cliente, metodo, ruta, cuerpo):
    r = cliente.request(metodo, ruta, json=cuerpo, headers=auth(TOKEN_FALSO))
    assert r.status_code == 409


def test_authorization_bien_formada_pero_ajena_da_401(cliente):
    pid, _ = crear_sala(cliente)
    r = cliente.get(f"/api/partidas/{pid}", headers=auth(TOKEN_FALSO))
    assert r.status_code == 401
    assert r.json() == {"error": "Token ausente o inválido para esta partida."}


def test_ruta_protegida_sin_token_da_401(cliente):
    pid, _ = crear_sala(cliente)
    assert cliente.post(f"/api/partidas/{pid}/iniciar").status_code == 401
    assert cliente.delete(f"/api/partidas/{pid}").status_code == 401


# ---------------------------------------------------------------- 4. cuerpo y Content-Type

@pytest.mark.parametrize("metodo", ["GET", "DELETE"])
def test_get_y_delete_no_admiten_cuerpo(cliente, metodo):
    pid, tokens = crear_sala(cliente)
    r = cliente.request(metodo, f"/api/partidas/{pid}", content=b"{}", headers=auth(tokens[0]))
    es_409(r)


@pytest.mark.parametrize("metodo", ["GET", "DELETE"])
def test_get_y_delete_no_admiten_content_type(cliente, metodo):
    pid, tokens = crear_sala(cliente)
    r = cliente.request(metodo, f"/api/partidas/{pid}",
                        headers={**auth(tokens[0]), "Content-Type": "application/json"})
    es_409(r)


def test_head_no_admite_cuerpo(cliente):
    r = cliente.request("HEAD", "/api/salud", content=b"x", headers={"Content-Type": "application/json"})
    assert r.status_code == 409


@pytest.mark.parametrize("tipo", [
    "application/json",
    "application/json; charset=utf-8",
    "application/json;charset=UTF-8",
    "Application/JSON",
])
def test_content_type_json_aceptado(cliente, tipo):
    r = cliente.post("/api/partidas", content=b'{"nombre":"Ana"}', headers={"Content-Type": tipo})
    assert r.status_code == 201


@pytest.mark.parametrize("tipo", [
    "text/plain",
    "application/x-www-form-urlencoded",
    "application/json; charset=latin-1",
    "application/jsonx",
])
def test_content_type_incorrecto_da_409(cliente, tipo):
    es_409(cliente.post("/api/partidas", content=b'{"nombre":"Ana"}', headers={"Content-Type": tipo}))


def test_cuerpo_sin_content_type_da_409(cliente):
    es_409(cliente.post("/api/partidas", content=b'{"nombre":"Ana"}'))


def test_content_type_repetido_da_409(cliente):
    r = cliente.post("/api/partidas", content=b'{"nombre":"Ana"}',
                     headers=[("Content-Type", "application/json")] * 2)
    es_409(r)


def test_cuerpo_de_mas_de_4kb_da_413(cliente):
    relleno = "x" * LIMITE_CUERPO
    r = cliente.post("/api/partidas", json={"nombre": relleno})
    assert r.status_code == 413
    assert r.json() == {"error": MSG_DEMASIADO_GRANDE}


def test_cuerpo_de_mas_de_4kb_sin_content_length_da_413(cliente):
    # Transferencia por partes (chunked): no hay Content-Length y se corta al pasar el límite.
    def partes():
        yield b'{"nombre":"'
        for _ in range(10):
            yield b"x" * 1000
        yield b'"}'
    r = cliente.post("/api/partidas", content=partes(), headers={"Content-Type": "application/json"})
    assert r.status_code == 413


def test_cuerpo_justo_de_4kb_no_es_413(cliente):
    base = b'{"nombre":""}'
    cuerpo = b'{"nombre":"' + b"x" * (LIMITE_CUERPO - len(base)) + b'"}'
    assert len(cuerpo) == LIMITE_CUERPO
    r = cliente.post("/api/partidas", content=cuerpo, headers={"Content-Type": "application/json"})
    assert r.status_code == 400  # llegó a la lógica: el nombre es demasiado largo (valor, no forma)


# ---------------------------------------------------------------- 5. JSON

@pytest.mark.parametrize("cuerpo", [
    b"{",                       # ilegible
    b"[]",                      # no es objeto
    b"5",
    b'"Ana"',
    b"null",
    b'{"nombre": NaN}',
    b"\xff\xfe",                # no es UTF-8
])
def test_json_invalido_o_que_no_es_objeto_da_409(cliente, cuerpo):
    es_409(cliente.post("/api/partidas", content=cuerpo, headers={"Content-Type": "application/json"}))


def test_claves_repetidas_dan_409(cliente):
    cuerpo = b'{"nombre": "Ana", "nombre": "Beto"}'
    mensaje = es_409(cliente.post("/api/partidas", content=cuerpo, headers={"Content-Type": "application/json"}))
    assert "repetido" in mensaje


def test_campo_desconocido_da_409(cliente):
    mensaje = es_409(cliente.post("/api/partidas", json={"nombre": "Ana", "admin": True}))
    assert "`admin`" in mensaje


def test_campo_obligatorio_faltante_da_409(cliente):
    es_409(cliente.post("/api/partidas", json={"puntos_para_ganar": 5}))


def test_cuerpo_obligatorio_vacio_da_409(cliente):
    es_409(cliente.post("/api/partidas", headers={"Content-Type": "application/json"}))


@pytest.mark.parametrize("puntos", [True, False, "5", 2.5, 5.0, [5], {"n": 5}])
def test_puntos_de_tipo_incorrecto_dan_409(cliente, puntos):
    es_409(cliente.post("/api/partidas", json={"nombre": "Ana", "puntos_para_ganar": puntos}))


@pytest.mark.parametrize("puntos, esperado", [(None, 5), (1, 1), (20, 20)])
def test_puntos_validos_o_null(cliente, puntos, esperado):
    r = cliente.post("/api/partidas", json={"nombre": "Ana", "puntos_para_ganar": puntos})
    assert r.status_code == 201
    assert r.json()["partida"]["puntos_para_ganar"] == esperado


@pytest.mark.parametrize("puntos", [0, 21, -3])
def test_puntos_fuera_de_rango_dan_400_desde_la_logica(cliente, puntos):
    assert cliente.post("/api/partidas", json={"nombre": "Ana", "puntos_para_ganar": puntos}).status_code == 400


@pytest.mark.parametrize("nombre", [5, None, True, ["Ana"]])
def test_nombre_de_tipo_incorrecto_da_409(cliente, nombre):
    es_409(cliente.post("/api/partidas", json={"nombre": nombre}))


@pytest.mark.parametrize("nombre", ["", "   ", "x" * 25, "a\x07b"])
def test_nombre_con_valor_invalido_da_400(cliente, nombre):
    assert cliente.post("/api/partidas", json={"nombre": nombre}).status_code == 400


@pytest.mark.parametrize("cartas", [[-1], [True], [1.5], ["3"], 3, None, [[1]]])
def test_cartas_de_tipo_incorrecto_dan_409(cliente, cartas):
    pid, tokens = crear_iniciada(cliente)
    es_409(cliente.put(f"/api/partidas/{pid}/respuestas", json={"cartas": cartas}, headers=auth(tokens[1])))


@pytest.mark.parametrize("cartas", [[], [0, 1, 2], [7, 7]])
def test_cantidad_o_repetidas_dan_400_no_409(cliente, cartas):
    pid, tokens = crear_iniciada(cliente)
    r = cliente.put(f"/api/partidas/{pid}/respuestas", json={"cartas": cartas}, headers=auth(tokens[1]))
    assert r.status_code == 400, r.text


@pytest.mark.parametrize("respuesta_id", [5, None, True, ["abc"]])
def test_respuesta_id_de_tipo_incorrecto_da_409(cliente, respuesta_id):
    pid, tokens = crear_iniciada(cliente)
    es_409(cliente.put(f"/api/partidas/{pid}/votos", json={"respuesta_id": respuesta_id}, headers=auth(tokens[1])))


@pytest.mark.parametrize("ruta", ["iniciar", "avanzar"])
def test_iniciar_y_avanzar_rechazan_cualquier_campo(cliente, ruta):
    pid, tokens = crear_sala(cliente)
    es_409(cliente.post(f"/api/partidas/{pid}/{ruta}", json={"x": 1}, headers=auth(tokens[0])))


@pytest.mark.parametrize("cuerpo", [None, {}])
def test_iniciar_acepta_sin_cuerpo_o_objeto_vacio(cliente, cuerpo):
    pid, tokens = crear_sala(cliente)
    r = cliente.post(f"/api/partidas/{pid}/iniciar", json=cuerpo, headers=auth(tokens[0]))
    assert r.status_code == 200, r.text


# ---------------------------------------------------------------- CORS y cabeceras de respuesta

@pytest.mark.parametrize("metodo, ruta", [
    ("HEAD", "/api/salud"),                 # éxito
    ("GET", "/api/nada"),                   # 404 de ruta
    ("POST", "/api/partidas?x=1"),          # 409 del middleware
    ("GET", f"/api/partidas/{ID_FALSO}"),   # 404 de la partida
])
def test_toda_respuesta_lleva_cors_y_cabeceras_de_seguridad(cliente, metodo, ruta):
    r = cliente.request(metodo, ruta)  # sin cabecera Origin, como curl
    assert r.headers["access-control-allow-origin"] == "*"
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["x-content-type-options"] == "nosniff"


def test_verificacion_previa_no_pasa_por_la_validacion(cliente):
    r = cliente.options(
        f"/api/partidas/{ID_FALSO}/respuestas",
        headers={
            "Origin": "https://democraxssy-anj.duckdns.org",
            "Access-Control-Request-Method": "PUT",
            "Access-Control-Request-Headers": "authorization, content-type",
        },
    )
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "*"
    assert "PUT" in r.headers["access-control-allow-methods"]


def test_errores_son_json_utf8(cliente):
    r = cliente.post("/api/partidas", json={"nombre": "Ana", "admin": 1})
    assert r.headers["content-type"] == "application/json; charset=utf-8"


# ---------------------------------------------------------------- tabla de reglas

def test_cada_ruta_de_la_api_tiene_su_regla_de_validacion():
    """Si alguien agrega una ruta a main.py, esta prueba obliga a declarar su validación."""
    rutas = set()
    for ruta in app.routes:
        for metodo in getattr(ruta, "methods", ()):
            rutas.add((metodo, ruta.path.replace("{partida_id}", ID_FALSO)))
    for metodo, ruta in rutas:
        assert buscar_regla(metodo, ruta) is not None, f"Falta la regla de validación de {metodo} {ruta}"
    assert len(rutas) == len(REGLAS)
