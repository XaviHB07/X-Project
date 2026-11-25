"""Pruebas de API de lo agregado el 17-nov-2026:

* Pendientes de sprints anteriores: estructura institucional (HU-A5, A6,
  A7), selección encadenada (HU-C2), ciclo con especialidad (HU-C3), cursos
  con código y estado (HU-C4), docente con apellidos y nombres (HU-A8),
  usuario del docente = DNI (HU-A4) y migración de los datos del MVP 1.
* Sprint 7: unirse a una actividad rápida con código (HU-Q5) y registro de
  respuestas asociadas a la cuenta del estudiante (HU-Q3).

Usan la misma base SQLite temporal y las mismas cuentas que `test_api.py`.
"""

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select

from src.repositories.sqlalchemy.models import (
    AcademicCycleORM,
    CourseORM,
    QuickActivityAnswerORM,
    QuickActivityQuestionORM,
    QuickActivityORM,
    QuickActivityResponseORM,
    SchemaMigrationORM,
    StudentORM,
)
from src.services.bootstrap import MVP1_CYCLE, MVP1_MIGRATION, MVP1_SPECIALTY
from src.services.bootstrap import _migrate_mvp1_institutional_schema
from src.services.quick_activity_email_service import ResultsEmailSettings
from tests.test_api import (  # noqa: F401  (fixture reutilizado)
    _create_second_teacher,
    _login_as_admin,
    _login_as_teacher,
    client,
)


# --------------------------------------------------------------------------
# Auxiliares
# --------------------------------------------------------------------------


def _institution(client: TestClient, university="UNI", faculty="FIIS", specialty="Sistemas"):
    """Crea universidad → facultad → especialidad como Administrador."""
    _login_as_admin(client)
    uni = client.post("/institutions/universities", json={"name": university})
    assert uni.status_code == 201, uni.text
    fac = client.post(
        f"/institutions/universities/{uni.json()['id']}/faculties", json={"name": faculty}
    )
    assert fac.status_code == 201, fac.text
    spe = client.post(
        f"/institutions/faculties/{fac.json()['id']}/specialties", json={"name": specialty}
    )
    assert spe.status_code == 201, spe.text
    return uni.json()["id"], fac.json()["id"], spe.json()["id"]


def _teacher_course(
    client: TestClient,
    code="SI807U",
    name="Inteligencia de Negocios",
    university="UNI",
    cycle_name="2026-II",
):
    """El docente registra su ciclo (con especialidad) y su curso."""
    _, _, specialty_id = _institution(client, university=university)
    _login_as_teacher(client)
    cycle = client.post(
        "/cycles", json={"name": cycle_name, "starts_on": "2026-08-24", "specialty_id": specialty_id}
    )
    assert cycle.status_code == 201, cycle.text
    course = client.post(
        "/courses", json={"name": name, "code": code, "cycle_id": cycle.json()["id"]}
    )
    assert course.status_code == 201, course.text
    return cycle.json(), course.json()


def _enroll_and_login_student(client: TestClient, course_id: int, code: str, name: str):
    """Matricula (como docente del curso) y entra con la cuenta del alumno."""
    _login_as_teacher(client)
    enrolled = client.post(
        f"/courses/{course_id}/students", json={"external_ref": code, "display_name": name}
    )
    assert enrolled.status_code == 201, enrolled.text
    _login_student(client, code)
    return enrolled.json()["id"]


def _login_student(client: TestClient, code: str) -> None:
    client.cookies.clear()
    first = client.post("/auth/login", json={"username": code, "password": code})
    if first.status_code == 200 and first.json()["must_change_password"]:
        assert client.post(
            "/auth/change-password", json={"new_password": f"{code}-clave-segura-123"}
        ).status_code == 200
        return
    if first.status_code != 200:
        again = client.post(
            "/auth/login", json={"username": code, "password": f"{code}-clave-segura-123"}
        )
        assert again.status_code == 200, again.text


QUESTIONS = [
    {"prompt": "¿Qué significa ETL?"},
    {
        "prompt": "¿Qué esquema usa una tabla de hechos al centro?",
        "options": ["Copo de nieve", "Estrella", "Relacional"],
        "correct_option": 1,
    },
]


def _published_activity(client: TestClient, course_id: int, **extra):
    _login_as_teacher(client)
    created = client.post(
        f"/courses/{course_id}/quick-activities",
        json={"title": "Repaso de BI", "questions": QUESTIONS, **extra},
    )
    assert created.status_code == 201, created.text
    activity = created.json()
    assert activity["status"] == "draft"
    assert activity["join_code"] is None
    published = client.post(
        f"/courses/{course_id}/quick-activities/{activity['id']}/publish",
        json={"duration_minutes": 15},
    )
    assert published.status_code == 200, published.text
    return published.json()


def _answers(activity_or_join):
    open_q, choice_q = activity_or_join["questions"]
    return [
        {"question_id": open_q["id"], "answer_text": "Extraer, transformar y cargar"},
        {"question_id": choice_q["id"], "selected_option": 1},
    ]


# --------------------------------------------------------------------------
# HU-A5 / HU-A6 / HU-A7
# --------------------------------------------------------------------------


class TestEstructuraInstitucional:
    def test_admin_builds_tree_and_names_are_unique_per_level(self, client: TestClient):
        uni_id, fac_id, spe_id = _institution(client)
        tree = client.get("/institutions").json()
        assert [u["name"] for u in tree] == ["UNI"]
        assert tree[0]["faculties"][0]["name"] == "FIIS"
        assert tree[0]["faculties"][0]["specialties"][0]["name"] == "Sistemas"

        assert client.post("/institutions/universities", json={"name": " uni "}).status_code == 409
        assert client.post(
            f"/institutions/universities/{uni_id}/faculties", json={"name": "fiis"}
        ).status_code == 409
        # El mismo nombre de facultad sí puede repetirse en otra universidad.
        other = client.post("/institutions/universities", json={"name": "PUCP"}).json()
        assert client.post(
            f"/institutions/universities/{other['id']}/faculties", json={"name": "FIIS"}
        ).status_code == 201

        renamed = client.patch(
            f"/institutions/specialties/{spe_id}", json={"name": "Ingeniería de Sistemas"}
        )
        assert renamed.status_code == 200
        assert renamed.json()["name"] == "Ingeniería de Sistemas"

    def test_delete_only_without_children_otherwise_disable(self, client: TestClient):
        uni_id, fac_id, spe_id = _institution(client)
        blocked = client.delete(f"/institutions/universities/{uni_id}")
        assert blocked.status_code == 409
        assert "deshabilítala" in blocked.json()["detail"]
        assert client.delete(f"/institutions/faculties/{fac_id}").status_code == 409

        assert client.delete(f"/institutions/specialties/{spe_id}").status_code == 204
        assert client.delete(f"/institutions/faculties/{fac_id}").status_code == 204
        assert client.delete(f"/institutions/universities/{uni_id}").status_code == 204
        assert client.get("/institutions").json() == []
        assert client.delete(f"/institutions/universities/{uni_id}").status_code == 404

    def test_disabled_items_are_kept_for_admin_but_hidden_from_teacher(self, client: TestClient):
        uni_id, fac_id, spe_id = _institution(client)
        disabled = client.patch(f"/institutions/universities/{uni_id}", json={"enabled": False})
        assert disabled.status_code == 200 and disabled.json()["enabled"] is False
        # El Administrador la sigue viendo (histórico)…
        admin_tree = client.get("/institutions").json()
        assert admin_tree[0]["enabled"] is False
        assert admin_tree[0]["faculties"][0]["specialties"][0]["id"] == spe_id
        assert client.get("/institutions?only_enabled=true").json() == []
        # …pero no admite hijos nuevos ni se ofrece al docente (HU-C2).
        assert client.post(
            f"/institutions/universities/{uni_id}/faculties", json={"name": "FC"}
        ).status_code == 409
        _login_as_teacher(client)
        assert client.get("/institutions").json() == []

    def test_only_admin_manages_and_students_cannot_read(self, client: TestClient):
        _login_as_teacher(client)
        assert client.post("/institutions/universities", json={"name": "X"}).status_code == 403
        assert client.get("/institutions").status_code == 200

        _, course = _teacher_course(client)
        _enroll_and_login_student(client, course["id"], "20201234A", "Ana Torres")
        assert client.get("/institutions").status_code == 403


# --------------------------------------------------------------------------
# HU-C2 / HU-C3
# --------------------------------------------------------------------------


class TestSeleccionEncadenadaYCiclo:
    def test_cycle_keeps_institutional_context(self, client: TestClient):
        cycle, _ = _teacher_course(client)
        assert cycle["specialty_id"] is not None
        assert cycle["university_name"] == "UNI"
        assert cycle["faculty_name"] == "FIIS"
        assert cycle["specialty_name"] == "Sistemas"
        listed = client.get("/cycles").json()[0]
        assert listed["specialty_name"] == "Sistemas"

    def test_only_enabled_specialties_can_be_selected(self, client: TestClient):
        uni_id, fac_id, spe_id = _institution(client)
        assert client.patch(f"/institutions/faculties/{fac_id}", json={"enabled": False}).status_code == 200
        _login_as_teacher(client)
        rejected = client.post("/cycles", json={"name": "2027-I", "specialty_id": spe_id})
        assert rejected.status_code == 409
        assert client.post("/cycles", json={"name": "2027-I", "specialty_id": 999}).status_code == 404

    def test_disabling_specialty_keeps_existing_cycles(self, client: TestClient):
        cycle, _ = _teacher_course(client)
        _login_as_admin(client)
        spe_id = cycle["specialty_id"]
        assert client.delete(f"/institutions/specialties/{spe_id}").status_code == 409
        client.patch(f"/institutions/specialties/{spe_id}", json={"enabled": False})
        _login_as_teacher(client)
        kept = client.get("/cycles").json()[0]
        assert kept["specialty_id"] == spe_id and kept["specialty_name"] == "Sistemas"
        # Editar otros campos sigue funcionando aunque la especialidad ya no se ofrezca.
        assert client.patch(f"/cycles/{cycle['id']}", json={"name": "2026-2"}).status_code == 200

    def test_teacher_can_move_cycle_to_another_specialty(self, client: TestClient):
        cycle, _ = _teacher_course(client)
        _login_as_admin(client)
        fac_id = client.get("/institutions").json()[0]["faculties"][0]["id"]
        other = client.post(
            f"/institutions/faculties/{fac_id}/specialties", json={"name": "Industrial"}
        ).json()
        _login_as_teacher(client)
        moved = client.patch(f"/cycles/{cycle['id']}", json={"specialty_id": other["id"]})
        assert moved.status_code == 200
        assert moved.json()["specialty_name"] == "Industrial"


# --------------------------------------------------------------------------
# HU-C4
# --------------------------------------------------------------------------


class TestGestionCursosDocente:
    def test_teacher_creates_course_in_own_cycle_and_it_is_assigned(self, client: TestClient):
        cycle, course = _teacher_course(client)
        assert course["code"] == "SI807U"
        assert course["enabled"] is True
        assert course["cycle_id"] == cycle["id"]
        assert [c["id"] for c in client.get("/courses").json()] == [course["id"]]
        assert client.get(f"/courses/{course['id']}").status_code == 200

    def test_code_is_unique_per_cycle(self, client: TestClient):
        cycle, course = _teacher_course(client)
        duplicate = client.post(
            "/courses", json={"name": "Otro", "code": "si 807u", "cycle_id": cycle["id"]}
        )
        assert duplicate.status_code == 409
        other_cycle = client.post("/cycles", json={"name": "2027-I"}).json()
        assert client.post(
            "/courses", json={"name": "Otro", "code": "SI807U", "cycle_id": other_cycle["id"]}
        ).status_code == 201

    def test_teacher_cannot_create_in_cycles_he_does_not_own(self, client: TestClient):
        _login_as_admin(client)
        admin_cycle = client.post("/cycles", json={"name": "Del admin"}).json()
        _login_as_teacher(client)
        assert client.post(
            "/courses", json={"name": "X", "cycle_id": admin_cycle["id"]}
        ).status_code == 403

    def test_update_disable_and_delete_rules(self, client: TestClient):
        cycle, course = _teacher_course(client)
        updated = client.patch(
            f"/courses/{course['id']}", json={"name": "BI avanzado", "code": "si808u"}
        )
        assert updated.status_code == 200
        assert updated.json()["name"] == "BI avanzado"
        assert updated.json()["code"] == "SI808U"

        client.post(
            f"/courses/{course['id']}/students",
            json={"external_ref": "20200001B", "display_name": "Luis Pérez"},
        )
        blocked = client.delete(f"/courses/{course['id']}")
        assert blocked.status_code == 409
        assert "deshabilítalo" in blocked.json()["detail"]

        disabled = client.patch(f"/courses/{course['id']}", json={"enabled": False})
        assert disabled.json()["enabled"] is False
        session = client.post(f"/courses/{course['id']}/class-sessions", json={"topic": "OLAP"})
        assert session.status_code == 409
        # Se conserva el histórico: la matrícula sigue consultable.
        assert len(client.get(f"/courses/{course['id']}/students").json()) == 1

        empty = client.post(
            "/courses", json={"name": "Vacío", "code": "TMP1", "cycle_id": cycle["id"]}
        ).json()
        assert client.delete(f"/courses/{empty['id']}").status_code == 204
        assert client.get(f"/courses/{empty['id']}").status_code in (403, 404)

    def test_other_teacher_cannot_edit_course(self, client: TestClient):
        _, course = _teacher_course(client)
        _create_second_teacher(client)
        client.cookies.clear()
        client.post(
            "/auth/login",
            json={"username": "teacher2", "password": "test-teacher2-password-123"},
        )
        assert client.patch(f"/courses/{course['id']}", json={"name": "X"}).status_code == 403
        assert client.delete(f"/courses/{course['id']}").status_code == 403


# --------------------------------------------------------------------------
# HU-A8 / HU-A4
# --------------------------------------------------------------------------


class TestDocenteDniApellidosNombres:
    def test_username_defaults_to_dni_and_initial_password_equals_user(self, client: TestClient):
        created = client.post(
            "/admin/teachers",
            json={
                "last_names": "Vilcapoma Ignacio",
                "first_names": "Edgar",
                "dni": "40123456",
                "email": "evilcapoma@example.com",
            },
        )
        assert created.status_code == 201, created.text
        teacher = created.json()
        assert teacher["username"] == "40123456"
        assert teacher["last_names"] == "Vilcapoma Ignacio"
        assert teacher["first_names"] == "Edgar"
        assert teacher["full_name"] == "Edgar Vilcapoma Ignacio"
        assert teacher["course_ids"] == []
        assert teacher["temporary_password"] == "40123456"

        client.cookies.clear()
        login = client.post("/auth/login", json={"username": "40123456", "password": "40123456"})
        assert login.status_code == 200
        assert login.json()["must_change_password"] is True
        assert client.get("/courses").status_code == 403

    def test_names_are_required_together(self, client: TestClient):
        response = client.post(
            "/admin/teachers",
            json={"last_names": "Solo Apellidos", "dni": "40999999", "email": "x@example.com"},
        )
        assert response.status_code == 422

    def test_update_keeps_separate_names(self, client: TestClient):
        teacher = client.post(
            "/admin/teachers",
            json={"last_names": "Pérez", "first_names": "Ana", "dni": "41111111",
                  "email": "ana@example.com"},
        ).json()
        updated = client.put(
            f"/admin/teachers/{teacher['id']}",
            json={"last_names": "Pérez Díaz", "first_names": "Ana María", "dni": "41111111",
                  "email": "ana@example.com"},
        )
        assert updated.status_code == 200
        assert updated.json()["full_name"] == "Ana María Pérez Díaz"
        listed = {t["id"]: t for t in client.get("/admin/teachers").json()}[teacher["id"]]
        assert listed["last_names"] == "Pérez Díaz"


# --------------------------------------------------------------------------
# Tarea técnica: migración del MVP 1
# --------------------------------------------------------------------------


class TestMigracionMvp1:
    def test_legacy_courses_and_cycles_move_to_institutional_schema(self, client: TestClient):
        legacy_course = client.post("/courses", json={"name": "Curso MVP 1"}).json()
        client.post(
            f"/courses/{legacy_course['id']}/students",
            json={"external_ref": "MVP001", "display_name": "Alumno MVP"},
        )
        client.post(f"/courses/{legacy_course['id']}/class-sessions", json={"topic": "Inicio"})
        legacy_cycle = client.post("/cycles", json={"name": "2026-I"}).json()
        assert legacy_cycle["specialty_id"] is None

        session_factory = client.app.state.app_context.auth_service._session_factory
        with session_factory() as session:
            session.delete(session.get(SchemaMigrationORM, MVP1_MIGRATION))
            session.commit()
        _migrate_mvp1_institutional_schema(session_factory)
        _migrate_mvp1_institutional_schema(session_factory)  # idempotente

        with session_factory() as session:
            course = session.get(CourseORM, legacy_course["id"])
            historic = session.get(AcademicCycleORM, course.cycle_id)
            assert historic.name == MVP1_CYCLE
            assert historic.starts_on is not None
            assert historic.specialty.name == MVP1_SPECIALTY
            assert course.roster_imported_at is not None  # la lista existente cuenta como carga
            assert session.get(AcademicCycleORM, legacy_cycle["id"]).specialty_id == historic.specialty_id
            assert len(session.execute(
                select(AcademicCycleORM).where(AcademicCycleORM.name == MVP1_CYCLE)
            ).scalars().all()) == 1
            # Ni la matrícula ni las sesiones se tocan.
            assert session.execute(
                select(StudentORM).where(StudentORM.course_id == legacy_course["id"])
            ).scalar_one().external_ref == "MVP001"

        tree = client.get("/institutions").json()
        assert tree[0]["faculties"][0]["specialties"][0]["name"] == MVP1_SPECIALTY


# --------------------------------------------------------------------------
# Sprint 7 — HU-Q5 (unirse) y HU-Q3 (registrar respuestas)
# --------------------------------------------------------------------------


class TestActividadRapida:
    def test_full_flow_join_submit_and_teacher_sees_responses(self, client: TestClient):
        _, course = _teacher_course(client)
        _enroll_and_login_student(client, course["id"], "20201234A", "Ana Torres")
        _login_as_teacher(client)
        activity = _published_activity(client, course["id"])
        assert activity["availability"] == "open"
        assert len(activity["join_code"]) == 6
        assert activity["join_url"] == f"/?actividad={activity['join_code']}"

        _login_student(client, "20201234A")
        typed_code = f" {activity['join_code'][:3].lower()}-{activity['join_code'][3:].lower()} "
        joined = client.post("/student/quick-activities/join", json={"code": typed_code})
        assert joined.status_code == 200, joined.text
        body = joined.json()
        assert body["course_name"] == "Inteligencia de Negocios"
        assert body["previous_attempts"] == 0
        assert all("correct_option" not in q for q in body["questions"])
        assert joined.headers["cache-control"] == "no-store"

        submitted = client.post(
            f"/student/quick-activities/{body['id']}/responses",
            json={"code": typed_code, "answers": _answers(body)},
        )
        assert submitted.status_code == 201, submitted.text
        assert submitted.json()["attempt"] == 1
        assert submitted.json()["can_submit_again"] is False

        # Una sola vez (HU-Q5, criterio 3).
        assert client.post(
            "/student/quick-activities/join", json={"code": activity["join_code"]}
        ).status_code == 409
        assert client.post(
            f"/student/quick-activities/{body['id']}/responses",
            json={"code": activity["join_code"], "answers": _answers(body)},
        ).status_code == 409
        mine = client.get("/student/quick-activities/responses").json()
        assert [item["activity_title"] for item in mine] == ["Repaso de BI"]

        # HU-Q3: la respuesta queda asociada a la cuenta y a la matrícula.
        _login_as_teacher(client)
        result = client.get(
            f"/courses/{course['id']}/quick-activities/{activity['id']}/responses"
        ).json()
        assert result["enrolled_count"] == 1 and result["respondent_count"] == 1
        response = result["responses"][0]
        assert response["student_code"] == "20201234A"
        assert response["student_name"] == "Ana Torres"
        answers = {a["question_id"]: a for a in response["answers"]}
        open_q, choice_q = activity["questions"]
        assert answers[open_q["id"]]["answer_text"] == "Extraer, transformar y cargar"
        assert answers[open_q["id"]]["is_correct"] is None
        assert answers[choice_q["id"]]["is_correct"] is True
        assert result["activity"]["response_count"] == 1

    def test_code_must_be_valid_and_current(self, client: TestClient):
        _, course = _teacher_course(client)
        _enroll_and_login_student(client, course["id"], "20201234A", "Ana Torres")
        assert client.post(
            "/student/quick-activities/join", json={"code": "ZZZZZZ"}
        ).status_code == 404

        activity = _published_activity(client, course["id"])
        code = activity["join_code"]
        service = client.app.state.app_context.quick_activity_service
        original_clock = service._clock
        service._clock = lambda: datetime.now(timezone.utc) + timedelta(minutes=16)
        try:
            _login_student(client, "20201234A")
            expired = client.post("/student/quick-activities/join", json={"code": code})
            assert expired.status_code == 410
            assert "venció" in expired.json()["detail"]
        finally:
            service._clock = original_clock

        _login_as_teacher(client)
        listed = client.get(f"/courses/{course['id']}/quick-activities").json()
        assert listed[0]["availability"] == "open"
        closed = client.post(f"/courses/{course['id']}/quick-activities/{activity['id']}/close")
        assert closed.json()["availability"] == "closed"
        assert client.post(
            f"/courses/{course['id']}/quick-activities/{activity['id']}/publish", json={}
        ).status_code == 409
        _login_student(client, "20201234A")
        assert client.post(
            "/student/quick-activities/join", json={"code": code}
        ).status_code == 410

    def test_student_must_belong_to_the_course(self, client: TestClient):
        cycle, course = _teacher_course(client)
        other = client.post(
            "/courses", json={"name": "Otro curso", "code": "OT1", "cycle_id": cycle["id"]}
        ).json()
        _enroll_and_login_student(client, other["id"], "20209999Z", "Ajeno")
        activity = _published_activity(client, course["id"])
        _login_student(client, "20209999Z")
        rejected = client.post(
            "/student/quick-activities/join", json={"code": activity["join_code"]}
        )
        assert rejected.status_code == 403

        # Un estudiante retirado del curso tampoco puede entrar.
        student_id = _enroll_and_login_student(client, course["id"], "20201111C", "Retirado")
        _login_as_teacher(client)
        assert client.patch(f"/students/{student_id}", json={"active": False}).status_code == 200
        _login_student(client, "20201111C")
        assert client.post(
            "/student/quick-activities/join", json={"code": activity["join_code"]}
        ).status_code == 403

    def test_teacher_can_allow_multiple_responses(self, client: TestClient):
        _, course = _teacher_course(client)
        _enroll_and_login_student(client, course["id"], "20201234A", "Ana Torres")
        activity = _published_activity(client, course["id"], allow_multiple_responses=True)
        _login_student(client, "20201234A")
        for expected_attempt in (1, 2):
            joined = client.post(
                "/student/quick-activities/join", json={"code": activity["join_code"]}
            ).json()
            assert joined["previous_attempts"] == expected_attempt - 1
            sent = client.post(
                f"/student/quick-activities/{activity['id']}/responses",
                json={"code": activity["join_code"], "answers": _answers(joined)},
            )
            assert sent.status_code == 201
            assert sent.json()["attempt"] == expected_attempt
        session_factory = client.app.state.app_context.auth_service._session_factory
        with session_factory() as session:
            assert session.query(QuickActivityResponseORM).count() == 2

    def test_answers_are_validated(self, client: TestClient):
        _, course = _teacher_course(client)
        _enroll_and_login_student(client, course["id"], "20201234A", "Ana Torres")
        activity = _published_activity(client, course["id"])
        _login_student(client, "20201234A")
        url = f"/student/quick-activities/{activity['id']}/responses"
        open_q, choice_q = activity["questions"]
        incomplete = client.post(url, json={
            "code": activity["join_code"],
            "answers": [{"question_id": open_q["id"], "answer_text": "algo"}],
        })
        assert incomplete.status_code == 422
        bad_option = client.post(url, json={
            "code": activity["join_code"],
            "answers": [
                {"question_id": open_q["id"], "answer_text": "algo"},
                {"question_id": choice_q["id"], "selected_option": 7},
            ],
        })
        assert bad_option.status_code == 422
        blank = client.post(url, json={
            "code": activity["join_code"],
            "answers": [
                {"question_id": open_q["id"], "answer_text": "   "},
                {"question_id": choice_q["id"], "selected_option": 0},
            ],
        })
        assert blank.status_code == 422
        # Nada quedó registrado: todavía puede responder.
        assert client.post(
            "/student/quick-activities/join", json={"code": activity["join_code"]}
        ).status_code == 200

    def test_activity_definition_is_validated(self, client: TestClient):
        _, course = _teacher_course(client)
        url = f"/courses/{course['id']}/quick-activities"
        assert client.post(url, json={"title": "X", "questions": []}).status_code == 422
        assert client.post(url, json={
            "title": "X", "questions": [{"prompt": "P", "options": ["Solo una"]}],
        }).status_code == 422
        assert client.post(url, json={
            "title": "X", "questions": [{"prompt": "P", "options": ["A", "B"], "correct_option": 3}],
        }).status_code == 422

    def test_only_course_teacher_manages_and_only_students_join(self, client: TestClient):
        _, course = _teacher_course(client)
        activity = _published_activity(client, course["id"])
        assert client.post(
            "/student/quick-activities/join", json={"code": activity["join_code"]}
        ).status_code == 403
        _create_second_teacher(client)
        client.cookies.clear()
        client.post(
            "/auth/login",
            json={"username": "teacher2", "password": "test-teacher2-password-123"},
        )
        assert client.get(f"/courses/{course['id']}/quick-activities").status_code == 403
        assert client.get(
            f"/courses/{course['id']}/quick-activities/{activity['id']}/responses"
        ).status_code == 403

    def test_disabled_course_does_not_accept_new_activities(self, client: TestClient):
        _, course = _teacher_course(client)
        client.patch(f"/courses/{course['id']}", json={"enabled": False})
        created = client.post(
            f"/courses/{course['id']}/quick-activities",
            json={"title": "X", "questions": QUESTIONS},
        )
        assert created.status_code == 409


class TestFrontendSprint7:
    def test_new_screens_and_scripts_are_served(self, client: TestClient):
        page = client.get("/").text
        institutions = client.get("/assets/institutions.js")
        quick = client.get("/assets/quick-activities.js")
        live = client.get("/assets/live-quiz.js")
        styles = client.get("/assets/styles.css")
        assert institutions.status_code == 200 and quick.status_code == 200
        assert live.status_code == 200 and styles.status_code == 200
        assert '<script src="/assets/institutions.js" defer></script>' in page
        assert '<script src="/assets/quick-activities.js" defer></script>' in page
        # HU-A5 a A7 y HU-C2
        assert 'id="institutions-page"' in page
        assert 'id="cycle-university"' in page and 'id="cycle-specialty"' in page
        assert "/institutions/universities" in institutions.text
        # HU-C4 y HU-A8
        assert 'id="course-code"' in page
        assert 'id="teacher-last-names"' in page and 'id="teacher-first-names"' in page
        # Sprint 7: pestaña del docente y vista del estudiante
        assert 'id="quick-tab"' in page and 'Cacería en vivo' in page
        assert 'id="quick-view"' in page and 'Nuevo quiz en vivo' in page
        assert 'id="student-activity-view"' in page and 'id="student-join-form"' in page
        assert 'name="quick-mode"' not in page
        assert "Cada estudiante responde a su ritmo" not in page
        assert "/student/quick-activities/join" in quick.text
        assert 'params.get("actividad")' in quick.text
        for asset in ("live-quiz.js", "qr-scanner.js", "vendor/jsQR.js"):
            assert client.get(f"/assets/{asset}").status_code == 200
        assert 'id="live-stage"' in page and 'id="student-scan-button"' in page
        assert "renderWolfFinale" in live.text
        assert "wolfRunnerMarkup" in live.text
        assert "wolf-leg-swing" in live.text
        assert "wolf-violet-edge" in live.text
        assert "wolf-face-glow" in live.text
        assert '<img class="wolf-runner"' not in live.text
        assert "wolf-paw-card.jpg" not in live.text
        assert "@keyframes wolf-leg-run" in styles.text
        assert "@keyframes wolf-trail-pulse" in styles.text
        assert "@keyframes wolf-dash" in styles.text
        assert "data.question.prompt" not in live.text
        assert "data.question.options" not in live.text
        assert 'const LIVE_COLORS = ["live-red", "live-blue", "live-yellow", "live-green"]' in live.text
        assert client.get("/assets/assets/wolf-paw-card.jpg").status_code == 200
        assert 'mode: "live"' in quick.text
        assert 'id="quick-question-seconds" type="number" min="5" max="120" value="30"' in page
        assert 'Number($("#quick-question-seconds").value) || 30' in quick.text


# --------------------------------------------------------------------------
# HU-Q2 (QR) y quiz en vivo
# --------------------------------------------------------------------------


LIVE_QUESTIONS = [
    {"prompt": "¿2 + 2?", "options": ["3", "4", "5"], "correct_option": 1},
    {"prompt": "¿Capital del Perú?", "options": ["Lima", "Cusco"], "correct_option": 0},
]


class _Clock:
    """Reloj manual para controlar los segundos de cada pregunta."""

    def __init__(self):
        self.now = datetime.now(timezone.utc)

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += timedelta(seconds=seconds)


def _live_quiz(client: TestClient, course_id: int, seconds: int = 20):
    _login_as_teacher(client)
    created = client.post(
        f"/courses/{course_id}/quick-activities",
        json={"title": "Quiz en vivo", "mode": "live", "question_seconds": seconds,
              "questions": LIVE_QUESTIONS},
    )
    assert created.status_code == 201, created.text
    assert created.json()["mode"] == "live"
    published = client.post(
        f"/courses/{course_id}/quick-activities/{created.json()['id']}/publish",
        json={"duration_minutes": 60},
    )
    assert published.status_code == 200
    assert published.json()["live_phase"] == "lobby"
    return published.json()


class TestQrYQuizEnVivo:
    def test_cumulative_ranking_uses_only_finished_live_quiz_points(self, client: TestClient):
        _, course = _teacher_course(client, code="RANK", name="Ranking")
        for code, name in (
            ("RANK001", "Ana María Zuluaga Pérez"),
            ("RANK002", "Beatriz Álvarez Torres"),
            ("RANK003", "Carlos Ibarra Ruiz"),
        ):
            _enroll_and_login_student(client, course["id"], code, name)

        service = client.app.state.app_context.quick_activity_service
        with service._session_factory() as session:
            students = session.execute(
                select(StudentORM)
                .where(StudentORM.course_id == course["id"])
                .order_by(StudentORM.id)
            ).scalars().all()

            def create_completed_activity(mode: str, title: str) -> tuple:
                activity = QuickActivityORM(
                    course_id=course["id"],
                    title=title,
                    status="closed",
                    mode=mode,
                    live_phase="finished" if mode == "live" else None,
                )
                session.add(activity)
                session.flush()
                question = QuickActivityQuestionORM(
                    activity_id=activity.id,
                    position=1,
                    prompt="P",
                    options=["A", "B"],
                    correct_option=0,
                )
                session.add(question)
                session.flush()
                return activity, question

            def add_result(activity, question, student, attempt: int, points: int) -> None:
                response = QuickActivityResponseORM(
                    activity_id=activity.id,
                    student_id=student.id,
                    user_id=student.user_id,
                    attempt=attempt,
                )
                session.add(response)
                session.flush()
                session.add(QuickActivityAnswerORM(
                    response_id=response.id,
                    question_id=question.id,
                    selected_option=0,
                    is_correct=True,
                    points=points,
                    response_ms=100,
                ))

            first, first_question = create_completed_activity("live", "Primera cacería")
            second, second_question = create_completed_activity("live", "Segunda cacería")
            unrelated, unrelated_question = create_completed_activity("self_paced", "Test")
            unfinished, unfinished_question = create_completed_activity("live", "En curso")
            unfinished.status = "published"
            unfinished.live_phase = "question"
            add_result(first, first_question, students[0], 1, 999)
            add_result(first, first_question, students[0], 2, 100)
            add_result(first, first_question, students[1], 1, 100)
            add_result(second, second_question, students[0], 1, 100)
            add_result(second, second_question, students[1], 1, 100)
            add_result(unrelated, unrelated_question, students[0], 1, 9000)
            add_result(unfinished, unfinished_question, students[0], 1, 8000)
            session.commit()

        response = client.get(f"/courses/{course['id']}/live-ranking")
        assert response.status_code == 200, response.text
        ranking = response.json()
        assert ranking["quiz_count"] == 2
        assert ranking["student_count"] == 3
        assert [
            (row["rank"], row["student_name"], row["points"])
            for row in ranking["students"]
        ] == [
            (1, "Beatriz Álvarez Torres", 200),
            (2, "Ana María Zuluaga Pérez", 200),
            (3, "Carlos Ibarra Ruiz", 0),
        ]
        _login_as_teacher(client)
        assert client.get(f"/courses/{course['id']}/live-ranking").status_code == 200

        other_course = _teacher_course(
            client,
            code="OTHER",
            name="Otro curso",
            university="OTHER-UNI",
            cycle_name="2026-III",
        )[1]
        _login_student(client, "RANK001")
        student_ranking = client.get(f"/courses/{course['id']}/live-ranking")
        assert student_ranking.status_code == 200
        assert client.get(
            f"/courses/{other_course['id']}/live-ranking"
        ).status_code == 404

    def test_live_quiz_defaults_to_30_seconds(self, client: TestClient):
        _, course = _teacher_course(client)
        created = client.post(
            f"/courses/{course['id']}/quick-activities",
            json={
                "title": "Tiempo predeterminado",
                "mode": "live",
                "questions": LIVE_QUESTIONS,
            },
        )
        assert created.status_code == 201, created.text
        assert created.json()["question_seconds"] == 30

    def test_teacher_gets_qr_with_public_join_link(self, client: TestClient):
        _, course = _teacher_course(client)
        activity = _published_activity(client, course["id"])
        qr = client.get(
            f"/courses/{course['id']}/quick-activities/{activity['id']}/qr.svg",
            headers={"X-Forwarded-Proto": "https", "Host": "catedra.onrender.com"},
        )
        assert qr.status_code == 200
        assert qr.headers["content-type"].startswith("image/svg+xml")
        assert "<svg" in qr.text
        assert qr.headers["x-join-url"] == (
            f"https://catedra.onrender.com/?actividad={activity['join_code']}"
        )
        draft = client.post(
            f"/courses/{course['id']}/quick-activities",
            json={"title": "Borrador", "questions": QUESTIONS},
        ).json()
        assert client.get(
            f"/courses/{course['id']}/quick-activities/{draft['id']}/qr.svg"
        ).status_code == 409

    def test_live_quiz_requires_scored_multiple_choice(self, client: TestClient):
        _, course = _teacher_course(client)
        response = client.post(
            f"/courses/{course['id']}/quick-activities",
            json={"title": "X", "mode": "live", "questions": QUESTIONS},
        )
        assert response.status_code == 422
        assert "opción múltiple" in response.json()["detail"]

        too_many_colors = client.post(
            f"/courses/{course['id']}/quick-activities",
            json={
                "title": "Demasiados colores",
                "mode": "live",
                "question_seconds": 20,
                "questions": [{
                    "prompt": "Elige",
                    "options": ["A", "B", "C", "D", "E"],
                    "correct_option": 0,
                }],
            },
        )
        assert too_many_colors.status_code == 422
        assert "cuatro alternativas" in too_many_colors.json()["detail"]

    def test_finale_is_synchronized_and_emails_entire_active_roster(self, client: TestClient):
        clock = _Clock()
        client.app.state.app_context.quick_activity_service._clock = clock
        _, course = _teacher_course(client, code="TESTKH", name="Test Kahoot")
        student_codes = ("TEST001", "TEST002", "TEST003", "TEST004")
        for index, code in enumerate(student_codes):
            _enroll_and_login_student(client, course["id"], code, f"Estudiante {index + 1}")

        with client.app.state.app_context.quick_activity_service._session_factory() as session:
            students = session.execute(
                select(StudentORM)
                .where(StudentORM.course_id == course["id"])
                .order_by(StudentORM.id)
            ).scalars().all()
            for index, student in enumerate(students, start=1):
                student.email = f"test{index}@example.test"
            session.commit()

        email_service = client.app.state.app_context.quick_activity_email_service
        email_service.settings = ResultsEmailSettings(
            enabled=True,
            host="smtp.example.test",
            port=587,
            username="test-account",
            password="test-password",
        )
        sent_messages = []

        class FakeSmtp:
            def __init__(self, host, port, timeout):
                assert (host, port, timeout) == ("smtp.example.test", 587, 20)

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def starttls(self, context):
                assert context is not None

            def login(self, username, password):
                assert (username, password) == ("test-account", "test-password")

            def send_message(self, message):
                sent_messages.append(message)
                return {}

        email_service._smtp_factory = FakeSmtp
        quiz = _live_quiz(client, course["id"])
        base = f"/courses/{course['id']}/quick-activities/{quiz['id']}"
        for code in student_codes[:3]:
            _login_student(client, code)
            joined = client.post(
                "/student/quick-activities/join", json={"code": quiz["join_code"]}
            )
            assert joined.status_code == 200
            assert joined.json()["questions"] == []

        _login_as_teacher(client)
        question = client.post(f"{base}/live/advance").json()
        assert question["phase"] == "question"
        _login_student(client, student_codes[0])
        student_state = client.get(f"/student/quick-activities/{quiz['id']}/live").json()
        assert student_state["option_count"] == 3
        assert set(student_state["question"]) == {"id", "position"}
        assert "prompt" not in student_state["question"]
        assert "options" not in student_state["question"]
        client.post(
            f"/student/quick-activities/{quiz['id']}/live/answers",
            json={"question_id": question["question"]["id"], "selected_option": 1},
        )
        for code in student_codes[1:3]:
            _login_student(client, code)
            client.post(
                f"/student/quick-activities/{quiz['id']}/live/answers",
                json={"question_id": question["question"]["id"], "selected_option": 0},
            )

        _login_as_teacher(client)
        client.post(f"{base}/live/advance")
        question_two = client.post(f"{base}/live/advance").json()
        for code, answer in zip(student_codes[:3], (0, 1, 0)):
            _login_student(client, code)
            client.post(
                f"/student/quick-activities/{quiz['id']}/live/answers",
                json={"question_id": question_two["question"]["id"], "selected_option": answer},
            )

        _login_as_teacher(client)
        client.post(f"{base}/live/advance")
        final = client.post(f"{base}/live/advance")
        assert final.status_code == 200, final.text
        result = final.json()
        assert result["phase"] == "finished"
        assert result["result_email_status"] == "sent"
        assert result["result_emails_sent"] == 4
        assert len(sent_messages) == 4
        assert {
            message["To"] for message in sent_messages
        } == {
            "test1@example.test", "test2@example.test",
            "test3@example.test", "test4@example.test",
        }
        first_html = sent_messages[0].get_body(preferencelist=("html",)).get_content()
        assert "Cacería en vivo" in sent_messages[0]["Subject"]
        assert "image/jpeg" in str(sent_messages[0])
        assert "posición" in first_html.casefold()
        assert sent_messages[0]["From"] == "Lobo Feroz <loboferez.notificaciones@gmail.com>"
        no_response = next(
            message for message in sent_messages if message["To"] == "test4@example.test"
        )
        no_response_text = no_response.get_body(preferencelist=("plain",)).get_content()
        no_response_html = no_response.get_body(preferencelist=("html",)).get_content()
        assert "0 puntos" in no_response_text
        assert "próxima cacería" in no_response_text.casefold()
        assert "Sin respuesta" in no_response_html

        _login_as_teacher(client)
        replay = client.get(f"{base}/live")
        assert replay.status_code == 200
        assert replay.json()["phase"] == "finished"
        assert len(sent_messages) == 4
        duplicate = email_service.notify_finished(course["id"], quiz["id"])
        assert duplicate["result_email_status"] == "already_sent"
        assert len(sent_messages) == 4
        for code in student_codes[:3]:
            _login_student(client, code)
            student_final = client.get(
                f"/student/quick-activities/{quiz['id']}/live"
            ).json()
            assert student_final["phase"] == "finished"
            assert student_final["finished_at"] == result["finished_at"]
            assert student_final["question"] is None
        with client.app.state.app_context.quick_activity_service._session_factory() as session:
            saved_quiz = session.get(QuickActivityORM, quiz["id"])
            assert saved_quiz.results_email_claimed_at is not None

    def test_full_live_game_with_speed_points_and_ranking(self, client: TestClient):
        clock = _Clock()
        service = client.app.state.app_context.quick_activity_service
        service._clock = clock
        _, course = _teacher_course(client)
        _enroll_and_login_student(client, course["id"], "20200001A", "Ana Rápida")
        _enroll_and_login_student(client, course["id"], "20200002B", "Beto Lento")
        quiz = _live_quiz(client, course["id"], seconds=20)
        base = f"/courses/{course['id']}/quick-activities/{quiz['id']}"

        # Sala de espera: los dos se unen con el código (Ana dos veces: reconexión).
        for code in ("20200001A", "20200002B", "20200001A"):
            _login_student(client, code)
            joined = client.post("/student/quick-activities/join", json={"code": quiz["join_code"]})
            assert joined.status_code == 200, joined.text
            assert joined.json()["mode"] == "live"
            state = client.get(f"/student/quick-activities/{quiz['id']}/live").json()
            assert state["phase"] == "lobby"
        # El test a su ritmo no aplica a un quiz en vivo.
        assert client.post(
            f"/student/quick-activities/{quiz['id']}/responses",
            json={"code": quiz["join_code"], "answers": [{"question_id": 1, "selected_option": 0}]},
        ).status_code == 409

        _login_as_teacher(client)
        lobby = client.get(f"{base}/live").json()
        assert lobby["phase"] == "lobby" and lobby["participant_count"] == 2
        q1 = client.post(f"{base}/live/advance").json()
        assert q1["phase"] == "question" and q1["position"] == 1
        assert q1["question"]["correct_option"] is None  # no se revela durante la pregunta
        question_id = q1["question"]["id"]

        # Ana acierta a los 2 s; Beto acierta a los 10 s.
        clock.advance(2)
        _login_student(client, "20200001A")
        student_view = client.get(f"/student/quick-activities/{quiz['id']}/live").json()
        assert student_view["phase"] == "question" and student_view["correct_option"] is None
        assert 17000 <= student_view["remaining_ms"] <= 18000
        assert client.post(
            f"/student/quick-activities/{quiz['id']}/live/answers",
            json={"question_id": question_id, "selected_option": 1},
        ).status_code == 201
        assert client.post(
            f"/student/quick-activities/{quiz['id']}/live/answers",
            json={"question_id": question_id, "selected_option": 1},
        ).status_code == 409  # una respuesta por pregunta
        clock.advance(8)
        _login_student(client, "20200002B")
        assert client.post(
            f"/student/quick-activities/{quiz['id']}/live/answers",
            json={"question_id": question_id, "selected_option": 1},
        ).status_code == 201

        # Se acaba el tiempo: pasa solo a resultados y ya no acepta respuestas.
        clock.advance(11)
        late = client.post(
            f"/student/quick-activities/{quiz['id']}/live/answers",
            json={"question_id": question_id, "selected_option": 0},
        )
        assert late.status_code == 409
        mine = client.get(f"/student/quick-activities/{quiz['id']}/live").json()
        assert mine["phase"] == "reveal" and mine["correct_option"] == 1
        assert mine["is_correct"] is True and mine["points"] == 750 and mine["rank"] == 2

        _login_as_teacher(client)
        reveal = client.get(f"{base}/live").json()
        assert reveal["phase"] == "reveal"
        assert reveal["distribution"] == [0, 2, 0]
        assert [row["student_name"] for row in reveal["leaderboard"]] == ["Ana Rápida", "Beto Lento"]
        assert reveal["leaderboard"][0]["points"] == 950

        # Pregunta 2: el docente la cierra antes de tiempo; solo Beto respondió (mal).
        q2 = client.post(f"{base}/live/advance").json()
        assert q2["position"] == 2 and q2["phase"] == "question"
        _login_student(client, "20200002B")
        client.post(
            f"/student/quick-activities/{quiz['id']}/live/answers",
            json={"question_id": q2["question"]["id"], "selected_option": 1},
        )
        _login_as_teacher(client)
        closed_early = client.post(f"{base}/live/advance").json()
        assert closed_early["phase"] == "reveal" and closed_early["distribution"] == [0, 1]

        final = client.post(f"{base}/live/advance").json()
        assert final["phase"] == "finished"
        assert final["activity"]["status"] == "closed"
        assert client.post(f"{base}/live/advance").status_code == 409

        _login_student(client, "20200001A")
        podium = client.get(f"/student/quick-activities/{quiz['id']}/live").json()
        assert podium["phase"] == "finished" and podium["rank"] == 1
        assert [row["student_code"] for row in podium["podium"]] == ["20200001A", "20200002B"]

        # HU-Q3: las respuestas quedan registradas con su puntaje.
        _login_as_teacher(client)
        recorded = client.get(f"{base}/responses").json()
        assert recorded["respondent_count"] == 2
        points = sorted(a["points"] for r in recorded["responses"] for a in r["answers"])
        assert points == [0, 750, 950]

    def test_live_endpoints_check_membership(self, client: TestClient):
        cycle, course = _teacher_course(client)
        other = client.post(
            "/courses", json={"name": "Otro", "code": "OT9", "cycle_id": cycle["id"]}
        ).json()
        _enroll_and_login_student(client, other["id"], "20209999Z", "Ajeno")
        quiz = _live_quiz(client, course["id"])
        _login_student(client, "20209999Z")
        assert client.post(
            "/student/quick-activities/join", json={"code": quiz["join_code"]}
        ).status_code == 403
        assert client.get(f"/student/quick-activities/{quiz['id']}/live").status_code == 403


# --------------------------------------------------------------------------
# HU-Q4 — Resultados de la actividad
# --------------------------------------------------------------------------


class TestResultadosActividad:
    def test_self_paced_results_summarize_group_comprehension(self, client: TestClient):
        _, course = _teacher_course(client)
        for code, name in (("20200001A", "Ana"), ("20200002B", "Beto"), ("20200003C", "Carla")):
            _enroll_and_login_student(client, course["id"], code, name)
        activity = _published_activity(client, course["id"], allow_multiple_responses=True)
        open_q, choice_q = activity["questions"]

        def send(code, option, text="respuesta"):
            _login_student(client, code)
            assert client.post(
                f"/student/quick-activities/{activity['id']}/responses",
                json={"code": activity["join_code"], "answers": [
                    {"question_id": open_q["id"], "answer_text": text},
                    {"question_id": choice_q["id"], "selected_option": option},
                ]},
            ).status_code == 201

        send("20200001A", 0, "Extraer y cargar")  # primero falla…
        send("20200001A", 1, "Extraer, transformar y cargar")  # …y su último envío acierta
        send("20200002B", 2)
        # Carla no responde.

        _login_as_teacher(client)
        results = client.get(
            f"/courses/{course['id']}/quick-activities/{activity['id']}/results"
        )
        assert results.status_code == 200, results.text
        data = results.json()
        assert data["enrolled_count"] == 3 and data["respondent_count"] == 2
        assert data["participation_rate"] == round(2 / 3, 4)
        assert data["scored_question_count"] == 1 and data["open_question_count"] == 1
        assert data["group_score"] == 0.5 and data["comprehension_level"] == "medio"
        assert data["hardest_question_position"] == 2

        open_result, choice_result = data["questions"]
        assert open_result["kind"] == "open" and open_result["correct_rate"] is None
        assert [a["answer_text"] for a in open_result["open_answers"]] == [
            "Extraer, transformar y cargar", "respuesta",
        ]
        # Cuenta el último envío de Ana (opción 1), no el primero.
        assert choice_result["distribution"] == [0, 1, 1]
        assert choice_result["correct_count"] == 1 and choice_result["correct_rate"] == 0.5

        assert [s["student_name"] for s in data["students"]] == ["Ana", "Beto"]
        assert data["students"][0]["attempt"] == 2
        assert data["students"][0]["score_rate"] == 1.0
        assert data["students"][1]["correct_count"] == 0

    def test_live_results_count_missing_answers_as_not_correct(self, client: TestClient):
        clock = _Clock()
        client.app.state.app_context.quick_activity_service._clock = clock
        _, course = _teacher_course(client)
        _enroll_and_login_student(client, course["id"], "20200001A", "Ana")
        _enroll_and_login_student(client, course["id"], "20200002B", "Beto")
        quiz = _live_quiz(client, course["id"])
        base = f"/courses/{course['id']}/quick-activities/{quiz['id']}"
        for code in ("20200001A", "20200002B"):
            _login_student(client, code)
            client.post("/student/quick-activities/join", json={"code": quiz["join_code"]})
        _login_as_teacher(client)
        q1 = client.post(f"{base}/live/advance").json()
        _login_student(client, "20200001A")
        client.post(
            f"/student/quick-activities/{quiz['id']}/live/answers",
            json={"question_id": q1["question"]["id"], "selected_option": 1},
        )
        # Beto no responde la pregunta 1; nadie responde la 2.
        _login_as_teacher(client)
        for _ in range(3):
            client.post(f"{base}/live/advance")

        data = client.get(f"{base}/results").json()
        assert data["respondent_count"] == 2
        first, second = data["questions"]
        assert first["correct_count"] == 1 and first["correct_rate"] == 0.5
        assert second["answered_count"] == 0 and second["correct_rate"] == 0.0
        assert data["group_score"] == 0.25 and data["comprehension_level"] == "bajo"
        assert data["students"][0]["student_name"] == "Ana"
        assert data["students"][0]["points"] == 1000

    def test_results_without_responses_and_access(self, client: TestClient):
        _, course = _teacher_course(client)
        activity = _published_activity(client, course["id"])
        empty = client.get(
            f"/courses/{course['id']}/quick-activities/{activity['id']}/results"
        ).json()
        assert empty["respondent_count"] == 0
        assert empty["group_score"] is None and empty["comprehension_level"] is None
        _create_second_teacher(client)
        client.cookies.clear()
        client.post(
            "/auth/login",
            json={"username": "teacher2", "password": "test-teacher2-password-123"},
        )
        assert client.get(
            f"/courses/{course['id']}/quick-activities/{activity['id']}/results"
        ).status_code == 403
