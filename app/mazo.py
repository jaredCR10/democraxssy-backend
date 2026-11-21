"""
mazo.py — Cartas de la partida (Persona 1).

Cada Partida tiene su propio Mazo, barajado al crearse. Las cartas se leen una sola vez
de cartas.json y se comparten (solo lectura) entre todas las partidas.

  - Cartas negras: se sacan en orden barajado; cuando se acaban, se vuelven a barajar todas.
  - Cartas blancas: se sacan de la pila; las jugadas van a los descartes y, cuando la pila
    se acaba, los descartes se barajan y forman la pila nueva. Las cartas que están en la
    mano de algún jugador nunca vuelven a la pila mientras sigan en su mano.
"""

from __future__ import annotations

import json
import secrets
from functools import lru_cache
from pathlib import Path

RUTA_CARTAS = Path(__file__).with_name("cartas.json")

# Generador aleatorio criptográfico: nadie puede predecir el orden de las cartas.
_azar = secrets.SystemRandom()


@lru_cache(maxsize=1)
def _cartas() -> tuple[tuple[dict, ...], tuple[str, ...]]:
    """Lee cartas.json una sola vez. Devuelve (negras, blancas)."""
    datos = json.loads(RUTA_CARTAS.read_text(encoding="utf-8"))
    negras = tuple({"texto": n["texto"], "elegir": int(n["elegir"])} for n in datos["negras"])
    blancas = tuple(str(b) for b in datos["blancas"])
    # Si una carta está mal escrita, que falle al arrancar y no en medio de una partida.
    for n in negras:
        if n["elegir"] not in (1, 2) or n["texto"].count("____") != n["elegir"]:
            raise ValueError(f"Carta negra mal formada en cartas.json: {n['texto']!r}")
    if len(set(blancas)) != len(blancas) or any(not b.strip() for b in blancas):
        raise ValueError("cartas.json tiene cartas blancas repetidas o vacías.")
    return negras, blancas


class Mazo:
    def __init__(self) -> None:
        negras, blancas = _cartas()
        self._negras_pila: list[int] = []
        self._blancas_pila: list[int] = list(range(len(blancas)))
        self._blancas_descartes: list[int] = []
        _azar.shuffle(self._blancas_pila)

    def sacar_negra(self) -> dict:
        """Devuelve una copia de la carta negra: {"texto": str, "elegir": 1 | 2}."""
        negras, _ = _cartas()
        if not self._negras_pila:
            self._negras_pila = list(range(len(negras)))
            _azar.shuffle(self._negras_pila)
        return dict(negras[self._negras_pila.pop()])

    def sacar_blancas(self, n: int) -> list[int]:
        """Saca n cartas blancas (sus ids). Rebaraja los descartes si la pila se acaba."""
        sacadas: list[int] = []
        for _ in range(n):
            if not self._blancas_pila:
                if not self._blancas_descartes:
                    break  # todas las cartas están en manos de jugadores
                self._blancas_pila = self._blancas_descartes
                self._blancas_descartes = []
                _azar.shuffle(self._blancas_pila)
            sacadas.append(self._blancas_pila.pop())
        return sacadas

    def descartar(self, cartas: list[int]) -> None:
        """Las cartas jugadas en una ronda vuelven al mazo (a los descartes)."""
        self._blancas_descartes.extend(cartas)

    def texto_blanca(self, carta_id: int) -> str:
        _, blancas = _cartas()
        return blancas[carta_id]
