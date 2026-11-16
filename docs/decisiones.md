# Decisiones del backend

Cada decisión con su justificación, para la revisión.

| Decisión | Por qué |
|---|---|
| Python 3.13 + FastAPI + Uvicorn | El grupo domina Python; FastAPI es liviano y permite controlar las respuestas de error |
| Estado en memoria | Las partidas son efímeras, no hay cuentas ni datos que deban durar; menos recursos que una base de datos |
| Un solo worker de Uvicorn | Cada worker tendría su propia memoria y los jugadores no verían la misma partida |
| OCI Container Instance con imagen de docker.io | Tecnología DevOps vista en el laboratorio de contenedores |
| nginx de la VM del frontend delante del contenedor | La Container Instance no trae HTTPS; se reutiliza el nginx y certbot existentes (HTTP y HTTPS) |
