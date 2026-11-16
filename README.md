# democraxssy-backend

Backend de **Cards for DemocraXSSy** (Redes, Grupo C). Implementa la API del `openapi.yaml`
del profesor: https://democraxssy.akamai.meseguercr.com/

## Estructura

```
app/
  main.py         Rutas HTTP (Persona 2)
  validacion.py   Middleware de validación: 409 / 413 (Persona 2)
  almacen.py      Partidas en memoria, locks, limpieza (Persona 2)
  juego.py        Reglas y estado de una partida — interfaz acordada (Persona 1)
  mazo.py         Mazo de cartas (Persona 1)
  cartas.json     Cartas propias (Persona 1)
pruebas/          Pruebas con pytest
docs/             Decisiones y documentación
Dockerfile        Imagen del backend
docker-compose.yml  Para correrlo en local
```

## Correr en local sin Docker (Python 3.13)

```
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements-dev.txt
uvicorn app.main:app --port 3000 --reload
pytest
```

## Correr en local con Docker

```
docker compose up --build
curl.exe -I http://localhost:3000/api/salud
```

## Publicar la imagen (la usa la OCI Container Instance)

```
docker login
docker build -t jaredcr10/democraxssy-backend:latest .
docker push jaredcr10/democraxssy-backend:latest
```

Después se reinicia la Container Instance para que descargue la imagen nueva
(las partidas en curso se pierden).
