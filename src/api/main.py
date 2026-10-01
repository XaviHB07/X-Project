"""Aplicación FastAPI: expone `SelectionService` y `FairnessMetricsService`
como una API REST.

Cómo correrla:

    uvicorn src.api.main:app --reload
    # o, de forma equivalente:
    python scripts/run_api.py

Documentación interactiva autogenerada disponible en /docs (Swagger UI)
y /redoc una vez levantado el servidor.

Diseño: cada endpoint hace tres cosas y nada más: (1) validar la forma
del request vía los esquemas Pydantic de `schemas.py`, (2) llamar a la
capa de servicios/repositorios, (3) traducir el resultado o la excepción
de dominio a una respuesta HTTP. La lógica de negocio real vive en
`src/services` y `src/strategies`.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import List

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from src.api.dependencies import get_fairness_service, get_selection_service, new_unit_of_work
from src.api.schemas import (
    AvailableMethodsResponse,
    CourseCreateRequest,
    CourseResponse,
    DecisionResultResponse,
    FairnessMetricsResponse,
    RunSelectionRequest,
    SelectionEventResponse,
    StudentEnrollRequest,
    StudentResponse,
    StudentStateResponse,
)
from src.repositories.interfaces import UnitOfWork
from src.services.bootstrap import build_app_context
from src.services.selection_service import NoEligibleStudentsError, NoClassSessionError
from src.strategies.registry import (
    InvalidSelectorParametersError,
    SelectorRegistry,
    UnknownSelectorError,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Se construye el contexto de aplicación (config + conexión a base de
    # datos + servicios) UNA sola vez al arrancar, y se cuelga de
    # `app.state` para que `dependencies.py` lo reparta por request sin
    # reconstruir nada. Ver src/services/bootstrap.py.
    app.state.app_context = build_app_context()
    yield


app = FastAPI(
    title="Selección Inteligente — Bayesian Fairness Bandit",
    description=(
        "API de producción para el sistema de selección equitativa de estudiantes. "
        "Ver el README del proyecto para el diseño completo (Strategy, Repository, "
        "Unit of Work) y la discusión de por qué esto reemplaza a 'guardar todo en "
        "memoria durante una corrida de simulación'."
    ),
    version="2.0.0",
    lifespan=lifespan,
)

STATIC_DIR = Path(__file__).with_name("static")
app.mount("/assets", StaticFiles(directory=STATIC_DIR), name="assets")


@app.get("/", include_in_schema=False)
def frontend() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health", tags=["infraestructura"])
def health() -> dict:
    return {"status": "ok"}


@app.get("/methods", response_model=AvailableMethodsResponse, tags=["infraestructura"])
def list_methods() -> AvailableMethodsResponse:
    """Estrategias de selección registradas y disponibles para usar en
    `POST /courses/{course_id}/sessions/select`.
    """
    return AvailableMethodsResponse(methods=SelectorRegistry.available())


# --------------------------------------------------------------------------
# Cursos
# --------------------------------------------------------------------------


@app.post(
    "/courses", response_model=CourseResponse, status_code=status.HTTP_201_CREATED, tags=["cursos"]
)
def create_course(payload: CourseCreateRequest, uow: UnitOfWork = Depends(new_unit_of_work)) -> CourseResponse:
    with uow:
        course = uow.courses.create(payload.name)
        uow.commit()
    return CourseResponse(id=course.id, name=course.name, created_at=course.created_at)


@app.get("/courses/{course_id}", response_model=CourseResponse, tags=["cursos"])
def get_course(course_id: int, uow: UnitOfWork = Depends(new_unit_of_work)) -> CourseResponse:
    with uow:
        course = uow.courses.get(course_id)
    if course is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Curso {course_id} no encontrado.")
    return CourseResponse(id=course.id, name=course.name, created_at=course.created_at)


# --------------------------------------------------------------------------
# Estudiantes
# --------------------------------------------------------------------------


@app.post(
    "/courses/{course_id}/students",
    response_model=StudentResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["estudiantes"],
)
def enroll_student(
    course_id: int, payload: StudentEnrollRequest, uow: UnitOfWork = Depends(new_unit_of_work)
) -> StudentResponse:
    """Matricula un estudiante en el curso (idempotente por `external_ref`).

    Es el equivalente en producción a `Student(student_id=i, ...)` en la
    simulación: la diferencia es que aquí crea también la fila de
    `student_state` en `Beta(alpha_init, beta_init)` de forma persistente,
    en vez de un objeto que muere al terminar la corrida.
    """
    with uow:
        student = uow.students.get_or_create(
            course_id=course_id,
            external_ref=payload.external_ref,
            display_name=payload.display_name,
            alpha_init=payload.alpha_init,
            beta_init=payload.beta_init,
        )
        uow.commit()
    return StudentResponse(
        id=student.id,
        course_id=student.course_id,
        external_ref=student.external_ref,
        display_name=student.display_name,
        created_at=student.created_at,
    )


@app.get(
    "/courses/{course_id}/students", response_model=List[StudentResponse], tags=["estudiantes"]
)
def list_students(course_id: int, uow: UnitOfWork = Depends(new_unit_of_work)) -> List[StudentResponse]:
    with uow:
        students = uow.students.list_by_course(course_id)
    return [
        StudentResponse(
            id=s.id, course_id=s.course_id, external_ref=s.external_ref,
            display_name=s.display_name, created_at=s.created_at,
        )
        for s in students
    ]


@app.get(
    "/students/{student_id}/state", response_model=StudentStateResponse, tags=["estudiantes"]
)
def get_student_state(student_id: int, uow: UnitOfWork = Depends(new_unit_of_work)) -> StudentStateResponse:
    with uow:
        candidates = uow.student_states.get_candidates_readonly([student_id])
    if not candidates:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Estudiante {student_id} no encontrado.")
    c = candidates[0]
    return StudentStateResponse(
        student_id=c.student_id,
        alpha=c.alpha,
        beta=c.beta,
        n_present=c.n_present,
        n_selected=c.n_selected,
        estimated_need_probability=c.alpha / (c.alpha + c.beta),
    )


@app.get(
    "/students/{student_id}/history",
    response_model=List[SelectionEventResponse],
    tags=["estudiantes"],
)
def get_student_history(
    student_id: int, limit: int = 50, uow: UnitOfWork = Depends(new_unit_of_work)
) -> List[SelectionEventResponse]:
    """Historial de eventos de selección del estudiante, más reciente
    primero -- la traza de auditoría que responde "¿por qué fue/no fue
    elegido este estudiante, y cuándo?".
    """
    with uow:
        events = uow.events.history_for_student(student_id, limit=limit)
    return [
        SelectionEventResponse(
            id=e.id, decision_run_id=e.decision_run_id, student_id=e.student_id,
            present=e.present, selected=e.selected, alpha_before=e.alpha_before,
            beta_before=e.beta_before, alpha_after=e.alpha_after, beta_after=e.beta_after,
            created_at=e.created_at,
        )
        for e in events
    ]


# --------------------------------------------------------------------------
# Selección (el caso de uso central)
# --------------------------------------------------------------------------


@app.post(
    "/courses/{course_id}/sessions/select",
    response_model=DecisionResultResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["selección"],
)
def run_selection(
    course_id: int,
    payload: RunSelectionRequest,
    selection_service=Depends(get_selection_service),
) -> DecisionResultResponse:
    """Ejecuta una selección real y la persiste de forma atómica.

    Este es EL endpoint que reemplaza al bucle `for class_idx in
    range(n_classes)` de la simulación: cada llamada es una "clase" o
    "evento de selección" real, hecha por un cliente externo, en
    cualquier momento, potencialmente al mismo tiempo que otras llamadas
    para otros cursos (o incluso el mismo curso, aunque eso dispararía el
    control de concurrencia descrito en el README).
    """
    try:
        result = selection_service.run_selection(
            course_id=course_id,
            present_student_ids=payload.present_student_ids,
            k=payload.k,
            method_name=payload.method,
            method_params=payload.method_params,
            class_session_id=payload.class_session_id,
            session_label=payload.session_label,
            request_id=payload.request_id,
        )
    except UnknownSelectorError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except InvalidSelectorParametersError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except NoEligibleStudentsError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except NoClassSessionError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc

    return DecisionResultResponse(
        decision_run_id=result.decision_run_id,
        class_session_id=result.class_session_id,
        method_name=result.method_name,
        considered_student_ids=result.considered_student_ids,
        selected_student_ids=result.selected_student_ids,
        created_at=result.created_at,
        request_id=result.request_id,
    )


# --------------------------------------------------------------------------
# Métricas de equidad
# --------------------------------------------------------------------------


@app.get(
    "/courses/{course_id}/fairness-metrics",
    response_model=FairnessMetricsResponse,
    tags=["métricas"],
)
def fairness_metrics(
    course_id: int, fairness_service=Depends(get_fairness_service)
) -> FairnessMetricsResponse:
    """Gini / CV / std / cobertura calculados sobre el estado actual
    persistido de todos los estudiantes del curso -- no hace falta
    "recorrer todo el historial" para responder esto (ver README).
    """
    metrics = fairness_service.compute_for_course(course_id)
    return FairnessMetricsResponse(course_id=course_id, **metrics)
