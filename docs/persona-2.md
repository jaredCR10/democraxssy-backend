# Backend — Guía para la Persona 2 (capa HTTP, validación y almacén)

Este documento tiene todo lo necesario para trabajar tu parte sin tener que preguntar. **Lee primero
`docs/contexto.md`**: explica cómo pensamos el proyecto completo y por qué (arquitectura, Container
Instances, nginx, estado en memoria, plan de la defensa). Si usas una IA para programar, pásale
`docs/contexto.md`, este archivo, `app/juego.py` y el `openapi.yaml` del profesor.

## 1. El proyecto en una página

- **Qué es:** el backend de *Cards for DemocraXSSy*. Implementa **la misma API** que el servidor del
  profesor (https://democraxssy.akamai.meseguercr.com/). Su contrato completo está en
  https://democraxssy.akamai.meseguercr.com/openapi.yaml — **esa es nuestra especificación**.
- **Por qué igual:** nuestro frontend (https://democraxssy-anj.duckdns.org) ya funciona contra el
  servidor del profesor; tiene que funcionar igual contra el nuestro (y cualquier frontend contra el nuestro).
- **Entrega:** jueves 3 de diciembre de 2026. En la defensa hay que justificar cada decisión.
- **Stack:** Python 3.13 + FastAPI + Uvicorn (un solo worker). Estado **en memoria** (sin base de datos).
- **Despliegue (Persona 3):** la imagen se sube a Docker Hub y corre en una **OCI Container Instance**
  (como en el lab de contenedores). El nginx de la VM del frontend le pone HTTP y HTTPS delante.

### Reparto

| Persona | Archivos | Qué hace |
|---|---|---|
| 1 | `app/juego.py`, `app/mazo.py`, `app/cartas.json` | Reglas del juego, fases, vistas, mazo propio |
| **2 (tú)** | `app/main.py`, `app/validacion.py`, `app/almacen.py` | Rutas HTTP, validación de solicitudes, partidas en memoria, seguridad |
| 3 | `Dockerfile`, `docker-compose.yml`, OCI, nginx, pruebas de punta a punta | Despliegue y pruebas de integración |

## 2. Preparar el entorno

```
git clone https://github.com/jaredCR10/democraxssy-backend.git
cd democraxssy-backend
git checkout -b <tu-nombre>
python -m venv .venv
.venv\Scripts\activate                 # en PowerShell, si falla: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
pip install -r requirements-dev.txt
uvicorn app.main:app --port 3000 --reload
```

- Prueba: `curl.exe -I http://localhost:3000/api/salud` → `200 OK`. Pruebas: `pytest`.
- Usa **Python 3.13** (es la versión de la imagen de Docker).
- Todo entra a `main` por **pull request** revisado por otra persona.
- No subas `.venv`, llaves, tokens ni certificados.

## 3. Reglas del acuerdo con la Persona 1

- `app/juego.py` es la **interfaz acordada**: no cambies nombres ni parámetros sin avisar.
- `juego.py` no sabe nada de HTTP. Tú recibes la solicitud, la validas, buscas la partida y llamas sus métodos.
- Cuando una acción no está permitida, la lógica lanza `ErrorJuego(codigo, mensaje)` con 400, 403, 404 o 409.
  Tú lo conviertes en: `JSONResponse({"error": e.mensaje}, status_code=e.codigo)`.
- **Quién valida qué:**
  - **Tú (forma):** consulta, cabeceras, Content-Type, tamaño, JSON, tipos de los campos, formato del token,
    token desconocido (401), partida inexistente (404).
  - **Persona 1 (valores y reglas):** largo del nombre, rango de puntos, cartas que no están en la mano,
    permisos (403) y fase correcta (409).
- Mientras la Persona 1 implementa, puedes programar todo contra la interfaz. Ella hará primero
  `__init__`, `unirse`, `jugador_por_token` y `vista` (fase `sala`) para que puedas probar de punta a punta.

## 4. Rutas (`app/main.py`)

| Método y ruta | Token | Llamada a la lógica | Éxito |
|---|---|---|---|
| `HEAD /api/salud` | no se admite | — | **200** sin cuerpo (ya está hecha) |
| `POST /api/partidas` | no se admite | `p = Partida(nombre, puntos)`; guardar `p` en el almacén; `j = p.anfitrion` | **201** Sesión |
| `POST /api/partidas/{id}/jugadores` | no se admite | `j = p.unirse(nombre)` | **201** Sesión |
| `GET /api/partidas/{id}` | opcional | `p.vista(j.id si hay token, si no None)` | **200** Vista |
| `POST /api/partidas/{id}/iniciar` | obligatorio | `p.iniciar(j.id)` | **200** Vista de `j` |
| `PUT /api/partidas/{id}/respuestas` | obligatorio | `p.responder(j.id, cartas)` | **200** Vista de `j` |
| `PUT /api/partidas/{id}/votos` | obligatorio | `p.votar(j.id, respuesta_id)` | **200** Vista de `j` |
| `POST /api/partidas/{id}/decision` | obligatorio | `p.decidir(j.id, respuesta_id)` | **200** Vista de `j` |
| `POST /api/partidas/{id}/avanzar` | obligatorio | `p.avanzar(j.id)` | **200** Vista de `j` |
| `DELETE /api/partidas/{id}` | obligatorio | `p.eliminar(j.id)`; luego borrarla del almacén | **204** sin cuerpo |

- **Sesión** (respuesta de crear y unirse):
  `{"partida_id": p.id, "jugador_id": j.id, "token": j.token, "partida": p.vista(j.id)}`
- **Cuerpos:**
  - crear: `{"nombre": str, "puntos_para_ganar": int | null}` (puntos opcional; `null` o ausente = 5)
  - unirse: `{"nombre": str}`
  - responder: `{"cartas": [int, ...]}`. Tú revisas que sea una lista de enteros ≥ 0 sin booleanos (409);
    la cantidad, las repetidas y que estén en la mano los revisa la lógica (400)
  - votar y decidir: `{"respuesta_id": "<12 hex>"}`
  - iniciar y avanzar: sin cuerpo o `{}`; **cualquier campo → 409**
- **Token:** `Authorization: Bearer <64 hex en minúscula>`. Con la partida encontrada,
  `j = p.jugador_por_token(token)`; si es `None` → **401** `"Token ausente o inválido para esta partida."`.
  En rutas con token obligatorio, si no viene → **401**.
- **Partida inexistente** (o id que no son 32 hex en minúscula) → **404** `"Partida no encontrada."`.
- **Ruta inexistente** → **404** `"Ruta no encontrada."` (ya está hecho).
- Toda respuesta de error es JSON: `{"error": "mensaje en español"}`. Un error inesperado → **500**
  `"Error interno del servidor."` (sin mostrar detalles de Python).

## 5. Validación de la forma (`app/validacion.py`) — middleware

Se ejecuta **antes** de las rutas. Todo lo siguiente responde **409** (salvo el tamaño, 413):

1. **Parámetros de consulta:** cualquier `?algo` → 409 `"La API no admite parámetros de consulta."`
2. **Override de método:** cabeceras `X-HTTP-Method-Override`, `X-HTTP-Method` o `X-Method-Override` → 409.
3. **Authorization:**
   - debe ser exactamente `Bearer ` + 64 caracteres hexadecimales **en minúscula**, y venir **una sola vez**;
   - en rutas públicas (`HEAD /api/salud`, `POST /api/partidas`, `POST …/jugadores`) **no se admite** → 409.
4. **Cuerpo y Content-Type:**
   - `HEAD`, `GET` y `DELETE` no admiten ni cuerpo ni `Content-Type` → 409;
   - con cuerpo, `Content-Type` debe ser `application/json` (opcionalmente `; charset=utf-8`) → si no, 409;
   - cuerpo de más de **4 KB** → **413** `"El cuerpo de la solicitud es demasiado grande."`
5. **JSON:**
   - que se pueda leer y sea un **objeto** (no lista, no número) → si no, 409;
   - **sin claves repetidas**: `json.loads(cuerpo, object_pairs_hook=...)` que detecte duplicados → 409;
   - **sin campos desconocidos**, con los **obligatorios** y del **tipo correcto** → si no, 409.
   - Cuidado: en Python `True` es un `int`. Para `puntos_para_ganar` y `cartas`, rechazar booleanos.
6. **Valores del juego** (nombre de 1 a 24, puntos de 1 a 20, cartas de la mano…) **no** son tuyos:
   llegan como `ErrorJuego(400, …)` desde la lógica.

### CORS y cabeceras de respuesta

- **Todas** las respuestas: `Access-Control-Allow-Origin: *`.
- `OPTIONS` (verificación previa): permitir `GET, HEAD, POST, PUT, DELETE` con las cabeceras
  `Authorization` y `Content-Type`. Ojo: el middleware del 409 no debe rechazar el `OPTIONS`.
- Recomendadas: `Content-Type: application/json; charset=utf-8`, `Cache-Control: no-store`,
  `X-Content-Type-Options: nosniff`.

## 6. Almacén en memoria (`app/almacen.py`)

- Diccionario `id → Partida` y un **`asyncio.Lock` por partida**: toda acción que modifica una partida
  se hace con su lock tomado (dos jugadores respondiendo a la vez no deben dejarla inconsistente).
- **Máximo de partidas** simultáneas (por ejemplo 200): crear una más → 409 con un mensaje claro.
  Evita que alguien llene la RAM creando partidas en un ciclo.
- **Limpieza periódica** (tarea en segundo plano al arrancar la app): cada 5 minutos borra las partidas
  con `ultima_actividad` de hace más de 2 horas.
- Tokens y comparación: los genera la lógica con `secrets`; la búsqueda por token usa `compare_digest`.
- **Un solo worker de Uvicorn** siempre: varios workers = varias memorias y las partidas no se verían.

## 7. Comportamiento confirmado en el servidor del profesor

Probado jugando una partida completa contra su API. Ante cualquier duda, **pruébalo contra su servidor**
(Swagger en su página o `curl.exe`) y copia el código de estado.

| Caso | Respuesta |
|---|---|
| Crear partida | 201 con `partida_id`, `jugador_id`, `token`, `partida` |
| Nombre repetido (sin distinguir mayúsculas) | 409 `"Ya hay un jugador con ese nombre."` |
| `?x=1` en la URL | 409 `"La API no admite parámetros de consulta."` |
| Campo desconocido en el JSON | 409 |
| `Authorization` en `POST /api/partidas` | 409 |
| Id de partida en mayúsculas | 404 |
| Votar fuera de la fase de votación | 409 `"La votación no está abierta."` |
| Avanzar en `terminada` | 409 `"No hay nada que avanzar en esta fase."` |
| Eliminar sin ser anfitrión | 403 |
| Eliminar siendo anfitrión en `terminada` | 204; después `GET` da 404 |
| Ruta inexistente | 404 `"Ruta no encontrada."` |
| `puntos_para_ganar` con `true`, `"5"` o `2.5` (tipo incorrecto) | 409 (lo valida la capa HTTP) |
| `puntos_para_ganar` fuera de 1..20, o nombre vacío o de más de 24 | 400 (lo valida la lógica) |
| `cartas` con un número negativo o un booleano (tipo incorrecto) | 409 (lo valida la capa HTTP) |
| `cartas` vacía, con 3 elementos o repetida | **400**, no 409: la capa HTTP solo revisa que sea una lista de enteros ≥ 0; la cantidad y las repetidas las revisa la lógica |
| `respuesta_id` que no son 12 hex (por ejemplo `"XYZ"`) | **404**, no 409: si es un texto, pásalo a la lógica, que responde 404 |

Los textos de error no tienen que ser idénticos a los del profesor; el **código** sí.

**Cuidado al comparar:** el servidor del profesor a veces pierde escrituras cuando recibe solicitudes
muy seguidas (por ejemplo, de 5 uniones seguidas una no quedó guardada aunque respondió 201). Al probar
contra él, deja unos 400 ms entre solicitudes y confirma el estado con `GET`.

## 8. Pruebas

- `pytest` con `TestClient` (ver `pruebas/test_salud.py`). Una prueba por regla del 409/413/401/404.
- Antes de cada pull request: `pytest` en verde y `docker compose up --build` funcionando.
- La Persona 3 tiene un script de punta a punta que juega una partida completa contra el servidor del profesor
  y contra el nuestro; cuando lo tenga, úsalo para comparar.

## 9. Calendario

| Semana | Qué |
|---|---|
| 16–22 nov | `validacion.py` completo con pruebas; `almacen.py` completo; esqueleto de las 9 rutas |
| 23–26 nov | Conectar las rutas con `juego.py` (sala primero); partidas de prueba con el frontend en local |
| 27 nov – 2 dic | Corregir diferencias con el servidor del profesor; documentar tus decisiones en `docs/decisiones.md`; ensayo de la defensa |

Para probar con nuestro frontend en local: corre el backend (`uvicorn … --port 3000`), abre el
frontend con Live Server y escribe `http://localhost:3000` como servidor.
