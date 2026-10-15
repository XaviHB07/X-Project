"""Inyección de dependencias de FastAPI.

El `AppContext` (ver `src/services/bootstrap.py`) se construye UNA vez,
al arrancar la aplicación (`main.py`, evento `startup`), y cada endpoint
lo obtiene vía `Depends(...)`. Esto evita reconstruir el engine de base
de datos, releer el YAML o reinstanciar el `EventBus` en cada request.
"""

from __future__ import annotations

from typing import Optional

from fastapi import HTTPException, Request, status

from src.repositories.interfaces import UnitOfWork
from src.services.bootstrap import AppContext
from src.services.fairness_service import FairnessMetricsService
from src.services.group_planning_service import GroupPlanningService
from src.services.roster_service import RosterService
from src.services.selection_service import SelectionService
from src.services.session_service import SessionService
from src.services.auth_service import AuthenticatedUser, ROLE_ADMIN, ROLE_STUDENT


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


def get_group_planning_service(request: Request) -> GroupPlanningService:
    return get_app_context(request).group_planning_service


def new_unit_of_work(request: Request) -> UnitOfWork:
    """Crea una `UnitOfWork` nueva para operaciones simples (matricular
    estudiante, crear curso, leer estado) que no ameritan un servicio de
    aplicación propio -- son operaciones CRUD directas sobre un único
    repositorio, sin lógica de negocio que orquestar.
    """
    return get_app_context(request).uow_factory()


def current_user(request: Request) -> AuthenticatedUser:
    user = getattr(request.state, "authenticated_user", None)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Inicia sesión para continuar.")
    return user


def require_admin(request: Request) -> AuthenticatedUser:
    user = current_user(request)
    if user.role != ROLE_ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Esta acción requiere permisos de administrador.")
    return user


def require_course_access(course_id: int, request: Request) -> None:
    user = current_user(request)
    if user.role == ROLE_STUDENT:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Usa el portal de estudiante para consultar tus cursos.")
    if not get_app_context(request).auth_service.has_course_access(user, course_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No tienes acceso a este curso.")


def require_student_access(student_id: int, request: Request) -> None:
    user = current_user(request)
    if user.role == ROLE_ADMIN:
        return
    if user.role == ROLE_STUDENT:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No tienes acceso a esta información.")
    with get_app_context(request).uow_factory() as uow:
        student = uow.students.get(student_id)
    if student is not None and not get_app_context(request).auth_service.has_course_access(
        user, student.course_id
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No tienes acceso a este estudiante.")


def require_class_session_access(class_session_id: int, request: Request) -> None:
    user = current_user(request)
    if user.role == ROLE_ADMIN:
        return
    if user.role == ROLE_STUDENT:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No tienes acceso a esta sesión.")
    with get_app_context(request).uow_factory() as uow:
        class_session = uow.class_sessions.get(class_session_id)
    if class_session is not None and not get_app_context(request).auth_service.has_course_access(
        user, class_session.course_id
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No tienes acceso a esta sesión.")
