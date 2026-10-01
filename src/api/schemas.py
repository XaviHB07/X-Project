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

from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


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
    present_student_ids: List[int] = Field(
        ..., min_length=1, description="Ids de los estudiantes presentes/elegibles en esta sesión."
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
