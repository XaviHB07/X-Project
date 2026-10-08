"""Tests de `SessionService` (HU-S1, HU-S2) y de su integración con la
selección aleatoria, sobre el repositorio in-memory."""

from datetime import date, datetime, timezone

import numpy as np
import pytest

import src.strategies  # noqa: F401  (registra las estrategias)
from src.repositories.in_memory.repository_impl import InMemoryDatabase
from src.repositories.in_memory.unit_of_work import InMemoryUnitOfWork
from src.services.errors import CourseNotFoundError, InvalidAttendanceError, SessionNotFoundError
from src.services.selection_service import NoClassSessionError, NoEligibleStudentsError, SelectionService
from src.services.session_service import SessionService


def setup(n_students=5):
    db = InMemoryDatabase()

    def uow_factory() -> InMemoryUnitOfWork:
        return InMemoryUnitOfWork(db)

    with uow_factory() as uow:
        course = uow.courses.create("Curso")
        ids = [
            uow.students.get_or_create(course.id, f"A{i}", f"Estudiante {i}", 1.0, 1.0).id
            for i in range(n_students)
        ]
        uow.commit()
    return uow_factory, SessionService(uow_factory), SelectionService(uow_factory), course.id, ids


class TestIniciarSesion:
    def test_proposal_defaults_to_today_without_topic_when_no_syllabus(self):
        _, sessions, _, course_id, _ = setup()
        proposal = sessions.propose(course_id)
        assert proposal.session_date == datetime.now(timezone.utc).date()
        assert proposal.suggested_topic is None

    def test_proposal_uses_syllabus_topic_for_that_date(self):
        _, sessions, _, course_id, _ = setup()
        sessions.set_syllabus_entry(course_id, date(2026, 10, 12), "Límites")
        assert sessions.propose(course_id, date(2026, 10, 12)).suggested_topic == "Límites"
        assert sessions.propose(course_id, date(2026, 10, 13)).suggested_topic is None

    def test_syllabus_entry_is_replaced_for_same_date(self):
        _, sessions, _, course_id, _ = setup()
        sessions.set_syllabus_entry(course_id, date(2026, 10, 12), "Límites")
        sessions.set_syllabus_entry(course_id, date(2026, 10, 12), "Derivadas")
        entries = sessions.list_syllabus(course_id)
        assert [(e.session_date, e.topic) for e in entries] == [(date(2026, 10, 12), "Derivadas")]

    def test_start_uses_today_and_syllabus_topic_when_teacher_does_not_override(self):
        _, sessions, _, course_id, _ = setup()
        today = datetime.now(timezone.utc).date()
        sessions.set_syllabus_entry(course_id, today, "Integrales")
        detail = sessions.start_session(course_id)
        assert detail.session.session_date == today
        assert detail.session.topic == "Integrales"

    def test_teacher_can_correct_the_proposed_topic(self):
        _, sessions, _, course_id, _ = setup()
        today = datetime.now(timezone.utc).date()
        sessions.set_syllabus_entry(course_id, today, "Integrales")
        detail = sessions.start_session(course_id, topic="  Repaso   de integrales ")
        assert detail.session.topic == "Repaso de integrales"

    def test_session_without_syllabus_or_topic_is_allowed(self):
        _, sessions, _, course_id, _ = setup()
        assert sessions.start_session(course_id).session.topic is None

    def test_by_default_all_active_students_start_present(self):
        _, sessions, _, course_id, ids = setup(4)
        detail = sessions.start_session(course_id)
        assert detail.present_count == 4
        assert {a.student_id for a in detail.attendance} == set(ids)

    def test_start_with_explicit_present_list(self):
        _, sessions, _, course_id, ids = setup(4)
        detail = sessions.start_session(course_id, present_student_ids=ids[:2])
        assert {a.student_id for a in detail.attendance if a.present} == set(ids[:2])
        assert detail.present_count == 2
        assert len(detail.attendance) == 4

    def test_start_rejects_students_from_other_course_or_withdrawn(self):
        uow_factory, sessions, _, course_id, ids = setup(3)
        with uow_factory() as uow:
            other_course = uow.courses.create("Otro").id
            foreign = uow.students.get_or_create(other_course, "Z", "Z", 1.0, 1.0).id
            uow.students.update(ids[0], active=False)
            uow.commit()
        with pytest.raises(InvalidAttendanceError):
            sessions.start_session(course_id, present_student_ids=[ids[1], foreign])
        with pytest.raises(InvalidAttendanceError):
            sessions.start_session(course_id, present_student_ids=[ids[0]])  # retirado

    def test_withdrawn_students_are_not_part_of_new_session(self):
        uow_factory, sessions, _, course_id, ids = setup(3)
        with uow_factory() as uow:
            uow.students.update(ids[0], active=False)
            uow.commit()
        detail = sessions.start_session(course_id)
        assert {a.student_id for a in detail.attendance} == set(ids[1:])

    def test_unknown_course_raises(self):
        _, sessions, _, _, _ = setup()
        with pytest.raises(CourseNotFoundError):
            sessions.start_session(999)
        with pytest.raises(CourseNotFoundError):
            sessions.propose(999)

    def test_too_long_topic_is_rejected(self):
        _, sessions, _, course_id, _ = setup()
        with pytest.raises(ValueError):
            sessions.start_session(course_id, topic="x" * 300)

    def test_list_sessions_most_recent_first(self):
        _, sessions, _, course_id, _ = setup()
        first = sessions.start_session(course_id, topic="Uno").session
        second = sessions.start_session(course_id, topic="Dos").session
        assert [s.id for s in sessions.list_sessions(course_id)] == [second.id, first.id]


class TestAsistencia:
    def test_mark_and_unmark_students(self):
        _, sessions, _, course_id, ids = setup(4)
        session_id = sessions.start_session(course_id).session.id
        detail = sessions.set_attendance(session_id, {ids[0]: False, ids[1]: False})
        assert detail.present_count == 2
        detail = sessions.set_attendance(session_id, {ids[0]: True})
        assert detail.present_count == 3
        assert sessions.get_session(session_id).present_count == 3

    def test_attendance_is_per_session(self):
        _, sessions, _, course_id, ids = setup(3)
        first = sessions.start_session(course_id).session.id
        second = sessions.start_session(course_id).session.id
        sessions.set_attendance(first, {ids[0]: False})
        assert sessions.get_session(first).present_count == 2
        assert sessions.get_session(second).present_count == 3

    def test_student_enrolled_after_start_counts_as_absent_until_marked(self):
        uow_factory, sessions, _, course_id, ids = setup(2)
        session_id = sessions.start_session(course_id).session.id
        with uow_factory() as uow:
            late = uow.students.get_or_create(course_id, "LATE", "Tardío", 1.0, 1.0).id
            uow.commit()
        detail = sessions.get_session(session_id)
        assert next(a for a in detail.attendance if a.student_id == late).present is False
        detail = sessions.set_attendance(session_id, {late: True})
        assert next(a for a in detail.attendance if a.student_id == late).present is True

    def test_rejects_foreign_students_and_saves_nothing(self):
        uow_factory, sessions, _, course_id, ids = setup(3)
        with uow_factory() as uow:
            other = uow.courses.create("Otro").id
            foreign = uow.students.get_or_create(other, "Z", "Z", 1.0, 1.0).id
            uow.commit()
        session_id = sessions.start_session(course_id).session.id
        with pytest.raises(InvalidAttendanceError):
            sessions.set_attendance(session_id, {ids[0]: False, foreign: True})
        assert sessions.get_session(session_id).present_count == 3  # ids[0] sigue presente

    def test_empty_update_and_unknown_session(self):
        _, sessions, _, course_id, _ = setup()
        session_id = sessions.start_session(course_id).session.id
        with pytest.raises(InvalidAttendanceError):
            sessions.set_attendance(session_id, {})
        with pytest.raises(SessionNotFoundError):
            sessions.set_attendance(9999, {1: True})
        with pytest.raises(SessionNotFoundError):
            sessions.get_session(9999)


class TestSeleccionUsaAsistencia:
    def test_selection_only_considers_students_marked_present(self):
        _, sessions, selection, course_id, ids = setup(6)
        session_id = sessions.start_session(course_id, present_student_ids=ids[:3]).session.id

        result = selection.run_selection(
            course_id=course_id,
            present_student_ids=None,
            k=3,
            method_name="roulette",
            class_session_id=session_id,
            rng=np.random.default_rng(0),
        )

        assert set(result.considered_student_ids) == set(ids[:3])
        assert set(result.selected_student_ids) == set(ids[:3])
        assert result.class_session_id == session_id

    def test_absent_students_do_not_accumulate_presence(self):
        uow_factory, sessions, selection, course_id, ids = setup(4)
        session_id = sessions.start_session(course_id, present_student_ids=ids[:2]).session.id
        selection.run_selection(
            course_id=course_id, present_student_ids=None, k=1, method_name="bayesian_fairness",
            class_session_id=session_id, rng=np.random.default_rng(1),
        )
        with uow_factory() as uow:
            states = {c.student_id: c for c in uow.student_states.get_all_candidates_for_course(course_id)}
        assert [states[i].n_present for i in ids] == [1, 1, 0, 0]

    def test_marking_absent_before_selecting_excludes_that_student(self):
        _, sessions, selection, course_id, ids = setup(3)
        session_id = sessions.start_session(course_id).session.id
        sessions.set_attendance(session_id, {ids[0]: False})
        result = selection.run_selection(
            course_id=course_id, present_student_ids=None, k=3, method_name="roulette",
            class_session_id=session_id, rng=np.random.default_rng(2),
        )
        assert set(result.selected_student_ids) == set(ids[1:])

    def test_no_one_present_raises(self):
        _, sessions, selection, course_id, ids = setup(3)
        session_id = sessions.start_session(course_id, present_student_ids=[]).session.id
        with pytest.raises(NoEligibleStudentsError):
            selection.run_selection(
                course_id=course_id, present_student_ids=None, k=1, method_name="roulette",
                class_session_id=session_id,
            )

    def test_requires_present_ids_or_session(self):
        _, _, selection, course_id, _ = setup()
        with pytest.raises(ValueError):
            selection.run_selection(
                course_id=course_id, present_student_ids=None, k=1, method_name="roulette"
            )

    def test_session_from_another_course_is_rejected(self):
        uow_factory, sessions, selection, course_id, ids = setup(3)
        with uow_factory() as uow:
            other = uow.courses.create("Otro").id
            uow.commit()
        foreign_session = sessions.start_session(other).session.id
        with pytest.raises(NoClassSessionError):
            selection.run_selection(
                course_id=course_id, present_student_ids=ids, k=1, method_name="roulette",
                class_session_id=foreign_session,
            )

    def test_explicit_ids_still_work_without_a_session(self):
        _, _, selection, course_id, ids = setup(3)
        result = selection.run_selection(
            course_id=course_id, present_student_ids=ids, k=1, method_name="roulette",
            rng=np.random.default_rng(3),
        )
        assert len(result.selected_student_ids) == 1
