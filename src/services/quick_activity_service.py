"""Actividades rápidas (épica 7) — Sprint 7.

Historias cubiertas en este módulo:

* HU-Q5 — el estudiante ingresa el código (o abre el enlace del QR) desde su
  cuenta y se une a la actividad. Se valida que el código esté vigente, que
  el estudiante pertenezca al curso y que responda una sola vez, salvo que el
  docente haya permitido varios envíos.
* HU-Q3 — el sistema registra las respuestas recibidas, asociadas a la cuenta
  del estudiante (`users.id`) y a su matrícula en el curso (`students.id`),
  para que después se generen los resultados (HU-Q4).

Además deja la base que comparten HU-Q1 y HU-Q2: una actividad con sus
preguntas cortas (abiertas o de opción múltiple) y su publicación con un
código temporal. La generación automática de preguntas con IA (HU-Q1) solo
tiene que enviar sus preguntas en el mismo formato de `create`, y la imagen
QR (HU-Q2) solo tiene que codificar el enlace `join_url` que devuelve
`publish`.

Dos modos de actividad:

* `self_paced` (test): cada estudiante responde todas las preguntas a su
  ritmo dentro del rango de tiempo que define el docente.
* `live` (quiz en vivo, tipo Kahoot/Quizizz): la pantalla del docente muestra
  una pregunta a la vez y los estudiantes responden desde su dispositivo. Cada
  pregunta tiene `question_seconds`; un acierto vale hasta 1000 puntos y baja
  linealmente hasta 500 según el tiempo usado (misma idea que Kahoot). El reloj
  del servidor es la referencia: los dispositivos solo muestran la cuenta
  regresiva que el servidor les indica.

Igual que `AuthService`, trabaja con la sesión de SQLAlchemy directamente.
"""

from __future__ import annotations

import hashlib
import secrets
import threading
import time
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from typing import Callable, Iterable, List, Optional, Sequence
from zoneinfo import ZoneInfo

from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from src.repositories.sqlalchemy.models import (
    AcademicCycleORM,
    ClassSessionORM,
    CourseORM,
    QuickActivityAnswerORM,
    QuickActivityORM,
    QuickActivityQuestionORM,
    QuickActivityResponseORM,
    StudentORM,
)

SessionFactory = Callable[[], Session]

# Sin 0/O ni 1/I/L para que el código se dicte y se copie sin confusiones.
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
RANKING_WEEK_COUNT = 15
RANKING_TIMEZONE = ZoneInfo("America/Lima")
CODE_LENGTH = 6
MAX_QUESTIONS = 20
MAX_OPTIONS = 6
MAX_ANSWER_LENGTH = 2000
DEFAULT_DURATION_MINUTES = 10
MAX_DURATION_MINUTES = 240
MODE_SELF_PACED = "self_paced"
MODE_LIVE = "live"
DEFAULT_QUESTION_SECONDS = 30
MIN_QUESTION_SECONDS = 5
MAX_QUESTION_SECONDS = 120
MAX_POINTS = 1000
LEADERBOARD_SIZE = 10
# Caché del ranking en vivo (ver `QuickActivityService._leaderboard`).
LEADERBOARD_CACHE_SIZE = 64
LEADERBOARD_CACHE_TTL_S = 15.0
# HU-Q4: bandas para resumir el nivel de comprensión del grupo según el
# porcentaje promedio de aciertos. Es un criterio provisional del equipo
# (alto ≥ 75 %, medio 50–74 %, bajo < 50 %), fácil de ajustar si el docente
# del curso define otro.
COMPREHENSION_HIGH = 0.75
COMPREHENSION_MEDIUM = 0.50


class QuickActivityNotFoundError(LookupError):
    """La actividad no existe o no pertenece al curso indicado."""


class InvalidJoinCodeError(LookupError):
    """HU-Q5: nadie publicó una actividad con ese código."""


class ActivityNotAvailableError(ValueError):
    """HU-Q5: la actividad existe pero no está vigente (borrador, vencida o
    cerrada)."""


class NotEnrolledInCourseError(PermissionError):
    """HU-Q5: el estudiante no pertenece (o ya no pertenece) al curso."""


class AlreadyRespondedError(ValueError):
    """HU-Q5: el estudiante ya respondió y el docente no permite reenvíos."""


class InvalidQuickActivityError(ValueError):
    """Datos de la actividad o de las respuestas con forma inválida."""


class QuickActivityStateError(ValueError):
    """La operación no corresponde al estado actual de la actividad."""


def _utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def normalize_join_code(code: str) -> str:
    """Acepta el código con espacios, guiones o en minúsculas."""
    return "".join(character for character in (code or "").upper() if character.isalnum())


class QuickActivityService:
    def __init__(
        self,
        session_factory: SessionFactory,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ):
        self._session_factory = session_factory
        self._clock = clock
        # activity_id -> (huella, creado_en, ranking). Ver `_leaderboard`.
        self._board_cache: "OrderedDict[int, tuple]" = OrderedDict()
        self._board_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Docente: preparación y publicación (base de HU-Q1 / HU-Q2)
    # ------------------------------------------------------------------

    def create(
        self,
        course_id: int,
        created_by_user_id: Optional[int],
        title: str,
        questions: Sequence[dict],
        class_session_id: Optional[int] = None,
        allow_multiple_responses: bool = False,
        mode: str = MODE_SELF_PACED,
        question_seconds: Optional[int] = None,
    ) -> dict:
        title = " ".join((title or "").split())
        if not title:
            raise InvalidQuickActivityError("La actividad necesita un título.")
        if mode not in (MODE_SELF_PACED, MODE_LIVE):
            raise InvalidQuickActivityError("Modo de actividad no válido.")
        cleaned_questions = self._clean_questions(questions)
        if mode == MODE_LIVE:
            # En vivo se puntúa al instante: todas las preguntas son de opción
            # múltiple y con alternativa correcta.
            for number, question in enumerate(cleaned_questions, start=1):
                if not question["options"] or question["correct_option"] is None:
                    raise InvalidQuickActivityError(
                        f"En el quiz en vivo la pregunta {number} debe ser de opción "
                        "múltiple y tener marcada la alternativa correcta."
                    )
                if len(question["options"]) > 4:
                    raise InvalidQuickActivityError(
                        f"La pregunta {number} admite como máximo cuatro alternativas "
                        "para responder con los botones de colores."
                    )
            question_seconds = int(question_seconds or DEFAULT_QUESTION_SECONDS)
            if not MIN_QUESTION_SECONDS <= question_seconds <= MAX_QUESTION_SECONDS:
                raise InvalidQuickActivityError(
                    f"El tiempo por pregunta debe estar entre {MIN_QUESTION_SECONDS} y "
                    f"{MAX_QUESTION_SECONDS} segundos."
                )
            allow_multiple_responses = False
        else:
            question_seconds = None
        with self._session_factory() as session:
            course = session.get(CourseORM, course_id)
            if course is None:
                raise QuickActivityNotFoundError(f"Curso {course_id} no encontrado.")
            if course.enabled is False:
                raise QuickActivityStateError(
                    "El curso está deshabilitado y no admite actividades nuevas."
                )
            if class_session_id is not None:
                class_session = session.get(ClassSessionORM, class_session_id)
                if class_session is None or class_session.course_id != course_id:
                    raise InvalidQuickActivityError(
                        "La sesión indicada no pertenece al curso."
                    )
            activity = QuickActivityORM(
                course_id=course_id,
                class_session_id=class_session_id,
                created_by_user_id=created_by_user_id,
                title=title,
                status="draft",
                allow_multiple_responses=bool(allow_multiple_responses),
                mode=mode,
                question_seconds=question_seconds,
            )
            activity.questions = [
                QuickActivityQuestionORM(
                    position=index,
                    prompt=question["prompt"],
                    options=question["options"],
                    correct_option=question["correct_option"],
                )
                for index, question in enumerate(cleaned_questions, start=1)
            ]
            session.add(activity)
            session.commit()
            return self._teacher_view(session, activity)

    def list_for_course(self, course_id: int) -> List[dict]:
        with self._session_factory() as session:
            activities = session.execute(
                select(QuickActivityORM)
                .where(QuickActivityORM.course_id == course_id)
                .options(selectinload(QuickActivityORM.questions))
                .order_by(QuickActivityORM.created_at.desc(), QuickActivityORM.id.desc())
            ).scalars().all()
            # Un solo conteo agrupado en vez de un `count(*)` por actividad
            # (consulta N+1 que crecía con cada actividad del curso).
            counts = dict(session.execute(
                select(QuickActivityResponseORM.activity_id, func.count(QuickActivityResponseORM.id))
                .join(QuickActivityORM, QuickActivityORM.id == QuickActivityResponseORM.activity_id)
                .where(QuickActivityORM.course_id == course_id)
                .group_by(QuickActivityResponseORM.activity_id)
            ).all()) if activities else {}
            return [
                self._teacher_view(session, activity, response_count=int(counts.get(activity.id, 0)))
                for activity in activities
            ]

    def get(self, course_id: int, activity_id: int) -> dict:
        with self._session_factory() as session:
            activity = self._activity_in_course(session, course_id, activity_id)
            return self._teacher_view(session, activity)

    def publish(
        self,
        course_id: int,
        activity_id: int,
        duration_minutes: int = DEFAULT_DURATION_MINUTES,
        allow_multiple_responses: Optional[bool] = None,
    ) -> dict:
        """Publica la actividad con un código temporal.

        Volver a publicar una actividad ya publicada extiende su vigencia y
        conserva el código (útil si el docente necesita unos minutos más).
        Una actividad cerrada no se vuelve a abrir.
        """
        if not 1 <= int(duration_minutes) <= MAX_DURATION_MINUTES:
            raise InvalidQuickActivityError(
                f"La vigencia debe estar entre 1 y {MAX_DURATION_MINUTES} minutos."
            )
        with self._session_factory() as session:
            activity = self._activity_in_course(session, course_id, activity_id)
            if activity.status == "closed":
                raise QuickActivityStateError("La actividad ya fue cerrada.")
            course = session.get(CourseORM, course_id)
            if course is not None and course.enabled is False:
                raise QuickActivityStateError(
                    "El curso está deshabilitado y no admite actividades nuevas."
                )
            if not activity.questions:
                raise InvalidQuickActivityError("La actividad no tiene preguntas.")
            now = self._clock()
            if activity.join_code is None:
                activity.join_code = self._new_code(session)
            if activity.published_at is None:
                activity.published_at = now
            activity.status = "published"
            activity.expires_at = now + timedelta(minutes=int(duration_minutes))
            if activity.mode == MODE_LIVE:
                # En vivo, la vigencia del código es el plazo para unirse; la
                # partida la conduce el docente pregunta por pregunta.
                if activity.live_phase is None:
                    activity.live_phase = "lobby"
            elif allow_multiple_responses is not None:
                activity.allow_multiple_responses = bool(allow_multiple_responses)
            session.commit()
            return self._teacher_view(session, activity)

    def close(self, course_id: int, activity_id: int) -> dict:
        with self._session_factory() as session:
            activity = self._activity_in_course(session, course_id, activity_id)
            if activity.status != "closed":
                activity.status = "closed"
                activity.closed_at = self._clock()
                if activity.mode == MODE_LIVE:
                    activity.live_phase = "finished"
                session.commit()
            return self._teacher_view(session, activity)

    def responses(self, course_id: int, activity_id: int) -> dict:
        """HU-Q3: respuestas registradas, con el estudiante que las envió."""
        with self._session_factory() as session:
            activity = self._activity_in_course(session, course_id, activity_id)
            rows = session.execute(
                select(QuickActivityResponseORM)
                .where(QuickActivityResponseORM.activity_id == activity.id)
                .options(
                    selectinload(QuickActivityResponseORM.answers),
                    selectinload(QuickActivityResponseORM.student),
                )
                .order_by(QuickActivityResponseORM.submitted_at, QuickActivityResponseORM.id)
            ).scalars().all()
            enrolled = int(session.execute(
                select(func.count(StudentORM.id)).where(
                    StudentORM.course_id == course_id, StudentORM.active.is_(True)
                )
            ).scalar_one())
            return {
                "activity": self._teacher_view(session, activity),
                "enrolled_count": enrolled,
                "respondent_count": len({row.student_id for row in rows}),
                "responses": [
                    {
                        "id": row.id,
                        "student_id": row.student_id,
                        "student_code": row.student.external_ref,
                        "student_name": row.student.display_name,
                        "user_id": row.user_id,
                        "attempt": row.attempt,
                        "submitted_at": _utc(row.submitted_at),
                        "answers": [self._answer_dict(answer) for answer in row.answers],
                    }
                    for row in rows
                ],
            }

    # ------------------------------------------------------------------
    # HU-Q4 — Resultados de la actividad
    # ------------------------------------------------------------------

    def results(self, course_id: int, activity_id: int) -> dict:
        """Resumen para que el docente conozca el nivel de comprensión del
        grupo a partir de las respuestas registradas (HU-Q3).

        * Participación: estudiantes que respondieron / matriculados activos.
        * Por pregunta: cuántos respondieron, cuántos eligieron cada
          alternativa y el % de aciertos sobre quienes participaron (en vivo,
          no responder a tiempo cuenta como no acertar).
        * Por estudiante: aciertos sobre las preguntas calificables.
        * Grupo: promedio del % de aciertos de los estudiantes y su nivel.

        Solo se califican las preguntas de opción múltiple con alternativa
        correcta. Las abiertas se listan para leerlas, sin nota, hasta que se
        califiquen (HU-E2/HU-E3). Si el test admitía varios envíos, cuenta el
        último envío de cada estudiante.
        """
        with self._session_factory() as session:
            activity = self._activity_in_course(session, course_id, activity_id)
            rows = session.execute(
                select(QuickActivityResponseORM)
                .where(QuickActivityResponseORM.activity_id == activity.id)
                .options(
                    selectinload(QuickActivityResponseORM.answers),
                    selectinload(QuickActivityResponseORM.student),
                )
                .order_by(QuickActivityResponseORM.attempt)
            ).scalars().all()
            enrolled = int(session.execute(
                select(func.count(StudentORM.id)).where(
                    StudentORM.course_id == course_id, StudentORM.active.is_(True)
                )
            ).scalar_one())
            latest = {}
            for row in rows:
                latest[row.student_id] = row  # queda el intento más alto
            participants = list(latest.values())
            scored = [q for q in activity.questions if q.options and q.correct_option is not None]
            scored_ids = {q.id for q in scored}

            questions = []
            for question in activity.questions:
                answers = [
                    (row, answer)
                    for row in participants
                    for answer in row.answers
                    if answer.question_id == question.id
                ]
                item = {
                    "id": question.id,
                    "position": question.position,
                    "prompt": question.prompt,
                    "kind": "choice" if question.options else "open",
                    "options": question.options,
                    "correct_option": question.correct_option,
                    "answered_count": len(answers),
                    "distribution": None,
                    "correct_count": None,
                    "correct_rate": None,
                    "open_answers": [],
                }
                if question.options:
                    distribution = [0] * len(question.options)
                    for _, answer in answers:
                        if answer.selected_option is not None and answer.selected_option < len(distribution):
                            distribution[answer.selected_option] += 1
                    item["distribution"] = distribution
                    if question.id in scored_ids:
                        correct = distribution[question.correct_option]
                        item["correct_count"] = correct
                        item["correct_rate"] = (
                            round(correct / len(participants), 4) if participants else None
                        )
                else:
                    item["open_answers"] = [
                        {
                            "student_name": row.student.display_name,
                            "student_code": row.student.external_ref,
                            "answer_text": answer.answer_text or "",
                        }
                        for row, answer in sorted(
                            answers, key=lambda pair: pair[0].student.display_name
                        )
                    ]
                questions.append(item)

            students = []
            for row in participants:
                correct = sum(
                    1 for answer in row.answers
                    if answer.question_id in scored_ids and answer.is_correct
                )
                students.append({
                    "student_name": row.student.display_name,
                    "student_code": row.student.external_ref,
                    "attempt": row.attempt,
                    "answered_count": len(row.answers),
                    "correct_count": correct if scored else None,
                    "score_rate": round(correct / len(scored), 4) if scored else None,
                    "points": (
                        sum(answer.points or 0 for answer in row.answers)
                        if activity.mode == MODE_LIVE else None
                    ),
                })
            students.sort(key=lambda item: (
                -(item["score_rate"] or 0), -(item["points"] or 0), item["student_name"]
            ))

            group_score = (
                round(sum(item["score_rate"] for item in students) / len(students), 4)
                if scored and students else None
            )
            if group_score is None:
                level = None
            elif group_score >= COMPREHENSION_HIGH:
                level = "alto"
            elif group_score >= COMPREHENSION_MEDIUM:
                level = "medio"
            else:
                level = "bajo"
            rated = [item for item in questions if item["correct_rate"] is not None]
            hardest = min(rated, key=lambda item: (item["correct_rate"], item["position"])) if rated else None
            return {
                "activity": self._teacher_view(session, activity),
                "enrolled_count": enrolled,
                "respondent_count": len(participants),
                "participation_rate": round(len(participants) / enrolled, 4) if enrolled else None,
                "scored_question_count": len(scored),
                "open_question_count": sum(1 for q in activity.questions if not q.options),
                "group_score": group_score,
                "comprehension_level": level,
                "hardest_question_position": hardest["position"] if hardest else None,
                "questions": questions,
                "students": students,
            }

    # ------------------------------------------------------------------
    # Estudiante: HU-Q5 (unirse) y HU-Q3 (registrar respuestas)
    # ------------------------------------------------------------------

    def join(self, student_user_id: int, code: str) -> dict:
        """HU-Q5: valida el código y devuelve las preguntas para responder."""
        with self._session_factory() as session:
            activity, enrollment = self._validate_access(session, student_user_id, code)
            previous = self._attempts(session, activity.id, enrollment.id)
            if activity.mode == MODE_LIVE:
                # En vivo, unirse registra al participante. Volver a entrar
                # (p. ej. tras recargar la página) no es un segundo envío: el
                # límite es una respuesta por pregunta.
                if not previous:
                    session.add(QuickActivityResponseORM(
                        activity_id=activity.id,
                        student_id=enrollment.id,
                        user_id=student_user_id,
                        attempt=1,
                        submitted_at=self._clock(),
                    ))
                    try:
                        session.commit()
                    except IntegrityError:
                        session.rollback()
                return self._student_view(session, activity, previous)
            if previous and not activity.allow_multiple_responses:
                raise AlreadyRespondedError(
                    "Ya respondiste esta actividad. El docente no habilitó más de un envío."
                )
            return self._student_view(session, activity, previous)

    def submit(
        self, student_user_id: int, activity_id: int, code: str, answers: Sequence[dict]
    ) -> dict:
        """HU-Q3: registra el envío asociado a la cuenta del estudiante.

        Vuelve a aplicar las validaciones de HU-Q5 (código vigente,
        pertenencia, envío único), porque entre el ingreso y el envío la
        actividad puede vencer o el docente puede cerrarla.
        """
        with self._session_factory() as session:
            activity, enrollment = self._validate_access(session, student_user_id, code)
            if activity.id != activity_id:
                raise InvalidJoinCodeError("El código no corresponde a esta actividad.")
            if activity.mode == MODE_LIVE:
                raise QuickActivityStateError(
                    "Este quiz es en vivo: responde cada pregunta cuando aparezca."
                )
            cleaned = self._clean_answers(activity, answers)
            previous = self._attempts(session, activity.id, enrollment.id)
            if previous and not activity.allow_multiple_responses:
                raise AlreadyRespondedError(
                    "Ya respondiste esta actividad. El docente no habilitó más de un envío."
                )
            response = QuickActivityResponseORM(
                activity_id=activity.id,
                student_id=enrollment.id,
                user_id=student_user_id,
                attempt=previous + 1,
                submitted_at=self._clock(),
            )
            response.answers = [QuickActivityAnswerORM(**answer) for answer in cleaned]
            session.add(response)
            try:
                session.commit()
            except IntegrityError as exc:
                # Dos envíos simultáneos del mismo estudiante: la restricción
                # única (actividad, matrícula, intento) deja pasar solo uno.
                session.rollback()
                raise AlreadyRespondedError(
                    "Ya se registró un envío tuyo para esta actividad."
                ) from exc
            return {
                "response_id": response.id,
                "activity_id": activity.id,
                "activity_title": activity.title,
                "attempt": response.attempt,
                "submitted_at": _utc(response.submitted_at),
                "answered_count": len(cleaned),
                "can_submit_again": bool(activity.allow_multiple_responses),
            }

    def student_submissions(self, student_user_id: int) -> List[dict]:
        """Envíos propios del estudiante (sin la alternativa correcta)."""
        with self._session_factory() as session:
            rows = session.execute(
                select(QuickActivityResponseORM, QuickActivityORM, CourseORM)
                .join(QuickActivityORM, QuickActivityORM.id == QuickActivityResponseORM.activity_id)
                .join(CourseORM, CourseORM.id == QuickActivityORM.course_id)
                .where(QuickActivityResponseORM.user_id == student_user_id)
                .order_by(QuickActivityResponseORM.submitted_at.desc())
            ).all()
            return [
                {
                    "response_id": response.id,
                    "activity_id": activity.id,
                    "activity_title": activity.title,
                    "course_id": course.id,
                    "course_name": course.name,
                    "attempt": response.attempt,
                    "submitted_at": _utc(response.submitted_at),
                }
                for response, activity, course in rows
            ]

    def student_live_activity_history(self, student_user_id: int) -> List[dict]:
        """Puntaje y puesto propio en cada quiz en vivo finalizado de sus cursos."""
        with self._session_factory() as session:
            enrollments = session.execute(
                select(StudentORM).where(
                    StudentORM.user_id == student_user_id,
                    StudentORM.active.is_(True),
                )
            ).scalars().all()
            course_ids = {student.course_id for student in enrollments}
            student_by_course = {
                student.course_id: student for student in enrollments
            }
            if not course_ids:
                return []

            activities = session.execute(
                select(QuickActivityORM, CourseORM.name)
                .join(CourseORM, CourseORM.id == QuickActivityORM.course_id)
                .where(
                    QuickActivityORM.course_id.in_(course_ids),
                    QuickActivityORM.mode == MODE_LIVE,
                    QuickActivityORM.status == "closed",
                    QuickActivityORM.live_phase == "finished",
                )
                .order_by(QuickActivityORM.closed_at.asc(), QuickActivityORM.id.asc())
                .options(selectinload(QuickActivityORM.questions))
            ).all()
            if not activities:
                return []

            activity_ids = [activity.id for activity, _ in activities]
            roster = session.execute(
                select(StudentORM).where(
                    StudentORM.course_id.in_(course_ids),
                    StudentORM.active.is_(True),
                )
            ).scalars().all()
            roster_by_course: dict[int, list[StudentORM]] = {}
            for student in roster:
                roster_by_course.setdefault(student.course_id, []).append(student)

            responses = session.execute(
                select(QuickActivityResponseORM)
                .where(QuickActivityResponseORM.activity_id.in_(activity_ids))
                .options(selectinload(QuickActivityResponseORM.answers))
                .order_by(QuickActivityResponseORM.attempt)
            ).scalars().all()
            latest_responses: dict[tuple[int, int], QuickActivityResponseORM] = {}
            for response in responses:
                latest_responses[(response.activity_id, response.student_id)] = response

            history = []
            for activity, course_name in activities:
                own_student = student_by_course.get(activity.course_id)
                if own_student is None:
                    continue
                ranking = []
                for student in roster_by_course.get(activity.course_id, []):
                    response = latest_responses.get((activity.id, student.id))
                    answers = response.answers if response else []
                    points = sum(answer.points or 0 for answer in answers)
                    correct_answers = sum(1 for answer in answers if answer.is_correct)
                    response_time = sum(
                        answer.response_ms or 0
                        for answer in answers
                        if answer.is_correct
                    )
                    ranking.append({
                        "student": student,
                        "points": points,
                        "correct_answers": correct_answers,
                        "response_time": response_time,
                        "participated": bool(answers),
                    })
                ranking.sort(key=lambda item: (
                    -item["points"],
                    item["response_time"],
                    self._random_tie_key(
                        activity.join_code or str(activity.id), item["student"].id
                    ),
                ))
                own_result = next(
                    item for item in ranking if item["student"].id == own_student.id
                )
                rank = next(
                    position
                    for position, item in enumerate(ranking, start=1)
                    if item["student"].id == own_student.id
                )
                history.append({
                    "activity_id": activity.id,
                    "course_id": activity.course_id,
                    "course_name": course_name,
                    "activity_title": activity.title,
                    "closed_at": _utc(activity.closed_at),
                    "points": own_result["points"],
                    "rank": rank,
                    "active_student_count": len(ranking),
                    "participated": own_result["participated"],
                    "correct_answers": own_result["correct_answers"],
                    "question_count": len(activity.questions),
                })
            return history


    # ------------------------------------------------------------------
    # Quiz en vivo (tipo Kahoot / Quizizz)
    # ------------------------------------------------------------------

    def _effective_phase(self, activity: QuickActivityORM) -> str:
        """La fase guardada, salvo que el tiempo de la pregunta ya se haya
        agotado: entonces pasa sola a `reveal` (sin esperar al docente)."""
        phase = activity.live_phase or "lobby"
        if activity.status == "closed":
            return "finished"
        if phase == "question" and self._remaining_ms(activity) <= 0:
            return "reveal"
        return phase

    def _remaining_ms(self, activity: QuickActivityORM) -> int:
        started = _utc(activity.live_started_at)
        if started is None or not activity.question_seconds:
            return 0
        end = started + timedelta(seconds=activity.question_seconds)
        return max(0, int((end - self._clock()).total_seconds() * 1000))

    @staticmethod
    def _current_question(activity: QuickActivityORM) -> Optional[QuickActivityQuestionORM]:
        if not activity.live_position:
            return None
        return next(
            (q for q in activity.questions if q.position == activity.live_position), None
        )

    def _live_activity(self, session: Session, course_id: int, activity_id: int) -> QuickActivityORM:
        activity = self._activity_in_course(session, course_id, activity_id)
        if activity.mode != MODE_LIVE:
            raise QuickActivityStateError("Esta actividad es un test, no un quiz en vivo.")
        return activity

    def live_advance(self, course_id: int, activity_id: int) -> dict:
        """Botón del docente: sala de espera → pregunta 1 → resultados de la
        pregunta → pregunta 2 → … → podio final."""
        with self._session_factory() as session:
            activity = self._live_activity(session, course_id, activity_id)
            if activity.status == "draft":
                raise QuickActivityStateError("Publica el quiz antes de iniciarlo.")
            phase = self._effective_phase(activity)
            if phase == "finished":
                raise QuickActivityStateError("El quiz ya terminó.")
            now = self._clock()
            total = len(activity.questions)
            if phase == "lobby":
                activity.live_position = 1
                activity.live_phase = "question"
                activity.live_started_at = now
            elif phase == "question":
                # El docente cierra la pregunta antes de que se acabe el tiempo.
                activity.live_phase = "reveal"
                activity.live_started_at = now - timedelta(seconds=activity.question_seconds or 0)
            elif (activity.live_position or 0) < total:
                activity.live_position = (activity.live_position or 0) + 1
                activity.live_phase = "question"
                activity.live_started_at = now
            else:
                activity.live_phase = "finished"
                activity.status = "closed"
                activity.closed_at = now
            session.commit()
            return self._teacher_live_state(session, activity)

    def live_state_for_teacher(self, course_id: int, activity_id: int) -> dict:
        with self._session_factory() as session:
            activity = self._live_activity(session, course_id, activity_id)
            return self._teacher_live_state(session, activity)

    def live_state_for_student(self, student_user_id: int, activity_id: int) -> dict:
        with self._session_factory() as session:
            activity, response = self._live_participant(session, student_user_id, activity_id)
            phase = self._effective_phase(activity)
            question = self._current_question(activity) if phase in ("question", "reveal") else None
            mine = None
            if question is not None:
                mine = next((a for a in response.answers if a.question_id == question.id), None)
            reveal = phase in ("reveal", "finished")
            # El ranking solo se necesita al cerrar cada pregunta: durante la
            # pregunta basta el conteo, que sale de la misma huella con la que
            # se valida la caché del ranking (una sola consulta agregada).
            fingerprint = self._board_fingerprint(session, activity)
            participant_count = fingerprint[1]
            board = self._leaderboard(session, activity, fingerprint) if reveal else []
            my_row = next((row for row in board if row["student_id"] == response.student_id), None)
            return {
                "activity_id": activity.id,
                "title": activity.title,
                "phase": phase,
                "finished_at": _utc(activity.closed_at) if phase == "finished" else None,
                "server_time": _utc(self._clock()),
                "position": activity.live_position,
                "question_count": len(activity.questions),
                "question_seconds": activity.question_seconds,
                "remaining_ms": self._remaining_ms(activity) if phase == "question" else 0,
                "question": None if question is None else {
                    "id": question.id,
                    "position": question.position,
                },
                "option_count": len(question.options or []) if question is not None else None,
                "answered": mine is not None,
                "selected_option": mine.selected_option if mine else None,
                # La respuesta correcta y el puntaje solo se muestran al cerrar
                # la pregunta, para que no circulen mientras otros responden.
                "correct_option": question.correct_option if (question and reveal) else None,
                "is_correct": mine.is_correct if (mine and reveal) else None,
                "points": mine.points if (mine and reveal) else None,
                "total_points": my_row["points"] if (my_row and reveal) else None,
                "rank": my_row["rank"] if (my_row and reveal) else None,
                "participant_count": participant_count,
                "podium": [
                    row for row in board if row["points"] > 0
                ][:3] if phase == "finished" else [],
                "leaderboard": [
                    {
                        "rank": row["rank"],
                        "student_name": row["student_name"],
                        "points": row["points"],
                        "correct": row["correct"],
                        "incorrect": row["incorrect"],
                        "unanswered": row["unanswered"],
                    }
                    for row in board
                ] if phase == "finished" else [],
            }

    def cumulative_live_ranking(
        self, course_id: int, student_user_id: Optional[int] = None
    ) -> dict:
        """Calcula Apertura, Clausura y total desde los puntos persistidos."""
        with self._session_factory() as session:
            course = session.get(CourseORM, course_id)
            if course is None:
                raise QuickActivityNotFoundError(f"Curso {course_id} no encontrado.")
            cycle = session.get(AcademicCycleORM, course.cycle_id) if course.cycle_id else None
            cycle_start = cycle.starts_on if cycle else None
            cycle_week_count = RANKING_WEEK_COUNT
            if cycle_start is not None and cycle and cycle.ends_on is not None:
                cycle_week_count = max(
                    1, (cycle.ends_on - cycle_start).days // 7 + 1
                )

            completed_quizzes = session.execute(
                select(QuickActivityORM.id, QuickActivityORM.closed_at).where(
                    QuickActivityORM.course_id == course_id,
                    QuickActivityORM.mode == MODE_LIVE,
                    QuickActivityORM.status == "closed",
                    QuickActivityORM.live_phase == "finished",
                )
            ).all()
            quiz_ids = [quiz.id for quiz in completed_quizzes]
            quiz_weeks = {
                quiz.id: self._ranking_week(quiz.closed_at, cycle_start)
                for quiz in completed_quizzes
            }
            latest_attempts = (
                select(
                    QuickActivityResponseORM.activity_id.label("activity_id"),
                    QuickActivityResponseORM.student_id.label("student_id"),
                    func.max(QuickActivityResponseORM.attempt).label("attempt"),
                )
                .where(QuickActivityResponseORM.activity_id.in_(quiz_ids))
                .group_by(
                    QuickActivityResponseORM.activity_id,
                    QuickActivityResponseORM.student_id,
                )
                .subquery()
            )
            score_rows = session.execute(
                select(
                    QuickActivityResponseORM.activity_id,
                    QuickActivityResponseORM.student_id,
                    func.sum(func.coalesce(QuickActivityAnswerORM.points, 0)).label("points"),
                )
                .join(
                    latest_attempts,
                    (latest_attempts.c.activity_id == QuickActivityResponseORM.activity_id)
                    & (latest_attempts.c.student_id == QuickActivityResponseORM.student_id)
                    & (latest_attempts.c.attempt == QuickActivityResponseORM.attempt),
                )
                .join(
                    QuickActivityAnswerORM,
                    QuickActivityAnswerORM.response_id == QuickActivityResponseORM.id,
                )
                .group_by(
                    QuickActivityResponseORM.activity_id,
                    QuickActivityResponseORM.student_id,
                )
            ).all() if quiz_ids else []

            points_by_period = {
                "apertura": {},
                "clausura": {},
                "total": {},
            }
            for row in score_rows:
                points = int(row.points or 0)
                points_by_period["total"][row.student_id] = (
                    points_by_period["total"].get(row.student_id, 0) + points
                )
                week = quiz_weeks.get(row.activity_id)
                period = (
                    "apertura" if week is not None and 1 <= week <= 7
                    else "clausura" if week is not None and 9 <= week <= cycle_week_count
                    else None
                )
                if period:
                    points_by_period[period][row.student_id] = (
                        points_by_period[period].get(row.student_id, 0) + points
                    )

            roster = session.execute(
                select(StudentORM.id, StudentORM.display_name).where(
                    StudentORM.course_id == course_id,
                    StudentORM.active.is_(True),
                )
            ).all()
            base = {
                "course_id": course.id,
                "course_name": course.name,
                "current_week": (
                    self._current_ranking_week(cycle_start) if cycle_start is not None else None
                ),
                "cycle_week_count": cycle_week_count,
            }
            aperture_quiz_count = sum(
                1 for week in quiz_weeks.values() if week is not None and 1 <= week <= 7
            )
            closing_quiz_count = sum(
                1 for week in quiz_weeks.values()
                if week is not None and 9 <= week <= cycle_week_count
            )
            periods = {
                "apertura": self._ranking_period(
                    "apertura",
                    roster,
                    points_by_period["apertura"],
                    aperture_quiz_count,
                    tie_scope=f"{course.id}:apertura",
                    available=cycle_start is not None,
                    start_week=1,
                    end_week=7,
                ),
                "clausura": self._ranking_period(
                    "clausura",
                    roster,
                    points_by_period["clausura"],
                    closing_quiz_count,
                    tie_scope=f"{course.id}:clausura",
                    available=cycle_start is not None and cycle_week_count >= 9,
                    start_week=9,
                    end_week=cycle_week_count,
                ),
                "total": self._ranking_period(
                    "total",
                    roster,
                    points_by_period["total"],
                    len(completed_quizzes),
                    tie_scope=f"{course.id}:total",
                    available=True,
                    start_week=None,
                    end_week=None,
                ),
            }

            if student_user_id is not None:
                student = session.execute(
                    select(StudentORM.id).where(
                        StudentORM.course_id == course_id,
                        StudentORM.user_id == student_user_id,
                        StudentORM.active.is_(True),
                    )
                ).scalar_one_or_none()
                if student is None:
                    raise QuickActivityNotFoundError("No se encontró la matrícula activa.")
                phase, message = self._student_ranking_phase(
                    base["current_week"], cycle_start is not None, cycle_week_count
                )
                phase_availability = {
                    "apertura": (
                        cycle_start is not None
                        and base["current_week"] is not None
                        and base["current_week"] >= 1
                    ),
                    "clausura": (
                        cycle_start is not None
                        and cycle_week_count >= 9
                        and base["current_week"] is not None
                        and base["current_week"] >= 9
                    ),
                    "total": True,
                }
                period_messages = {
                    "apertura": (
                        "Configura la fecha de inicio del ciclo."
                        if cycle_start is None
                        else "Disponible desde la semana 1."
                    ),
                    "clausura": (
                        "Configura la fecha de inicio del ciclo."
                        if cycle_start is None
                        else "Este ciclo no llega a la semana 9."
                        if cycle_week_count < 9
                        else "Disponible desde la semana 9."
                    ),
                }
                student_periods = []
                for code, period in periods.items():
                    available = phase_availability[code]
                    student_row = next(
                        (
                            item for item in period["students"]
                            if item["student_id"] == student
                        ),
                        None,
                    )
                    student_periods.append({
                        "code": code,
                        "available": available,
                        "start_week": period["start_week"],
                        "end_week": period["end_week"],
                        "quiz_count": period["quiz_count"],
                        "rank": (
                            student_row["rank"]
                            if available and student_row is not None
                            else None
                        ),
                        "points": (
                            student_row["points"]
                            if available and student_row is not None
                            else None
                        ),
                        "message": None if available else (
                            "El curso todavía no inicia."
                            if phase == "not_started"
                            else period_messages.get(code)
                        ),
                    })
                return {
                    **base,
                    "view": "student",
                    "phase": phase,
                    "message": message,
                    "rank": None,
                    "student_count": len(roster),
                    "student_periods": student_periods,
                    "periods": [],
                }

            return {
                **base,
                "view": "teacher",
                "phase": self._teacher_ranking_phase(
                    base["current_week"], cycle_start is not None, cycle_week_count
                ),
                "message": None if cycle_start is not None else (
                    "Configura la fecha de inicio del ciclo para separar Apertura y Clausura."
                ),
                "rank": None,
                "student_count": len(roster),
                "student_periods": [],
                "periods": list(periods.values()),
            }

    @classmethod
    def _ranking_period(
        cls,
        code: str,
        roster,
        points_by_student: dict[int, int],
        quiz_count: int,
        tie_scope: str,
        available: bool,
        start_week: Optional[int],
        end_week: Optional[int],
    ) -> dict:
        ordered = sorted(
            roster,
            key=lambda row: (
                -points_by_student.get(row.id, 0),
                cls._random_tie_key(tie_scope, row.id),
            ),
        )
        return {
            "code": code,
            "available": available,
            "start_week": start_week,
            "end_week": end_week,
            "quiz_count": quiz_count,
            "student_count": len(ordered),
            "students": [
                {
                    "rank": rank,
                    "student_id": row.id,
                    "student_name": row.display_name,
                    "points": points_by_student.get(row.id, 0),
                }
                for rank, row in enumerate(ordered, start=1)
            ] if available else [],
        }

    @staticmethod
    def _ranking_week(value: Optional[datetime], cycle_start) -> Optional[int]:
        if value is None or cycle_start is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        local_date = value.astimezone(RANKING_TIMEZONE).date()
        return (local_date - cycle_start).days // 7 + 1

    def _current_ranking_week(self, cycle_start) -> int:
        now = self._clock()
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        local_date = now.astimezone(RANKING_TIMEZONE).date()
        return (local_date - cycle_start).days // 7 + 1

    @staticmethod
    def _student_ranking_phase(
        current_week: Optional[int], cycle_available: bool, week_count: int
    ) -> tuple[str, Optional[str]]:
        if not cycle_available or current_week is None:
            return "cycle_not_configured", (
                "El docente debe configurar la fecha de inicio del ciclo para habilitar el ranking."
            )
        if current_week < 1:
            return "not_started", "El ciclo académico todavía no comienza."
        if current_week <= 7:
            return "apertura", None
        if current_week == 8:
            return "exam", "Semana 8: semana de examen parcial. El ranking de fase está en pausa."
        if current_week <= week_count:
            return "clausura", None
        if week_count >= 9:
            return "clausura", "Ciclo finalizado. Esta es tu posición final de Clausura."
        return "cycle_finished", "El ciclo académico ya finalizó."

    @staticmethod
    def _teacher_ranking_phase(
        current_week: Optional[int], cycle_available: bool, week_count: int
    ) -> str:
        phase, _ = QuickActivityService._student_ranking_phase(
            current_week, cycle_available, week_count
        )
        return phase

    @staticmethod
    def _random_tie_key(scope: str, student_id: int) -> bytes:
        """Stable pseudo-random tie order that does not change between refreshes."""
        return hashlib.sha256(f"{scope}:{student_id}".encode()).digest()

    def live_answer(
        self, student_user_id: int, activity_id: int, question_id: int, selected_option: int
    ) -> dict:
        """Registra la respuesta a la pregunta en curso (una por pregunta)."""
        with self._session_factory() as session:
            activity, response = self._live_participant(session, student_user_id, activity_id)
            phase = self._effective_phase(activity)
            question = self._current_question(activity)
            if phase != "question" or question is None:
                raise QuickActivityStateError("No hay una pregunta abierta en este momento.")
            if question.id != question_id:
                raise QuickActivityStateError("Esa pregunta ya se cerró.")
            if any(answer.question_id == question.id for answer in response.answers):
                raise AlreadyRespondedError("Ya respondiste esta pregunta.")
            if selected_option is None or not 0 <= int(selected_option) < len(question.options):
                raise InvalidQuickActivityError("Elige una alternativa válida.")
            limit_ms = (activity.question_seconds or DEFAULT_QUESTION_SECONDS) * 1000
            elapsed_ms = max(0, limit_ms - self._remaining_ms(activity))
            if elapsed_ms >= limit_ms:
                raise QuickActivityStateError("Se acabó el tiempo de esta pregunta.")
            correct = int(selected_option) == question.correct_option
            points = round(MAX_POINTS * (1 - (elapsed_ms / limit_ms) / 2)) if correct else 0
            session.add(QuickActivityAnswerORM(
                response_id=response.id,
                question_id=question.id,
                selected_option=int(selected_option),
                is_correct=correct,
                points=points,
                response_ms=elapsed_ms,
                answered_at=self._clock(),
            ))
            try:
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                raise AlreadyRespondedError("Ya respondiste esta pregunta.") from exc
            return {"question_id": question.id, "selected_option": int(selected_option)}

    def _live_participant(self, session: Session, student_user_id: int, activity_id: int):
        activity = session.execute(
            select(QuickActivityORM)
            .where(QuickActivityORM.id == activity_id)
            .options(selectinload(QuickActivityORM.questions))
        ).scalar_one_or_none()
        if activity is None or activity.mode != MODE_LIVE:
            raise QuickActivityNotFoundError("Quiz en vivo no encontrado.")
        enrollment = session.execute(
            select(StudentORM).where(
                StudentORM.user_id == student_user_id,
                StudentORM.course_id == activity.course_id,
                StudentORM.active.is_(True),
            ).limit(1)
        ).scalar_one_or_none()
        if enrollment is None:
            raise NotEnrolledInCourseError("No estás matriculado en el curso de este quiz.")
        response = session.execute(
            select(QuickActivityResponseORM)
            .where(
                QuickActivityResponseORM.activity_id == activity.id,
                QuickActivityResponseORM.student_id == enrollment.id,
            )
            .options(selectinload(QuickActivityResponseORM.answers))
            .limit(1)
        ).scalar_one_or_none()
        if response is None:
            raise NotEnrolledInCourseError("Primero únete al quiz con su código.")
        return activity, response

    @staticmethod
    def _board_fingerprint(session: Session, activity: QuickActivityORM) -> tuple:
        """Huella barata de los datos que determinan el ranking.

        Las respuestas solo se insertan (nunca se editan ni se borran
        durante el quiz), así que (participantes, respuestas, último id de
        respuesta y de participante, cantidad de preguntas) cambia siempre
        que el ranking pueda cambiar. Es una sola consulta agregada sobre
        índices; reemplaza al `count(*)` que ya se hacía en cada consulta.
        """
        row = session.execute(
            select(
                func.count(func.distinct(QuickActivityResponseORM.id)),
                func.count(QuickActivityAnswerORM.id),
                func.coalesce(func.max(QuickActivityAnswerORM.id), 0),
                func.coalesce(func.max(QuickActivityResponseORM.id), 0),
            )
            .select_from(QuickActivityResponseORM)
            .outerjoin(
                QuickActivityAnswerORM,
                QuickActivityAnswerORM.response_id == QuickActivityResponseORM.id,
            )
            .where(QuickActivityResponseORM.activity_id == activity.id)
        ).one()
        return (activity.id, int(row[0]), int(row[1]), int(row[2]), int(row[3]),
                len(activity.questions))

    def _leaderboard(
        self,
        session: Session,
        activity: QuickActivityORM,
        fingerprint: Optional[tuple] = None,
    ) -> List[dict]:
        """Ranking de un quiz en vivo.

        Plan de optimización, tareas 3.3–3.5. Antes se cargaban TODAS las
        respuestas como objetos ORM (3 consultas: envíos, respuestas y
        estudiantes) y se sumaba en Python, y eso se repetía en cada
        consulta de cada estudiante durante `reveal`/`finished` y en cada
        consulta del docente (una por segundo). Ahora:

        * los totales se calculan en PostgreSQL con una agregación
          (`GROUP BY` del envío), una sola consulta sin hidratar objetos;
        * el resultado se guarda en una caché por actividad que se invalida
          sola cuando cambia la huella de datos (`_board_fingerprint`): un
          envío nuevo, una respuesta nueva o una pregunta más. Con 40
          estudiantes mirando los resultados, el ranking se calcula una vez
          y no 40. El TTL corto solo acota la frescura de datos que la
          huella no ve (p. ej. un nombre editado a mitad del quiz).

        El orden y los valores son exactamente los de antes: mismos campos,
        mismo criterio de desempate (`_random_tie_key`).
        """
        if fingerprint is None:
            fingerprint = self._board_fingerprint(session, activity)
        now = time.monotonic()
        with self._board_lock:
            cached = self._board_cache.get(activity.id)
            if (
                cached is not None
                and cached[0] == fingerprint
                and now - cached[1] < LEADERBOARD_CACHE_TTL_S
            ):
                self._board_cache.move_to_end(activity.id)
                return [dict(row) for row in cached[2]]

        board = self._compute_leaderboard(session, activity)
        with self._board_lock:
            self._board_cache[activity.id] = (fingerprint, now, board)
            self._board_cache.move_to_end(activity.id)
            while len(self._board_cache) > LEADERBOARD_CACHE_SIZE:
                self._board_cache.popitem(last=False)
        return [dict(row) for row in board]

    def _compute_leaderboard(self, session: Session, activity: QuickActivityORM) -> List[dict]:
        answer = QuickActivityAnswerORM
        rows = session.execute(
            select(
                QuickActivityResponseORM.student_id,
                StudentORM.display_name,
                StudentORM.external_ref,
                func.coalesce(func.sum(func.coalesce(answer.points, 0)), 0),
                func.count(case((answer.is_correct.is_(True), 1))),
                # Igual que antes (`not answer.is_correct`): cuenta como
                # incorrecta toda respuesta que no sea correcta.
                func.count(case(
                    (answer.id.is_not(None) & answer.is_correct.is_not(True), 1)
                )),
                func.count(answer.id),
                func.coalesce(func.sum(case(
                    (answer.is_correct.is_(True), func.coalesce(answer.response_ms, 0)),
                    else_=0,
                )), 0),
            )
            .select_from(QuickActivityResponseORM)
            .join(StudentORM, StudentORM.id == QuickActivityResponseORM.student_id)
            .outerjoin(answer, answer.response_id == QuickActivityResponseORM.id)
            .where(QuickActivityResponseORM.activity_id == activity.id)
            .group_by(
                QuickActivityResponseORM.id,
                QuickActivityResponseORM.student_id,
                StudentORM.display_name,
                StudentORM.external_ref,
            )
        ).all()
        question_count = len(activity.questions)
        board = [
            {
                "student_id": student_id,
                "student_name": name,
                "student_code": code,
                "points": int(points),
                "correct": int(correct),
                "incorrect": int(incorrect),
                "unanswered": max(0, question_count - int(answered)),
                "time_ms": int(time_ms),
            }
            for student_id, name, code, points, correct, incorrect, answered, time_ms in rows
        ]
        board.sort(key=lambda item: (
            -item["points"],
            item["time_ms"],
            self._random_tie_key(
                activity.join_code or str(activity.id), item["student_id"]
            ),
        ))
        for index, item in enumerate(board, start=1):
            item["rank"] = index
        return board

    def _teacher_live_state(self, session: Session, activity: QuickActivityORM) -> dict:
        phase = self._effective_phase(activity)
        question = self._current_question(activity) if phase in ("question", "reveal") else None
        board = self._leaderboard(session, activity)
        answered_count = 0
        per_option: dict = {}
        if question is not None:
            # Antes se cargaban todas las respuestas de la pregunta como
            # objetos; basta un conteo agrupado por alternativa.
            counts = session.execute(
                select(QuickActivityAnswerORM.selected_option, func.count(QuickActivityAnswerORM.id))
                .join(QuickActivityResponseORM)
                .where(
                    QuickActivityResponseORM.activity_id == activity.id,
                    QuickActivityAnswerORM.question_id == question.id,
                )
                .group_by(QuickActivityAnswerORM.selected_option)
            ).all()
            per_option = {option: int(total) for option, total in counts}
            answered_count = sum(per_option.values())
        reveal = phase in ("reveal", "finished")
        distribution = None
        if question is not None and reveal:
            distribution = [0] * len(question.options or [])
            for option, total in per_option.items():
                if option is not None and option < len(distribution):
                    distribution[option] += total
        return {
            "activity": self._teacher_view(session, activity, response_count=len(board)),
            "phase": phase,
            "finished_at": _utc(activity.closed_at) if phase == "finished" else None,
            "server_time": _utc(self._clock()),
            "position": activity.live_position,
            "question_count": len(activity.questions),
            "remaining_ms": self._remaining_ms(activity) if phase == "question" else 0,
            "participant_count": len(board),
            "participants": [
                {"student_name": row["student_name"], "student_code": row["student_code"]}
                for row in sorted(board, key=lambda item: item["student_name"])
            ],
            "question": None if question is None else {
                "id": question.id,
                "position": question.position,
                "prompt": question.prompt,
                "options": question.options,
                "correct_option": question.correct_option if reveal else None,
            },
            "answered_count": answered_count,
            "distribution": distribution,
            "leaderboard": (
                board if phase == "finished"
                else board[:LEADERBOARD_SIZE] if reveal
                else []
            ),
        }

    # ------------------------------------------------------------------
    # Validaciones
    # ------------------------------------------------------------------

    def _validate_access(self, session: Session, student_user_id: int, code: str):
        normalized = normalize_join_code(code)
        if not normalized:
            raise InvalidJoinCodeError("Ingresa el código de la actividad.")
        activity = session.execute(
            select(QuickActivityORM)
            .where(QuickActivityORM.join_code == normalized)
            .options(selectinload(QuickActivityORM.questions))
        ).scalar_one_or_none()
        if activity is None:
            raise InvalidJoinCodeError("El código no corresponde a ninguna actividad.")
        # Vigencia (HU-Q5, criterio 1).
        if activity.status == "closed":
            raise ActivityNotAvailableError("El docente ya cerró esta actividad.")
        if activity.status != "published":
            raise ActivityNotAvailableError("La actividad todavía no está publicada.")
        if _utc(activity.expires_at) is None or _utc(activity.expires_at) <= self._clock():
            raise ActivityNotAvailableError("El código de esta actividad ya venció.")
        course = session.get(CourseORM, activity.course_id)
        if course is None or course.enabled is False:
            raise ActivityNotAvailableError("El curso de esta actividad no está disponible.")
        # Pertenencia al curso (HU-Q5, criterio 2).
        enrollment = session.execute(
            select(StudentORM).where(
                StudentORM.user_id == student_user_id,
                StudentORM.course_id == activity.course_id,
                StudentORM.active.is_(True),
            ).limit(1)
        ).scalar_one_or_none()
        if enrollment is None:
            raise NotEnrolledInCourseError(
                "No estás matriculado en el curso de esta actividad."
            )
        return activity, enrollment

    @staticmethod
    def _attempts(session: Session, activity_id: int, student_id: int) -> int:
        return int(session.execute(
            select(func.count(QuickActivityResponseORM.id)).where(
                QuickActivityResponseORM.activity_id == activity_id,
                QuickActivityResponseORM.student_id == student_id,
            )
        ).scalar_one())

    @staticmethod
    def _clean_questions(questions: Sequence[dict]) -> List[dict]:
        if not questions:
            raise InvalidQuickActivityError("Agrega al menos una pregunta.")
        if len(questions) > MAX_QUESTIONS:
            raise InvalidQuickActivityError(
                f"Una actividad rápida admite hasta {MAX_QUESTIONS} preguntas."
            )
        cleaned = []
        for number, question in enumerate(questions, start=1):
            prompt = " ".join(str(question.get("prompt") or "").split())
            if not prompt:
                raise InvalidQuickActivityError(f"La pregunta {number} está vacía.")
            raw_options = question.get("options") or []
            options = [" ".join(str(option).split()) for option in raw_options]
            options = [option for option in options if option]
            if len(raw_options) and len(options) != len(raw_options):
                raise InvalidQuickActivityError(
                    f"La pregunta {number} tiene alternativas vacías."
                )
            if options and not 2 <= len(options) <= MAX_OPTIONS:
                raise InvalidQuickActivityError(
                    f"La pregunta {number} debe tener entre 2 y {MAX_OPTIONS} alternativas."
                )
            correct = question.get("correct_option")
            if correct is not None:
                if not options or not 0 <= int(correct) < len(options):
                    raise InvalidQuickActivityError(
                        f"La alternativa correcta de la pregunta {number} no existe."
                    )
                correct = int(correct)
            cleaned.append({
                "prompt": prompt,
                "options": options or None,
                "correct_option": correct,
            })
        return cleaned

    @staticmethod
    def _clean_answers(activity: QuickActivityORM, answers: Iterable[dict]) -> List[dict]:
        questions = {question.id: question for question in activity.questions}
        provided = {}
        for answer in answers or []:
            question_id = answer.get("question_id")
            if question_id not in questions:
                raise InvalidQuickActivityError("Una respuesta no corresponde a la actividad.")
            if question_id in provided:
                raise InvalidQuickActivityError("Respondiste dos veces la misma pregunta.")
            provided[question_id] = answer
        missing = [q.position for q in activity.questions if q.id not in provided]
        if missing:
            raise InvalidQuickActivityError(
                "Responde todas las preguntas antes de enviar (falta: "
                + ", ".join(str(position) for position in missing) + ")."
            )
        cleaned = []
        for question in activity.questions:
            answer = provided[question.id]
            if question.options:
                selected = answer.get("selected_option")
                if selected is None or not 0 <= int(selected) < len(question.options):
                    raise InvalidQuickActivityError(
                        f"Elige una alternativa válida en la pregunta {question.position}."
                    )
                selected = int(selected)
                cleaned.append({
                    "question_id": question.id,
                    "answer_text": None,
                    "selected_option": selected,
                    "is_correct": (
                        None if question.correct_option is None
                        else selected == question.correct_option
                    ),
                })
            else:
                text = str(answer.get("answer_text") or "").strip()
                if not text:
                    raise InvalidQuickActivityError(
                        f"Escribe tu respuesta a la pregunta {question.position}."
                    )
                if len(text) > MAX_ANSWER_LENGTH:
                    raise InvalidQuickActivityError(
                        f"La respuesta a la pregunta {question.position} supera "
                        f"los {MAX_ANSWER_LENGTH} caracteres."
                    )
                cleaned.append({
                    "question_id": question.id,
                    "answer_text": text,
                    "selected_option": None,
                    "is_correct": None,
                })
        return cleaned

    @staticmethod
    def _new_code(session: Session) -> str:
        for _ in range(50):
            code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
            taken = session.execute(
                select(QuickActivityORM.id).where(QuickActivityORM.join_code == code)
            ).scalar_one_or_none()
            if taken is None:
                return code
        raise RuntimeError("No se pudo generar un código único para la actividad.")

    @staticmethod
    def _activity_in_course(session: Session, course_id: int, activity_id: int) -> QuickActivityORM:
        activity = session.execute(
            select(QuickActivityORM)
            .where(QuickActivityORM.id == activity_id)
            .options(selectinload(QuickActivityORM.questions))
        ).scalar_one_or_none()
        if activity is None or activity.course_id != course_id:
            raise QuickActivityNotFoundError(f"Actividad {activity_id} no encontrada.")
        return activity

    # ------------------------------------------------------------------
    # Representaciones
    # ------------------------------------------------------------------

    def _availability(self, activity: QuickActivityORM) -> str:
        if activity.status == "published":
            expires = _utc(activity.expires_at)
            return "open" if expires and expires > self._clock() else "expired"
        return activity.status  # draft / closed

    def _teacher_view(
        self,
        session: Session,
        activity: QuickActivityORM,
        response_count: Optional[int] = None,
    ) -> dict:
        if response_count is None:
            response_count = int(session.execute(
                select(func.count(QuickActivityResponseORM.id)).where(
                    QuickActivityResponseORM.activity_id == activity.id
                )
            ).scalar_one())
        return {
            "id": activity.id,
            "course_id": activity.course_id,
            "class_session_id": activity.class_session_id,
            "title": activity.title,
            "status": activity.status,
            "availability": self._availability(activity),
            "join_code": activity.join_code,
            "join_url": f"/?actividad={activity.join_code}" if activity.join_code else None,
            "published_at": _utc(activity.published_at),
            "expires_at": _utc(activity.expires_at),
            "closed_at": _utc(activity.closed_at),
            "allow_multiple_responses": bool(activity.allow_multiple_responses),
            "mode": activity.mode or MODE_SELF_PACED,
            "question_seconds": activity.question_seconds,
            "live_phase": self._effective_phase(activity) if activity.mode == MODE_LIVE else None,
            "created_at": _utc(activity.created_at),
            "response_count": response_count,
            "questions": [
                {
                    "id": question.id,
                    "position": question.position,
                    "prompt": question.prompt,
                    "options": question.options,
                    "correct_option": question.correct_option,
                }
                for question in activity.questions
            ],
        }

    def _student_view(
        self, session: Session, activity: QuickActivityORM, previous_attempts: int
    ) -> dict:
        course = session.get(CourseORM, activity.course_id)
        return {
            "id": activity.id,
            "title": activity.title,
            "course_id": activity.course_id,
            "course_name": course.name if course else "",
            "join_code": activity.join_code,
            "expires_at": _utc(activity.expires_at),
            "allow_multiple_responses": bool(activity.allow_multiple_responses),
            "mode": activity.mode or MODE_SELF_PACED,
            "question_seconds": activity.question_seconds,
            "previous_attempts": previous_attempts,
            # Sin `correct_option`: el estudiante no debe ver la respuesta.
            "questions": [] if activity.mode == MODE_LIVE else [
                {
                    "id": question.id,
                    "position": question.position,
                    "prompt": question.prompt,
                    "options": question.options,
                }
                for question in activity.questions
            ],
        }

    @staticmethod
    def _answer_dict(answer: QuickActivityAnswerORM) -> dict:
        return {
            "question_id": answer.question_id,
            "answer_text": answer.answer_text,
            "selected_option": answer.selected_option,
            "is_correct": answer.is_correct,
            "points": answer.points,
            "response_ms": answer.response_ms,
        }
