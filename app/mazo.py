"""
mazo.py — Cartas de la partida (Persona 1).
Cada Partida tiene su propio Mazo. Las cartas se leen de cartas.json.
"""

from __future__ import annotations


class Mazo:
    def sacar_negra(self) -> dict: ...                  # {"texto": str, "elegir": 1 | 2}
    def sacar_blancas(self, n: int) -> list[int]: ...   # rebaraja los descartes si se acaba
    def texto_blanca(self, carta_id: int) -> str: ...
