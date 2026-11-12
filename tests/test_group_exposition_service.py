"""Tests de `GroupExpositionService` (nota grupal + notas individuales de
un grupo expositor), sobre el repositorio in-memory."""

import pytest

from src.domain.entities import GroupExpositionMemberEntry, StudentGroup
from src.repositories.in_memory.repository_impl import InMemoryDatabase
from src.repositories.in_memory.unit_of_work import InMemoryUnitOfWork
from src.services.errors import CourseNotFoundError, SessionNotFoundError
from src.services.group_exposition_service import (
    GroupExpositionNotFoundError,
    GroupExpositionService,
    InvalidGroupExpositionError,
)
from src.services.group_planning_service import GroupPlanningService


def setup(n_students=4):
    db = InMemoryDatabase()

    def uow_factory() -> InMemoryUnitOfWork:
        return InMemoryUnitOfWork(db)

    with uow_factory() as uow:
        course = uow.courses.create("Curso")
        other_course = uow.courses.create("Otro curso")
        ids = [
            uow.students.get_or_create(course.id, f"A{i}", f"Estudiante {i}", 1.0, 1.0).id
            for i in range(n_students)
        ]
        outsider = uow.students.get_or_create(other_course.id, "X1", "Ajeno", 1.0, 1.0).id
        uow.commit()
    return uow_factory, GroupExpositionService(uow_factory), course.id, other_course.id, ids, outsider


def entries(ids, score=4.0):
    return [
        GroupExpositionMemberEntry(student_id=student_id, present=True, score=score, position=index + 1)
        for index, student_id in enumerate(ids)
    ]


class TestRegistrarExposicion:
    def test_records_group_score_and_one_score_per_member(self):
        _, service, course_id, _, ids, _ = setup()
        members = [
            GroupExpositionMemberEntry(ids[0], present=True, score=4.5, position=2),
            GroupExpositionMemberEntry(ids[1], present=True, score=3.0, position=1),
            GroupExpositionMemberEntry(ids[2], present=False),
        ]
        exposition = service.record(
            course_id, "  Grupo   1 ", 4.0, members, comment="  Buen dominio  ", duration_seconds=312
        )

        assert exposition.group_name == "Grupo 1"
        assert exposition.group_score == 4.0
        assert exposition.comment == "Buen dominio"
        assert exposition.duration_seconds == 312
        # Orden de exposición primero; el ausente (sin posición) al final.
        assert [m.student_id for m in exposition.members] == [ids[1], ids[0], ids[2]]
        assert [m.score for m in exposition.members] == [3.0, 4.5, None]
        assert [m.present for m in exposition.members] == [True, True, False]
        assert exposition.members[0].display_name == "Estudiante 1"
        assert service.list_for_course(course_id) == [exposition]
        assert service.get(course_id, exposition.id) == exposition

    def test_present_member_requires_individual_score(self):
        _, service, course_id, _, ids, _ = setup()
        with pytest.raises(InvalidGroupExpositionError, match="presente"):
            service.record(
                course_id, "Grupo 1", 4.0,
                [GroupExpositionMemberEntry(ids[0], present=True, score=None)],
            )

    @pytest.mark.parametrize("score", [-0.1, 5.1, float("nan")])
    def test_scores_must_be_between_zero_and_five(self, score):
        _, service, course_id, _, ids, _ = setup()
        with pytest.raises(InvalidGroupExpositionError):
            service.record(course_id, "Grupo 1", score, entries(ids[:2]))
        with pytest.raises(InvalidGroupExpositionError):
            service.record(course_id, "Grupo 1", 4.0, entries(ids[:2], score=score))

    def test_rejects_repeated_empty_or_foreign_members(self):
        _, service, course_id, _, ids, outsider = setup()
        with pytest.raises(InvalidGroupExpositionError, match="repitas"):
            service.record(course_id, "Grupo 1", 4.0, entries([ids[0], ids[0]]))
        with pytest.raises(InvalidGroupExpositionError, match="al menos"):
            service.record(course_id, "Grupo 1", 4.0, [])
        with pytest.raises(InvalidGroupExpositionError, match="matriculados"):
            service.record(course_id, "Grupo 1", 4.0, entries([ids[0], outsider]))
        with pytest.raises(InvalidGroupExpositionError, match="nombre"):
            service.record(course_id, "   ", 4.0, entries(ids[:2]))

    def test_session_and_plan_must_belong_to_the_course(self):
        uow_factory, service, course_id, other_course_id, ids, _ = setup()
        with uow_factory() as uow:
            session = uow.class_sessions.create(course_id, label="Clase")
            foreign_session = uow.class_sessions.create(other_course_id, label="Otra")
            plan = uow.group_plans.create(
                course_id, "Proyecto final", 2, [StudentGroup("Grupo 1", ids[:2])]
            )
            foreign_plan = uow.group_plans.create(other_course_id, "Ajena", 2, [])
            uow.commit()

        exposition = service.record(
            course_id, "Grupo 1", 4.0, entries(ids[:2]),
            class_session_id=session.id, group_plan_id=plan.id,
        )
        assert exposition.class_session_id == session.id
        assert exposition.group_plan_id == plan.id
        assert exposition.plan_name == "Proyecto final"

        with pytest.raises(SessionNotFoundError):
            service.record(
                course_id, "Grupo 1", 4.0, entries(ids[:2]), class_session_id=foreign_session.id
            )
        with pytest.raises(InvalidGroupExpositionError, match="propuesta"):
            service.record(
                course_id, "Grupo 1", 4.0, entries(ids[:2]), group_plan_id=foreign_plan.id
            )
        with pytest.raises(CourseNotFoundError):
            service.record(999, "Grupo 1", 4.0, entries(ids[:2]))


class TestCorregirExposicion:
    def test_update_replaces_scores_and_keeps_identity(self):
        _, service, course_id, _, ids, _ = setup()
        original = service.record(course_id, "Grupo 1", 3.0, entries(ids[:3], score=3.0))

        updated = service.update(
            course_id,
            original.id,
            group_score=4.5,
            members=[
                GroupExpositionMemberEntry(ids[0], present=True, score=5.0, position=1),
                GroupExpositionMemberEntry(ids[3], present=False),
            ],
            comment="Corregido",
        )

        assert updated.id == original.id
        assert updated.group_name == "Grupo 1"
        assert updated.group_score == 4.5
        assert updated.comment == "Corregido"
        assert [(m.student_id, m.score, m.present) for m in updated.members] == [
            (ids[0], 5.0, True),
            (ids[3], None, False),
        ]
        assert len(service.list_for_course(course_id)) == 1

    def test_update_is_scoped_to_the_course(self):
        _, service, course_id, other_course_id, ids, _ = setup()
        exposition = service.record(course_id, "Grupo 1", 3.0, entries(ids[:2]))
        with pytest.raises(GroupExpositionNotFoundError):
            service.update(other_course_id, exposition.id, 4.0, entries(ids[:2]))
        with pytest.raises(GroupExpositionNotFoundError):
            service.update(course_id, 999, 4.0, entries(ids[:2]))
        with pytest.raises(GroupExpositionNotFoundError):
            service.get(other_course_id, exposition.id)


class TestPropuestaEliminada:
    def test_scores_survive_when_the_group_plan_is_deleted(self):
        uow_factory, service, course_id, _, ids, _ = setup()
        with uow_factory() as uow:
            plan = uow.group_plans.create(
                course_id, "Proyecto final", 2, [StudentGroup("Grupo 1", ids[:2])]
            )
            uow.commit()
        exposition = service.record(
            course_id, "Grupo 1", 4.0, entries(ids[:2]), group_plan_id=plan.id
        )

        GroupPlanningService(uow_factory).delete(course_id, plan.id)

        kept = service.get(course_id, exposition.id)
        assert kept.group_plan_id is None
        assert kept.plan_name == "Proyecto final"
        assert kept.group_score == 4.0
