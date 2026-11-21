"""Pruebas de app/mazo.py (Persona 1)."""

from app.mazo import Mazo, _cartas


def test_carta_negra_tiene_texto_y_elegir():
    negra = Mazo().sacar_negra()
    assert set(negra) == {"texto", "elegir"}
    assert "____" in negra["texto"] and negra["elegir"] in (1, 2)


def test_las_negras_se_rebarajan_al_acabarse():
    negras, _ = _cartas()
    m = Mazo()
    for _ in range(len(negras) * 3):        # da varias vueltas sin fallar
        m.sacar_negra()


def test_sacar_blancas_sin_repetir_y_texto():
    _, blancas = _cartas()
    m = Mazo()
    ids = m.sacar_blancas(len(blancas))
    assert sorted(ids) == list(range(len(blancas)))
    assert m.texto_blanca(ids[0]) == blancas[ids[0]]


def test_sin_cartas_disponibles_no_falla_y_los_descartes_vuelven():
    _, blancas = _cartas()
    m = Mazo()
    todas = m.sacar_blancas(len(blancas))
    assert m.sacar_blancas(1) == []          # todas están en manos de jugadores
    m.descartar(todas[:1])
    assert m.sacar_blancas(1) == todas[:1]   # la descartada vuelve a salir
