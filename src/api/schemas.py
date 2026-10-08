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

from pydantic import BaseModel, Field, model_validator


class CourseCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, examples=["Cálculo II - Sección 4"])


class CourseResponse(BaseModel):
    id: int
    name: str
    created_at: datetime


class StudentEnrollRequest(BaseModel):
    external_ref: str = Field(
        ..., min_length=1, max_length=255,
        description="Identificador estable del estudiante (código de matrícula, DNI, etc.)",
        examples=["2024-0001"],
    )
    display_name: str = Field(..., min_length=1, max_length=255, examples=["Ana Torres"])
    alpha_init: float = Field(1.0, gt=0, description="Prior alpha si el estudiante es nuevo.")
    beta_init: float = Field(1.0, gt=0, description="Prior beta si el estudiante es nuevo.")


class StudentResponse(BaseModel):
    id: int
    course_id: int
    external_ref: str
    display_name: str
    created_at: datetime
    active: bool = True


class StudentUpdateRequest(BaseModel):
    """Edición parcial: solo se cambian los campos enviados."""

    display_name: Optional[str] = Field(None, min_length=1, max_length=255)
    external_ref: Optional[str] = Field(None, min_length=1, max_length=255)
    active: Optional[bool] = Field(
        None, description="false = retirar del curso (conserva su historial); true = reincorporar."
    )

    @model_validator(mode="after")
    def _at_least_one_field(self) -> "StudentUpdateRequest":
        if self.display_name is None and self.external_ref is None and self.active is None:
            raise ValueError("Envía al menos un campo: display_name, external_ref o active.")
        return self


class RosterRowErrorResponse(BaseModel):
    row: int = Field(..., description="Número de fila en el Excel (la 1 es el encabezado).")
    message: str


class RosterImportResponse(BaseModel):
    total_rows: int
    created: int
    updated: int
    unchanged: int
    errors: List[RosterRowErrorResponse]


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


class FairnessMetricsResponse(BaseModel):
    course_id: int
    n_students: int
    gini: float
    cv: float
    std: float
    coverage: float


class AvailableMethodsResponse(BaseModel):
    methods: List[str]
