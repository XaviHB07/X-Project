"""Esquemas Pydantic de request/response.

Se mantienen separados de `src/domain/entities.py` y
`src/domain/value_objects.py` a propósito: el dominio no debería
depender de Pydantic (podría usarse sin FastAPI, p. ej. desde
`scripts/run_experiment.py`), y el esquema HTTP puede necesitar
validaciones o formas distintas a las del dominio interno (paginación,
campos opcionales para el cliente, etc.) sin que eso contamine el
dominio.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class CourseCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, examples=["Cálculo II - Sección 4"])
    cycle_id: Optional[int] = Field(None, gt=0)


class CourseResponse(BaseModel):
    id: int
    name: str
    created_at: datetime
    cycle_id: Optional[int] = None
    roster_imported: bool = False


class AcademicCycleCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, examples=["2026-II"])
    starts_on: Optional[date] = None

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("El nombre del ciclo no puede estar vacío.")
        return value


class AcademicCycleResponse(BaseModel):
    id: int
    name: str
    created_at: datetime
    starts_on: Optional[date] = None


class AcademicCycleStartDateRequest(BaseModel):
    starts_on: date


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=120)
    password: str = Field(..., min_length=1, max_length=1024)


class PasswordChangeRequest(BaseModel):
    new_password: str = Field(..., min_length=12, max_length=1024)


class AuthenticatedUserResponse(BaseModel):
    id: int
    username: str
    full_name: str
    role: str
    must_change_password: bool = False


class TeacherAssignmentResponse(AuthenticatedUserResponse):
    phone_number: Optional[str] = None
    email: Optional[str] = None
    course_ids: List[int]


class TeacherCreatedResponse(TeacherAssignmentResponse):
    temporary_password: str


class TemporaryPasswordResponse(BaseModel):
    temporary_password: str


class TeacherCreateRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=120)
    full_name: str = Field(..., min_length=1, max_length=255)
    phone_number: Optional[str] = Field(None, max_length=32)
    email: str = Field(..., min_length=3, max_length=255)
    course_ids: List[int] = Field(..., min_length=1)

    @field_validator("username", "full_name", "email")
    @classmethod
    def _strip_required_values(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Este campo no puede estar vacío.")
        return cleaned

    @field_validator("email")
    @classmethod
    def _validate_email_shape(cls, value: str) -> str:
        if (
            any(character.isspace() for character in value)
            or value.count("@") != 1
            or "." not in value.rsplit("@", 1)[1]
        ):
            raise ValueError("Ingresa un correo electrónico válido.")
        return value


class StudentAccountCreateRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=120)
    full_name: str = Field(..., min_length=1, max_length=255)
    email: str = Field(..., min_length=3, max_length=255)

    @field_validator("full_name", "email")
    @classmethod
    def _strip_required_values(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Este campo no puede estar vacío.")
        return cleaned

    @field_validator("email")
    @classmethod
    def _validate_email_shape(cls, value: str) -> str:
        if (
            any(character.isspace() for character in value)
            or value.count("@") != 1
            or "." not in value.rsplit("@", 1)[1]
        ):
            raise ValueError("Ingresa un correo electrónico válido.")
        return value.lower()


    @field_validator("username")
    @classmethod
    def _strip_username(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("El código del estudiante no puede estar vacío.")
        return cleaned

class StudentAccountResponse(BaseModel):
    id: int
    username: str
    full_name: str
    email: Optional[str] = None
    role: str = "estudiante"
    course_ids: List[int] = Field(default_factory=list)


class StudentAccountCreatedResponse(StudentAccountResponse):
    temporary_password: str


class TeacherCourseAssignmentRequest(BaseModel):
    course_ids: List[int]

    @field_validator("course_ids")
    @classmethod
    def _unique_course_ids(cls, value: List[int]) -> List[int]:
        if len(value) != len(set(value)) or any(course_id <= 0 for course_id in value):
            raise ValueError("Los cursos deben ser IDs positivos y no repetidos.")
        return value


class StudentEnrollRequest(BaseModel):
    external_ref: str = Field(
        ..., min_length=1, max_length=120,
        description="Identificador estable del estudiante (código de matrícula, DNI, etc.)",
        examples=["2024-0001"],
    )
    display_name: str = Field(..., min_length=1, max_length=255, examples=["Ana Torres"])
    phone_number: Optional[str] = Field(None, max_length=32)
    email: Optional[str] = Field(None, max_length=255)
    alpha_init: float = Field(1.0, gt=0, description="Prior alpha si el estudiante es nuevo.")
    beta_init: float = Field(1.0, gt=0, description="Prior beta si el estudiante es nuevo.")

    @field_validator("external_ref", "display_name")
    @classmethod
    def _strip_required_values(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("El código y nombre del estudiante son obligatorios.")
        return cleaned


class StudentResponse(BaseModel):
    id: int
    course_id: int
    external_ref: str
    display_name: str
    phone_number: Optional[str] = None
    email: Optional[str] = None
    user_id: Optional[int] = None
    roster_number: Optional[str] = None
    specialty: Optional[str] = None
    student_condition: Optional[str] = None
    times_repeated: Optional[str] = None
    created_at: datetime
    active: bool = True


class StudentEnrollmentResponse(StudentResponse):
    account_username: str
    temporary_password: Optional[str] = None


class StudentUpdateRequest(BaseModel):
    """Edición parcial: solo se cambian los campos enviados."""

    display_name: Optional[str] = Field(None, min_length=1, max_length=255)
    external_ref: Optional[str] = Field(None, min_length=1, max_length=255)
    phone_number: Optional[str] = Field(None, max_length=32)
    email: Optional[str] = Field(None, max_length=255)
    active: Optional[bool] = Field(
        None, description="false = retirar del curso (conserva su historial); true = reincorporar."
    )

    @model_validator(mode="after")
    def _at_least_one_field(self) -> "StudentUpdateRequest":
        if not self.model_fields_set.intersection(
            {"display_name", "external_ref", "active", "phone_number", "email"}
        ):
            raise ValueError(
                "Envía al menos un campo: display_name, external_ref, active, phone_number o email."
            )
        return self


class RosterRowErrorResponse(BaseModel):
    row: int = Field(..., description="Número de fila en el Excel (la 1 es el encabezado).")
    message: str


class ImportedStudentAccountResponse(BaseModel):
    row_number: int
    username: str
    full_name: str
    email: Optional[str] = None
    temporary_password: str


class UpdatedStudentAccountResponse(BaseModel):
    row_number: int
    username: str
    full_name: str
    email: Optional[str] = None


class RosterImportResponse(BaseModel):
    total_rows: int
    created: int
    updated: int
    unchanged: int
    errors: List[RosterRowErrorResponse]
    warnings: List[RosterRowErrorResponse] = Field(default_factory=list)
    created_accounts: List[ImportedStudentAccountResponse] = Field(default_factory=list)
    updated_accounts: List[UpdatedStudentAccountResponse] = Field(default_factory=list)


class SyllabusEntryRequest(BaseModel):
    session_date: date
    topic: str = Field(..., min_length=1, max_length=255, examples=["Límites y continuidad"])


class SyllabusEntryResponse(BaseModel):
    id: int
    course_id: int
    session_date: date
    topic: str


class SessionProposalResponse(BaseModel):
    session_date: date
    suggested_topic: Optional[str] = Field(
        None, description="Tema del sílabo para esa fecha; null si el curso no tiene sílabo cargado."
    )


class SessionStartRequest(BaseModel):
    topic: Optional[str] = Field(
        None, max_length=255,
        description="Tema confirmado o corregido por el docente. Si se omite, se usa el del sílabo (si existe).",
    )
    session_date: Optional[date] = Field(None, description="Si se omite, la fecha actual.")
    present_student_ids: Optional[List[int]] = Field(
        None, description="Presentes al iniciar. Si se omite, todos los estudiantes activos quedan presentes."
    )
    label: Optional[str] = Field(None, max_length=255, description="Etiqueta libre (opcional).")


class AttendanceEntryResponse(BaseModel):
    student_id: int
    external_ref: str
    display_name: str
    present: bool


class SessionDetailResponse(BaseModel):
    id: int
    course_id: int
    session_date: Optional[date]
    topic: Optional[str]
    label: Optional[str]
    created_at: datetime
    present_count: int
    total_count: int
    attendance: List[AttendanceEntryResponse]


class SessionSummaryResponse(BaseModel):
    id: int
    course_id: int
    session_date: Optional[date]
    topic: Optional[str]
    label: Optional[str]
    created_at: datetime


class StudentCourseResponse(BaseModel):
    course_id: int
    course_name: str
    cycle_id: Optional[int] = None
    cycle_name: Optional[str] = None
    cycle_starts_on: Optional[date] = None


class StudentWeekResponse(BaseModel):
    week_number: int = Field(..., ge=1, le=16)
    sessions: List[SessionSummaryResponse]


class StudentWeeksResponse(BaseModel):
    course_id: int
    cycle_starts_on: date
    weeks: List[StudentWeekResponse]
    unassigned_sessions: List[SessionSummaryResponse] = Field(default_factory=list)


class AttendanceMark(BaseModel):
    student_id: int = Field(..., gt=0)
    present: bool


class AttendanceUpdateRequest(BaseModel):
    attendance: List[AttendanceMark] = Field(..., min_length=1)


class StudentStateResponse(BaseModel):
    student_id: int
    alpha: float
    beta: float
    n_present: int
    n_selected: int
    estimated_need_probability: float = Field(
        ..., description="alpha / (alpha + beta): estimación puntual de 'necesita oportunidad', solo informativa."
    )


class SelectionEventResponse(BaseModel):
    id: int
    decision_run_id: int
    student_id: int
    present: bool
    selected: bool
    alpha_before: float
    beta_before: float
    alpha_after: float
    beta_after: float
    created_at: datetime


class RunSelectionRequest(BaseModel):
    present_student_ids: Optional[List[int]] = Field(
        None, min_length=1,
        description=(
            "Ids de los estudiantes presentes/elegibles. Si se omite, se usa la asistencia "
            "registrada en la sesión indicada por `class_session_id`."
        ),
    )
    k: int = Field(..., gt=0, description="Cantidad de estudiantes a seleccionar.")
    method: str = Field(
        "bayesian_fairness",
        description="Clave registrada en SelectorRegistry: roulette | weighted_softmax | bayesian_fairness.",
    )
    method_params: Optional[Dict[str, float]] = Field(
        None, description="Hiperparámetros de la estrategia; si se omite, se usan los de config/default.yaml."
    )
    class_session_id: Optional[int] = Field(
        None, gt=0, description="Reusar una sesión de clase ya creada; si se omite, se crea una nueva."
    )
    session_label: Optional[str] = Field(None, description="Etiqueta legible para la sesión (opcional).")
    request_id: Optional[str] = Field(
        None, description="Id de correlación externo (p. ej. el request id del cliente) para trazabilidad."
    )

    @model_validator(mode="after")
    def _need_present_or_session(self) -> "RunSelectionRequest":
        if self.present_student_ids is None and self.class_session_id is None:
            raise ValueError("Indica present_student_ids o una class_session_id con asistencia registrada.")
        return self


class DecisionResultResponse(BaseModel):
    decision_run_id: int
    class_session_id: int
    method_name: str
    considered_student_ids: List[int]
    selected_student_ids: List[int]
    created_at: datetime
    request_id: Optional[str] = None


class ParticipationEntryRequest(BaseModel):
    student_id: int = Field(..., gt=0)
    score: float = Field(..., ge=0, le=5)
    present: bool
    question: Optional[str] = Field(None, max_length=1000)
    comment: Optional[str] = Field(None, max_length=1000)


class ParticipationBatchRequest(BaseModel):
    participations: List[ParticipationEntryRequest] = Field(..., min_length=1)


class ParticipationResponse(BaseModel):
    id: int
    decision_run_id: int
    student_id: int
    external_ref: str
    display_name: str
    score: float
    present: bool
    created_at: datetime
    question: Optional[str] = None
    comment: Optional[str] = None


class StudentGroupRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    student_ids: List[int] = Field(default_factory=list)


class GroupPlanGenerateRequest(BaseModel):
    max_group_size: int = Field(..., ge=1, le=1000)
    name: Optional[str] = Field(None, max_length=255)


class ManualGroupPlanRequest(BaseModel):
    group_count: int = Field(..., ge=1, le=100)
    name: Optional[str] = Field(None, max_length=255)


class GroupPlanUpdateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    max_group_size: int = Field(..., ge=1, le=1000)
    groups: List[StudentGroupRequest] = Field(..., min_length=1, max_length=100)


class StudentGroupResponse(BaseModel):
    name: str
    student_ids: List[int]


class GroupPlanResponse(BaseModel):
    id: Optional[int] = None
    course_id: int
    name: str
    max_group_size: int
    groups: List[StudentGroupResponse]
    created_at: datetime


class FairnessMetricsResponse(BaseModel):
    course_id: int
    n_students: int
    gini: float
    cv: float
    std: float
    coverage: float


class AvailableMethodsResponse(BaseModel):
    methods: List[str]
