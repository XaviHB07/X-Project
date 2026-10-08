"""Tests de participaciones (HU-P4) — el núcleo que cierra MVP 1.

Qué se protege aquí, y por qué estos casos y no otros:

- **Nada se registra con datos cruzados.** Un estudiante del curso A en la
  sesión del curso B no es un detalle: no rompe nada visible, pero contamina el
  historial de los dos cursos y las métricas de equidad salen raras. Es el
  fallo más difícil de detectar después.

- **La asistencia se congela.** Si dependiera del estado vivo, corregir la
  asistencia de ayer cambiaría las participaciones de ayer, y el docente
  vería sus datos moverse sin haber hecho nada.

- **Anular no es borrar.** Un historial del que se pueden quitar cosas a
  gusto no es auditable.

- **Varias participaciones por estudiante en la misma sesión.** El backlog de
  HU-P1 pide explícitamente "dar menor probabilidad a quienes ya participaron",
  lo que implica que repetir es legítimo. Un UNIQUE Prevent would be wrong.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.repositories.in_memory.repository_impl import InMemoryDatabase
from src.repositories.in_memory.unit_of_work import InMemoryUnitOfWork
from src.repositories.interfaces import ParticipationError
from src.services.errors import (
    ParticipationNotFoundError,
    SessionNotFoundError,
    StudentNotFoundError,
)
from src.services.participation_service import ParticipationService


@pytest.fixture
def ctx():
    """Un curso, 3 estudiantes, una sesión con todos presentes."""
    db = InMemoryDatabase()
    factory = lambda: InMemoryUnitOfWork(db)  # noqa: E731

    with factory() as uow:
        curso = uow.courses.create("Cálculo II")
        a = uow.students.get_or_create(curso.id, "A1", "Ana Torres", 1.0, 1.0)
        b = uow.students.get_or_create(curso.id, "A2", "Bruno Diaz", 1.0, 1.0)
        c = uow.students.get_or_create(curso.id, "A3", "Carla Ruiz", 1.0, 1.0)
        sesion = uow.class_sessions.create(curso.id, topic="Liderazgo")
        uow.attendance.set_many(sesion.id, {a.id: True, b.id: True, c.id: True})
        uow.commit()

    return {
        "db": db,
        "factory": factory,
        "service": ParticipationService(factory),
        "curso": curso,
        "sesion": sesion,
        "a": a,
        "b": b,
        "c": c,
    }


class TestRegistro:
    def test_registra_y_devuelve_con_nombre(self, ctx):
        r = ctx["service"].register(
            class_session_id=ctx["sesion"].id,
            student_id=ctx["a"].id,
            question="¿Qué es liderazgo?",
        )
        assert r.participation.id > 0
        assert r.student.display_name == "Ana Torres"
        assert r.participation.present is True

    def test_pregunta_vacia_se_rechaza(self, ctx):
        with pytest.raises(ParticipationError, match="vacia"):
            ctx["service"].register(ctx["sesion"].id, ctx["a"].id, "   ")

    def test_respuesta_opcional(self, ctx):
        r = ctx["service"].register(ctx["sesion"].id, ctx["a"].id, "¿Y ahora?", None)
        assert r.participation.answer is None

    def test_respuesta_se_limpia(self, ctx):
        r = ctx["service"].register(ctx["sesion"].id, ctx["a"].id, "P?", "  hola  ")
        assert r.participation.answer == "hola"

    def test_rechaza_pregunta_larga(self, ctx):
        with pytest.raises(ParticipationError, match="excede"):
            ctx["service"].register(ctx["sesion"].id, ctx["a"].id, "x" * 2001)

    def test_sesion_inexistente(self, ctx):
        with pytest.raises(SessionNotFoundError):
            ctx["service"].register(99999, ctx["a"].id, "¿?")

    def test_estudiante_inexistente(self, ctx):
        with pytest.raises(StudentNotFoundError):
            ctx["service"].register(ctx["sesion"].id, 99999, "¿?")


class test_estudiante_de_otro_curso:
    """El caso que más dano hace y menos se ve."""

    def test_lo_rechaza(self, ctx):
        db, factory = ctx["db"], ctx["factory"]
        with factory() as uow:
            otro = uow.courses.create("Física I")
            ajeno = uow.students.get_or_create(otro.id, "F1", "De Otro Curso", 1.0, 1.0)
            uow.commit()

        with pytest.raises(ParticipationError, match="curso"):
            ctx["service"].register(ctx["sesion"].id, ajeno.id, "¿?")


class TestAsistenciaCongelada:
    """El motivo del queja de 'mis datos se movieron solos'."""

    def test_queda_presente_si_estaba_presente(self, ctx):
        r = ctx["service"].register(ctx["sesion"].id, ctx["a"].id, "¿?")
        assert r.participation.present is True

    def test_corrector_asisistencia_no_cambia_el_historico(self, ctx):
        """El caso exacto: registrar, luego marcar ausente, y el registro
        anterior debe seguir diciendo 'presente'.

        Si dependiera del estado vivo, corregir la asistencia reescribiria el
        pasado y el docente veria sus datos moverse sin hacer nada.
        """
        r = ctx["service"].register(ctx["sesion"].id, ctx["a"].id, "¿?")
        pid, sid = r.participation.id, r.participation.student_id

        with ctx["factory"]() as uow:
            uow.attendance.set_many(ctx["sesion"].id, {sid: False})
            uow.commit()

        con_ctx = ctx["service"].list_for_session(ctx["sesion"].id)
        assert len(con_ctx) == 1
        assert con_ctx[0].participation.present is True, (
            "corregir la asistencia reescribio una participacion ya registrada"
        )

    def test_registra_ausente_como_ausente(self, ctx):
        with ctx["factory"]() as uow:
            uow.attendance.set_many(ctx["sesion"].id, {ctx["c"].id: False})
            uow.commit()

        r = ctx["service"].register(ctx["sesion"].id, ctx["c"].id, "¿?")
        assert r.participation.present is False

    def test_se_puede_omitir_el_congelamiento(self, ctx):
        """El interruptor existe para el caso contrario: el profe pregunta a
        un ausente a proposito."""
        r = ctx["service"].register(
            ctx["sesion"].id, ctx["c"].id, "¿?", freeze_attendance=False
        )
        assert r.participation.present is True


class TestVariasPorEstudiante:
    """HU-P1 pide reducir probabilidad a quienes ya participaron: repetir es
    una necesidad real, no un error."""

    def test_dos_participaciones_del_mismo(self, ctx):
        s = ctx["service"]
        s.register(ctx["sesion"].id, ctx["a"].id, "Primera")
        s.register(ctx["sesion"].id, ctx["a"].id, "Segunda")
        assert len(s.list_for_session(ctx["sesion"].id)) == 2


class TestHistorial:
    def test_orden_cronologico(self, ctx):
        s = ctx["service"]
        s.register(ctx["sesion"].id, ctx["a"].id, "Primera")
        s.register(ctx["sesion"].id, ctx["b"].id, "Segunda")
        items = s.list_for_session(ctx["sesion"].id)
        assert [i.participation.student_id for i in items] == [
            ctx["a"].id,
            ctx["b"].id,
        ]

    def test_historial_del_estudiante_mas_reciente_primero(self, ctx):
        s = ctx["service"]
        s.register(ctx["sesion"].id, ctx["a"].id, "Vieja")
        s.register(ctx["sesion"].id, ctx["a"].id, "Nueva")
        items = s.list_for_student(ctx["a"].id)
        assert items[0].participation.question == "Nueva"

    def test_estudiante_sin_historial(self, ctx):
        assert ctx["service"].list_for_student(ctx["c"].id) == []


class TestAnulacion:
    def test_anular_no_borra(self, ctx):
        s = ctx["service"]
        r = s.register(ctx["sesion"].id, ctx["a"].id, "¿?")
        pid = r.participation.id

        s.anular(pid, motivo="se equivocaron de estudiante")

        # Sigue existiendo, y ahora se ve al pedir las anuladas.
        with ctx["factory"]() as uow:
            assert uow.participations.get(pid) is not None
        assert s.list_for_session(ctx["sesion"].id) == []
        incl = s.list_for_session(ctx["sesion"].id, include_anuladas=True)
        assert len(incl) == 1
        assert incl[0].participation.anulada is True
        assert incl[0].participation.motivo_anulacion == "se equivocaron de estudiante"

    def test_anular_inexistente(self, ctx):
        with pytest.raises(ParticipationNotFoundError):
            ctx["service"].anular(99999, "x")


class TestResumen:
    def test_cuenta(self, ctx):
        s = ctx["service"]
        s.register(ctx["sesion"].id, ctx["a"].id, "1")
        s.register(ctx["sesion"].id, ctx["a"].id, "2")
        s.register(ctx["sesion"].id, ctx["b"].id, "3")
        r = s.summary_for_session(ctx["sesion"].id)
        assert r.total == 3
        assert r.estudiantes_participando == 2
        assert r.capacidad_presentes == 3
        assert r.participaciones_por_estudiante == 1.0

    def test_sin_presentes_no_divide_por_cero(self, ctx):
        """Con 0 presentes la media no esta definida. Devolver 0.0 es mejor
        que reventar con ZeroDivisionError en mitad de la clase."""
        with ctx["factory"]() as uow:
            uow.attendance.set_many(
                ctx["sesion"].id,
                {ctx["a"].id: False, ctx["b"].id: False, ctx["c"].id: False},
            )
            uow.commit()
        r = ctx["service"].summary_for_session(ctx["sesion"].id)
        assert r.capacidad_presentes == 0
        assert r.participaciones_por_estudiante == 0.0


class TestAlineadoConElSorteo:
    """La participación puede quedar atada al sorteo del que salió."""

    def test_registra_con_decision_run(self, ctx):
        from src.services.selection_service import SelectionService
        from src.domain.events import EventBus

        db, factory = ctx["db"], ctx["factory"]
        with factory() as uow:
            run = uow.decision_runs.create(
                ctx["sesion"].id, "roulette", 1, 1, None
            )
            uow.commit()
            run_id = run.id

        r = ctx["service"].register(
            ctx["sesion"].id, ctx["a"].id, "¿?", decision_run_id=run_id
        )
        assert r.participation.decision_run_id == run_id

    def test_rechaza_sorteo_de_otra_sesion(self, ctx):
        factory = ctx["factory"]
        with factory() as uow:
            otra = uow.class_sessions.create(ctx["curso"].id)
            run = uow.decision_runs.create(otra.id, "roulette", 1, 1, None)
            uow.commit()
            otro_run = run.id

        with pytest.raises(ParticipationError, match="otra sesion"):
            ctx["service"].register(
                ctx["sesion"].id, ctx["a"].id, "¿?", decision_run_id=otro_run
            )