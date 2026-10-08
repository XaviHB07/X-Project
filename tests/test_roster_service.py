"""Tests de `RosterService` (HU-C1) sobre el repositorio in-memory."""

import io

import pytest
from openpyxl import Workbook

from src.repositories.in_memory.repository_impl import InMemoryDatabase
from src.repositories.in_memory.unit_of_work import InMemoryUnitOfWork
from src.repositories.interfaces import DuplicateStudentError
from src.services.errors import CourseNotFoundError, StudentNotFoundError
from src.services.roster_import import RosterFormatError
from src.services.roster_service import RosterService


def make_xlsx(rows) -> bytes:
    wb = Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def setup():
    db = InMemoryDatabase()

    def uow_factory() -> InMemoryUnitOfWork:
        return InMemoryUnitOfWork(db)

    with uow_factory() as uow:
        course = uow.courses.create("Curso")
        uow.commit()
    return uow_factory, RosterService(uow_factory), course.id


def roster(uow_factory, course_id, include_inactive=False):
    with uow_factory() as uow:
        return uow.students.list_by_course(course_id, include_inactive=include_inactive)


class TestImport:
    def test_imports_students_and_associates_them_to_the_course(self):
        uow_factory, service, course_id = setup()
        result = service.import_roster(
            course_id, make_xlsx([["codigo", "nombre"], ["A1", "Ana"], ["A2", "Luis"]])
        )
        assert (result.created, result.updated, result.unchanged) == (2, 0, 0)
        assert [s.display_name for s in roster(uow_factory, course_id)] == ["Ana", "Luis"]

    def test_each_imported_student_gets_initial_state(self):
        uow_factory, service, course_id = setup()
        service.import_roster(course_id, make_xlsx([["codigo", "nombre"], ["A1", "Ana"]]))
        with uow_factory() as uow:
            candidates = uow.student_states.get_all_candidates_for_course(course_id)
        assert len(candidates) == 1
        assert (candidates[0].alpha, candidates[0].beta) == (1.0, 1.0)

    def test_reimport_is_idempotent_and_updates_changed_names(self):
        uow_factory, service, course_id = setup()
        service.import_roster(course_id, make_xlsx([["codigo", "nombre"], ["A1", "Ana"], ["A2", "Luis"]]))
        result = service.import_roster(
            course_id, make_xlsx([["codigo", "nombre"], ["A1", "Ana"], ["A2", "Luis Pérez"], ["A3", "Eva"]])
        )
        assert (result.created, result.updated, result.unchanged) == (1, 1, 1)
        names = {s.external_ref: s.display_name for s in roster(uow_factory, course_id)}
        assert names == {"A1": "Ana", "A2": "Luis Pérez", "A3": "Eva"}

    def test_students_missing_from_new_file_are_not_removed(self):
        uow_factory, service, course_id = setup()
        service.import_roster(course_id, make_xlsx([["codigo", "nombre"], ["A1", "Ana"], ["A2", "Luis"]]))
        service.import_roster(course_id, make_xlsx([["codigo", "nombre"], ["A1", "Ana"]]))
        assert len(roster(uow_factory, course_id)) == 2

    def test_invalid_rows_are_reported_and_valid_rows_saved(self):
        uow_factory, service, course_id = setup()
        result = service.import_roster(
            course_id, make_xlsx([["codigo", "nombre"], ["A1", "Ana"], ["A2", None]])
        )
        assert result.created == 1
        assert [e.row_number for e in result.errors] == [3]
        assert len(roster(uow_factory, course_id)) == 1

    def test_bad_structure_saves_nothing(self):
        uow_factory, service, course_id = setup()
        with pytest.raises(RosterFormatError):
            service.import_roster(course_id, make_xlsx([["foo", "bar"], ["A1", "Ana"]]))
        assert roster(uow_factory, course_id) == []

    def test_unknown_course_raises(self):
        _, service, _ = setup()
        with pytest.raises(CourseNotFoundError):
            service.import_roster(999, make_xlsx([["codigo", "nombre"], ["A1", "Ana"]]))

    def test_same_code_in_two_courses_is_allowed(self):
        uow_factory, service, course_a = setup()
        with uow_factory() as uow:
            course_b = uow.courses.create("Otro").id
            uow.commit()
        data = make_xlsx([["codigo", "nombre"], ["A1", "Ana"]])
        service.import_roster(course_a, data)
        service.import_roster(course_b, data)
        assert len(roster(uow_factory, course_a)) == 1
        assert len(roster(uow_factory, course_b)) == 1


class TestEdicion:
    def _one_student(self):
        uow_factory, service, course_id = setup()
        service.import_roster(course_id, make_xlsx([["codigo", "nombre"], ["A1", "Ana"], ["A2", "Luis"]]))
        return uow_factory, service, course_id, roster(uow_factory, course_id)

    def test_rename_student(self):
        _, service, _, students = self._one_student()
        updated = service.update_student(students[0].id, display_name="Ana María")
        assert updated.display_name == "Ana María"
        assert updated.external_ref == "A1"

    def test_withdraw_hides_student_but_keeps_state_and_reimport_reactivates(self):
        uow_factory, service, course_id, students = self._one_student()
        service.update_student(students[0].id, active=False)
        assert [s.external_ref for s in roster(uow_factory, course_id)] == ["A2"]
        assert len(roster(uow_factory, course_id, include_inactive=True)) == 2
        with uow_factory() as uow:
            assert uow.student_states.get_candidates_readonly([students[0].id])  # historial intacto

        result = service.import_roster(
            course_id, make_xlsx([["codigo", "nombre"], ["A1", "Ana"], ["A2", "Luis"]])
        )
        assert result.updated == 1  # reactivación
        assert len(roster(uow_factory, course_id)) == 2

    def test_change_code_to_existing_one_is_rejected(self):
        _, service, _, students = self._one_student()
        with pytest.raises(DuplicateStudentError):
            service.update_student(students[0].id, external_ref="A2")

    def test_unknown_student_raises(self):
        _, service, _, _ = self._one_student()
        with pytest.raises(StudentNotFoundError):
            service.update_student(9999, display_name="X")
