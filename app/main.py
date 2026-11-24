"""
main.py — Rutas HTTP (Persona 2).

Implementa las 10 operaciones del openapi.yaml del profesor y las conecta con app/juego.py.

Recorrido de una solicitud (de afuera hacia adentro):

    CabecerasMiddleware   CORS y seguridad en TODA respuesta; un error inesperado → 500 en JSON
      CORSMiddleware      responde la verificación previa (OPTIONS)
        ValidacionMiddleware   forma de la solicitud: 409 / 413 (app/validacion.py)
          ruta             busca la partida (404), el token (401) y llama a la lógica
            juego.py       reglas: 400 / 403 / 404 / 409 con ErrorJuego

Todas las rutas son `async def`: corren en el bucle de eventos (no en hilos aparte) y cada
acción sobre una partida se hace con su lock tomado (almacen.bloqueada).
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.almacen import almacen
from app.juego import ErrorJuego, Jugador, Partida
from app.validacion import RespuestaJSON, ValidacionMiddleware

log = logging.getLogger("democraxssy")

MSG_RUTA = "Ruta no encontrada."
MSG_TOKEN = "Token ausente o inválido para esta partida."
MSG_INTERNO = "Error interno del servidor."

# Cabeceras que lleva toda respuesta, también los errores y las de curl (sin cabecera Origin).
CABECERAS_COMUNES = [
    (b"access-control-allow-origin", b"*"),
    (b"cache-control", b"no-store"),
    (b"x-content-type-options", b"nosniff"),
]


@asynccontextmanager
async def ciclo_de_vida(_app: FastAPI):
    """Al arrancar, lanza la limpieza periódica de partidas abandonadas; al apagar, la detiene."""
    tarea = asyncio.create_task(almacen.limpiar_periodicamente())
    yield
    tarea.cancel()


# Sin /docs ni /openapi.json automáticos: la API solo expone las rutas del enunciado.
app = FastAPI(
    title="Cards for DemocraXSSy",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    default_response_class=RespuestaJSON,
    lifespan=ciclo_de_vida,
)


class CabecerasMiddleware:
    """El más externo. Agrega CABECERAS_COMUNES a cada respuesta y convierte cualquier error
    no previsto en un 500 JSON sin detalles de Python (el detalle queda en el registro)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        iniciada = False

        async def send_con_cabeceras(mensaje):
            nonlocal iniciada
            if mensaje["type"] == "http.response.start":
                iniciada = True
                presentes = {k.lower() for k, _ in mensaje.get("headers", [])}
                extra = [(k, v) for k, v in CABECERAS_COMUNES if k not in presentes]
                mensaje = {**mensaje, "headers": list(mensaje.get("headers", [])) + extra}
            await send(mensaje)

        try:
            await self.app(scope, receive, send_con_cabeceras)
        except Exception:
            log.exception("Error no controlado en %s %s", scope.get("method"), scope.get("path"))
            if not iniciada:
                await RespuestaJSON({"error": MSG_INTERNO}, status_code=500)(scope, receive, send_con_cabeceras)


# En Starlette el último add_middleware queda como el más externo: el orden de abajo produce
# Cabeceras → CORS → Validación → rutas. Así la verificación previa (OPTIONS) la responde CORS
# sin pasar por la validación, y toda respuesta (incluidos los 409) lleva las cabeceras.
app.add_middleware(ValidacionMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "HEAD", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)
app.add_middleware(CabecerasMiddleware)


# ------------------------------------------------------------------ errores


@app.exception_handler(ErrorJuego)
async def error_juego(_request: Request, e: ErrorJuego) -> RespuestaJSON:
    return RespuestaJSON({"error": e.mensaje}, status_code=e.codigo)


@app.exception_handler(StarletteHTTPException)
async def error_http(_request: Request, exc: StarletteHTTPException) -> RespuestaJSON:
    # 405 (la ruta existe pero no con ese método, p. ej. GET /api/salud) también se informa
    # como ruta inexistente, igual que el servidor del profesor.
    if exc.status_code in (404, 405):
        return RespuestaJSON({"error": MSG_RUTA}, status_code=404)
    return RespuestaJSON({"error": "Error en la solicitud."}, status_code=exc.status_code)


# ------------------------------------------------------------------ ayudantes


def jugador_de(partida: Partida, request: Request, obligatorio: bool = True) -> Jugador | None:
    """El jugador dueño del token (ya validado en su forma por el middleware).
    Sin token: 401 si la ruta lo exige, None si es opcional. Token ajeno: siempre 401."""
    token = request.state.token
    if token is None:
        if obligatorio:
            raise ErrorJuego(401, MSG_TOKEN)
        return None
    jugador = partida.jugador_por_token(token)
    if jugador is None:
        raise ErrorJuego(401, MSG_TOKEN)
    return jugador


def sesion(partida: Partida, jugador: Jugador) -> dict:
    """Esquema Sesion: lo que reciben quien crea la partida y quien se une."""
    return {
        "partida_id": partida.id,
        "jugador_id": jugador.id,
        "token": jugador.token,
        "partida": partida.vista(jugador.id),
    }


# ------------------------------------------------------------------ rutas


@app.head("/api/salud")
async def salud() -> Response:
    return Response(status_code=200)


@app.post("/api/partidas")
async def crear_partida(request: Request) -> RespuestaJSON:
    cuerpo = request.state.cuerpo
    partida = Partida(cuerpo["nombre"], cuerpo.get("puntos_para_ganar"))  # 400 si nombre o puntos no valen
    almacen.agregar(partida)                                                # 409 si el servidor está lleno
    return RespuestaJSON(sesion(partida, partida.anfitrion), status_code=201)


@app.post("/api/partidas/{partida_id}/jugadores")
async def unirse(partida_id: str, request: Request) -> RespuestaJSON:
    async with almacen.bloqueada(partida_id) as partida:
        jugador = partida.unirse(request.state.cuerpo["nombre"])
        return RespuestaJSON(sesion(partida, jugador), status_code=201)


@app.get("/api/partidas/{partida_id}")
async def obtener_partida(partida_id: str, request: Request) -> RespuestaJSON:
    async with almacen.bloqueada(partida_id) as partida:
        jugador = jugador_de(partida, request, obligatorio=False)
        return RespuestaJSON(partida.vista(jugador.id if jugador else None))


@app.delete("/api/partidas/{partida_id}")
async def eliminar_partida(partida_id: str, request: Request) -> Response:
    async with almacen.bloqueada(partida_id) as partida:
        jugador = jugador_de(partida, request)
        partida.eliminar(jugador.id)   # 403 si no es el anfitrión, 409 si no está terminada
        almacen.eliminar(partida.id)
    return Response(status_code=204)


@app.post("/api/partidas/{partida_id}/iniciar")
async def iniciar(partida_id: str, request: Request) -> RespuestaJSON:
    async with almacen.bloqueada(partida_id) as partida:
        jugador = jugador_de(partida, request)
        partida.iniciar(jugador.id)
        return RespuestaJSON(partida.vista(jugador.id))


@app.put("/api/partidas/{partida_id}/respuestas")
async def responder(partida_id: str, request: Request) -> RespuestaJSON:
    async with almacen.bloqueada(partida_id) as partida:
        jugador = jugador_de(partida, request)
        partida.responder(jugador.id, request.state.cuerpo["cartas"])
        return RespuestaJSON(partida.vista(jugador.id))


@app.put("/api/partidas/{partida_id}/votos")
async def votar(partida_id: str, request: Request) -> RespuestaJSON:
    async with almacen.bloqueada(partida_id) as partida:
        jugador = jugador_de(partida, request)
        partida.votar(jugador.id, request.state.cuerpo["respuesta_id"])
        return RespuestaJSON(partida.vista(jugador.id))


@app.post("/api/partidas/{partida_id}/decision")
async def decidir(partida_id: str, request: Request) -> RespuestaJSON:
    async with almacen.bloqueada(partida_id) as partida:
        jugador = jugador_de(partida, request)
        partida.decidir(jugador.id, request.state.cuerpo["respuesta_id"])
        return RespuestaJSON(partida.vista(jugador.id))


@app.post("/api/partidas/{partida_id}/avanzar")
async def avanzar(partida_id: str, request: Request) -> RespuestaJSON:
    async with almacen.bloqueada(partida_id) as partida:
        jugador = jugador_de(partida, request)
        partida.avanzar(jugador.id)
        return RespuestaJSON(partida.vista(jugador.id))
