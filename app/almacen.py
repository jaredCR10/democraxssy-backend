"""
almacen.py — Partidas en memoria (Persona 2).

  - Diccionario id → Partida, con un asyncio.Lock por partida.
  - Máximo de partidas simultáneas (protege la memoria del contenedor).
  - Tarea periódica que borra las partidas abandonadas (usa Partida.ultima_actividad).

Las partidas viven en la memoria de este proceso (aprobado por el profesor). Por eso Uvicorn
corre con un solo worker: con varios, cada uno tendría su propio almacén y los jugadores de
una misma partida podrían caer en procesos distintos.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from contextlib import asynccontextmanager
from typing import AsyncIterator

from app.juego import ErrorJuego, Partida

log = logging.getLogger("democraxssy.almacen")

PATRON_ID = re.compile(r"[0-9a-f]{32}")
MSG_NO_ENCONTRADA = "Partida no encontrada."

# Valores por defecto; se pueden cambiar con variables de entorno sin tocar el código.
MAX_PARTIDAS = int(os.environ.get("DEMOCRAXSSY_MAX_PARTIDAS", "200"))
INACTIVIDAD_MAXIMA = int(os.environ.get("DEMOCRAXSSY_INACTIVIDAD_S", str(2 * 60 * 60)))  # 2 horas
INTERVALO_LIMPIEZA = int(os.environ.get("DEMOCRAXSSY_LIMPIEZA_S", str(5 * 60)))        # 5 minutos


class Almacen:
    def __init__(self, max_partidas: int = MAX_PARTIDAS, inactividad_maxima: float = INACTIVIDAD_MAXIMA):
        self.max_partidas = max_partidas
        self.inactividad_maxima = inactividad_maxima
        self._partidas: dict[str, Partida] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def __len__(self) -> int:
        return len(self._partidas)

    # ------------------------------------------------------------ altas, bajas y consultas

    def agregar(self, partida: Partida) -> None:
        """Guarda una partida nueva. Si se llegó al máximo, primero borra las abandonadas;
        si aun así no hay espacio, responde 409 (nadie puede llenar la RAM en un ciclo)."""
        if len(self._partidas) >= self.max_partidas:
            self.limpiar()
        if len(self._partidas) >= self.max_partidas:
            raise ErrorJuego(
                409,
                f"El servidor alcanzó el máximo de {self.max_partidas} partidas activas. "
                "Intenta de nuevo más tarde.",
            )
        self._partidas[partida.id] = partida
        self._locks[partida.id] = asyncio.Lock()

    def obtener(self, partida_id: str) -> Partida | None:
        """La partida, o None si no existe o el id no son 32 hexadecimales en minúscula."""
        if not PATRON_ID.fullmatch(partida_id):
            return None
        return self._partidas.get(partida_id)

    def obtener_o_404(self, partida_id: str) -> Partida:
        partida = self.obtener(partida_id)
        if partida is None:
            raise ErrorJuego(404, MSG_NO_ENCONTRADA)
        return partida

    def eliminar(self, partida_id: str) -> None:
        self._partidas.pop(partida_id, None)
        self._locks.pop(partida_id, None)

    # ------------------------------------------------------------ exclusión mutua

    @asynccontextmanager
    async def bloqueada(self, partida_id: str) -> AsyncIterator[Partida]:
        """Da la partida con su lock tomado: dos jugadores actuando a la vez se atienden
        uno después del otro y la partida nunca queda a medio cambiar.

        Si la partida se eliminó mientras se esperaba el lock, responde 404.
        Cada acceso cuenta como actividad (también las consultas periódicas del frontend):
        una partida con alguien mirándola no se considera abandonada.
        """
        partida = self.obtener_o_404(partida_id)
        lock = self._locks.setdefault(partida_id, asyncio.Lock())
        async with lock:
            if self._partidas.get(partida_id) is not partida:
                raise ErrorJuego(404, MSG_NO_ENCONTRADA)
            partida.ultima_actividad = time.time()
            yield partida

    # ------------------------------------------------------------ limpieza

    def limpiar(self) -> int:
        """Borra las partidas sin actividad por más de `inactividad_maxima` segundos.
        No toca las que tienen el lock tomado (alguien está actuando en ese momento).
        Devuelve cuántas borró."""
        limite = time.time() - self.inactividad_maxima
        viejas = [
            pid for pid, p in self._partidas.items()
            if p.ultima_actividad < limite and not self._locks.get(pid, asyncio.Lock()).locked()
        ]
        for pid in viejas:
            self.eliminar(pid)
        if viejas:
            log.info("Limpieza: %d partida(s) abandonada(s) borrada(s); quedan %d.", len(viejas), len(self))
        return len(viejas)

    async def limpiar_periodicamente(self, intervalo: float = INTERVALO_LIMPIEZA) -> None:
        """Tarea en segundo plano que arranca con la aplicación (ver main.py)."""
        while True:
            await asyncio.sleep(intervalo)
            try:
                self.limpiar()
            except Exception:  # la limpieza nunca debe tumbar el servidor
                log.exception("Falló la limpieza de partidas")


# Almacén único del proceso, compartido por todas las rutas.
almacen = Almacen()
