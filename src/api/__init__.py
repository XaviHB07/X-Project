"""Capa HTTP (FastAPI): el punto de entrada real para "los usuarios
finales" que menciona la pregunta original -- aquí es donde una app
externa (front-end, sistema de asistencia, integración con el LMS del
colegio, etc.) interactúa con el sistema.

Esta capa es deliberadamente delgada: `main.py` solo valida la forma de
la solicitud (vía `schemas.py`) y delega TODO el trabajo real a
`src/services`. Ningún endpoint contiene lógica bayesiana, SQL, ni
conocimiento de qué estrategia existe -- eso viola la separación de
capas y es exactamente lo que se busca evitar.
"""
