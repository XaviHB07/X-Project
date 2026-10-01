"""Inyección de dependencias de FastAPI.

El `AppContext` (ver `src/services/bootstrap.py`) se construye UNA vez,
al arrancar la aplicación (`main.py`, evento `startup`), y cada endpoint
lo obtiene vía `Depends(...)`. Esto evita reconstruir el engine de base
de datos, releer el YAML o reinstanciar el `EventBus` en cada request.
"""

from __future__ import annotations

from typing import Optional

from fastapi import Request

from src.repositories.interfaces import UnitOfWork
from src.services.bootstrap import AppContext
from src.services.fairness_service import FairnessMetricsService
from src.services.selection_service import SelectionService


def get_app_context(request: Request) -> AppContext:
    return request.app.state.app_context


def get_selection_service(request: Request) -> SelectionService:
    return get_app_context(request).selection_service


def get_fairness_service(request: Request) -> FairnessMetricsService:
    return get_app_context(request).fairness_service


def new_unit_of_work(request: Request) -> UnitOfWork:
    """Crea una `UnitOfWork` nueva para operaciones simples (matricular
    estudiante, crear curso, leer estado) que no ameritan un servicio de
    aplicación propio -- son operaciones CRUD directas sobre un único
    repositorio, sin lógica de negocio que orquestar.
    """
    return get_app_context(request).uow_factory()
