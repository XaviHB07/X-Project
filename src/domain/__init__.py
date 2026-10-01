"""Modelos de dominio: entidades y value objects.

Nada en este paquete importa SQLAlchemy, FastAPI, numpy (salvo tipos
básicos) ni ningún detalle de infraestructura. Esa es la regla: el
dominio se puede leer y entender sin saber cómo se persiste ni cómo se
expone por HTTP.
"""
