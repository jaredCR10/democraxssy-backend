"""
juego.py — Reglas y estado de una partida (Persona 1).

Interfaz acordada con la Persona 2: no cambiar nombres ni parámetros sin avisar.
Este módulo no sabe nada de HTTP. Cuando una acción no está permitida lanza
ErrorJuego(codigo, mensaje) y la capa HTTP lo convierte en {"error": mensaje}.

Estado de la implementación:
  - Fase "sala": __init__, anfitrion, unirse, jugador_por_token, vista   ✔
  - Rondas: iniciar, responder, votar, decidir, avanzar, eliminar       pendiente
"""

from __future__ import annotations

import secrets
import time
import unicodedata
from dataclasses import dataclass, field

from app.mazo import Mazo

MIN_JUGADORES = 4
MAX_JUGADORES = 22
CARTAS_EN_MANO = 7
PUNTOS_POR_DEFECTO = 5
PUNTOS_MIN = 1
PUNTOS_MAX = 20
NOMBRE_MIN = 1
NOMBRE_MAX = 24


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


# ---------------------------------------------------------------- validaciones

def validar_nombre(nombre: str) -> str:
    """Recorta espacios y revisa largo y caracteres de control. Devuelve el nombre limpio.

    Los caracteres < y > SÍ se permiten: el nombre se guarda tal cual y el frontend
    lo muestra siempre como texto plano (es parte del juego sobre XSS).
    """
    if not isinstance(nombre, str):
        raise ErrorJuego(400, "El nombre debe ser un texto.")
    limpio = nombre.strip()
    if not NOMBRE_MIN <= len(limpio) <= NOMBRE_MAX:
        raise ErrorJuego(400, f"El nombre debe tener entre {NOMBRE_MIN} y {NOMBRE_MAX} caracteres.")
    if any(unicodedata.category(c) == "Cc" for c in limpio):
        raise ErrorJuego(400, "El nombre no puede tener caracteres de control.")
    return limpio


def validar_puntos(puntos: int | None) -> int:
    """None significa "usar el valor por defecto" (5)."""
    if puntos is None:
        return PUNTOS_POR_DEFECTO
    # En Python True y False también son int: se rechazan explícitamente.
    if isinstance(puntos, bool) or not isinstance(puntos, int) or not PUNTOS_MIN <= puntos <= PUNTOS_MAX:
        raise ErrorJuego(400, f"Los puntos para ganar deben ser un entero entre {PUNTOS_MIN} y {PUNTOS_MAX}.")
    return puntos


# ---------------------------------------------------------------- partida

class Partida:
    id: str
    fase: str                  # sala | respuestas | votacion | decision | resultado | terminada
    ultima_actividad: float

    def __init__(self, nombre_anfitrion: str, puntos_para_ganar: int | None = None):
        nombre = validar_nombre(nombre_anfitrion)
        self.puntos_para_ganar: int = validar_puntos(puntos_para_ganar)

        self.id = secrets.token_hex(16)                 # 32 hex
        self.fase = "sala"
        self.jugadores: list[Jugador] = []              # en orden de llegada
        self.historial: list[dict] = []
        self.ganador_id: str | None = None
        self.ronda = None                               # None mientras la fase sea "sala"
        self._mazo = Mazo()

        anfitrion = self._agregar_jugador(nombre)
        self._anfitrion_id = anfitrion.id
        self._tocar()

    # ------------------------------------------------------------ consultas

    @property
    def anfitrion(self) -> Jugador:
        return self._jugador(self._anfitrion_id)

    def jugador_por_token(self, token: str) -> Jugador | None:
        """El jugador dueño del token, o None (la capa HTTP responde 401).

        compare_digest tarda lo mismo acierte o no, para no filtrar información
        del token por el tiempo de respuesta. Se revisan todos los jugadores siempre.
        """
        encontrado = None
        for j in self.jugadores:
            if secrets.compare_digest(j.token, token):
                encontrado = j
        return encontrado

    # ------------------------------------------------------------ acciones

    def unirse(self, nombre: str) -> Jugador:
        if self.fase != "sala":
            raise ErrorJuego(409, "La partida ya comenzó; no se puede unir nadie más.")
        limpio = validar_nombre(nombre)
        if len(self.jugadores) >= MAX_JUGADORES:
            raise ErrorJuego(409, "La partida está llena.")
        if any(j.nombre.casefold() == limpio.casefold() for j in self.jugadores):
            raise ErrorJuego(409, "Ya hay un jugador con ese nombre.")
        jugador = self._agregar_jugador(limpio)
        self._tocar()
        return jugador

    def iniciar(self, jugador_id: str) -> None:
        raise NotImplementedError("Pendiente: rondas")

    def responder(self, jugador_id: str, cartas: list[int]) -> None:
        raise NotImplementedError("Pendiente: rondas")

    def votar(self, jugador_id: str, respuesta_id: str) -> None:
        raise NotImplementedError("Pendiente: rondas")

    def decidir(self, jugador_id: str, respuesta_id: str) -> None:
        raise NotImplementedError("Pendiente: rondas")

    def avanzar(self, jugador_id: str) -> None:
        raise NotImplementedError("Pendiente: rondas")

    def eliminar(self, jugador_id: str) -> None:
        raise NotImplementedError("Pendiente: rondas")

    # ------------------------------------------------------------ vista

    def vista(self, jugador_id: str | None) -> dict:
        """El JSON "Vista" del openapi.yaml. jugador_id None = vista pública (yo = null).

        Nunca incluye tokens ni la mano de otros jugadores.
        """
        yo = self._jugador(jugador_id) if jugador_id is not None else None
        return {
            "id": self.id,
            "fase": self.fase,
            "anfitrion_id": self._anfitrion_id,
            "puntos_para_ganar": self.puntos_para_ganar,
            "jugadores": [self._jugador_publico(j) for j in self.jugadores],
            "ronda": None,  # la vista de la ronda se agrega con las fases de juego
            "yo": self._vista_yo(yo) if yo else None,
            "historial": [dict(r) for r in self.historial],
            "ganador_id": self.ganador_id if self.fase == "terminada" else None,
        }

    # ------------------------------------------------------------ internos

    def _agregar_jugador(self, nombre: str) -> Jugador:
        ids_usados = {j.id for j in self.jugadores}
        jugador_id = secrets.token_hex(8)               # 16 hex
        while jugador_id in ids_usados:                 # prácticamente imposible, pero gratis
            jugador_id = secrets.token_hex(8)
        jugador = Jugador(id=jugador_id, nombre=nombre, token=secrets.token_hex(32))  # token: 64 hex
        self.jugadores.append(jugador)
        return jugador

    def _jugador(self, jugador_id: str) -> Jugador:
        for j in self.jugadores:
            if j.id == jugador_id:
                return j
        raise ErrorJuego(404, "Jugador no encontrado en esta partida.")

    def _soberano_id(self) -> str | None:
        return None  # se define al iniciar la primera ronda

    def _jugador_publico(self, j: Jugador) -> dict:
        return {
            "id": j.id,
            "nombre": j.nombre,
            "puntos": j.puntos,
            "es_anfitrion": j.id == self._anfitrion_id,
            "es_soberano": j.id == self._soberano_id(),
            "ya_respondio": False,  # se calcula con la ronda
            "ya_voto": False,       # se calcula con la ronda
        }

    def _vista_yo(self, j: Jugador) -> dict:
        return {
            "id": j.id,
            "nombre": j.nombre,
            "mano": [{"id": c, "texto": self._mazo.texto_blanca(c)} for c in j.mano],
            "mi_voto": None,        # se calcula con la ronda
            "puede_avanzar": j.id == self._anfitrion_id or j.id == self._soberano_id(),
        }

    def _tocar(self) -> None:
        """Marca actividad reciente (el almacén borra las partidas inactivas)."""
        self.ultima_actividad = time.time()
