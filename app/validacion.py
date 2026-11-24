"""
validacion.py — Middleware de validación de solicitudes (Persona 2).

Revisa la "forma" de cada solicitud antes de llegar a las rutas (ver openapi.yaml):
  - 409: parámetros de consulta, cabeceras inválidas o repetidas, Content-Type,
         cuerpo en HEAD/GET/DELETE, X-HTTP-Method-Override, JSON inválido,
         campos desconocidos, repetidos o de tipo incorrecto.
  - 413: cuerpo de más de 4 KB.

Los valores del juego (largo del nombre, rango de puntos, cartas de la mano…) no se revisan
aquí: llegan como ErrorJuego(400, …) desde app/juego.py.

Es un middleware ASGI "puro" (no BaseHTTPMiddleware) porque necesita leer el cuerpo con un
límite, cortar a los 4 KB aunque no venga Content-Length, y luego entregarle a la ruta el
mismo cuerpo ya leído. Lo que valida lo deja en request.state para las rutas:
  - request.state.cuerpo: dict con el JSON ya revisado ({} si no hubo cuerpo)
  - request.state.token:  el token de Authorization (64 hex) o None
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from fastapi.responses import JSONResponse

LIMITE_CUERPO = 4 * 1024  # bytes

MSG_CONSULTA = "La API no admite parámetros de consulta."
MSG_OVERRIDE = "No se admiten las cabeceras X-HTTP-Method-Override, X-HTTP-Method ni X-Method-Override."
MSG_AUTH_REPETIDA = "La cabecera Authorization solo puede enviarse una vez."
MSG_AUTH_PUBLICA = "Esta ruta es pública: no admite la cabecera Authorization."
MSG_AUTH_FORMATO = "Authorization debe ser 'Bearer ' seguido de 64 caracteres hexadecimales en minúscula."
MSG_CT_REPETIDO = "La cabecera Content-Type solo puede enviarse una vez."
MSG_SIN_CUERPO = "Las solicitudes HEAD, GET y DELETE no admiten cuerpo ni Content-Type."
MSG_CONTENT_TYPE = "Content-Type debe ser application/json (opcionalmente con ; charset=utf-8)."
MSG_CUERPO_OBLIGATORIO = "Falta el cuerpo JSON de la solicitud."
MSG_DEMASIADO_GRANDE = "El cuerpo de la solicitud es demasiado grande."
PREFIJO_JSON = "Cuerpo JSON inválido o inesperado: "

CABECERAS_OVERRIDE = (b"x-http-method-override", b"x-http-method", b"x-method-override")
PATRON_AUTH = re.compile(r"Bearer ([0-9a-f]{64})")
PATRON_CONTENT_TYPE = re.compile(r'application/json\s*(;\s*charset\s*=\s*"?utf-8"?\s*)?', re.IGNORECASE)


class RespuestaJSON(JSONResponse):
    """JSON en UTF-8 y declarado así (Starlette solo agrega el charset a los tipos text/*)."""
    media_type = "application/json; charset=utf-8"


# ------------------------------------------------------------------ tipos de los campos


def _es_texto(v: Any) -> bool:
    return isinstance(v, str)


def _es_entero_o_nulo(v: Any) -> bool:
    # type(...) is int: en Python True y False también son int, y aquí no valen.
    return v is None or type(v) is int


def _es_lista_de_enteros_no_negativos(v: Any) -> bool:
    return isinstance(v, list) and all(type(x) is int and x >= 0 for x in v)


@dataclass(frozen=True)
class Campo:
    es_valido: Callable[[Any], bool]
    descripcion: str
    obligatorio: bool = True


TEXTO = Campo(_es_texto, "un texto")
ENTERO_O_NULO = Campo(_es_entero_o_nulo, "un número entero o null", obligatorio=False)
LISTA_DE_ENTEROS = Campo(_es_lista_de_enteros_no_negativos, "una lista de números enteros mayores o iguales a 0")

# Esquemas de los cuerpos (components.schemas del openapi.yaml).
NUEVA_PARTIDA = {"nombre": TEXTO, "puntos_para_ganar": ENTERO_O_NULO}
NUEVO_JUGADOR = {"nombre": TEXTO}
JUGADA = {"cartas": LISTA_DE_ENTEROS}
ELECCION = {"respuesta_id": TEXTO}
VACIO: dict[str, Campo] = {}  # iniciar y avanzar: sin cuerpo o {}


# ------------------------------------------------------------------ reglas por ruta


@dataclass(frozen=True)
class Regla:
    """Qué admite cada operación de la API.

    token:   "no" (ruta pública), "opcional" o "obligatorio".
    esquema: None si el método no admite cuerpo (HEAD, GET, DELETE).
    cuerpo_obligatorio: False para iniciar y avanzar (aceptan cuerpo vacío o {}).
    """
    metodo: str
    plantilla: str
    token: str
    esquema: dict[str, Campo] | None = None
    cuerpo_obligatorio: bool = False
    patron: re.Pattern = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        # Cualquier segmento no vacío entra como id: si no son 32 hex, la ruta responde
        # 404 "Partida no encontrada." (igual que el servidor del profesor), no 404 de ruta.
        regex = re.escape(self.plantilla).replace(re.escape("{partida_id}"), "[^/]+")
        object.__setattr__(self, "patron", re.compile(regex))


P = "/api/partidas/{partida_id}"
REGLAS: list[Regla] = [
    Regla("HEAD", "/api/salud", token="no"),
    Regla("POST", "/api/partidas", token="no", esquema=NUEVA_PARTIDA, cuerpo_obligatorio=True),
    Regla("GET", P, token="opcional"),
    Regla("DELETE", P, token="obligatorio"),
    Regla("POST", P + "/jugadores", token="no", esquema=NUEVO_JUGADOR, cuerpo_obligatorio=True),
    Regla("POST", P + "/iniciar", token="obligatorio", esquema=VACIO),
    Regla("PUT", P + "/respuestas", token="obligatorio", esquema=JUGADA, cuerpo_obligatorio=True),
    Regla("PUT", P + "/votos", token="obligatorio", esquema=ELECCION, cuerpo_obligatorio=True),
    Regla("POST", P + "/decision", token="obligatorio", esquema=ELECCION, cuerpo_obligatorio=True),
    Regla("POST", P + "/avanzar", token="obligatorio", esquema=VACIO),
]


def buscar_regla(metodo: str, ruta: str) -> Regla | None:
    return next((r for r in REGLAS if r.metodo == metodo and r.patron.fullmatch(ruta)), None)


# ------------------------------------------------------------------ JSON


class ErrorDeForma(Exception):
    """Solicitud con forma inválida: se responde con `codigo` (409 o 413)."""

    def __init__(self, mensaje: str, codigo: int = 409):
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.codigo = codigo


def _sin_claves_repetidas(pares: list[tuple[str, Any]]) -> dict:
    objeto: dict = {}
    for clave, valor in pares:
        if clave in objeto:
            raise ErrorDeForma(f"{PREFIJO_JSON}campo repetido `{clave}`.")
        objeto[clave] = valor
    return objeto


def _rechazar_constante(nombre: str) -> None:
    raise ErrorDeForma(f"{PREFIJO_JSON}`{nombre}` no es un valor JSON válido.")


def leer_json(cuerpo: bytes) -> dict:
    """Convierte el cuerpo en un objeto JSON o lanza ErrorDeForma (409)."""
    try:
        texto = cuerpo.decode("utf-8")
        datos = json.loads(texto, object_pairs_hook=_sin_claves_repetidas, parse_constant=_rechazar_constante)
    except ErrorDeForma:
        raise
    except (UnicodeDecodeError, ValueError, RecursionError):
        # ValueError incluye JSONDecodeError y enteros con demasiados dígitos;
        # RecursionError, un JSON de miles de corchetes anidados.
        raise ErrorDeForma(f"{PREFIJO_JSON}no es JSON válido en UTF-8.") from None
    if not isinstance(datos, dict):
        raise ErrorDeForma(f"{PREFIJO_JSON}se esperaba un objeto JSON.")
    return datos


def revisar_esquema(datos: dict, esquema: dict[str, Campo]) -> None:
    """Sin campos desconocidos, con los obligatorios y del tipo correcto (409)."""
    for clave in datos:
        if clave not in esquema:
            if esquema:
                esperados = " o ".join(f"`{c}`" for c in esquema)
                raise ErrorDeForma(f"{PREFIJO_JSON}campo desconocido `{clave}`; se esperaba {esperados}.")
            raise ErrorDeForma(f"{PREFIJO_JSON}campo desconocido `{clave}`; se esperaba un cuerpo vacío o {{}}.")
    for clave, campo in esquema.items():
        if clave not in datos:
            if campo.obligatorio:
                raise ErrorDeForma(f"{PREFIJO_JSON}falta el campo obligatorio `{clave}`.")
        elif not campo.es_valido(datos[clave]):
            raise ErrorDeForma(f"{PREFIJO_JSON}el campo `{clave}` debe ser {campo.descripcion}.")


# ------------------------------------------------------------------ middleware


def _cabeceras(scope: dict, nombre: bytes) -> list[str]:
    return [v.decode("latin-1") for k, v in scope["headers"] if k == nombre]


class ValidacionMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        regla = buscar_regla(scope["method"], scope["path"])
        if regla is None:
            # OPTIONS (verificación previa de CORS) o una ruta que no existe (404):
            # no es una operación de la API, no hay forma que validar.
            return await self.app(scope, receive, send)
        try:
            token = self._revisar_cabeceras(scope, regla)
            cuerpo = await self._leer_cuerpo(scope, receive, regla)
            datos = self._revisar_cuerpo(cuerpo, regla)
        except ErrorDeForma as e:
            return await RespuestaJSON({"error": e.mensaje}, status_code=e.codigo)(scope, receive, send)
        except _ClienteDesconectado:
            return

        estado = scope.setdefault("state", {})
        estado["token"] = token
        estado["cuerpo"] = datos

        # La ruta vuelve a recibir el cuerpo que ya se leyó (una sola vez).
        entregado = False

        async def receive_con_cuerpo():
            nonlocal entregado
            if not entregado:
                entregado = True
                return {"type": "http.request", "body": cuerpo, "more_body": False}
            return await receive()

        await self.app(scope, receive_con_cuerpo, send)

    # 1 a 3: consulta, override y Authorization
    def _revisar_cabeceras(self, scope: dict, regla: Regla) -> str | None:
        if scope.get("query_string"):
            raise ErrorDeForma(MSG_CONSULTA)
        if any(k in CABECERAS_OVERRIDE for k, _ in scope["headers"]):
            raise ErrorDeForma(MSG_OVERRIDE)

        auth = _cabeceras(scope, b"authorization")
        if len(auth) > 1:
            raise ErrorDeForma(MSG_AUTH_REPETIDA)
        if not auth:
            return None  # si la ruta lo exige, la ruta responde 401 (después de buscar la partida: 404 primero)
        if regla.token == "no":
            raise ErrorDeForma(MSG_AUTH_PUBLICA)
        coincide = PATRON_AUTH.fullmatch(auth[0])
        if not coincide:
            raise ErrorDeForma(MSG_AUTH_FORMATO)
        return coincide.group(1)

    # 4: cuerpo, Content-Type y tamaño
    async def _leer_cuerpo(self, scope: dict, receive, regla: Regla) -> bytes:
        tipos = _cabeceras(scope, b"content-type")
        if len(tipos) > 1:
            raise ErrorDeForma(MSG_CT_REPETIDO)
        largo = _cabeceras(scope, b"content-length")
        por_partes = bool(_cabeceras(scope, b"transfer-encoding"))

        if regla.esquema is None:  # HEAD, GET, DELETE
            hay_cuerpo = por_partes or any(v.strip() != "0" for v in largo)
            if tipos or hay_cuerpo:
                raise ErrorDeForma(MSG_SIN_CUERPO)
            return b""

        if tipos and not PATRON_CONTENT_TYPE.fullmatch(tipos[0].strip()):
            raise ErrorDeForma(MSG_CONTENT_TYPE)
        if largo and largo[0].strip().isdigit() and int(largo[0]) > LIMITE_CUERPO:
            raise ErrorDeForma(MSG_DEMASIADO_GRANDE, 413)

        # Se lee por partes y se corta al pasar el límite, aunque el cliente no haya enviado
        # Content-Length (transferencia chunked) o haya mentido en él.
        partes: list[bytes] = []
        total = 0
        while True:
            mensaje = await receive()
            if mensaje["type"] == "http.disconnect":
                raise _ClienteDesconectado
            trozo = mensaje.get("body", b"")
            total += len(trozo)
            if total > LIMITE_CUERPO:
                raise ErrorDeForma(MSG_DEMASIADO_GRANDE, 413)
            partes.append(trozo)
            if not mensaje.get("more_body", False):
                break
        cuerpo = b"".join(partes)

        if cuerpo and not tipos:
            raise ErrorDeForma(MSG_CONTENT_TYPE)
        return cuerpo

    # 5: JSON
    def _revisar_cuerpo(self, cuerpo: bytes, regla: Regla) -> dict:
        if regla.esquema is None:
            return {}
        if not cuerpo:
            if regla.cuerpo_obligatorio:
                raise ErrorDeForma(MSG_CUERPO_OBLIGATORIO)
            return {}
        datos = leer_json(cuerpo)
        revisar_esquema(datos, regla.esquema)
        return datos


class _ClienteDesconectado(Exception):
    pass
