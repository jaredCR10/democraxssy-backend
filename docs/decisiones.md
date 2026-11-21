# Decisiones del backend

Cada decisión con su justificación, para la revisión.

| Decisión | Por qué |
|---|---|
| Python 3.13 + FastAPI + Uvicorn | El grupo domina Python; FastAPI es liviano y permite controlar las respuestas de error |
| Estado en memoria | Las partidas son efímeras, no hay cuentas ni datos que deban durar; menos recursos que una base de datos |
| Un solo worker de Uvicorn | Cada worker tendría su propia memoria y los jugadores no verían la misma partida |
| OCI Container Instance con imagen de docker.io | Tecnología DevOps vista en el laboratorio de contenedores |
| nginx de la VM del frontend delante del contenedor | La Container Instance no trae HTTPS; se reutiliza el nginx y certbot existentes (HTTP y HTTPS) |
| Forma CI.Standard.A1.Flex (ARM) | La E4 no tenía cupo en la cuenta; la A1 es eficiente y suficiente |
| Imagen multiarquitectura (amd64 + arm64) | La A1 es ARM y las laptops x86; OCI rechaza una imagen de otra arquitectura |
| IP privada fija 10.0.8.50 y Security List TCP/3000 solo desde 10.0.8.99/32 | Solo nginx llega al contenedor; la IP no cambia al recrear la instancia |
| Subdominio api-democraxssy-anj.duckdns.org, HTTP y HTTPS sin redirección | El enunciado exige que el backend soporte ambos protocolos |
| Excepción en el firewall anti-SSRF solo para 10.0.8.50:3000 | nginx necesita llegar al backend; el resto de la red interna sigue bloqueada |
| nginx de la VM del frontend como proxy inverso (HTTP y HTTPS) del backend | Ya tiene IP reservada, certbot con renovación automática y puertos abiertos: cero recursos nuevos. **Aprobado por el profesor** |
