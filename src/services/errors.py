"""Errores de dominio de la capa de servicios (Sprint 1).

La API los traduce a códigos HTTP (ver `src/api/main.py`); los servicios
no saben nada de HTTP.
"""

from __future__ import annotations


class CourseNotFoundError(LookupError):
    """El curso indicado no existe."""


class StudentNotFoundError(LookupError):
    """El estudiante indicado no existe."""


class SessionNotFoundError(LookupError):
    """La sesión de clase indicada no existe."""


class InvalidAttendanceError(ValueError):
    """Se intentó marcar asistencia de estudiantes que no pertenecen (o
    ya no están activos) en el curso de la sesión."""
