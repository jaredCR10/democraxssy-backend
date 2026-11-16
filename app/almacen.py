"""
almacen.py — Partidas en memoria (Persona 2).

  - Diccionario id → Partida, con un asyncio.Lock por partida.
  - Máximo de partidas simultáneas.
  - Tarea periódica que borra las partidas abandonadas (usa Partida.ultima_actividad).
"""
