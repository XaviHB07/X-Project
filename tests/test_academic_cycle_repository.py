"""HU-C3 — contrato del repositorio de ciclos académicos, ejercitado sobre
la implementación in-memory (la de SQLAlchemy se cubre de punta a punta en
`test_api.py::TestGestionCicloAcademicoDocente`)."""

from datetime import date

import pytest

from src.repositories.in_memory.repository_impl import InMemoryDatabase
from src.repositories.in_memory.unit_of_work import InMemoryUnitOfWork
from src.repositories.interfaces import AcademicCycleInUseError, DuplicateAcademicCycleError


@pytest.fixture()
def uow_factory():
    db = InMemoryDatabase()
    return lambda: InMemoryUnitOfWork(db)


def test_name_is_unique_per_owner(uow_factory):
    with uow_factory() as uow:
        uow.cycles.create("2027-I", owner_teacher_id=1)
        uow.cycles.create("2027-I", owner_teacher_id=2)
        uow.cycles.create("2027-I")  # sin dueño (Administrador)
        with pytest.raises(DuplicateAcademicCycleError):
            uow.cycles.create("2027-I", owner_teacher_id=1)
        with pytest.raises(DuplicateAcademicCycleError):
            uow.cycles.create("2027-I")


def test_update_changes_only_given_fields(uow_factory):
    with uow_factory() as uow:
        cycle = uow.cycles.create(
            "2027-I", starts_on=date(2027, 3, 1), ends_on=date(2027, 7, 1), owner_teacher_id=1
        )
        updated = uow.cycles.update(cycle.id, name="2027-1", enabled=False)
        assert updated.name == "2027-1"
        assert updated.enabled is False
        assert updated.starts_on == date(2027, 3, 1)
        assert updated.ends_on == date(2027, 7, 1)
        cleared = uow.cycles.update(cycle.id, clear_ends_on=True)
        assert cleared.ends_on is None
        assert uow.cycles.update(999, name="X") is None


def test_delete_is_blocked_while_cycle_has_courses(uow_factory):
    with uow_factory() as uow:
        empty = uow.cycles.create("Vacío")
        used = uow.cycles.create("Con curso")
        uow.courses.create("Curso", cycle_id=used.id)
        assert uow.cycles.count_courses(used.id) == 1
        assert uow.cycles.delete(empty.id) is True
        assert uow.cycles.get(empty.id) is None
        assert uow.cycles.delete(empty.id) is False
        with pytest.raises(AcademicCycleInUseError):
            uow.cycles.delete(used.id)
        assert uow.cycles.get(used.id) is not None
