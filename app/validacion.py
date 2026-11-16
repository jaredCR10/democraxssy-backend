"""
validacion.py — Middleware de validación de solicitudes (Persona 2).

Revisa la "forma" de cada solicitud antes de llegar a las rutas (ver openapi.yaml):
  - 409: parámetros de consulta, cabeceras inválidas o repetidas, Content-Type,
         cuerpo en HEAD/GET/DELETE, X-HTTP-Method-Override, JSON inválido,
         campos desconocidos, repetidos o de tipo incorrecto.
  - 413: cuerpo de más de 4 KB.
"""
