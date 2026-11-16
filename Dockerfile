# Imagen del backend de Cards for DemocraXSSy.
# Misma versión de Python que se usa en desarrollo (3.13).
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /srv

# Primero las dependencias: si solo cambia el código, Docker reutiliza esta capa.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

# No correr como root.
RUN useradd --system --no-create-home democraxssy
USER democraxssy

EXPOSE 3000

# Docker revisa cada 30 s que el servicio responda HEAD /api/salud.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; r=urllib.request.Request('http://127.0.0.1:3000/api/salud', method='HEAD'); sys.exit(0 if urllib.request.urlopen(r, timeout=2).status == 200 else 1)"

# Un solo worker: las partidas viven en la memoria de este proceso.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "3000", "--workers", "1", "--no-server-header"]
