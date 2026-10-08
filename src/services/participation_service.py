"""Casos de uso de participación (HU-P4).

Este servicio es lo que cierra MVP 1. Sin él, el sistema sortea estudiantes
pero no queda constancia de qué se preguntó ni de qué respondió: el criterio
de éxito del Roadmap dice textualmente "queda un historial trazable", y eso no
se cumple sin una tabla de participaciones.

QUÉ GUARDA Y QUÉ NO

  `selection_events` (lo que ya existía) es la traza del ALGORITMO: qué
  estudiantes se consideraron, con qué alpha/beta, y quién salió elegido.

  `participations` (esto) es la traza de lo que PASÓ EN CLASE: qué se
  preguntó, qué respondió y cuándo.

  Son cosas distintas y hacen falta las dos. Con solo `selection_events` se
  puede responder "¿por qué se eligió a este estudiante?", pero no "¿qué se le
  preguntó?", que es lo que el docente necesita para calificar después.

DECISIÓN DE DISEÑO: LA ASISTENCIA SE CONGELA

  Al registrar una participación se copia el estado de asistencia actual del
  estudiante. No se lee en vivo después.

  El motivo es concreto: el docente puede corregir la asistencia cuando está
  revisando. Si el historial se calculara al vuelo, al corregir la asistencia
  de ayer cambiarían las participaciones de ayer, y el docente vería sus datos
  moverse sin haber hecho nada. Congelarlo hace que cada registro sea una foto
  de ese instante.

  La corrección sigue siendo posible, pero es explícita: se anula la
  participación y se vuelve a registrar. El rastro queda (`anulada`).

ANULACIÓN LÓGICA, NUNCA BORRADO

  Una participación mal registrada se corrige, pero el hecho de que estuvo mal
  también es información: si mañana aparecen cinco participaciones anuladas
  de un mismo estudiante, eso señala un problema en cómo se lleva el registro,
  y borrarlas lo escondería.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, List, Optional

from src.domain.entities import Participation, Student
from src.repositories.interfaces import ParticipationError, UnitOfWork
from src.services.errors import (
    CourseNotFoundError,
    ParticipationNotFoundError,
    SessionNotFoundError,
    StudentNotFoundError,
)

UnitOfWorkFactory = Callable[[], UnitOfWork]

MAX_QUESTION_LENGTH = 2000
MAX_ANSWER_LENGTH = 5000


@dataclass(frozen=True)
class ParticipationWithStudent:
    """Una participación junto con los datos del estudiante.

    Se devuelve unida porque el historial siempre se muestra con el nombre al
    lado: un listado de ids sin nombre no le sirve de nada al docente.
    """

    participation: Participation
    student: Student


@dataclass(frozen=True)
class SessionParticipationSummary:
    """Resumen de lo que va迄今为止 en una sesión.

    El docente lo ve mientras da la clase: cuántas participaciones lleva, y
    para comprobar que el reparto está siendo justo antes de que sea tarde.
    """

    class_session_id: int
    total: int
    estudiantes_participando: int
    capacidad_presentes: int

    @property
    def participaciones_por_estudiante(self) -> float:
        """Participaciones de media por estudiante presente.

        0.0 si no hay presentes: la media no está definida y devolver una
        división por cero sería peor que devolver "no hay datos".
        """
        if self.capacidad_presentes <= 0:
            return 0.0
        return round(self.total / self.capacidad_presentes, 3)


class ParticipationService:
    """Casos de uso de participación (HU-P4).

    Toda la escritura pasa por un `UnitOfWork`, igual que el resto de
    servicios: o se guarda la participación entera, o no se guarda nada.
    """

    def __init__(self, uow_factory: UnitOfWorkFactory):
        self._uow_factory = uow_factory

    # -- HU-P4: registrar --------------------------------------------

    def register(
        self,
        class_session_id: int,
        student_id: int,
        question: str,
        answer: Optional[str] = None,
        decision_run_id: Optional[int] = None,
        created_by: Optional[str] = None,
        asked_at: Optional[datetime] = None,
        freeze_attendance: bool = True,
    ) -> ParticipationWithStudent:
        """Registra una participación y la devuelve junto al estudiante.

        Se devuelve unida (y no solo la `Participation`) por una razón práctica:
        la respuesta de la API lleva el nombre del estudiante, y el nombre no
        está en la participación. Si el servicio devolviera solo la
        participación, el endpoint tendría que abrir otra transacción para
        buscarla, y entre una y otra el estudiante podría haber sido retirado.
        Una sola lectura, un estado coherente.

        `decision_run_id` es opcional a propósito: HU-P4 no lo pide, y el
        docente a veces pregunta por su cuenta, sin sorteo. Cuando sí viene,
        queda atado al sorteo del que salió el estudiante, que es lo que
        permite reconstruir después la sesión completa.

        `freeze_attendance=True` (el valor por defecto) copia la asistencia
        actual. Se expone el interruptor por si el caso de uso futuro es
        justo lo contrario (registrar "el docente preguntó a un ausente").
        """
        question = (question or "").strip()
        if not question:
            raise ParticipationError("la pregunta no puede ir vacia")
        if len(question) > MAX_QUESTION_LENGTH:
            raise ParticipationError(
                f"la pregunta excede {MAX_QUESTION_LENGTH} caracteres"
            )

        answer_clean = (answer or "").strip() or None
        if answer_clean and len(answer_clean) > MAX_ANSWER_LENGTH:
            raise ParticipationError(
                f"la respuesta excede {MAX_ANSWER_LENGTH} caracteres"
            )

        momento = asked_at or datetime.now(timezone.utc)

        with self._uow_factory() as uow:
            sesion = uow.class_sessions.get(class_session_id)
            if sesion is None:
                raise SessionNotFoundError(f"sesion {class_session_id} no existe")

            estudiante = uow.students.get(student_id)
            if estudiante is None:
                raise StudentNotFoundError(f"estudiante {student_id} no existe")
            if estudiante.course_id != sesion.course_id:
                # El repositorio tambien lo valida; repetirlo aqui da un
                # error de dominio legible en vez de uno de infraestructura.
                raise ParticipationError(
                    f"el estudiante {student_id} es del curso "
                    f"{estudiante.course_id} y la sesion {class_session_id} "
                    f"es del curso {sesion.course_id}"
                )

            presente = True
            if freeze_attendance:
                presentes = set(uow.attendance.present_ids(class_session_id))
                presente = student_id in presentes

            p = uow.participations.create(
                class_session_id=class_session_id,
                student_id=student_id,
                question=question,
                answer=answer_clean,
                asked_at=momento,
                decision_run_id=decision_run_id,
                created_by=created_by,
                present=presente,
            )
            # Se arma la respuesta antes del commit: el estudiante ya está
            # cargado, y así no hace falta una segunda transacción.
            unido = ParticipationWithStudent(participation=p, student=estudiante)
            uow.commit()
            return unido

    # -- HU-P4: historial --------------------------------------------

    def list_for_session(
        self,
        class_session_id: int,
        include_anuladas: bool = False,
    ) -> List[ParticipationWithStudent]:
        """Historial de una sesión, en orden cronológico.

        Es lo que HU-P4 llama "historial trazable": quién participó, cuándo,
        con qué pregunta y con qué respuesta.
        """
        with self._uow_factory() as uow:
            if uow.class_sessions.get(class_session_id) is None:
                raise SessionNotFoundError(f"sesion {class_session_id} no existe")

            items = uow.participations.list_for_session(
                class_session_id, include_anuladas=include_anuladas
            )
            return [self._join(uow, p) for p in items]

    def list_for_student(
        self,
        student_id: int,
        include_anuladas: bool = False,
    ) -> List[ParticipationWithStudent]:
        """Historial completo de un estudiante, más reciente primero."""
        with self._uow_factory() as uow:
            if uow.students.get(student_id) is None:
                raise StudentNotFoundError(f"estudiante {student_id} no existe")
            items = uow.participations.list_for_student(
                student_id, include_anuladas=include_anuladas
            )
            return [self._join(uow, p) for p in items]

    def get(self, participation_id: int) -> Participation:
        with self._uow_factory() as uow:
            p = uow.participations.get(participation_id)
            if p is None:
                raise ParticipationNotFoundError(
                    f"participacion {participation_id} no existe"
                )
            return p

    def get_with_student(self, participation_id: int) -> ParticipationWithStudent:
        """Una participación concreta, unida a su estudiante.

        Existe sobre todo para el endpoint de anulación: se necesita devolver
        la participación recién anulada con el nombre del estudiante al lado, y
        hacerlo con una sola lectura evita que el estado cambie entre la
        escritura y la lectura.
        """
        with self._uow_factory() as uow:
            p = uow.participations.get(participation_id)
            if p is None:
                raise ParticipationNotFoundError(
                    f"participacion {participation_id} no existe"
                )
            return self._join(uow, p)

    def summary_for_session(self, class_session_id: int) -> SessionParticipationSummary:
        """Resumen para mostrar al docente durante la clase."""
        with self._uow_factory() as uow:
            if uow.class_sessions.get(class_session_id) is None:
                raise SessionNotFoundError(f"sesion {class_session_id} no existe")

            items = uow.participations.list_for_session(class_session_id)
            presentes = uow.attendance.present_ids(class_session_id)
            return SessionParticipationSummary(
                class_session_id=class_session_id,
                total=len(items),
                estudiantes_participando=len({p.student_id for p in items}),
                capacidad_presentes=len(presentes),
            )

    # -- HU-P4: anulación --------------------------------------------

    def anular(
        self,
        participation_id: int,
        motivo: Optional[str] = None,
    ) -> Participation:
        """Anula una participación sin borrarla (ver el docstring del módulo)."""
        with self._uow_factory() as uow:
            p = uow.participations.anular(participation_id, motivo)
            if p is None:
                raise ParticipationNotFoundError(
                    f"participacion {participation_id} no existe"
                )
            uow.commit()
            return p

    @staticmethod
    def _join(uow: UnitOfWork, p: Participation) -> ParticipationWithStudent:
        estudiante = uow.students.get(p.student_id)
        if estudiante is None:
            # No deberia ocurrir (FK), pero si el estudiante se borrara a mano
            # de la base, devolver un objeto con `None` haria fallar al cliente
            # con un AttributeError dificil de leer. Se lanza un error claro.
            raise StudentNotFoundError(
                f"la participacion {p.id} referencia al estudiante "
                f"{p.student_id}, que no existe"
            )
        return ParticipationWithStudent(participation=p, student=estudiante)


__all__ = [
    "ParticipationService",
    "ParticipationWithStudent",
    "SessionParticipationSummary",
    "MAX_QUESTION_LENGTH",
    "MAX_ANSWER_LENGTH",
    "CourseNotFoundError",
]