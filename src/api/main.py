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
from datetime import date, datetime, timezone
import os
from pathlib import Path
from typing import List, Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from urllib.parse import quote

from src.domain.entities import GroupExpositionMemberEntry, StudentGroup
from src.api.dependencies import (
    current_user,
    get_fairness_service,
    get_group_exposition_service,
    get_group_planning_service,
    get_grade_analysis_service,
    get_material_service,
    get_roster_service,
    get_selection_service,
    get_session_service,
    new_unit_of_work,
    require_admin,
    require_class_session_access,
    require_course_access,
    require_student_access,
)
from src.api.schemas import (
    AcademicCycleCreateRequest,
    AcademicCycleResponse,
    AcademicCycleStartDateRequest,
    AcademicCycleUpdateRequest,
    AuthenticatedUserResponse,
    AttendanceEntryResponse,
    AttendanceUpdateRequest,
    AvailableMethodsResponse,
    CourseCreateRequest,
    CourseMaterialResponse,
    CourseResponse,
    ExposureTimeSettingsRequest,
    ExposureTimeSettingsResponse,
    DecisionResultResponse,
    FairnessMetricsResponse,
    WeeklyGradesResponse,
    WeeklyParticipationDetailsResponse,
    GroupExpositionCreateRequest,
    GroupExpositionResponse,
    GroupExpositionUpdateRequest,
    WeeklyGroupExpositionDetailsResponse,
    GroupPlanGenerateRequest,
    GroupPlanResponse,
    GroupPlanUpdateRequest,
    ManualGroupPlanRequest,
    LoginRequest,
    ParticipationBatchRequest,
    ParticipationGradeVisibilityRequest,
    ParticipationResponse,
    RosterImportResponse,
    RosterRowErrorResponse,
    RunSelectionRequest,
    SelectionEventResponse,
    SessionDetailResponse,
    SessionProposalResponse,
    SessionStartRequest,
    SessionSummaryResponse,
    StudentGroupResponse,
    StudentEnrollRequest,
    StudentEnrollmentResponse,
    StudentResponse,
    StudentAccountCreateRequest,
    StudentAccountCreatedResponse,
    StudentAccountResponse,
    StudentCourseResponse,
    StudentParticipationHistoryResponse,
    StudentWeekResponse,
    StudentWeeksResponse,
    StudentStateResponse,
    StudentUpdateRequest,
    TeacherAssignmentResponse,
    TeacherActiveRequest,
    TeacherCreatedResponse,
    TeacherCreateRequest,
    TeacherCourseAssignmentRequest,
    TeacherUpdateRequest,
    PasswordChangeRequest,
    TemporaryPasswordResponse,
    SyllabusEntryRequest,
    SyllabusEntryResponse,
)
from src.repositories.interfaces import (
    AcademicCycleInUseError,
    DuplicateAcademicCycleError,
    DuplicateStudentError,
    InvalidParticipationStudentError,
    ParticipationDecisionNotFoundError,
    UnitOfWork,
)
from src.services.bootstrap import build_app_context
from src.services.auth_service import AuthenticatedUser
from src.services.auth_service import (
    ROLE_ADMIN,
    ROLE_STUDENT,
    ROLE_TEACHER,
    hash_initial_student_password,
)
from src.services.errors import (
    CourseNotFoundError,
    InvalidAttendanceError,
    SessionNotFoundError,
    StudentNotFoundError,
)
from src.services.group_exposition_service import (
    GroupExpositionNotFoundError,
    GroupExpositionService,
    InvalidGroupExpositionError,
)
from src.services.group_planning_service import (
    GroupPlanNotFoundError,
    GroupPlanningService,
    InvalidGroupPlanError,
)
from src.services.grade_analysis_service import GradeAnalysisError, GradeAnalysisService
from src.services.material_service import (
    MAX_MATERIAL_FILE_BYTES,
    CourseMaterialNotFoundError,
    CourseMaterialService,
    MaterialFormatError,
)
from src.services.roster_import import MAX_FILE_BYTES, RosterFormatError
from src.services.roster_service import RosterAlreadyImportedError
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


@app.middleware("http")
async def authenticate_requests(request: Request, call_next):
    public_paths = {"/", "/health", "/auth/login", "/auth/logout"}
    if (
        request.url.path not in public_paths
        and not request.url.path.startswith("/assets/")
        and hasattr(request.app.state, "app_context")
    ):
        user = request.app.state.app_context.auth_service.user_for_token(
            request.cookies.get("aula_session")
        )
        if user is None:
            return JSONResponse(
                {"detail": "Inicia sesión para continuar."},
                status_code=status.HTTP_401_UNAUTHORIZED,
            )
        request.state.authenticated_user = user
        if (
            user.must_change_password
            and request.url.path not in {"/auth/me", "/auth/change-password", "/auth/logout"}
        ):
            return JSONResponse(
                {"detail": "Debes configurar una contraseña nueva antes de continuar."},
                status_code=status.HTTP_403_FORBIDDEN,
            )
    response = await call_next(request)
    if request.method != "GET" and (
        request.url.path.startswith("/auth/")
        or request.url.path.startswith("/admin/teachers")
        or request.url.path.startswith("/admin/students")
        or request.url.path.endswith("/students/import")
        or request.url.path.endswith("/students")
        or request.url.path.endswith("/reset-password")
        or "/materials" in request.url.path
    ):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/health", tags=["infraestructura"])
def health() -> dict:
    return {"status": "ok"}


@app.post("/auth/login", response_model=AuthenticatedUserResponse, tags=["autenticación"])
def login(payload: LoginRequest, request: Request, response: Response) -> AuthenticatedUserResponse:
    result = request.app.state.app_context.auth_service.login(
        payload.username.strip(), payload.password
    )
    if result is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Usuario o contraseña incorrectos.")
    token, user = result
    response.set_cookie(
        "aula_session",
        token,
        max_age=12 * 60 * 60,
        httponly=True,
        secure=os.environ.get("AUTH_COOKIE_SECURE", "false").lower() == "true",
        samesite="strict",
        path="/",
    )
    return AuthenticatedUserResponse(**user.__dict__)


@app.get("/auth/me", response_model=AuthenticatedUserResponse, tags=["autenticación"])
def who_am_i(user: AuthenticatedUser = Depends(current_user)) -> AuthenticatedUserResponse:
    return AuthenticatedUserResponse(**user.__dict__)


@app.post(
    "/auth/change-password",
    response_model=AuthenticatedUserResponse,
    tags=["autenticación"],
)
def change_password(
    payload: PasswordChangeRequest,
    request: Request,
    user: AuthenticatedUser = Depends(current_user),
) -> AuthenticatedUserResponse:
    updated = request.app.state.app_context.auth_service.change_password(
        user.id,
        payload.new_password,
        request.cookies.get("aula_session"),
    )
    return AuthenticatedUserResponse(**updated.__dict__)


@app.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT, tags=["autenticación"])
def logout(request: Request, response: Response) -> None:
    request.app.state.app_context.auth_service.logout(request.cookies.get("aula_session"))
    response.delete_cookie(
        "aula_session",
        path="/",
        httponly=True,
        secure=os.environ.get("AUTH_COOKIE_SECURE", "false").lower() == "true",
        samesite="strict",
    )


# Fecha de reserva para `created_at` en filas heredadas de una base anterior
# al Sprint 1, donde la columna admitia NULL. Ver `_student_response`.
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


@app.get(
    "/methods", response_model=AvailableMethodsResponse, tags=["infraestructura"],
    dependencies=[Depends(current_user)],
)
def list_methods() -> AvailableMethodsResponse:
    """Estrategias de selección registradas y disponibles para usar en
    `POST /courses/{course_id}/sessions/select`.
    """
    return AvailableMethodsResponse(methods=SelectorRegistry.available())


def _student_response(s) -> StudentResponse:
    return StudentResponse(
        id=s.id, course_id=s.course_id, external_ref=s.external_ref,
display_name=s.display_name,
        # `created_at` puede venir en None en una base creada antes del
        # Sprint 1: la migracion de `bootstrap.py` aniade las columnas nuevas
        # (students.active, class_sessions.session_date/topic), pero NO rellena
        # created_at en las filas que ya existian, porque en el esquema
        # anterior se permitia que fuera NULL.
        #
        # Sin este defecto, toda la API devolvio 500 al abrir un curso
        # importado de una instalacion previa. Se resuelve con la epoca: es
        # una fecha verosimil y, sobre todo, el campo es obligatorio en el
        # esquema nuevo, asi que no puede quedar en null.
        created_at=s.created_at or _EPOCH,
        active=s.active,
        # Telefono y email llegan de la carga de estudiantes (HU-C1). Son
        # opcionales: un estudiante importado antes de que existieran esas
        # columnas los tiene en None, y eso tiene que ser valido.
        phone_number=s.phone_number, email=s.email,
        user_id=s.user_id,
        roster_number=s.roster_number,
        specialty=s.specialty,
        student_condition=s.student_condition,
        times_repeated=s.times_repeated,
    )


def _course_response(course) -> CourseResponse:
    return CourseResponse(
        id=course.id,
        name=course.name,
        created_at=course.created_at,
        cycle_id=course.cycle_id,
        roster_imported=course.roster_imported_at is not None,
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


def _require_cycle_editor(user: AuthenticatedUser) -> AuthenticatedUser:
    """HU-C3: el docente gestiona sus ciclos; el Administrador conserva el
    acceso completo. Los estudiantes no gestionan ciclos."""
    if user.role not in (ROLE_ADMIN, ROLE_TEACHER):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Solo docentes y administradores gestionan ciclos."
        )
    return user


def _can_manage_cycle(user: AuthenticatedUser, cycle) -> bool:
    if user.role == ROLE_ADMIN:
        return True
    return user.role == ROLE_TEACHER and cycle.owner_teacher_id == user.id


def _cycle_response(cycle, user: AuthenticatedUser, course_count: int) -> AcademicCycleResponse:
    return AcademicCycleResponse(
        id=cycle.id,
        name=cycle.name,
        created_at=cycle.created_at,
        starts_on=cycle.starts_on,
        ends_on=cycle.ends_on,
        enabled=cycle.enabled,
        owner_teacher_id=cycle.owner_teacher_id,
        course_count=course_count,
        can_manage=_can_manage_cycle(user, cycle),
    )


def _managed_cycle_or_error(uow: UnitOfWork, cycle_id: int, user: AuthenticatedUser):
    cycle = uow.cycles.get(cycle_id)
    if cycle is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Ciclo {cycle_id} no encontrado.")
    if not _can_manage_cycle(user, cycle):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Solo el docente que creó el ciclo puede modificarlo."
        )
    return cycle


@app.post(
    "/cycles",
    response_model=AcademicCycleResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["ciclos"],
)
def create_cycle(
    payload: AcademicCycleCreateRequest,
    user: AuthenticatedUser = Depends(current_user),
    uow: UnitOfWork = Depends(new_unit_of_work),
) -> AcademicCycleResponse:
    """HU-C3: registra un ciclo académico. Si lo crea un docente, queda
    como dueño; si lo crea el Administrador, el ciclo no tiene dueño."""
    _require_cycle_editor(user)
    owner_id = user.id if user.role == ROLE_TEACHER else None
    try:
        with uow:
            cycle = uow.cycles.create(
                payload.name,
                starts_on=payload.starts_on,
                ends_on=payload.ends_on,
                owner_teacher_id=owner_id,
            )
            uow.commit()
    except DuplicateAcademicCycleError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return _cycle_response(cycle, user, course_count=0)


@app.patch(
    "/cycles/{cycle_id}",
    response_model=AcademicCycleResponse,
    tags=["ciclos"],
)
def update_cycle(
    cycle_id: int,
    payload: AcademicCycleUpdateRequest,
    user: AuthenticatedUser = Depends(current_user),
    uow: UnitOfWork = Depends(new_unit_of_work),
) -> AcademicCycleResponse:
    """HU-C3: modifica nombre, fechas o estado (habilitado/deshabilitado)
    del ciclo. Deshabilitar lo da de baja sin borrarlo."""
    _require_cycle_editor(user)
    sent = payload.model_fields_set
    if "name" in sent and payload.name is None:
        raise HTTPException(422, "El nombre no puede quedar vacío.")
    if "starts_on" in sent and payload.starts_on is None:
        raise HTTPException(
            422, "La fecha de inicio no puede quedar vacía."
        )
    try:
        with uow:
            current = _managed_cycle_or_error(uow, cycle_id, user)
            new_starts = payload.starts_on if "starts_on" in sent else current.starts_on
            new_ends = payload.ends_on if "ends_on" in sent else current.ends_on
            if new_starts and new_ends and new_ends < new_starts:
                raise HTTPException(
                    422,
                    "La fecha de fin no puede ser anterior a la fecha de inicio.",
                )
            cycle = uow.cycles.update(
                cycle_id,
                name=payload.name,
                starts_on=payload.starts_on,
                ends_on=payload.ends_on,
                enabled=payload.enabled,
                clear_ends_on="ends_on" in sent and payload.ends_on is None,
            )
            course_count = uow.cycles.count_courses(cycle_id)
            uow.commit()
    except DuplicateAcademicCycleError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return _cycle_response(cycle, user, course_count)


@app.delete(
    "/cycles/{cycle_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["ciclos"],
)
def delete_cycle(
    cycle_id: int,
    user: AuthenticatedUser = Depends(current_user),
    uow: UnitOfWork = Depends(new_unit_of_work),
) -> Response:
    """HU-C3: la eliminación definitiva solo procede si el ciclo no tiene
    cursos asociados; en otro caso debe deshabilitarse."""
    _require_cycle_editor(user)
    try:
        with uow:
            _managed_cycle_or_error(uow, cycle_id, user)
            uow.cycles.delete(cycle_id)
            uow.commit()
    except AcademicCycleInUseError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get(
    "/cycles", response_model=List[AcademicCycleResponse], tags=["ciclos"],
    dependencies=[Depends(current_user)],
)
def list_cycles(
    request: Request,
    user: AuthenticatedUser = Depends(current_user),
    uow: UnitOfWork = Depends(new_unit_of_work),
) -> List[AcademicCycleResponse]:
    with uow:
        cycles = uow.cycles.list_all()
        if user.role != ROLE_ADMIN:
            allowed_ids = set(
                request.app.state.app_context.auth_service.cycle_ids_for_user(user)
            )
            cycles = [cycle for cycle in cycles if cycle.id in allowed_ids]
        counts = {cycle.id: uow.cycles.count_courses(cycle.id) for cycle in cycles}
    return [_cycle_response(cycle, user, counts[cycle.id]) for cycle in cycles]


@app.get(
    "/student/courses",
    response_model=List[StudentCourseResponse],
    tags=["estudiantes"],
    dependencies=[Depends(current_user)],
)
def list_student_courses(
    request: Request, user: AuthenticatedUser = Depends(current_user)
) -> List[StudentCourseResponse]:
    if user.role != ROLE_STUDENT:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Este recurso es exclusivo para estudiantes.")
    courses = request.app.state.app_context.auth_service.student_courses(user.id)
    return [StudentCourseResponse(**course) for course in courses]


@app.get(
    "/student/courses/{course_id}/weeks",
    response_model=StudentWeeksResponse,
    tags=["estudiantes"],
    dependencies=[Depends(current_user)],
)
def list_student_course_weeks(
    course_id: int,
    request: Request,
    user: AuthenticatedUser = Depends(current_user),
    uow: UnitOfWork = Depends(new_unit_of_work),
    session_service=Depends(get_session_service),
) -> StudentWeeksResponse:
    if user.role != ROLE_STUDENT:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Este recurso es exclusivo para estudiantes.")
    if not request.app.state.app_context.auth_service.has_course_access(user, course_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No se encontró el curso matriculado.")
    with uow:
        course = uow.courses.get(course_id)
        cycle = uow.cycles.get(course.cycle_id) if course and course.cycle_id else None
    if course is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No se encontró el curso matriculado.")
    cycle_starts_on = cycle.starts_on if cycle else None
    sessions = session_service.list_sessions(course_id)
    grouped: list[list[SessionSummaryResponse]] = [[] for _ in range(16)]
    unassigned: list[SessionSummaryResponse] = []
    for item in sessions:
        session = SessionSummaryResponse(
            id=item.id,
            course_id=item.course_id,
            session_date=item.session_date,
            topic=item.topic,
            label=item.label,
            created_at=item.created_at,
        )
        if item.session_date is None or cycle_starts_on is None:
            unassigned.append(session)
            continue
        day_offset = (item.session_date - cycle_starts_on).days
        week_number = day_offset // 7 + 1
        if 1 <= week_number <= 16:
            grouped[week_number - 1].append(session)
        else:
            unassigned.append(session)
    return StudentWeeksResponse(
        course_id=course_id,
        cycle_starts_on=cycle_starts_on,
        weeks=(
            [
                StudentWeekResponse(week_number=index + 1, sessions=week_sessions)
                for index, week_sessions in enumerate(grouped)
            ]
            if cycle_starts_on is not None
            else []
        ),
        unassigned_sessions=unassigned,
    )


@app.get(
    "/student/history",
    response_model=List[StudentParticipationHistoryResponse],
    tags=["estudiantes"],
    dependencies=[Depends(current_user)],
)
def list_student_participation_history(
    request: Request,
    user: AuthenticatedUser = Depends(current_user),
) -> List[StudentParticipationHistoryResponse]:
    if user.role != ROLE_STUDENT:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Este recurso es exclusivo para estudiantes.")
    history = request.app.state.app_context.auth_service.student_participation_history(
        user.id
    )
    return [StudentParticipationHistoryResponse(**entry) for entry in history]


@app.get(
    "/admin/teachers",
    response_model=List[TeacherAssignmentResponse],
    tags=["administración"],
    dependencies=[Depends(require_admin)],
)
def list_teachers(request: Request) -> List[TeacherAssignmentResponse]:
    teachers = request.app.state.app_context.auth_service.teachers()
    return [TeacherAssignmentResponse(**teacher) for teacher in teachers]


@app.get(
    "/admin/students",
    response_model=List[StudentAccountResponse],
    tags=["administración"],
    dependencies=[Depends(require_admin)],
)
def list_student_accounts(request: Request) -> List[StudentAccountResponse]:
    accounts = request.app.state.app_context.auth_service.students()
    return [StudentAccountResponse(**account) for account in accounts]


@app.post(
    "/admin/students",
    response_model=StudentAccountCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["administración"],
    dependencies=[Depends(require_admin)],
)
def create_student_account(
    payload: StudentAccountCreateRequest, request: Request
) -> StudentAccountCreatedResponse:
    try:
        account, temporary_password = request.app.state.app_context.auth_service.create_student(
            payload.username, payload.full_name, payload.email
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return StudentAccountCreatedResponse(**account, temporary_password=temporary_password)


@app.post(
    "/admin/students/{student_id}/reset-password",
    response_model=TemporaryPasswordResponse,
    tags=["administración"],
    dependencies=[Depends(require_admin)],
)
def reset_student_account_password(student_id: int, request: Request) -> TemporaryPasswordResponse:
    try:
        temporary_password = request.app.state.app_context.auth_service.reset_student_password(
            student_id
        )
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return TemporaryPasswordResponse(temporary_password=temporary_password)


@app.post(
    "/admin/teachers",
    response_model=TeacherCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["administración"],
    dependencies=[Depends(require_admin)],
)
def create_teacher(
    payload: TeacherCreateRequest, request: Request
) -> TeacherCreatedResponse:
    try:
        teacher, temporary_password = request.app.state.app_context.auth_service.create_teacher(
            username=payload.username,
            full_name=payload.full_name,
            dni=payload.dni,
            email=payload.email,
            phone_number=payload.phone_number,
            course_ids=payload.course_ids,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return TeacherCreatedResponse(**teacher, temporary_password=temporary_password)


@app.put(
    "/admin/teachers/{teacher_id}",
    response_model=TeacherAssignmentResponse,
    tags=["administración"],
    dependencies=[Depends(require_admin)],
)
def update_teacher(
    teacher_id: int, payload: TeacherUpdateRequest, request: Request
) -> TeacherAssignmentResponse:
    try:
        teacher = request.app.state.app_context.auth_service.update_teacher(
            teacher_id=teacher_id,
            username=payload.username,
            full_name=payload.full_name,
            dni=payload.dni,
            email=payload.email,
            phone_number=payload.phone_number,
        )
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return TeacherAssignmentResponse(**teacher)


@app.patch(
    "/admin/teachers/{teacher_id}/status",
    response_model=TeacherAssignmentResponse,
    tags=["administración"],
    dependencies=[Depends(require_admin)],
)
def set_teacher_status(
    teacher_id: int, payload: TeacherActiveRequest, request: Request
) -> TeacherAssignmentResponse:
    try:
        teacher = request.app.state.app_context.auth_service.set_teacher_active(
            teacher_id, payload.active
        )
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return TeacherAssignmentResponse(**teacher)


@app.post(
    "/admin/teachers/{teacher_id}/reset-password",
    response_model=TemporaryPasswordResponse,
    tags=["administración"],
    dependencies=[Depends(require_admin)],
)
def reset_teacher_password(teacher_id: int, request: Request) -> TemporaryPasswordResponse:
    try:
        temporary_password = request.app.state.app_context.auth_service.reset_teacher_password(
            teacher_id
        )
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return TemporaryPasswordResponse(temporary_password=temporary_password)


@app.put(
    "/admin/teachers/{teacher_id}/courses",
    response_model=TeacherAssignmentResponse,
    tags=["administración"],
    dependencies=[Depends(require_admin)],
)
def assign_teacher_courses(
    teacher_id: int,
    payload: TeacherCourseAssignmentRequest,
    request: Request,
) -> TeacherAssignmentResponse:
    auth_service = request.app.state.app_context.auth_service
    try:
        updated = auth_service.assign_courses(teacher_id, payload.course_ids)
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    if not updated:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Docente {teacher_id} no encontrado.")
    teacher = next(
        (item for item in auth_service.teachers() if item["id"] == teacher_id), None
    )
    if teacher is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Docente {teacher_id} no encontrado.")
    return TeacherAssignmentResponse(**teacher)


@app.post(
    "/courses", response_model=CourseResponse, status_code=status.HTTP_201_CREATED, tags=["cursos"],
    dependencies=[Depends(require_admin)],
)
def create_course(payload: CourseCreateRequest, uow: UnitOfWork = Depends(new_unit_of_work)) -> CourseResponse:
    with uow:
        if payload.cycle_id is not None:
            target_cycle = uow.cycles.get(payload.cycle_id)
            if target_cycle is None:
                raise HTTPException(
                    status.HTTP_404_NOT_FOUND, f"Ciclo {payload.cycle_id} no encontrado."
                )
            if not target_cycle.enabled:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    f"El ciclo “{target_cycle.name}” está deshabilitado y no admite cursos nuevos.",
                )
        course = uow.courses.create(payload.name, cycle_id=payload.cycle_id)
        uow.commit()
    return _course_response(course)


@app.get(
    "/courses", response_model=List[CourseResponse], tags=["cursos"],
    dependencies=[Depends(current_user)],
)
def list_courses(
    request: Request,
    user: AuthenticatedUser = Depends(current_user),
    uow: UnitOfWork = Depends(new_unit_of_work),
) -> List[CourseResponse]:
    """Todos los cursos (HU-S1: el docente elige el curso de la sesión)."""
    if user.role == ROLE_STUDENT:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Consulta los cursos y sesiones desde el portal de estudiante.",
        )
    with uow:
        courses = uow.courses.list_all()
    allowed_ids = set(request.app.state.app_context.auth_service.course_ids_for_user(user))
    courses = [course for course in courses if course.id in allowed_ids]
    return [_course_response(course) for course in courses]


@app.get(
    "/courses/{course_id}", response_model=CourseResponse, tags=["cursos"],
    dependencies=[Depends(require_course_access)],
)
def get_course(course_id: int, uow: UnitOfWork = Depends(new_unit_of_work)) -> CourseResponse:
    with uow:
        course = uow.courses.get(course_id)
    if course is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Curso {course_id} no encontrado.")
    return _course_response(course)


# --------------------------------------------------------------------------
# Material académico (HU-M1)
# --------------------------------------------------------------------------


def _course_material_response(material) -> CourseMaterialResponse:
    return CourseMaterialResponse(
        id=material.id,
        course_id=material.course_id,
        class_session_id=material.class_session_id,
        file_name=material.file_name,
        title=material.title,
        topic=material.topic,
        content_type=material.content_type,
        size_bytes=material.size_bytes,
        created_at=material.created_at,
        updated_at=material.updated_at,
    )


@app.get(
    "/courses/{course_id}/materials",
    response_model=List[CourseMaterialResponse],
    tags=["material académico"],
    dependencies=[Depends(require_course_access)],
)
def list_course_materials(
    course_id: int,
    material_service: CourseMaterialService = Depends(get_material_service),
) -> List[CourseMaterialResponse]:
    try:
        return [
            _course_material_response(material)
            for material in material_service.list_for_course(course_id)
        ]
    except CourseNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


@app.post(
    "/courses/{course_id}/materials",
    response_model=CourseMaterialResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["material académico"],
    dependencies=[Depends(require_course_access)],
)
def upload_course_material(
    course_id: int,
    file: UploadFile = File(...),
    title: Optional[str] = Form(None, max_length=255),
    topic: Optional[str] = Form(None, max_length=255),
    class_session_id: Optional[int] = Form(None, gt=0),
    material_service: CourseMaterialService = Depends(get_material_service),
) -> CourseMaterialResponse:
    file_data = file.file.read(MAX_MATERIAL_FILE_BYTES + 1)
    try:
        material = material_service.upload(
            course_id=course_id,
            file_name=file.filename or "",
            file_data=file_data,
            title=title,
            topic=topic,
            class_session_id=class_session_id,
        )
    except CourseNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except SessionNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except MaterialFormatError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return _course_material_response(material)


@app.get(
    "/courses/{course_id}/materials/{material_id}/content",
    tags=["material académico"],
    dependencies=[Depends(require_course_access)],
)
def download_course_material(
    course_id: int,
    material_id: int,
    material_service: CourseMaterialService = Depends(get_material_service),
) -> Response:
    try:
        content = material_service.get_content(course_id, material_id)
    except CourseNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except CourseMaterialNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    response = Response(
        content=content.file_data,
        media_type=content.content_type,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(content.file_name)}",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        },
    )
    return response


@app.get(
    "/courses/{course_id}/materials/{material_id}/text",
    response_class=PlainTextResponse,
    tags=["material académico"],
    dependencies=[Depends(require_course_access)],
)
def read_course_material_text(
    course_id: int,
    material_id: int,
    material_service: CourseMaterialService = Depends(get_material_service),
) -> PlainTextResponse:
    try:
        content = material_service.get_content(course_id, material_id)
    except CourseNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except CourseMaterialNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return PlainTextResponse(content.extracted_text, headers={"Cache-Control": "no-store"})


@app.put(
    "/courses/{course_id}/materials/{material_id}",
    response_model=CourseMaterialResponse,
    tags=["material académico"],
    dependencies=[Depends(require_course_access)],
)
def replace_course_material(
    course_id: int,
    material_id: int,
    file: UploadFile = File(...),
    material_service: CourseMaterialService = Depends(get_material_service),
) -> CourseMaterialResponse:
    file_data = file.file.read(MAX_MATERIAL_FILE_BYTES + 1)
    try:
        material = material_service.replace_file(
            course_id, material_id, file.filename or "", file_data
        )
    except CourseNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except CourseMaterialNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except MaterialFormatError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return _course_material_response(material)


@app.delete(
    "/courses/{course_id}/materials/{material_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["material académico"],
    dependencies=[Depends(require_course_access)],
)
def delete_course_material(
    course_id: int,
    material_id: int,
    material_service: CourseMaterialService = Depends(get_material_service),
) -> None:
    try:
        material_service.delete(course_id, material_id)
    except CourseNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except CourseMaterialNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


# --------------------------------------------------------------------------
# Estudiantes
# --------------------------------------------------------------------------


@app.post(
    "/courses/{course_id}/students",
    response_model=StudentEnrollmentResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["estudiantes"],
    dependencies=[Depends(require_course_access)],
)
def enroll_student(
    course_id: int,
    payload: StudentEnrollRequest,
    uow: UnitOfWork = Depends(new_unit_of_work),
) -> StudentEnrollmentResponse:
    """Matricula un estudiante en el curso (idempotente por `external_ref`).

    Es el equivalente en producción a `Student(student_id=i, ...)` en la
    simulación: la diferencia es que aquí crea también la fila de
    `student_state` en `Beta(alpha_init, beta_init)` de forma persistente,
    en vez de un objeto que muere al terminar la corrida.
    """
    with uow:
        normalized_email = payload.email.strip().lower() if payload.email else None
        username_account = uow.student_accounts.get_by_username(payload.external_ref)
        email_account = (
            uow.student_accounts.get_by_email(normalized_email)
            if normalized_email
            else None
        )
        if (
            username_account is not None
            and email_account is not None
            and username_account.id != email_account.id
        ):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "El código y el correo ya pertenecen a cuentas diferentes.",
            )
        account = email_account or username_account
        if account is not None and account.role != ROLE_STUDENT:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "El código o correo ya pertenece a una cuenta que no es de estudiante.",
            )
        if account is not None and not account.active:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "La cuenta de estudiante asociada está inactiva.",
            )
        if (
            account is not None
            and account.email
            and normalized_email
            and account.email.strip().lower() != normalized_email
        ):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "El código ya pertenece a una cuenta asociada a otro correo.",
            )
        temporary_password = None
        if account is None:
            temporary_password = payload.external_ref
            account = uow.student_accounts.create_student(
                username=payload.external_ref,
                full_name=payload.display_name,
                email=normalized_email,
                password_hash=hash_initial_student_password(temporary_password),
            )
        elif account.username != payload.external_ref:
            account = uow.student_accounts.update_username(account.id, payload.external_ref)
        student = uow.students.get_or_create(
            course_id=course_id,
            external_ref=payload.external_ref,
            display_name=payload.display_name,
            alpha_init=payload.alpha_init,
            beta_init=payload.beta_init,
            phone_number=payload.phone_number,
            email=normalized_email,
            user_id=account.id,
        )
        uow.commit()
    return StudentEnrollmentResponse(
        **_student_response(student).model_dump(),
        account_username=account.username,
        temporary_password=temporary_password,
    )


@app.post(
    "/courses/{course_id}/students/import",
    response_model=RosterImportResponse,
    tags=["estudiantes"],
    dependencies=[Depends(require_course_access)],
)
def import_students_from_excel(
    course_id: int,
    response: Response,
    file: UploadFile = File(..., description="Excel .xlsx con columnas de código y nombre."),
    roster_service=Depends(get_roster_service),
) -> RosterImportResponse:
    """HU-C1: carga la lista de estudiantes desde un Excel.

    Encabezados aceptados: `codigo` (o matrícula) y `nombre` (o apellidos y
    nombres). Las filas válidas se guardan; las inválidas se devuelven en
    `errors` con su número de fila. Si el archivo no tiene la estructura
    esperada, responde 400 y no se guarda nada. Para cursos asociados a un
    ciclo, solo se permite una carga con filas válidas; los cursos históricos
    sin ciclo conservan su comportamiento idempotente.
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
    except RosterAlreadyImportedError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    response.headers["Cache-Control"] = "no-store"
    return RosterImportResponse(
        total_rows=result.total_rows,
        created=result.created,
        updated=result.updated,
        unchanged=result.unchanged,
        errors=[RosterRowErrorResponse(row=e.row_number, message=e.message) for e in result.errors],
        warnings=[
            RosterRowErrorResponse(row=warning.row_number, message=warning.message)
            for warning in result.warnings
        ],
        created_accounts=result.created_accounts,
        updated_accounts=result.updated_accounts,
    )


@app.get(
    "/courses/{course_id}/students", response_model=List[StudentResponse], tags=["estudiantes"],
    dependencies=[Depends(require_course_access)],
)
def list_students(
    course_id: int, include_inactive: bool = False, uow: UnitOfWork = Depends(new_unit_of_work)
) -> List[StudentResponse]:
    """Lista del curso. Por defecto solo estudiantes activos; con
    `include_inactive=true` también los retirados."""
    with uow:
        students = uow.students.list_by_course(course_id, include_inactive=include_inactive)
    return [_student_response(s) for s in students]


@app.patch(
    "/students/{student_id}", response_model=StudentResponse, tags=["estudiantes"],
    dependencies=[Depends(require_student_access)],
)
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


@app.post(
    "/students/{student_id}/reset-password",
    response_model=TemporaryPasswordResponse,
    tags=["estudiantes"],
    dependencies=[Depends(require_student_access)],
)
def reset_student_password(
    student_id: int,
    request: Request,
    uow: UnitOfWork = Depends(new_unit_of_work),
) -> TemporaryPasswordResponse:
    user: AuthenticatedUser = request.state.authenticated_user
    if user.role not in {ROLE_ADMIN, ROLE_TEACHER}:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo un docente o administrador puede restablecer la contraseña.")
    with uow:
        student = uow.students.get(student_id)
    if student is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Estudiante {student_id} no encontrado.")
    if student.user_id is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Este estudiante aún no tiene una cuenta asociada.")
    try:
        temporary_password = request.app.state.app_context.auth_service.reset_student_password(
            student.user_id
        )
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return TemporaryPasswordResponse(temporary_password=temporary_password)


@app.get(
    "/students/{student_id}/state", response_model=StudentStateResponse, tags=["estudiantes"],
    dependencies=[Depends(require_student_access)],
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
    dependencies=[Depends(require_student_access)],
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
    dependencies=[Depends(require_course_access)],
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
    "/courses/{course_id}/syllabus", response_model=List[SyllabusEntryResponse], tags=["sesiones"],
    dependencies=[Depends(require_course_access)],
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
    dependencies=[Depends(require_course_access)],
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


@app.get(
    "/courses/{course_id}/exposure-time-settings",
    response_model=ExposureTimeSettingsResponse,
    tags=["sesiones"],
    dependencies=[Depends(require_course_access)],
)
def get_exposure_time_settings(
    course_id: int,
    uow: UnitOfWork = Depends(new_unit_of_work),
) -> ExposureTimeSettingsResponse:
    with uow:
        if uow.courses.get(course_id) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Curso {course_id} no encontrado.")
        settings = uow.exposure_time_settings.get_or_create(course_id)
        uow.commit()
    return ExposureTimeSettingsResponse(
        course_id=settings.course_id,
        min_minutes=settings.min_minutes,
        max_minutes=settings.max_minutes,
        updated_at=settings.updated_at,
    )


@app.put(
    "/courses/{course_id}/exposure-time-settings",
    response_model=ExposureTimeSettingsResponse,
    tags=["sesiones"],
    dependencies=[Depends(require_course_access)],
)
def update_exposure_time_settings(
    course_id: int,
    payload: ExposureTimeSettingsRequest,
    uow: UnitOfWork = Depends(new_unit_of_work),
) -> ExposureTimeSettingsResponse:
    with uow:
        if uow.courses.get(course_id) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Curso {course_id} no encontrado.")
        settings = uow.exposure_time_settings.update(
            course_id, payload.min_minutes, payload.max_minutes
        )
        uow.commit()
    return ExposureTimeSettingsResponse(
        course_id=settings.course_id,
        min_minutes=settings.min_minutes,
        max_minutes=settings.max_minutes,
        updated_at=settings.updated_at,
    )


@app.post(
    "/courses/{course_id}/class-sessions",
    response_model=SessionDetailResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["sesiones"],
    dependencies=[Depends(require_course_access)],
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
    dependencies=[Depends(require_course_access)],
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
    "/class-sessions/{class_session_id}", response_model=SessionDetailResponse, tags=["sesiones"],
    dependencies=[Depends(require_class_session_access)],
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
    dependencies=[Depends(require_class_session_access)],
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
    dependencies=[Depends(require_course_access)],
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


@app.post(
    "/courses/{course_id}/decision-runs/{decision_run_id}/participations",
    response_model=List[ParticipationResponse],
    status_code=status.HTTP_201_CREATED,
    tags=["participación"],
    dependencies=[Depends(require_course_access)],
)
def record_participations(
    course_id: int,
    decision_run_id: int,
    payload: ParticipationBatchRequest,
    uow: UnitOfWork = Depends(new_unit_of_work),
) -> List[ParticipationResponse]:
    """Registra la nota y asistencia de los estudiantes seleccionados."""
    student_ids = [item.student_id for item in payload.participations]
    if len(student_ids) != len(set(student_ids)):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "No repitas un estudiante en el mismo registro de participación.",
        )
    try:
        with uow:
            records = uow.participations.record_many(
                course_id,
                decision_run_id,
                {
                    item.student_id: (item.score, item.present)
                    for item in payload.participations
                },
                {
                    item.student_id: (
                        (item.question or "").strip() or None,
                        (item.comment or "").strip() or None,
                        item.difficulty,
                        item.grade_visible,
                    )
                    for item in payload.participations
                },
            )
            uow.commit()
    except ParticipationDecisionNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except InvalidParticipationStudentError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return [ParticipationResponse(**record.__dict__) for record in records]


@app.get(
    "/courses/{course_id}/participations",
    response_model=List[ParticipationResponse],
    tags=["participación"],
    dependencies=[Depends(require_course_access)],
)
def list_course_participations(
    course_id: int,
    limit: int = 200,
    uow: UnitOfWork = Depends(new_unit_of_work),
) -> List[ParticipationResponse]:
    """Historial de notas y asistencia del curso, más reciente primero."""
    if not 1 <= limit <= 1000:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "El límite debe estar entre 1 y 1000."
        )
    with uow:
        records = uow.participations.list_by_course(course_id, limit=limit)
    return [ParticipationResponse(**record.__dict__) for record in records]


@app.patch(
    "/courses/{course_id}/participations/{participation_id}/visibility",
    response_model=ParticipationResponse,
    tags=["participación"],
    dependencies=[Depends(require_course_access)],
)
def update_participation_grade_visibility(
    course_id: int,
    participation_id: int,
    payload: ParticipationGradeVisibilityRequest,
    uow: UnitOfWork = Depends(new_unit_of_work),
) -> ParticipationResponse:
    with uow:
        record = uow.participations.set_grade_visibility(
            course_id, participation_id, payload.grade_visible
        )
        if record is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                "No se encontró la participación en el curso indicado.",
            )
        uow.commit()
    return ParticipationResponse(**record.__dict__)


@app.get(
    "/courses/{course_id}/weekly-grades",
    response_model=WeeklyGradesResponse,
    tags=["análisis académico"],
    dependencies=[Depends(require_course_access)],
)
def weekly_grades(
    course_id: int,
    cycle_id: int,
    grade_service: GradeAnalysisService = Depends(get_grade_analysis_service),
) -> WeeklyGradesResponse:
    try:
        result = grade_service.weekly_matrix(course_id, cycle_id)
    except CourseNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except GradeAnalysisError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return WeeklyGradesResponse(**result)


@app.get(
    "/courses/{course_id}/weekly-grades/details",
    response_model=WeeklyParticipationDetailsResponse,
    tags=["análisis académico"],
    dependencies=[Depends(require_course_access)],
)
def weekly_grade_details(
    course_id: int,
    cycle_id: int,
    student_id: int,
    week: int,
    grade_service: GradeAnalysisService = Depends(get_grade_analysis_service),
) -> WeeklyParticipationDetailsResponse:
    try:
        result = grade_service.weekly_participation_details(
            course_id, cycle_id, student_id, week
        )
    except CourseNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except GradeAnalysisError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return WeeklyParticipationDetailsResponse(**result)


@app.get(
    "/courses/{course_id}/weekly-group-grades/details",
    response_model=WeeklyGroupExpositionDetailsResponse,
    tags=["análisis académico"],
    dependencies=[Depends(require_course_access)],
)
def weekly_group_grade_details(
    course_id: int,
    cycle_id: int,
    student_id: int,
    week: int,
    grade_service: GradeAnalysisService = Depends(get_grade_analysis_service),
) -> WeeklyGroupExpositionDetailsResponse:
    try:
        result = grade_service.weekly_group_details(
            course_id, cycle_id, student_id, week
        )
    except CourseNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except GradeAnalysisError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return WeeklyGroupExpositionDetailsResponse(**result)


def _member_entries(members) -> List[GroupExpositionMemberEntry]:
    return [
        GroupExpositionMemberEntry(
            student_id=member.student_id,
            present=member.present,
            score=member.score,
            position=member.position,
        )
        for member in members
    ]


def _group_exposition_response(exposition) -> GroupExpositionResponse:
    return GroupExpositionResponse(
        id=exposition.id,
        course_id=exposition.course_id,
        group_name=exposition.group_name,
        group_score=exposition.group_score,
        members=[member.__dict__ for member in exposition.members],
        created_at=exposition.created_at,
        updated_at=exposition.updated_at,
        class_session_id=exposition.class_session_id,
        group_plan_id=exposition.group_plan_id,
        plan_name=exposition.plan_name,
        comment=exposition.comment,
        duration_seconds=exposition.duration_seconds,
    )


@app.post(
    "/courses/{course_id}/group-expositions",
    response_model=GroupExpositionResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["exposiciones"],
    dependencies=[Depends(require_course_access)],
)
def record_group_exposition(
    course_id: int,
    payload: GroupExpositionCreateRequest,
    exposition_service: GroupExpositionService = Depends(get_group_exposition_service),
) -> GroupExpositionResponse:
    """Registra la nota grupal y las notas individuales del grupo expositor."""
    try:
        exposition = exposition_service.record(
            course_id,
            group_name=payload.group_name,
            group_score=payload.group_score,
            members=_member_entries(payload.members),
            class_session_id=payload.class_session_id,
            group_plan_id=payload.group_plan_id,
            comment=payload.comment,
            duration_seconds=payload.duration_seconds,
        )
    except (CourseNotFoundError, SessionNotFoundError) as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except InvalidGroupExpositionError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return _group_exposition_response(exposition)


@app.put(
    "/courses/{course_id}/group-expositions/{exposition_id}",
    response_model=GroupExpositionResponse,
    tags=["exposiciones"],
    dependencies=[Depends(require_course_access)],
)
def update_group_exposition(
    course_id: int,
    exposition_id: int,
    payload: GroupExpositionUpdateRequest,
    exposition_service: GroupExpositionService = Depends(get_group_exposition_service),
) -> GroupExpositionResponse:
    """Corrige las notas de una exposición ya registrada."""
    try:
        exposition = exposition_service.update(
            course_id,
            exposition_id,
            group_score=payload.group_score,
            members=_member_entries(payload.members),
            comment=payload.comment,
            duration_seconds=payload.duration_seconds,
        )
    except (CourseNotFoundError, GroupExpositionNotFoundError) as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except InvalidGroupExpositionError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return _group_exposition_response(exposition)


@app.get(
    "/courses/{course_id}/group-expositions",
    response_model=List[GroupExpositionResponse],
    tags=["exposiciones"],
    dependencies=[Depends(require_course_access)],
)
def list_group_expositions(
    course_id: int,
    limit: int = 200,
    exposition_service: GroupExpositionService = Depends(get_group_exposition_service),
) -> List[GroupExpositionResponse]:
    """Exposiciones calificadas del curso, la más reciente primero."""
    if not 1 <= limit <= 1000:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "El límite debe estar entre 1 y 1000."
        )
    try:
        expositions = exposition_service.list_for_course(course_id, limit=limit)
    except CourseNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return [_group_exposition_response(exposition) for exposition in expositions]


@app.get(
    "/courses/{course_id}/group-expositions/{exposition_id}",
    response_model=GroupExpositionResponse,
    tags=["exposiciones"],
    dependencies=[Depends(require_course_access)],
)
def get_group_exposition(
    course_id: int,
    exposition_id: int,
    exposition_service: GroupExpositionService = Depends(get_group_exposition_service),
) -> GroupExpositionResponse:
    try:
        exposition = exposition_service.get(course_id, exposition_id)
    except (CourseNotFoundError, GroupExpositionNotFoundError) as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return _group_exposition_response(exposition)


def _group_plan_response(plan) -> GroupPlanResponse:
    return GroupPlanResponse(
        id=getattr(plan, "id", None),
        course_id=plan.course_id,
        name=plan.name,
        max_group_size=plan.max_group_size,
        groups=[
            StudentGroupResponse(name=group.name, student_ids=group.student_ids)
            for group in plan.groups
        ],
        created_at=plan.created_at,
    )


@app.get(
    "/courses/{course_id}/group-plans",
    response_model=List[GroupPlanResponse],
    tags=["grupos"],
    dependencies=[Depends(require_course_access)],
)
def list_group_plans(
    course_id: int,
    group_service: GroupPlanningService = Depends(get_group_planning_service),
) -> List[GroupPlanResponse]:
    try:
        plans = group_service.list_plans(course_id)
    except CourseNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return [_group_plan_response(plan) for plan in plans]


@app.post(
    "/courses/{course_id}/group-plans",
    response_model=GroupPlanResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["grupos"],
    dependencies=[Depends(require_course_access)],
)
def generate_group_plan(
    course_id: int,
    payload: GroupPlanGenerateRequest,
    group_service: GroupPlanningService = Depends(get_group_planning_service),
) -> GroupPlanResponse:
    try:
        plan = group_service.generate(
            course_id,
            max_group_size=payload.max_group_size,
            name=payload.name,
        )
    except CourseNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except InvalidGroupPlanError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return _group_plan_response(plan)


@app.post(
    "/courses/{course_id}/group-plans/manual",
    response_model=GroupPlanResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["grupos"],
    dependencies=[Depends(require_course_access)],
)
def create_manual_group_plan(
    course_id: int,
    payload: ManualGroupPlanRequest,
    group_service: GroupPlanningService = Depends(get_group_planning_service),
) -> GroupPlanResponse:
    try:
        plan = group_service.create_manual(
            course_id,
            group_count=payload.group_count,
            name=payload.name,
        )
    except CourseNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except InvalidGroupPlanError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return _group_plan_response(plan)


@app.post(
    "/courses/{course_id}/group-plans/confirm",
    response_model=GroupPlanResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["grupos"],
    dependencies=[Depends(require_course_access)],
)
def confirm_group_plan(
    course_id: int,
    payload: GroupPlanUpdateRequest,
    group_service: GroupPlanningService = Depends(get_group_planning_service),
) -> GroupPlanResponse:
    try:
        plan = group_service.confirm(
            course_id,
            name=payload.name,
            max_group_size=payload.max_group_size,
            groups=[
                StudentGroup(name=group.name, student_ids=group.student_ids)
                for group in payload.groups
            ],
        )
    except CourseNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except InvalidGroupPlanError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return _group_plan_response(plan)


@app.put(
    "/courses/{course_id}/group-plans/{plan_id}",
    response_model=GroupPlanResponse,
    tags=["grupos"],
    dependencies=[Depends(require_course_access)],
)
def update_group_plan(
    course_id: int,
    plan_id: int,
    payload: GroupPlanUpdateRequest,
    group_service: GroupPlanningService = Depends(get_group_planning_service),
) -> GroupPlanResponse:
    try:
        plan = group_service.update(
            course_id,
            plan_id,
            name=payload.name,
            max_group_size=payload.max_group_size,
            groups=[
                StudentGroup(name=group.name, student_ids=group.student_ids)
                for group in payload.groups
            ],
        )
    except CourseNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except GroupPlanNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except InvalidGroupPlanError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return _group_plan_response(plan)


@app.delete(
    "/courses/{course_id}/group-plans/{plan_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["grupos"],
    dependencies=[Depends(require_course_access)],
)
def delete_group_plan(
    course_id: int,
    plan_id: int,
    group_service: GroupPlanningService = Depends(get_group_planning_service),
) -> Response:
    try:
        group_service.delete(course_id, plan_id)
    except CourseNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except GroupPlanNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------------
# Métricas de equidad
# --------------------------------------------------------------------------


@app.get(
    "/courses/{course_id}/fairness-metrics",
    response_model=FairnessMetricsResponse,
    tags=["métricas"],
    dependencies=[Depends(require_course_access)],
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
