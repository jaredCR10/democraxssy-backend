"""Pruebas de las rondas de app/juego.py (Persona 1): iniciar, responder, votar,
decidir, avanzar, eliminar y la vista de la ronda."""

import json
import re

import pytest

from app.juego import ErrorJuego, Partida, armar_frase

HEX12 = re.compile(r"^[0-9a-f]{12}$")


# ---------------------------------------------------------------- ayudantes

def partida(n=4, puntos=5):
    """Partida en sala con n jugadores: J0 (anfitrión), J1, J2…"""
    p = Partida("J0", puntos)
    for i in range(1, n):
        p.unirse(f"J{i}")
    return p


def iniciada(n=4, puntos=5):
    p = partida(n, puntos)
    p.iniciar(p.anfitrion.id)
    return p


def soberano(p):
    return next(j for j in p.jugadores if j.id == p.ronda.soberano_id)


def votantes(p):
    return [j for j in p.jugadores if j.id != p.ronda.soberano_id]


def responder_todos(p, cuantos=None):
    elegir = p.ronda.carta_negra["elegir"]
    for j in votantes(p)[:cuantos]:
        p.responder(j.id, j.mano[:elegir])


def votar_todos(p, respuesta_id=None):
    for j in votantes(p):
        p.votar(j.id, respuesta_id or p.ronda.orden[0].id)


def ids_respuestas(p, jugador_id=None):
    return [r["id"] for r in p.vista(jugador_id)["ronda"]["respuestas"]]


def codigo(fn, *args):
    with pytest.raises(ErrorJuego) as e:
        fn(*args)
    return e.value.codigo


# ---------------------------------------------------------------- iniciar

def test_iniciar_reparte_7_cartas_y_el_anfitrion_es_soberano():
    p = iniciada()
    assert p.fase == "respuestas"
    assert p.ronda.numero == 1
    assert p.ronda.soberano_id == p.anfitrion.id
    assert all(len(j.mano) == 7 for j in p.jugadores)
    todas = [c for j in p.jugadores for c in j.mano]
    assert len(set(todas)) == len(todas)              # nadie comparte cartas


@pytest.mark.parametrize("n", [1, 3, 5])
def test_iniciar_con_pocos_o_impares_da_409(n):
    p = partida(n)
    assert codigo(p.iniciar, p.anfitrion.id) == 409


def test_iniciar_con_22_jugadores():
    p = iniciada(22)
    assert all(len(j.mano) == 7 for j in p.jugadores)


def test_solo_el_anfitrion_inicia():
    p = partida()
    assert codigo(p.iniciar, p.jugadores[1].id) == 403


def test_iniciar_dos_veces_da_409():
    p = iniciada()
    assert codigo(p.iniciar, p.anfitrion.id) == 409


# ---------------------------------------------------------------- responder

def test_responder_quita_las_cartas_de_la_mano():
    p = iniciada()
    j = votantes(p)[0]
    elegidas = j.mano[: p.ronda.carta_negra["elegir"]]
    p.responder(j.id, elegidas)
    assert all(c not in j.mano for c in elegidas)
    assert len(j.mano) == 7 - len(elegidas)
    assert p.fase == "respuestas"


def test_cuando_todos_responden_pasa_sola_a_votacion():
    p = iniciada()
    responder_todos(p)
    assert p.fase == "votacion"
    assert len(p.ronda.orden) == 3


def test_el_soberano_no_responde():
    p = iniciada()
    s = soberano(p)
    assert codigo(p.responder, s.id, s.mano[:1]) == 403


def test_no_se_responde_dos_veces():
    p = iniciada()
    j = votantes(p)[0]
    elegir = p.ronda.carta_negra["elegir"]
    p.responder(j.id, j.mano[:elegir])
    assert codigo(p.responder, j.id, j.mano[:elegir]) == 409


def test_cartas_invalidas_dan_400():
    p = iniciada()
    j = votantes(p)[0]
    elegir = p.ronda.carta_negra["elegir"]
    ajena = votantes(p)[1].mano[0]
    assert codigo(p.responder, j.id, j.mano[: elegir + 1]) == 400        # cantidad incorrecta
    assert codigo(p.responder, j.id, [ajena] * elegir) == 400            # carta de otro (o repetida)
    assert codigo(p.responder, j.id, [True] * elegir) == 400             # booleanos no son cartas
    if elegir == 2:
        assert codigo(p.responder, j.id, [j.mano[0], j.mano[0]]) == 400  # repetida


def test_responder_fuera_de_fase_da_409():
    p = partida()
    assert codigo(p.responder, p.jugadores[1].id, [0]) == 409


# ---------------------------------------------------------------- votar

def test_votacion_y_paso_automatico_a_decision():
    p = iniciada()
    responder_todos(p)
    rid = p.ronda.orden[0].id
    votar_todos(p, rid)
    assert p.fase == "decision"
    assert p.ronda.favoritas == [rid]


def test_se_puede_votar_por_la_propia_respuesta():
    p = iniciada()
    responder_todos(p)
    j = votantes(p)[0]
    propia = p.ronda.respuestas[j.id].id
    p.votar(j.id, propia)
    assert p.vista(j.id)["yo"]["mi_voto"] == propia


def test_el_soberano_no_vota_y_nadie_vota_dos_veces():
    p = iniciada()
    responder_todos(p)
    rid = p.ronda.orden[0].id
    assert codigo(p.votar, soberano(p).id, rid) == 403
    j = votantes(p)[0]
    p.votar(j.id, rid)
    assert codigo(p.votar, j.id, rid) == 409


def test_votar_respuesta_inexistente_da_404():
    p = iniciada()
    responder_todos(p)
    assert codigo(p.votar, votantes(p)[0].id, "000000000000") == 404


def test_votar_fuera_de_fase_da_409_antes_que_403():
    # Igual que el servidor del profesor: el soberano votando fuera de fase recibe 409.
    p = iniciada()
    assert codigo(p.votar, soberano(p).id, "000000000000") == 409


def test_empate_en_favoritas():
    p = iniciada(6)
    responder_todos(p)
    a, b = p.ronda.orden[0].id, p.ronda.orden[1].id
    vs = votantes(p)
    for j, rid in zip(vs, [a, a, b, b]):
        p.votar(j.id, rid)
    p.avanzar(p.anfitrion.id)                       # cierra la votación aunque falte un voto
    assert p.fase == "decision"
    assert sorted(p.ronda.favoritas) == sorted([a, b])


# ---------------------------------------------------------------- decidir

def test_decidir_da_punto_y_registra_historial():
    p = iniciada()
    responder_todos(p)
    rid = p.ronda.orden[0].id
    votar_todos(p, rid)
    autor = next(j for j in p.jugadores if p.ronda.respuestas.get(j.id) and p.ronda.respuestas[j.id].id == rid)
    p.decidir(soberano(p).id, rid)
    assert p.fase == "resultado"
    assert autor.puntos == 1
    h = p.historial[-1]
    assert h["numero"] == 1 and h["ganador_id"] == autor.id
    assert h["soberano_id"] == p.anfitrion.id
    assert h["respeto_al_pueblo"] is True
    assert "____" not in h["frase"]


def test_el_soberano_puede_traicionar_al_pueblo():
    p = iniciada()
    responder_todos(p)
    favorita, otra = p.ronda.orden[0].id, p.ronda.orden[1].id
    votar_todos(p, favorita)
    p.decidir(soberano(p).id, otra)
    assert p.historial[-1]["respeto_al_pueblo"] is False


def test_si_nadie_vota_se_respeta_al_pueblo():
    p = iniciada()
    responder_todos(p)
    p.avanzar(p.anfitrion.id)                       # cierra la votación sin votos
    assert p.ronda.favoritas == []
    p.decidir(soberano(p).id, p.ronda.orden[0].id)
    assert p.historial[-1]["respeto_al_pueblo"] is True


def test_solo_el_soberano_decide():
    p = iniciada()
    responder_todos(p)
    votar_todos(p)
    assert codigo(p.decidir, votantes(p)[0].id, p.ronda.orden[0].id) == 403
    assert codigo(p.decidir, soberano(p).id, "000000000000") == 404


def test_decidir_fuera_de_fase_da_409():
    p = iniciada()
    assert codigo(p.decidir, soberano(p).id, "000000000000") == 409


def test_alcanzar_los_puntos_termina_la_partida():
    p = iniciada(puntos=1)
    responder_todos(p)
    votar_todos(p)
    rid = p.ronda.orden[0].id
    autor_id = p.ronda.orden[0].autor_id
    p.decidir(soberano(p).id, rid)
    assert p.fase == "terminada"
    assert p.vista(None)["ganador_id"] == autor_id


# ---------------------------------------------------------------- avanzar

def test_avanzar_en_respuestas_necesita_dos_respuestas():
    p = iniciada()
    assert codigo(p.avanzar, p.anfitrion.id) == 409    # 0 respuestas
    responder_todos(p, cuantos=1)
    assert codigo(p.avanzar, p.anfitrion.id) == 409    # 1 respuesta
    responder_todos_restantes = votantes(p)[1]
    p.responder(responder_todos_restantes.id, responder_todos_restantes.mano[: p.ronda.carta_negra["elegir"]])
    p.avanzar(p.anfitrion.id)
    assert p.fase == "votacion"
    assert len(p.ronda.orden) == 2


def test_quien_no_respondio_igual_puede_votar():
    p = iniciada()
    responder_todos(p, cuantos=2)
    p.avanzar(p.anfitrion.id)
    rezagado = votantes(p)[2]
    p.votar(rezagado.id, p.ronda.orden[0].id)
    assert p.ronda.votos[rezagado.id] == p.ronda.orden[0].id


def test_solo_anfitrion_o_soberano_avanzan():
    p = iniciada()
    responder_todos(p, cuantos=2)
    assert codigo(p.avanzar, votantes(p)[0].id) == 403


def test_avanzar_en_decision_o_sala_da_409():
    p = partida()
    assert codigo(p.avanzar, p.anfitrion.id) == 409
    p = iniciada()
    responder_todos(p)
    votar_todos(p)
    assert codigo(p.avanzar, p.anfitrion.id) == 409


def test_nueva_ronda_rota_el_soberano_y_rellena_las_manos():
    p = iniciada()
    orden_ids = [j.id for j in p.jugadores]
    for numero in range(1, 6):                         # más vueltas que jugadores
        esperado = orden_ids[(numero - 1) % 4]
        assert p.ronda.numero == numero and p.ronda.soberano_id == esperado
        assert all(len(j.mano) == 7 for j in p.jugadores)
        responder_todos(p)
        votar_todos(p)
        p.decidir(soberano(p).id, p.ronda.orden[0].id)
        if p.fase == "terminada":
            break
        p.avanzar(soberano(p).id)                      # el soberano también puede avanzar
        assert p.fase == "respuestas"


def test_avanzar_en_terminada_da_409():
    p = iniciada(puntos=1)
    responder_todos(p)
    votar_todos(p)
    p.decidir(soberano(p).id, p.ronda.orden[0].id)
    assert codigo(p.avanzar, p.anfitrion.id) == 409


# ---------------------------------------------------------------- eliminar

def test_eliminar_solo_anfitrion_y_terminada():
    p = iniciada(puntos=1)
    assert codigo(p.eliminar, p.anfitrion.id) == 409      # todavía no termina
    responder_todos(p)
    votar_todos(p)
    p.decidir(soberano(p).id, p.ronda.orden[0].id)
    assert codigo(p.eliminar, p.jugadores[1].id) == 403
    p.eliminar(p.anfitrion.id)                            # no lanza error


# ---------------------------------------------------------------- vista de la ronda

CLAVES_RONDA = {"numero", "soberano_id", "carta_negra", "respuestas_recibidas", "votos_emitidos",
                "respuestas", "favoritas_del_pueblo", "ganadora"}


def test_vista_durante_respuestas_no_revela_nada():
    p = iniciada()
    responder_todos(p, cuantos=2)
    r = p.vista(None)["ronda"]
    assert set(r) == CLAVES_RONDA
    assert r["respuestas"] == [] and r["respuestas_recibidas"] == 2
    assert r["favoritas_del_pueblo"] == [] and r["ganadora"] is None
    jugadores = p.vista(None)["jugadores"]
    assert sum(j["ya_respondio"] for j in jugadores) == 2
    assert sum(j["es_soberano"] for j in jugadores) == 1


def test_vista_en_votacion_anonima_y_barajada_fija():
    p = iniciada()
    responder_todos(p)
    j = votantes(p)[0]
    respuestas = p.vista(j.id)["ronda"]["respuestas"]
    assert len(respuestas) == 3
    for r in respuestas:
        assert set(r) == {"id", "cartas", "frase", "es_mia"}   # sin votos ni autor
        assert HEX12.match(r["id"])
    assert sum(r["es_mia"] for r in respuestas) == 1
    assert not any(r["es_mia"] for r in p.vista(None)["ronda"]["respuestas"])
    assert ids_respuestas(p) == ids_respuestas(p)              # el orden no cambia entre consultas


def test_vista_en_decision_muestra_votos_pero_no_autor():
    p = iniciada()
    responder_todos(p)
    votar_todos(p)
    r = p.vista(None)["ronda"]
    assert all(set(x) == {"id", "cartas", "frase", "es_mia", "votos"} for x in r["respuestas"])
    assert sum(x["votos"] for x in r["respuestas"]) == 3 and r["votos_emitidos"] == 3
    assert r["favoritas_del_pueblo"] == [p.ronda.orden[0].id]


def test_vista_en_resultado_muestra_autor_y_ganadora():
    p = iniciada()
    responder_todos(p)
    votar_todos(p)
    rid = p.ronda.orden[0].id
    p.decidir(soberano(p).id, rid)
    r = p.vista(None)["ronda"]
    assert r["ganadora"] == rid
    assert all("autor_id" in x and "votos" in x for x in r["respuestas"])


def test_vista_yo_con_mano_texto_y_puede_avanzar():
    p = iniciada()
    yo = p.vista(p.jugadores[1].id)["yo"]
    assert len(yo["mano"]) == 7
    assert all(isinstance(c["id"], int) and c["texto"] for c in yo["mano"])
    assert yo["puede_avanzar"] is False
    assert p.vista(p.anfitrion.id)["yo"]["puede_avanzar"] is True   # anfitrión y soberano


def test_la_vista_nunca_expone_manos_ajenas_ni_tokens():
    p = iniciada()
    responder_todos(p)
    j1, j2 = p.jugadores[1], p.jugadores[2]
    texto = json.dumps(p.vista(j1.id), ensure_ascii=False)
    assert all(t.token not in texto for t in p.jugadores)
    textos_mano_j2 = {p._mazo.texto_blanca(c) for c in j2.mano}
    textos_mano_j1 = {c["texto"] for c in p.vista(j1.id)["yo"]["mano"]}
    assert textos_mano_j2.isdisjoint(textos_mano_j1)


def test_partida_completa_de_principio_a_fin():
    p = iniciada(6, puntos=2)
    rondas = 0
    while p.fase != "terminada":
        rondas += 1
        responder_todos(p)
        votar_todos(p)
        p.decidir(soberano(p).id, p.ronda.orden[0].id)
        if p.fase == "resultado":
            p.avanzar(p.anfitrion.id)
        assert rondas < 50
    v = p.vista(p.anfitrion.id)
    assert v["fase"] == "terminada" and v["ganador_id"]
    assert len(v["historial"]) == rondas
    ganador = next(j for j in v["jugadores"] if j["id"] == v["ganador_id"])
    assert ganador["puntos"] == 2
    json.dumps(v)                                              # se puede convertir a JSON


# ---------------------------------------------------------------- frase

def test_armar_frase():
    assert armar_frase("La ley prohíbe ____.", ["Un meme como política pública."]) == \
        "La ley prohíbe un meme como política pública."
    assert armar_frase("____: el poder detrás del trono.", ["El clip de la oficina."]) == \
        "El clip de la oficina: el poder detrás del trono."
    assert armar_frase("Primero ____, después ____.", ["La sala.", "El caos."]) == \
        "Primero la sala, después el caos."
    assert armar_frase("Hackeado con ____.", ["<script>alert('x')</script>."]) == \
        "Hackeado con <script>alert('x')</script>."
    assert armar_frase("Un informe en ____.", ["PDF escaneado."]) == "Un informe en PDF escaneado."


# ---------------------------------------------------------------- orden de errores (como el profesor)

def test_permiso_antes_que_fase_en_iniciar_avanzar_y_eliminar():
    p = partida()
    no_anfitrion = p.jugadores[1].id
    assert codigo(p.avanzar, no_anfitrion) == 403        # en sala: 403, no 409
    assert codigo(p.eliminar, no_anfitrion) == 403       # sin terminar: 403, no 409
    p.iniciar(p.anfitrion.id)
    assert codigo(p.iniciar, no_anfitrion) == 403        # ya iniciada: 403, no 409
    assert codigo(p.iniciar, p.anfitrion.id) == 409


def test_fase_antes_que_permiso_en_responder_votar_y_decidir():
    p = iniciada()
    s = soberano(p)
    assert codigo(p.votar, s.id, "000000000000") == 409               # soberano, fuera de votación
    assert codigo(p.decidir, votantes(p)[0].id, "000000000000") == 409  # no soberano, fuera de decisión
    responder_todos(p)
    assert codigo(p.responder, s.id, s.mano[:1]) == 409               # soberano, fuera de respuestas


def test_unirse_a_partida_iniciada_da_409_aunque_el_nombre_sea_invalido():
    p = iniciada()
    assert codigo(p.unirse, "") == 409
    assert codigo(p.unirse, "j1") == 409


def test_empate_triple_en_favoritas():
    p = iniciada()
    responder_todos(p)
    for j, r in zip(votantes(p), p.ronda.orden):
        p.votar(j.id, r.id)
    assert p.fase == "decision" and len(p.ronda.favoritas) == 3


def test_vista_terminada_conserva_la_ronda():
    p = iniciada(puntos=1)
    responder_todos(p)
    votar_todos(p)
    p.decidir(soberano(p).id, p.ronda.orden[0].id)
    v = p.vista(p.jugadores[1].id)
    assert v["fase"] == "terminada" and v["ronda"] is not None
    assert all("autor_id" in r and "votos" in r for r in v["ronda"]["respuestas"])
    assert [j["es_soberano"] for j in v["jugadores"]] == [True, False, False, False]
    assert v["yo"]["puede_avanzar"] is False
