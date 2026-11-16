"""
juego.py — Interfaz acordada entre la Persona 1 (lógica) y la Persona 2 (HTTP).
Solo nombres y tipos: la Persona 1 rellena cada método. No cambiar nombres sin avisar.
"""

from __future__ import annotations
from dataclasses import dataclass, field

MIN_JUGADORES = 4
MAX_JUGADORES = 22
CARTAS_EN_MANO = 7
PUNTOS_POR_DEFECTO = 5


class ErrorJuego(Exception):
    def __init__(self, codigo: int, mensaje: str):   # codigo: 400, 403, 404 o 409
        super().__init__(mensaje)
        self.codigo = codigo
        self.mensaje = mensaje


@dataclass
class Jugador:
    id: str
    nombre: str
    token: str
    puntos: int = 0
    mano: list[int] = field(default_factory=list)


class Partida:
    id: str
    fase: str                  # sala | respuestas | votacion | decision | resultado | terminada
    ultima_actividad: float

    def __init__(self, nombre_anfitrion: str, puntos_para_ganar: int | None = None): ...

    @property
    def anfitrion(self) -> Jugador: ...

    def jugador_por_token(self, token: str) -> Jugador | None: ...

    def unirse(self, nombre: str) -> Jugador: ...
    def iniciar(self, jugador_id: str) -> None: ...
    def responder(self, jugador_id: str, cartas: list[int]) -> None: ...
    def votar(self, jugador_id: str, respuesta_id: str) -> None: ...
    def decidir(self, jugador_id: str, respuesta_id: str) -> None: ...
    def avanzar(self, jugador_id: str) -> None: ...
    def eliminar(self, jugador_id: str) -> None: ...

    def vista(self, jugador_id: str | None) -> dict: ...   # el JSON "Vista" del openapi.yaml
