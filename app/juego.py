"""
juego.py — Reglas y estado de una partida (Persona 1).

Interfaz acordada con la Persona 2: no cambiar nombres ni parámetros sin avisar.
Este módulo no sabe nada de HTTP. Cuando una acción no está permitida lanza
ErrorJuego(codigo, mensaje) y la capa HTTP lo convierte en {"error": mensaje}.

Flujo de fases:
    sala → respuestas → votacion → decision → resultado → (nueva ronda) respuestas …
                                                       ↘ terminada (alguien llegó a los puntos)

Orden de las comprobaciones (comprobado jugando contra el servidor del profesor):
    - responder, votar, decidir:   fase (409) → permiso (403) → datos (400 / 404)
    - iniciar, avanzar, eliminar:  permiso (403) → fase (409) → datos
  Ej.: el soberano que vota fuera de la votación recibe 409, pero quien no es anfitrión
  y quiere iniciar una partida ya iniciada recibe 403.
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
MIN_RESPUESTAS_PARA_VOTAR = 2

_azar = secrets.SystemRandom()   # aleatorio criptográfico: nadie puede predecir el orden


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


@dataclass
class Respuesta:
    id: str
    autor_id: str
    cartas: list[int]          # en el orden en que llenan los espacios
    votos: int = 0


@dataclass
class Ronda:
    numero: int
    soberano_id: str
    carta_negra: dict                                               # {"texto", "elegir"}
    respuestas: dict[str, Respuesta] = field(default_factory=dict)  # autor_id → Respuesta
    orden: list[Respuesta] = field(default_factory=list)            # barajado al abrir la votación
    votos: dict[str, str] = field(default_factory=dict)             # votante_id → respuesta_id
    favoritas: list[str] = field(default_factory=list)
    ganadora: str | None = None


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


def armar_frase(texto_negra: str, textos_blancas: list[str]) -> str:
    """Rellena cada "____" de la carta negra con el texto de una carta blanca.

    La carta blanca pierde su punto final y su primera letra pasa a minúscula,
    salvo que el espacio esté al inicio de una oración (entonces se deja igual).
    """
    partes = texto_negra.split("____")
    frase = partes[0]
    for texto, siguiente in zip(textos_blancas, partes[1:]):
        relleno = texto[:-1] if texto.endswith(".") else texto
        antes = frase.rstrip()
        inicio_de_oracion = antes == "" or antes[-1] in ".!?¿¡"
        if not inicio_de_oracion and relleno[:1].isupper() and not relleno[1:2].isupper():
            relleno = relleno[0].lower() + relleno[1:]
        frase += relleno + siguiente
    return frase


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
        self.ronda: Ronda | None = None                 # None mientras la fase sea "sala"
        self._mazo = Mazo()
        self._ids_respuesta: set[str] = set()

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

    # ------------------------------------------------------------ sala

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
        jugador = self._jugador(jugador_id)
        if jugador.id != self._anfitrion_id:
            raise ErrorJuego(403, "Solo el anfitrión puede iniciar la partida.")
        if self.fase != "sala":
            raise ErrorJuego(409, "La partida ya comenzó.")
        n = len(self.jugadores)
        if n < MIN_JUGADORES:
            raise ErrorJuego(409, f"Hacen falta al menos {MIN_JUGADORES} jugadores para empezar (hay {n}).")
        if n % 2 != 0:
            raise ErrorJuego(409, f"El número de jugadores, contando al soberano, tiene que ser par (hay {n}).")
        # La primera ronda la gobierna el anfitrión; _nueva_ronda reparte las 7 cartas.
        self._nueva_ronda(soberano=jugador)
        self._tocar()

    # ------------------------------------------------------------ ronda

    def responder(self, jugador_id: str, cartas: list[int]) -> None:
        jugador = self._jugador(jugador_id)
        ronda = self.ronda
        if self.fase != "respuestas" or ronda is None:
            raise ErrorJuego(409, "No es momento de responder.")
        if jugador.id == ronda.soberano_id:
            raise ErrorJuego(403, "El soberano no responde: él decide la ganadora.")
        if jugador.id in ronda.respuestas:
            raise ErrorJuego(409, "Ya enviaste tu respuesta en esta ronda.")

        elegir = ronda.carta_negra["elegir"]
        if (not isinstance(cartas, list)
                or any(isinstance(c, bool) or not isinstance(c, int) for c in cartas)):
            raise ErrorJuego(400, "Las cartas deben ser una lista de números.")
        if len(cartas) != elegir:
            raise ErrorJuego(400, f"Debes elegir exactamente {elegir} carta{'s' if elegir > 1 else ''}.")
        if len(set(cartas)) != len(cartas):
            raise ErrorJuego(400, "No puedes repetir una carta.")
        if any(c not in jugador.mano for c in cartas):
            raise ErrorJuego(400, "Esa carta no está en tu mano.")

        for c in cartas:
            jugador.mano.remove(c)
        ronda.respuestas[jugador.id] = Respuesta(
            id=self._nuevo_id_respuesta(), autor_id=jugador.id, cartas=list(cartas)
        )
        if len(ronda.respuestas) == len(self._votantes()):
            self._abrir_votacion()
        self._tocar()

    def votar(self, jugador_id: str, respuesta_id: str) -> None:
        jugador = self._jugador(jugador_id)
        ronda = self.ronda
        if self.fase != "votacion" or ronda is None:
            raise ErrorJuego(409, "La votación no está abierta.")
        if jugador.id == ronda.soberano_id:
            raise ErrorJuego(403, "El soberano no vota; él tiene la última palabra.")
        if jugador.id in ronda.votos:
            raise ErrorJuego(409, "Ya votaste en esta ronda.")
        respuesta = self._respuesta(respuesta_id)   # 404 si no existe

        ronda.votos[jugador.id] = respuesta.id
        respuesta.votos += 1
        if len(ronda.votos) == len(self._votantes()):
            self._cerrar_votacion()
        self._tocar()

    def decidir(self, jugador_id: str, respuesta_id: str) -> None:
        jugador = self._jugador(jugador_id)
        ronda = self.ronda
        if self.fase != "decision" or ronda is None:
            raise ErrorJuego(409, "No es momento de decidir.")
        if jugador.id != ronda.soberano_id:
            raise ErrorJuego(403, "Solo el soberano elige la respuesta ganadora.")
        ganadora = self._respuesta(respuesta_id)    # 404 si no existe

        autor = self._jugador(ganadora.autor_id)
        autor.puntos += 1
        ronda.ganadora = ganadora.id
        self.historial.append({
            "numero": ronda.numero,
            "soberano_id": ronda.soberano_id,
            "ganador_id": autor.id,
            "frase": self._frase(ronda, ganadora),
            # Si nadie votó, no hay voluntad popular que traicionar.
            "respeto_al_pueblo": not ronda.favoritas or ganadora.id in ronda.favoritas,
        })
        for r in ronda.respuestas.values():          # las cartas jugadas vuelven al mazo
            self._mazo.descartar(r.cartas)

        if autor.puntos >= self.puntos_para_ganar:
            self.fase = "terminada"
            self.ganador_id = autor.id
        else:
            self.fase = "resultado"
        self._tocar()

    def avanzar(self, jugador_id: str) -> None:
        jugador = self._jugador(jugador_id)
        ronda = self.ronda
        if jugador.id not in (self._anfitrion_id, self._soberano_id()):
            raise ErrorJuego(403, "Solo el anfitrión o el soberano pueden avanzar la partida.")
        if self.fase not in ("respuestas", "votacion", "resultado") or ronda is None:
            raise ErrorJuego(409, "No hay nada que avanzar en esta fase.")

        if self.fase == "respuestas":
            if len(ronda.respuestas) < MIN_RESPUESTAS_PARA_VOTAR:
                raise ErrorJuego(
                    409, f"Se necesitan al menos {MIN_RESPUESTAS_PARA_VOTAR} respuestas para abrir la votación."
                )
            self._abrir_votacion()
        elif self.fase == "votacion":
            self._cerrar_votacion()
        else:  # "resultado": el soberano pasa al siguiente jugador
            i = next(k for k, j in enumerate(self.jugadores) if j.id == ronda.soberano_id)
            self._nueva_ronda(soberano=self.jugadores[(i + 1) % len(self.jugadores)])
        self._tocar()

    def eliminar(self, jugador_id: str) -> None:
        """Si no lanza error, la capa HTTP borra la partida del almacén (204)."""
        jugador = self._jugador(jugador_id)
        if jugador.id != self._anfitrion_id:
            raise ErrorJuego(403, "Solo el anfitrión puede eliminar la partida.")
        if self.fase != "terminada":
            raise ErrorJuego(409, "Solo se puede eliminar una partida terminada.")

    # ------------------------------------------------------------ vista

    def vista(self, jugador_id: str | None) -> dict:
        """El JSON "Vista" del openapi.yaml. jugador_id None = vista pública (yo = null).

        Nunca incluye tokens, la mano de otros jugadores ni el autor de una respuesta
        antes de la fase "resultado".
        """
        yo = self._jugador(jugador_id) if jugador_id is not None else None
        return {
            "id": self.id,
            "fase": self.fase,
            "anfitrion_id": self._anfitrion_id,
            "puntos_para_ganar": self.puntos_para_ganar,
            "jugadores": [self._jugador_publico(j) for j in self.jugadores],
            "ronda": self._vista_ronda(yo) if self.ronda else None,
            "yo": self._vista_yo(yo) if yo else None,
            "historial": [dict(r) for r in self.historial],
            "ganador_id": self.ganador_id if self.fase == "terminada" else None,
        }

    def _vista_ronda(self, yo: Jugador | None) -> dict:
        ronda = self.ronda
        mostrar_votos = self.fase in ("decision", "resultado", "terminada")
        mostrar_autor = self.fase in ("resultado", "terminada")
        respuestas = []
        if self.fase != "respuestas":                # durante "respuestas" no se revela nada
            for r in ronda.orden:
                item = {
                    "id": r.id,
                    "cartas": [self._mazo.texto_blanca(c) for c in r.cartas],
                    "frase": self._frase(ronda, r),
                    "es_mia": yo is not None and r.autor_id == yo.id,
                }
                if mostrar_votos:
                    item["votos"] = r.votos
                if mostrar_autor:
                    item["autor_id"] = r.autor_id
                respuestas.append(item)
        return {
            "numero": ronda.numero,
            "soberano_id": ronda.soberano_id,
            "carta_negra": dict(ronda.carta_negra),
            "respuestas_recibidas": len(ronda.respuestas),
            "votos_emitidos": len(ronda.votos),
            "respuestas": respuestas,
            "favoritas_del_pueblo": list(ronda.favoritas) if mostrar_votos else [],
            "ganadora": ronda.ganadora,
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

    def _respuesta(self, respuesta_id: str) -> Respuesta:
        for r in self.ronda.respuestas.values():
            if r.id == respuesta_id:
                return r
        raise ErrorJuego(404, "Esa respuesta no existe en esta ronda.")

    def _nuevo_id_respuesta(self) -> str:
        rid = secrets.token_hex(6)                      # 12 hex
        while rid in self._ids_respuesta:
            rid = secrets.token_hex(6)
        self._ids_respuesta.add(rid)
        return rid

    def _votantes(self) -> list[Jugador]:
        """Todos menos el soberano: responden y votan."""
        return [j for j in self.jugadores if j.id != self.ronda.soberano_id]

    def _nueva_ronda(self, soberano: Jugador) -> None:
        for j in self.jugadores:                        # rellenar las manos a 7
            faltan = CARTAS_EN_MANO - len(j.mano)
            if faltan > 0:
                j.mano.extend(self._mazo.sacar_blancas(faltan))
        numero = self.ronda.numero + 1 if self.ronda else 1
        self.ronda = Ronda(numero=numero, soberano_id=soberano.id, carta_negra=self._mazo.sacar_negra())
        self.fase = "respuestas"

    def _abrir_votacion(self) -> None:
        orden = list(self.ronda.respuestas.values())
        _azar.shuffle(orden)                            # anónimas: el orden no delata al autor
        self.ronda.orden = orden
        self.fase = "votacion"

    def _cerrar_votacion(self) -> None:
        maximo = max((r.votos for r in self.ronda.orden), default=0)
        self.ronda.favoritas = [r.id for r in self.ronda.orden if maximo > 0 and r.votos == maximo]
        self.fase = "decision"

    def _frase(self, ronda: Ronda, respuesta: Respuesta) -> str:
        return armar_frase(ronda.carta_negra["texto"], [self._mazo.texto_blanca(c) for c in respuesta.cartas])

    def _soberano_id(self) -> str | None:
        return self.ronda.soberano_id if self.ronda else None

    def _jugador_publico(self, j: Jugador) -> dict:
        ronda = self.ronda
        return {
            "id": j.id,
            "nombre": j.nombre,
            "puntos": j.puntos,
            "es_anfitrion": j.id == self._anfitrion_id,
            "es_soberano": j.id == self._soberano_id(),
            "ya_respondio": bool(ronda) and j.id in ronda.respuestas,
            "ya_voto": bool(ronda) and j.id in ronda.votos,
        }

    def _vista_yo(self, j: Jugador) -> dict:
        return {
            "id": j.id,
            "nombre": j.nombre,
            "mano": [{"id": c, "texto": self._mazo.texto_blanca(c)} for c in j.mano],
            "mi_voto": self.ronda.votos.get(j.id) if self.ronda else None,
            "puede_avanzar": j.id == self._anfitrion_id or j.id == self._soberano_id(),
        }

    def _tocar(self) -> None:
        """Marca actividad reciente (el almacén borra las partidas inactivas)."""
        self.ultima_actividad = time.time()
