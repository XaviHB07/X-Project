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
from src.services.roster_service import RosterService
from src.services.selection_service import SelectionService
from src.services.session_service import SessionService
from src.services.participation_service import ParticipationService


def get_app_context(request: Request) -> AppContext:
    return request.app.state.app_context


def get_selection_service(request: Request) -> SelectionService:
    return get_app_context(request).selection_service


def get_fairness_service(request: Request) -> FairnessMetricsService:
    return get_app_context(request).fairness_service


def get_roster_service(request: Request) -> RosterService:
    return get_app_context(request).roster_service


def get_session_service(request: Request) -> SessionService:
    return get_app_context(request).session_service


def get_participation_service(request: Request) -> ParticipationService:
    return get_app_context(request).participation_service


def new_unit_of_work(request: Request) -> UnitOfWork:
    """Crea una `UnitOfWork` nueva para operaciones simples (matricular
    estudiante, crear curso, leer estado) que no ameritan un servicio de
    aplicación propio -- son operaciones CRUD directas sobre un único
    repositorio, sin lógica de negocio que orquestar.
    """
    return get_app_context(request).uow_factory()
