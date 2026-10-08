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
from datetime import date
from pathlib import Path
from typing import List, Optional

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from src.api.dependencies import (
    get_fairness_service,
    get_roster_service,
    get_selection_service,
    get_session_service,
    new_unit_of_work,
)
from src.api.schemas import (
    AttendanceEntryResponse,
    AttendanceUpdateRequest,
    AvailableMethodsResponse,
    CourseCreateRequest,
    CourseResponse,
    DecisionResultResponse,
    FairnessMetricsResponse,
    RosterImportResponse,
    RosterRowErrorResponse,
    RunSelectionRequest,
    SelectionEventResponse,
    SessionDetailResponse,
    SessionProposalResponse,
    SessionStartRequest,
    SessionSummaryResponse,
    StudentEnrollRequest,
    StudentResponse,
    StudentStateResponse,
    StudentUpdateRequest,
    SyllabusEntryRequest,
    SyllabusEntryResponse,
)
from src.repositories.interfaces import DuplicateStudentError, UnitOfWork
from src.services.bootstrap import build_app_context
from src.services.errors import (
    CourseNotFoundError,
    InvalidAttendanceError,
    SessionNotFoundError,
    StudentNotFoundError,
)
from src.services.roster_import import MAX_FILE_BYTES, RosterFormatError
from src.services.session_service import SessionDetail
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


@app.middleware("http")
async def prevent_frontend_cache(request: Request, call_next):
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/assets/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
    return response


@app.get("/health", tags=["infraestructura"])
def health() -> dict:
    return {"status": "ok"}


@app.get("/methods", response_model=AvailableMethodsResponse, tags=["infraestructura"])
def list_methods() -> AvailableMethodsResponse:
    """Estrategias de selección registradas y disponibles para usar en
    `POST /courses/{course_id}/sessions/select`.
    """
    return AvailableMethodsResponse(methods=SelectorRegistry.available())


def _student_response(s) -> StudentResponse:
    return StudentResponse(
        id=s.id, course_id=s.course_id, external_ref=s.external_ref,
        display_name=s.display_name, created_at=s.created_at, active=s.active,
        phone_number=s.phone_number, email=s.email,
    )


def _session_detail_response(detail: SessionDetail) -> SessionDetailResponse:
    session = detail.session
    return SessionDetailResponse(
        id=session.id,
        course_id=session.course_id,
        session_date=session.session_date,
        topic=session.topic,
        label=session.label,
        created_at=session.created_at,
        present_count=detail.present_count,
        total_count=len(detail.attendance),
        attendance=[
            AttendanceEntryResponse(
                student_id=a.student_id, external_ref=a.external_ref,
                display_name=a.display_name, present=a.present,
            )
            for a in detail.attendance
        ],
    )


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


@app.get("/courses", response_model=List[CourseResponse], tags=["cursos"])
def list_courses(uow: UnitOfWork = Depends(new_unit_of_work)) -> List[CourseResponse]:
    """Todos los cursos (HU-S1: el docente elige el curso de la sesión)."""
    with uow:
        courses = uow.courses.list_all()
    return [CourseResponse(id=c.id, name=c.name, created_at=c.created_at) for c in courses]


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
    course_id: int,
    payload: StudentEnrollRequest,
    uow: UnitOfWork = Depends(new_unit_of_work),
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
            phone_number=payload.phone_number,
            email=payload.email,
        )
        uow.commit()
    return _student_response(student)


@app.post(
    "/courses/{course_id}/students/import",
    response_model=RosterImportResponse,
    tags=["estudiantes"],
)
def import_students_from_excel(
    course_id: int,
    file: UploadFile = File(..., description="Excel .xlsx con columnas de código y nombre."),
    roster_service=Depends(get_roster_service),
) -> RosterImportResponse:
    """HU-C1: carga (o re-carga) la lista de estudiantes desde un Excel.

    Encabezados aceptados: `codigo` (o matrícula) y `nombre` (o apellidos y
    nombres). Las filas válidas se guardan; las inválidas se devuelven en
    `errors` con su número de fila. Si el archivo no tiene la estructura
    esperada, responde 400 y no se guarda nada. Es idempotente: volver a
    cargar el archivo actualiza nombres y no duplica estudiantes.
    """
    if not (file.filename or "").lower().endswith(".xlsx"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "El archivo debe ser un Excel en formato .xlsx.")
    data = file.file.read(MAX_FILE_BYTES + 1)  # endpoint síncrono: corre en el threadpool
    try:
        result = roster_service.import_roster(course_id, data)
    except CourseNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except RosterFormatError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return RosterImportResponse(
        total_rows=result.total_rows,
        created=result.created,
        updated=result.updated,
        unchanged=result.unchanged,
        errors=[RosterRowErrorResponse(row=e.row_number, message=e.message) for e in result.errors],
    )


@app.get(
    "/courses/{course_id}/students", response_model=List[StudentResponse], tags=["estudiantes"]
)
def list_students(
    course_id: int, include_inactive: bool = False, uow: UnitOfWork = Depends(new_unit_of_work)
) -> List[StudentResponse]:
    """Lista del curso. Por defecto solo estudiantes activos; con
    `include_inactive=true` también los retirados."""
    with uow:
        students = uow.students.list_by_course(course_id, include_inactive=include_inactive)
    return [_student_response(s) for s in students]


@app.patch("/students/{student_id}", response_model=StudentResponse, tags=["estudiantes"])
def update_student(
    student_id: int,
    payload: StudentUpdateRequest,
    roster_service=Depends(get_roster_service),
) -> StudentResponse:
    """HU-C1: corrige nombre/código, retira (`active=false`) o reincorpora a un estudiante."""
    try:
        student = roster_service.update_student(
            student_id,
            external_ref=payload.external_ref,
            display_name=payload.display_name,
            active=payload.active,
            phone_number=payload.phone_number,
            email=payload.email,
        )
    except StudentNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except DuplicateStudentError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return _student_response(student)


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
# Sesiones de clase y asistencia (HU-S1, HU-S2)
# --------------------------------------------------------------------------


@app.post(
    "/courses/{course_id}/syllabus",
    response_model=SyllabusEntryResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["sesiones"],
)
def set_syllabus_entry(
    course_id: int, payload: SyllabusEntryRequest, session_service=Depends(get_session_service)
) -> SyllabusEntryResponse:
    """Registra (o reemplaza) el tema previsto para una fecha. Es lo que
    el sistema propone al iniciar una sesión ese día."""
    try:
        entry = session_service.set_syllabus_entry(course_id, payload.session_date, payload.topic)
    except CourseNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return SyllabusEntryResponse(
        id=entry.id, course_id=entry.course_id, session_date=entry.session_date, topic=entry.topic
    )


@app.get(
    "/courses/{course_id}/syllabus", response_model=List[SyllabusEntryResponse], tags=["sesiones"]
)
def list_syllabus(
    course_id: int, session_service=Depends(get_session_service)
) -> List[SyllabusEntryResponse]:
    try:
        entries = session_service.list_syllabus(course_id)
    except CourseNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return [
        SyllabusEntryResponse(id=e.id, course_id=e.course_id, session_date=e.session_date, topic=e.topic)
        for e in entries
    ]


@app.get(
    "/courses/{course_id}/class-sessions/proposal",
    response_model=SessionProposalResponse,
    tags=["sesiones"],
)
def propose_session(
    course_id: int,
    session_date: Optional[date] = None,
    session_service=Depends(get_session_service),
) -> SessionProposalResponse:
    """HU-S1: fecha (hoy por defecto) y tema propuesto (del sílabo, si existe)
    para mostrar al docente ANTES de iniciar la sesión."""
    try:
        proposal = session_service.propose(course_id, session_date)
    except CourseNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return SessionProposalResponse(
        session_date=proposal.session_date, suggested_topic=proposal.suggested_topic
    )


@app.post(
    "/courses/{course_id}/class-sessions",
    response_model=SessionDetailResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["sesiones"],
)
def start_class_session(
    course_id: int, payload: SessionStartRequest, session_service=Depends(get_session_service)
) -> SessionDetailResponse:
    """HU-S1: inicia una sesión de clase con el tema confirmado/corregido
    por el docente y deja registrada la asistencia inicial (por defecto,
    todos los estudiantes activos presentes)."""
    try:
        detail = session_service.start_session(
            course_id,
            topic=payload.topic,
            session_date=payload.session_date,
            present_student_ids=payload.present_student_ids,
            label=payload.label,
        )
    except CourseNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except (InvalidAttendanceError, ValueError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return _session_detail_response(detail)


@app.get(
    "/courses/{course_id}/class-sessions",
    response_model=List[SessionSummaryResponse],
    tags=["sesiones"],
)
def list_class_sessions(
    course_id: int, session_service=Depends(get_session_service)
) -> List[SessionSummaryResponse]:
    try:
        sessions = session_service.list_sessions(course_id)
    except CourseNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return [
        SessionSummaryResponse(
            id=x.id, course_id=x.course_id, session_date=x.session_date,
            topic=x.topic, label=x.label, created_at=x.created_at,
        )
        for x in sessions
    ]


@app.get(
    "/class-sessions/{class_session_id}", response_model=SessionDetailResponse, tags=["sesiones"]
)
def get_class_session(
    class_session_id: int, session_service=Depends(get_session_service)
) -> SessionDetailResponse:
    try:
        detail = session_service.get_session(class_session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return _session_detail_response(detail)


@app.put(
    "/class-sessions/{class_session_id}/attendance",
    response_model=SessionDetailResponse,
    tags=["sesiones"],
)
def update_attendance(
    class_session_id: int,
    payload: AttendanceUpdateRequest,
    session_service=Depends(get_session_service),
) -> SessionDetailResponse:
    """HU-S2: marca o desmarca la asistencia de uno o varios estudiantes.
    La selección posterior (`present_student_ids` omitido) usa esta marca."""
    try:
        detail = session_service.set_attendance(
            class_session_id, {m.student_id: m.present for m in payload.attendance}
        )
    except SessionNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except InvalidAttendanceError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return _session_detail_response(detail)


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
