"""
main.py — Rutas HTTP (Persona 2).

Por ahora solo trae lo mínimo para probar el despliegue (Docker, OCI, nginx):
  HEAD /api/salud  → 200 sin cuerpo
  cualquier otra   → 404 {"error": "Ruta no encontrada."}

Las demás operaciones del openapi.yaml se agregan aquí y llaman a app/juego.py.
"""

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

# Sin /docs ni /openapi.json automáticos: la API solo expone las rutas del enunciado.
app = FastAPI(title="Cards for DemocraXSSy", docs_url=None, redoc_url=None, openapi_url=None)

# CORS (igual que la API del profesor): cualquier origen puede llamar a la API, y la
# verificación previa (OPTIONS) permite estos métodos y cabeceras. Sin esto, el navegador
# bloquea las respuestas cuando el frontend está en otro dominio.
# IMPORTANTE (Persona 2): este middleware debe quedar como el MÁS EXTERNO. En Starlette el
# último add_middleware es el más externo, así que el de validación (409) se agrega ANTES
# que este; así las respuestas de error también llevan la cabecera y el OPTIONS no se rechaza.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "HEAD", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.head("/api/salud")
async def salud() -> Response:
    return Response(status_code=200)


@app.exception_handler(StarletteHTTPException)
async def error_http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    mensajes = {404: "Ruta no encontrada.", 405: "Ruta no encontrada."}
    codigo = 404 if exc.status_code == 405 else exc.status_code
    return JSONResponse({"error": mensajes.get(exc.status_code, "Error en la solicitud.")}, status_code=codigo)
