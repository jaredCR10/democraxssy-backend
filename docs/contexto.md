# Contexto del proyecto: cómo lo pensamos y por qué

Este documento explica **qué se pide, cómo decidimos hacerlo y por qué**. Sirve para que cualquiera del
grupo (o una IA que le ayude) entienda el proyecto completo, y para preparar la defensa, donde el
profesor pide mostrar y justificar cada decisión.

## 1. Qué pide el enunciado (backend, 70 %, entrega jueves 3 de diciembre de 2026)

- Que los jugadores puedan jugar una partida **completa** y terminarla.
- El backend debe soportar **HTTP y HTTPS**, y la solución debe estar en Internet con **HTTPS**.
- Desplegado con alguna **tecnología DevOps vista en clase** (Terraform o contenedores).
- **Todos** los datos validados en el backend y en el frontend; **todas** las llamadas HTTP y HTTPS
  validadas y demostradas; todas las operaciones del backend usadas por el frontend.
- Se califica completitud, funcionalidad, facilidad, calidad y **uso racional de recursos**
  (direccionamiento, CPU, memoria).
- Debe poder revisarse de forma virtual. En la defensa el profesor quiere **ver arrancar el backend**.
- Cualquier comportamiento no especificado se consulta con el profesor.

## 2. De dónde partimos

- **Frontend (ya entregado):** https://democraxssy-anj.duckdns.org — HTML, CSS y JavaScript puro, servido
  por nginx en una VM de OCI (`democraxssy-web`, Oracle Linux 9, 1 OCPU / 2 GB, IP reservada
  129.80.235.41). Tiene un proxy en nginx (`/proxy/...`) para hablar con backends HTTP desde la página
  HTTPS, protegido con un firewall anti-SSRF.
- **Servidor del profesor:** https://democraxssy.akamai.meseguercr.com/ — su `openapi.yaml` es el contrato
  de la API. Nuestro backend **implementa exactamente esa API**, así nuestro frontend (y cualquier otro)
  funciona contra él sin cambios. Por las pistas, el del profesor está hecho en Rust con Fermyon Spin,
  pero el lenguaje no importa: HTTP es independiente del lenguaje.
- Respuestas previas del profesor: "contraseña" y "nombre de juego" se ignoran (la contraseña es el token
  del jugador y el nombre de juego es el ID de la partida, decisiones ya tomadas en el frontend).

## 3. Arquitectura

```
                         Internet
                            │
            ┌───────────────┴────────────────┐
            │ https://democraxssy-anj…        │ http:// y https://api-democraxssy-anj…
            ▼                                 ▼
   ┌──────────────────── VM de OCI (democraxssy-web) ─────────────────────┐
   │ nginx                                                                │
   │  ├─ frontend: HTTP → redirige a HTTPS; HTTPS sirve el sitio y /proxy │
   │  └─ API: HTTP (80) y HTTPS (443), sin redirección ──┐                │
   └─────────────────────────────────────────────────────┼────────────────┘
                                                          │ http://10.0.0.50:3000  (IP privada, misma VCN)
                                                          ▼
                              ┌──────── OCI Container Instance ────────┐
                              │ contenedor: Python 3.13 + FastAPI      │
                              │ imagen: docker.io/jaredcr10/           │
                              │         democraxssy-backend:latest     │
                              │ partidas en memoria (1 proceso)        │
                              └────────────────────────────────────────┘
```

(La IP privada `10.0.0.50` es un ejemplo; se fija al crear la Container Instance.)

## 4. Decisiones y justificación

### Tecnología del backend

| Decisión | Por qué | Alternativas descartadas |
|---|---|---|
| **Python 3.13 + FastAPI + Uvicorn** | El grupo domina Python. FastAPI es liviano y permite controlar las respuestas de error, que en esta API son muy estrictas (409, 413…). Misma versión de Python en las laptops y en la imagen | Node.js (también válido; se eligió por conocimiento del grupo) |
| **Validación propia en un middleware** | La API exige 409 ante consultas, cabeceras, campos desconocidos o repetidos; los frameworks por defecto son más permisivos (FastAPI devuelve 422 e ignora campos extra), así que se programa explícitamente | Confiar en la validación automática de FastAPI/Pydantic |
| **Lógica del juego separada de HTTP** (`juego.py` vs `main.py`) | Se puede programar y probar cada parte por separado, y trabajar en paralelo con una interfaz acordada | Todo en un archivo |

### Estado

| Decisión | Por qué |
|---|---|
| **Partidas en memoria** (sin base de datos) | Las partidas duran minutos y se eliminan al terminar; no hay cuentas ni datos que deban sobrevivir. Una base de datos sumaría otro servicio, memoria y fallos posibles sin que el enunciado lo pida: uso racional de recursos |
| **Un solo proceso (1 worker de Uvicorn, 1 contenedor)** | Cada proceso tiene su propia memoria; con varios, dos jugadores podrían caer en procesos distintos y no verían la misma partida. Uno alcanza de sobra: 22 jugadores consultando cada 2 s son ~11 peticiones por segundo |
| **Límite de partidas y limpieza de abandonadas** | Que la memoria no crezca sin control |
| **Lock por partida** | Que dos jugadores actuando a la vez no dejen la partida inconsistente |
| Consecuencia asumida | Si el contenedor se reinicia, se pierden las partidas en curso. No se actualiza a mitad de una partida ni durante la defensa |

¿Por qué el servidor del profesor quizá sí guarda estado aparte? Corre en una plataforma *serverless*
(cada petición puede caer en una instancia distinta). El nuestro es un solo proceso que vive todo el tiempo.

### Despliegue (DevOps)

| Decisión | Por qué |
|---|---|
| **Contenedores, no Terraform** | Terraform crea infraestructura (VMs, redes), no corre la aplicación; un `apply` en vivo tarda minutos y depende de la capacidad de OCI (ya nos falló la A1 por "Out of capacity") |
| **OCI Container Instances con imagen de docker.io** | Es exactamente lo que se vio en el **lab de contenedores** (allí: `docker.io` / `bkimminich/juice-shop`, puerto TCP 3000). OCI corre el contenedor sin que administremos un servidor. Política de reinicio **Always** |
| **Imagen pública en Docker Hub** (`jaredcr10/democraxssy-backend`) | Igual que en el lab; la imagen no contiene secretos |
| **Forma CI.Standard.E4.Flex, 1 OCPU y memoria mínima** | El backend consume muy poco; procesador AMD x86, compatible con la imagen construida en nuestras laptops |
| **Misma VCN que la VM del frontend, IP privada fija** | nginx llega al contenedor por la red interna; la IP fija evita reconfigurar nginx cada vez que se recrea la instancia. El puerto 3000 solo se permite desde la VCN, no desde Internet |
| **nginx de la VM delante del contenedor** | La Container Instance no trae HTTPS. Se reutiliza el nginx y certbot que ya funcionan en la VM: cero recursos nuevos |
| **Subdominio propio para la API** (`api-democraxssy-anj.duckdns.org`) con certificado de Let's Encrypt | nginx distingue frontend y API por el nombre; el frontend no se toca |
| **API por HTTP y HTTPS, sin redirección** | El enunciado pide soportar ambos. Redirigir HTTP→HTTPS impediría demostrar HTTP y rompe peticiones de la API (un POST redirigido pierde el cuerpo; CORS no acepta redirecciones en la verificación previa). El frontend sí sigue redirigiendo a HTTPS |
| **Excepción en el firewall anti-SSRF** para la IP y puerto del contenedor | El firewall del frontend impide que nginx se conecte a direcciones internas; se permite solo esa IP y puerto |
| **Docker Compose solo para desarrollo** | Cada uno corre el backend igual en su laptop (`docker compose up --build`) antes de publicarlo |
| **Contenedor sin root, con límites y *healthcheck*** | Seguridad (el proyecto es sobre XSS) y control de recursos |

### Seguridad

- Nombres, cartas y frases pueden traer `<script>`: el backend los guarda y devuelve como texto; el
  frontend siempre los muestra como texto plano.
- IDs y tokens con `secrets` (aleatorios criptográficos); tokens comparados con `compare_digest`.
- Errores sin detalles internos; límite de 4 KB por solicitud; límite de partidas.

## 5. Ciclo de trabajo

1. Programar en la rama propia y probar en local (`uvicorn … --reload`, `pytest`, `docker compose up --build`).
2. Pull request a `main`, revisado por otra persona (en la defensa todos deben poder explicar todo).
3. Publicar: `docker build` + `docker push` a Docker Hub.
4. Reiniciar la Container Instance para que descargue la imagen nueva.

## 6. La defensa (plan)

1. Mostrar la arquitectura y justificar las decisiones de este documento.
2. **Arrancar el backend en vivo:** crear (o reiniciar) la Container Instance en la consola de OCI; se ve
   cómo descarga la imagen de docker.io y en 1–2 minutos responde `HEAD /api/salud`.
3. Demostrar las llamadas por **HTTPS** y por **HTTP** (`curl.exe` y el frontend; por HTTP el frontend usa su proxy).
4. Jugar una partida completa con el frontend contra nuestro backend.
5. Mostrar validaciones: errores 409/413/401/403/404 y una prueba de XSS con un nombre como `<svg onload=alert(1)>`.
6. Mostrar el consumo de recursos (forma mínima, memoria del contenedor).

## 7. Pendiente de confirmar con el profesor

- Que Container Instances + nginx en la VM del frontend le parezca bien.
- Que las partidas puedan vivir solo en memoria.
