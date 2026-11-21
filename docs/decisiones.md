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
