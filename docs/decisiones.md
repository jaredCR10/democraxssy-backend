# Decisiones del backend

Cada decisión con su justificación, para la revisión.

| Decisión | Por qué |
|---|---|
| Python 3.13 + FastAPI + Uvicorn | El grupo domina Python; FastAPI es liviano y permite controlar las respuestas de error |
| Estado en memoria | Las partidas son efímeras, no hay cuentas ni datos que deban durar; menos recursos que una base de datos. **Aprobado por el profesor**: si el backend se apaga, se crea una partida nueva |
| Un solo worker de Uvicorn | Cada worker tendría su propia memoria y los jugadores no verían la misma partida |
| OCI Container Instance con imagen de docker.io | Tecnología DevOps vista en el laboratorio de contenedores |
| nginx de la VM del frontend delante del contenedor | La Container Instance no trae HTTPS; se reutiliza el nginx y certbot existentes (HTTP y HTTPS) |
| Forma CI.Standard.A1.Flex (ARM) | La E4 no tenía cupo en la cuenta; la A1 es eficiente y suficiente |
| Imagen multiarquitectura (amd64 + arm64) | La A1 es ARM y las laptops x86; OCI rechaza una imagen de otra arquitectura |
| IP privada fija 10.0.8.50 y Security List TCP/3000 solo desde 10.0.8.99/32 | Solo nginx llega al contenedor; la IP no cambia al recrear la instancia |
| Subdominio api-democraxssy-anj.duckdns.org, HTTP y HTTPS sin redirección | El enunciado exige que el backend soporte ambos protocolos |
| Excepción en el firewall anti-SSRF solo para 10.0.8.50:3000 | nginx necesita llegar al backend; el resto de la red interna sigue bloqueada |
| nginx de la VM del frontend como proxy inverso (HTTP y HTTPS) del backend | Ya tiene IP reservada, certbot con renovación automática y puertos abiertos: cero recursos nuevos. **Aprobado por el profesor** |

## Reglas del juego: qué viene de dónde

Todo lo de esta tabla se **comprobó jugando partidas contra el servidor del profesor** (21 nov 2026)
y nuestra lógica se comporta igual. Las pruebas `pruebas/test_rondas.py` lo verifican.

| Regla | Origen |
|---|---|
| Si nadie votó, `respeto_al_pueblo` es `true` | openapi.yaml (y comprobado) |
| Votan todos menos el soberano, también quien no respondió; se vale votar por la propia | openapi.yaml (y comprobado) |
| Orden de errores en responder, votar y decidir: fase (409) → permiso (403) → datos (400/404) | Comprobado en el servidor del profesor |
| Orden de errores en iniciar, avanzar y eliminar: permiso (403) → fase (409) | Comprobado en el servidor del profesor |
| Menos de 4 jugadores o número impar al iniciar → 409 | Comprobado en el servidor del profesor |
| Unirse a una partida ya iniciada → 409, aunque el nombre sea inválido | Comprobado en el servidor del profesor |
| El anfitrión es el soberano de la primera ronda; luego rota en orden de llegada, en círculo | Comprobado en el servidor del profesor |
| Las respuestas se barajan una vez por ronda: el orden no cambia entre consultas y es el mismo para todos | Comprobado en el servidor del profesor |
| Las manos se rellenan a 7 al empezar cada ronda (el soberano conserva sus 7) | Comprobado en el servidor del profesor |
| Empates: todas las más votadas entran en `favoritas_del_pueblo` | Comprobado en el servidor del profesor |
| En `terminada` se sigue mostrando la última ronda completa (votos y autores) | Comprobado en el servidor del profesor |
| En la frase, la carta blanca pierde el punto final y empieza en minúscula (salvo al inicio de una oración o si es una sigla) | Comprobado en el servidor del profesor |
| Las cartas jugadas vuelven al mazo | Decisión nuestra: así nunca se agotan, ni con 22 jugadores (no se nota al jugar) |
| Mazo barajado con aleatoriedad criptográfica (`secrets`) | Decisión nuestra: nadie puede predecir las cartas |
| `cartas.json` se valida al arrancar (espacios `____` = `elegir`, sin repetidas) | Decisión nuestra: una carta mal escrita falla al iniciar y no en medio de una partida |
| Cartas propias (44 negras, 9 con dos espacios, y 266 blancas) | El enunciado prohíbe copiar; mismo estilo de sátira política |

## Capa HTTP, validación y almacén (Persona 2)

Archivos: `app/main.py`, `app/validacion.py`, `app/almacen.py`. Pruebas: `pruebas/test_validacion.py`,
`pruebas/test_almacen.py`, `pruebas/test_api.py`, `pruebas/test_robustez.py`.

### Recorrido de una solicitud

```
CabecerasMiddleware      CORS y seguridad en TODA respuesta; error inesperado → 500 en JSON
  CORSMiddleware         responde la verificación previa (OPTIONS)
    ValidacionMiddleware forma de la solicitud → 409 / 413
      ruta               partida (404) → token (401) → llama a juego.py
        juego.py         reglas → 400 / 403 / 404 / 409
```

| Decisión | Por qué |
|---|---|
| Validación en un **middleware ASGI propio**, no en FastAPI/Pydantic | FastAPI responde 422 e ignora campos extra; la API exige 409 ante consultas, cabeceras, campos desconocidos o repetidos. Un middleware ASGI "puro" (no `BaseHTTPMiddleware`) permite leer el cuerpo con límite y luego entregarle a la ruta el mismo cuerpo |
| **Tabla de reglas** (`REGLAS` en `validacion.py`), una por operación | Cada operación declara si admite token, si admite cuerpo y su esquema. Una prueba obliga a que toda ruta de `main.py` tenga su regla: no se puede agregar una ruta sin validar |
| Orden de las validaciones: consulta → override → Authorization → Content-Type → tamaño → JSON | Primero lo barato (cabeceras), después leer el cuerpo. La forma se revisa **antes** de buscar la partida: `?x=1` sobre una partida inexistente da 409, no 404 |
| El cuerpo se lee **por partes y se corta a los 4 KB** | Aunque el cliente no mande `Content-Length` (transferencia *chunked*) o mienta en él, nunca se guarda en memoria más de 4 KB por solicitud. Si `Content-Length` ya dice más de 4 KB, se responde 413 sin leer nada |
| JSON con `object_pairs_hook` y sin `NaN`/`Infinity` | Python acepta por defecto claves repetidas (se queda con la última) y `NaN`; la API exige rechazarlos (409) |
| `type(x) is int` para enteros | En Python `True` es un `int`; `puntos_para_ganar: true` debe dar 409 |
| JSON anidado miles de veces → 409 | `json.loads` lanzaría `RecursionError`; se captura para que no se convierta en 500 |
| `Authorization` en rutas protegidas sin token → la ruta responde **401 después de buscar la partida** | Así una partida inexistente da 404 aunque falte el token, igual que el servidor del profesor |
| Id de partida que no son 32 hex en minúscula → **404 "Partida no encontrada."** (no 404 de ruta) | Comprobado en el servidor del profesor |
| 405 (ruta existente con otro método, p. ej. `GET /api/salud`) → 404 "Ruta no encontrada." | Igual que el servidor del profesor |
| Cabeceras comunes en **toda** respuesta (`Access-Control-Allow-Origin: *`, `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`) | El `CORSMiddleware` de Starlette solo agrega CORS si la solicitud trae `Origin` (curl no lo manda). `no-store`: las vistas cambian cada segundo y llevan la mano del jugador; ningún proxy ni navegador debe guardarlas |
| Errores siempre en JSON `application/json; charset=utf-8`; un error inesperado → 500 `"Error interno del servidor."` | Nunca se muestran detalles de Python (el detalle queda en el registro del contenedor) |
| Rutas `async def` + **un `asyncio.Lock` por partida** | Las rutas corren en el bucle de eventos (no en hilos). Cada acción toma el lock de su partida: dos jugadores respondiendo a la vez se atienden uno tras otro; dos que se unen al mismo tiempo con el mismo nombre → uno 201 y otro 409 (probado en `test_robustez.py`). Partidas distintas no se bloquean entre sí |
| Si la partida se elimina mientras otra solicitud espera su lock → 404 | La solicitud rezagada no actúa sobre una partida borrada |
| **Máximo 200 partidas** simultáneas → 409 con mensaje claro (antes de rechazar, se limpian las abandonadas) | Que nadie llene la memoria del contenedor creando partidas en un ciclo. Cambiable con `DEMOCRAXSSY_MAX_PARTIDAS` |
| **Limpieza cada 5 min** de partidas sin actividad por **2 h**; arranca y se detiene con la app (*lifespan*) | Libera la memoria de partidas abandonadas. No toca una partida con el lock tomado. Cambiable con `DEMOCRAXSSY_INACTIVIDAD_S` y `DEMOCRAXSSY_LIMPIEZA_S` |
| Toda solicitud a una partida cuenta como actividad (también el `GET` de la consulta periódica) | Una partida con alguien mirándola (por ejemplo, la sala esperando jugadores) no se borra |

### Comprobado

- `pytest`: 229 pruebas en verde (incluidas las de la Persona 1).
- Servidor real con Uvicorn (mismo comando del `Dockerfile`), por HTTP y por HTTPS (certificado de prueba):
  `curl` confirma 200, 201, 409 por consulta y por campo desconocido, 413 con transferencia *chunked*,
  verificación previa CORS 200 y cabeceras comunes en un 404.
- Partida completa con **nuestro frontend** contra nuestro backend, en 4 ventanas, por HTTP y por HTTPS:
  crear, unirse, iniciar, responder, votar, decidir, avanzar, terminar y eliminar, sin errores; el jugador
  `<svg onload=alert(1)>` se muestra como texto.
