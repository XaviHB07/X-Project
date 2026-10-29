"""Tests de integración de la API HTTP (`src/api/main.py`), de punta a
punta contra una base de datos SQLite temporal real (no in-memory): esta
es la única suite que ejercita la implementación de persistencia de
SQLAlchemy (`src/repositories/sqlalchemy/`), incluyendo la creación de
tablas y el ciclo completo request -> transacción -> respuesta.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from src.repositories.sqlalchemy.models import RoleORM, UserORM
from src.services.auth_service import hash_password


@pytest.fixture()
def client(monkeypatch, tmp_path):
    db_path = tmp_path / "test_api.db"
    # `DATABASE_URL` tiene prioridad sobre config/default.yaml (ver
    # `services/bootstrap.load_config`): así cada test usa su propia
    # base de datos SQLite temporal y no interfiere con los demás.
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.delenv("ADMIN_USERNAME", raising=False)
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)

    from src.api.main import app

    with TestClient(app) as test_client:
        auth_service = app.state.app_context.auth_service
        with auth_service._session_factory() as session:
            administrator_role_id = session.execute(
                select(RoleORM.id).where(RoleORM.name == "administrador")
            ).scalar_one()
            teacher_role_id = session.execute(
                select(RoleORM.id).where(RoleORM.name == "docente")
            ).scalar_one()
            session.add_all([
                UserORM(
                    username="admin",
                    full_name="Admin Test",
                    password_hash=hash_password("test-admin-password-123"),
                    role_id=administrator_role_id,
                ),
                UserORM(
                    username="teacher",
                    full_name="Teacher Test",
                    password_hash=hash_password("test-teacher-password-123"),
                    role_id=teacher_role_id,
                ),
            ])
            session.commit()
        login = test_client.post(
            "/auth/login",
            json={"username": "admin", "password": "test-admin-password-123"},
        )
        assert login.status_code == 200
        yield test_client


class TestInfraestructura:
    def test_frontend_and_assets_are_served(self, client: TestClient):
        page = client.get("/")
        script = client.get("/assets/app.js")
        styles = client.get("/assets/styles.css")

        assert page.status_code == 200
        assert page.headers["cache-control"] == "no-store, no-cache, must-revalidate, max-age=0"
        assert 'id="course-title"' in page.text
        assert "Los ciclos académicos y la matrícula de estudiantes" in page.text
        assert script.status_code == 200
        assert script.headers["cache-control"] == "no-store, no-cache, must-revalidate, max-age=0"
        assert "/sessions/select" in script.text
        assert 'api("/courses")' in script.text
        assert styles.status_code == 200
        assert 'id="management-view"' in page.text
        assert "Ciclos académicos" in page.text
        assert "Matrícula de estudiantes" in page.text
        assert 'id="cycles-setup-page"' in page.text
        assert 'id="teacher-management-page"' in page.text
        assert 'id="teachers-view-button"' in page.text
        assert 'id="academic-setup-page"' in page.text
        assert 'id="course-creation-page"' in page.text
        assert 'id="course-creation-list"' in page.text
        assert 'id="course-creation-list-title">Cursos existentes</h3>' in page.text
        assert 'id="courses-view-button"' in page.text
        assert 'id="enrollment-view-button"' in page.text
        assert 'id="create-cycle-form"' in page.text
        assert 'id="create-cycle-form"' in page.text[:page.text.index('id="academic-setup-page"')]
        assert page.text.index('id="create-course-form"') > page.text.index('id="academic-setup-page"')
        assert 'elements.dailyViewButton.hidden = isAdminView' in script.text
        assert 'id="management-tab"' not in page.text
        assert 'id="groups-tab"' in page.text
        assert 'id="groups-view"' in page.text
        assert 'id="group-generation-form"' in page.text
        assert 'id="create-manual-groups-button"' in page.text
        assert 'id="active-role"' in page.text
        assert 'id="mark-session-present-button"' in page.text
        assert '<option value="docente">Docente</option>' in page.text
        assert '<option value="administrador">Administrador</option>' in page.text
        assert 'data-edit-id="${id}"' in script.text
        assert '<details class="teacher-directory-item">' in script.text
        assert "function renderCourseCreation()" in script.text
        assert 'id="password-change-form"' in page.text
        assert 'id="create-teacher-form"' in page.text
        assert 'id="create-teacher-form" class="teacher-create-form" hidden' in page.text
        assert 'id="register-teacher-button"' in page.text
        assert 'id="create-teacher-course-search"' in page.text
        assert 'id="assignment-course-search"' in page.text
        assert 'id="daily-course-picker"' in page.text
        assert 'id="daily-cycle"' in page.text
        assert 'id="daily-course"' in page.text
        assert 'id="enrollment-course"' in page.text
        assert "/auth/change-password" in script.text

    def test_api_requires_authenticated_account(self, client: TestClient):
        client.cookies.clear()
        assert client.get("/courses").status_code == 401
        assert client.get("/auth/me").status_code == 401

    def test_invalid_login_is_rejected(self, client: TestClient):
        client.cookies.clear()
        response = client.post(
            "/auth/login", json={"username": "admin", "password": "wrong-password"}
        )
        assert response.status_code == 401

    def test_logout_revokes_session_and_accepts_expired_session(self, client: TestClient):
        response = client.post("/auth/logout")
        assert response.status_code == 204
        assert client.get("/auth/me").status_code == 401

        client.cookies.clear()
        expired_session_logout = client.post("/auth/logout")
        assert expired_session_logout.status_code == 204

    def test_health(self, client: TestClient):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_administrator_can_manage_student_roster(self, client: TestClient):
        course_id = new_course(client)
        created = client.post(
            f"/courses/{course_id}/students",
            json={"external_ref": "A1", "display_name": "Ana"},
        )
        assert created.json()["account_username"] == "A1"
        assert created.json()["temporary_password"]
        assert created.headers["cache-control"] == "no-store"
        student_id = created.json()["id"]
        updated = client.patch(
            f"/students/{student_id}", json={"display_name": "Ana María"}
        )
        imported = upload(client, course_id, [["codigo", "nombre"], ["A2", "Luis"]])

        assert created.status_code == 201
        assert updated.status_code == 200
        assert imported.status_code == 200

    def test_list_methods_includes_defaults(self, client: TestClient):
        resp = client.get("/methods")
        assert resp.status_code == 200
        methods = set(resp.json()["methods"])
        assert {"roulette", "weighted_softmax", "bayesian_fairness"}.issubset(methods)


class TestCiclosAcademicos:
    def test_create_and_list_cycles_and_associate_course(self, client: TestClient):
        created = client.post("/cycles", json={"name": "  2026-II  "})
        assert created.status_code == 201
        cycle = created.json()
        assert cycle["name"] == "2026-II"
        assert client.get("/cycles").json() == [cycle]

        course = client.post(
            "/courses", json={"name": "Cálculo", "cycle_id": cycle["id"]}
        )
        assert course.status_code == 201
        assert course.json()["cycle_id"] == cycle["id"]
        assert course.json()["roster_imported"] is False

    def test_cycle_start_date_can_be_created_and_updated(self, client: TestClient):
        cycle = client.post(
            "/cycles", json={"name": "2029-I", "starts_on": "2029-03-01"}
        )
        assert cycle.status_code == 201
        assert cycle.json()["starts_on"] == "2029-03-01"
        updated = client.patch(
            f"/cycles/{cycle.json()['id']}", json={"starts_on": "2029-03-08"}
        )
        assert updated.status_code == 200
        assert updated.json()["starts_on"] == "2029-03-08"

    def test_duplicate_cycle_name_returns_conflict(self, client: TestClient):
        assert client.post("/cycles", json={"name": "2026-II"}).status_code == 201
        duplicate = client.post("/cycles", json={"name": " 2026-II "})
        assert duplicate.status_code == 409

    def test_course_rejects_unknown_cycle(self, client: TestClient):
        response = client.post(
            "/courses", json={"name": "Curso", "cycle_id": 999}
        )
        assert response.status_code == 404

    def test_admin_assigns_courses_to_teacher_and_teacher_is_scoped(self, client: TestClient):
        cycle = client.post("/cycles", json={"name": "2027-I"}).json()
        assigned_course = client.post(
            "/courses", json={"name": "Asignado", "cycle_id": cycle["id"]}
        ).json()
        unassigned_course = client.post(
            "/courses", json={"name": "No asignado", "cycle_id": cycle["id"]}
        ).json()

        teacher_list = client.get("/admin/teachers")
        assert teacher_list.status_code == 200
        teacher_id = teacher_list.json()[0]["id"]
        assigned = client.put(
            f"/admin/teachers/{teacher_id}/courses",
            json={"course_ids": [assigned_course["id"]]},
        )
        assert assigned.status_code == 200
        assert assigned.json()["course_ids"] == [assigned_course["id"]]

        client.cookies.clear()
        login = client.post(
            "/auth/login",
            json={"username": "teacher", "password": "test-teacher-password-123"},
        )
        assert login.status_code == 200
        assert [item["id"] for item in client.get("/courses").json()] == [assigned_course["id"]]
        assert client.get(f"/courses/{assigned_course['id']}").status_code == 200
        assert client.get(f"/courses/{unassigned_course['id']}").status_code == 403
        assert client.get(f"/courses/{assigned_course['id']}/group-plans").status_code == 200
        assert client.get(f"/courses/{unassigned_course['id']}/group-plans").status_code == 403
        assert client.post("/cycles", json={"name": "No autorizado"}).status_code == 403
        assert client.post("/courses", json={"name": "No autorizado"}).status_code == 403
        assert client.get("/admin/teachers").status_code == 403

    def test_admin_creates_teacher_and_reset_requires_password_change(
        self, client: TestClient
    ):
        cycle = client.post("/cycles", json={"name": "2028-I"}).json()
        course = client.post(
            "/courses", json={"name": "Matemática", "cycle_id": cycle["id"]}
        ).json()
        created = client.post(
            "/admin/teachers",
            json={
                "username": "docente-nuevo",
                "full_name": "Docente Nuevo",
                "phone_number": "555-0102",
                "email": "docente@example.com",
                "course_ids": [course["id"]],
            },
        )
        assert created.status_code == 201
        teacher = created.json()
        assert teacher["course_ids"] == [course["id"]]
        assert teacher["phone_number"] == "555-0102"
        assert teacher["email"] == "docente@example.com"
        assert created.headers["cache-control"] == "no-store"
        first_temporary_password = teacher.pop("temporary_password")
        assert len(first_temporary_password) >= 12
        assert "temporary_password" not in client.get("/admin/teachers").text

        client.cookies.clear()
        login = client.post(
            "/auth/login",
            json={
                "username": "docente-nuevo",
                "password": first_temporary_password,
            },
        )
        assert login.status_code == 200
        assert login.json()["must_change_password"] is True
        assert client.get("/courses").status_code == 403
        changed = client.post(
            "/auth/change-password",
            json={"new_password": "docente-password-final-123"},
        )
        assert changed.status_code == 200
        assert changed.json()["must_change_password"] is False
        assert [item["id"] for item in client.get("/courses").json()] == [course["id"]]

        client.cookies.clear()
        client.post(
            "/auth/login",
            json={"username": "admin", "password": "test-admin-password-123"},
        )
        reset = client.post(f"/admin/teachers/{teacher['id']}/reset-password")
        assert reset.status_code == 200
        assert reset.headers["cache-control"] == "no-store"
        second_temporary_password = reset.json()["temporary_password"]

        client.cookies.clear()
        reset_login = client.post(
            "/auth/login",
            json={
                "username": "docente-nuevo",
                "password": second_temporary_password,
            },
        )
        assert reset_login.status_code == 200
        assert reset_login.json()["must_change_password"] is True
        assert client.get("/courses").status_code == 403
        final_change = client.post(
            "/auth/change-password",
            json={"new_password": "docente-password-final-456"},
        )
        assert final_change.status_code == 200


class TestFlujoCompleto:
    def test_create_course_enroll_select_and_read_back(self, client: TestClient):
        course_resp = client.post("/courses", json={"name": "Curso API"})
        assert course_resp.status_code == 201
        course_id = course_resp.json()["id"]

        student_ids = []
        for i in range(6):
            resp = client.post(
                f"/courses/{course_id}/students",
                json={"external_ref": f"E{i}", "display_name": f"Estudiante {i}"},
            )
            assert resp.status_code == 201
            student_ids.append(resp.json()["id"])

        select_resp = client.post(
            f"/courses/{course_id}/sessions/select",
            json={"present_student_ids": student_ids, "k": 2, "method": "bayesian_fairness"},
        )
        assert select_resp.status_code == 201
        body = select_resp.json()
        assert len(body["selected_student_ids"]) == 2
        assert set(body["considered_student_ids"]) == set(student_ids)

        selected_id = body["selected_student_ids"][0]

        state_resp = client.get(f"/students/{selected_id}/state")
        assert state_resp.status_code == 200
        state = state_resp.json()
        assert state["n_selected"] == 1
        assert state["n_present"] == 1
        assert state["beta"] == 2.0

        history_resp = client.get(f"/students/{selected_id}/history")
        assert history_resp.status_code == 200
        history = history_resp.json()
        assert len(history) == 1
        assert history[0]["selected"] is True

        metrics_resp = client.get(f"/courses/{course_id}/fairness-metrics")
        assert metrics_resp.status_code == 200
        metrics = metrics_resp.json()
        assert metrics["n_students"] == 6
        assert 0.0 <= metrics["gini"] <= 1.0


class TestPropuestasDeGrupos:
    def test_generate_edit_and_reload_group_plan(self, client: TestClient):
        course_id = new_course(client, "Curso con grupos")
        student_ids = [
            client.post(
                f"/courses/{course_id}/students",
                json={"external_ref": f"G{i}", "display_name": f"Estudiante {i}"},
            ).json()["id"]
            for i in range(7)
        ]

        generated = client.post(
            f"/courses/{course_id}/group-plans",
            json={"max_group_size": 3, "name": "Proyecto inicial"},
        )
        assert generated.status_code == 201
        original = generated.json()
        assert original["id"] is None
        assert original["name"] == "Proyecto inicial"
        assert sorted(len(group["student_ids"]) for group in original["groups"]) == [2, 2, 3]
        assert sorted(
            student_id for group in original["groups"] for student_id in group["student_ids"]
        ) == sorted(student_ids)
        assert client.get(f"/courses/{course_id}/group-plans").json() == []

        groups = original["groups"]
        moved_students = groups[0]["student_ids"][:2]
        groups[0]["student_ids"] = groups[0]["student_ids"][2:]
        groups[1]["student_ids"].extend(moved_students)
        groups[0]["name"] = "Equipo A"
        groups[1]["name"] = "Equipo B"
        confirmed = client.post(
            f"/courses/{course_id}/group-plans/confirm",
            json={
                "name": "Proyecto revisado",
                "max_group_size": 3,
                "groups": groups,
            },
        )
        assert confirmed.status_code == 201
        updated = confirmed
        assert updated.json()["name"] == "Proyecto revisado"
        assert updated.json()["groups"][0]["name"] == "Equipo A"
        assert max(len(group["student_ids"]) for group in updated.json()["groups"]) > 3

        reloaded = client.get(f"/courses/{course_id}/group-plans")
        assert reloaded.status_code == 200
        assert reloaded.json()[0]["id"] == updated.json()["id"]
        assert reloaded.json()[0]["groups"] == updated.json()["groups"]

    def test_edit_rejects_duplicates_and_allows_unassigned_students(
        self, client: TestClient
    ):
        course_id = new_course(client, "Curso grupos inválidos")
        student_ids = [
            client.post(
                f"/courses/{course_id}/students",
                json={"external_ref": f"GX{i}", "display_name": f"Persona {i}"},
            ).json()["id"]
            for i in range(3)
        ]
        plan = client.post(
            f"/courses/{course_id}/group-plans", json={"max_group_size": 2}
        ).json()
        groups = plan["groups"]
        groups[1]["student_ids"].append(groups[0]["student_ids"][0])

        duplicate = client.post(
            f"/courses/{course_id}/group-plans/confirm",
            json={
                "name": "Distribución inválida",
                "max_group_size": 2,
                "groups": groups,
            },
        )
        assert duplicate.status_code == 400

        missing = client.post(
            f"/courses/{course_id}/group-plans/confirm",
            json={
                "name": "Distribución incompleta",
                "max_group_size": 2,
                "groups": [
                    {"name": "Grupo 1", "student_ids": student_ids[:2]},
                    {"name": "Grupo 2", "student_ids": []},
                ],
            },
        )
        assert missing.status_code == 201
        assert student_ids[2] not in [
            student_id
            for group in missing.json()["groups"]
            for student_id in group["student_ids"]
        ]

        unknown = client.post(
            f"/courses/{course_id}/group-plans/confirm",
            json={
                "name": "Estudiante externo",
                "max_group_size": 2,
                "groups": [
                    {"name": "Grupo 1", "student_ids": [999999]},
                    {"name": "Grupo 2", "student_ids": []},
                ],
            },
        )
        assert unknown.status_code == 400

    def test_generate_requires_students_and_plans_can_be_deleted(self, client: TestClient):
        course_id = new_course(client, "Curso grupos vacío")
        empty = client.post(
            f"/courses/{course_id}/group-plans", json={"max_group_size": 3}
        )
        assert empty.status_code == 400

        client.post(
            f"/courses/{course_id}/students",
            json={"external_ref": "ONE", "display_name": "Única"},
        )
        plan = client.post(
            f"/courses/{course_id}/group-plans", json={"max_group_size": 3}
        ).json()
        saved = client.post(
            f"/courses/{course_id}/group-plans/confirm",
            json={
                "name": plan["name"],
                "max_group_size": plan["max_group_size"],
                "groups": plan["groups"],
            },
        ).json()
        deleted = client.delete(f"/courses/{course_id}/group-plans/{saved['id']}")
        assert deleted.status_code == 204
        assert client.get(f"/courses/{course_id}/group-plans").json() == []

    def test_manual_group_plan_uses_roster_and_is_saved(self, client: TestClient):
        course_id = new_course(client, "Curso grupos manuales")
        student_ids = [
            client.post(
                f"/courses/{course_id}/students",
                json={"external_ref": f"GM{i}", "display_name": f"Persona {i}"},
            ).json()["id"]
            for i in range(5)
        ]

        response = client.post(
            f"/courses/{course_id}/group-plans/manual",
            json={"group_count": 3, "name": "Grupos elegidos"},
        )
        assert response.status_code == 201
        plan = response.json()
        assert plan["id"] is None
        assert plan["name"] == "Grupos elegidos"
        assert sorted(
            student_id for group in plan["groups"] for student_id in group["student_ids"]
        ) == sorted(student_ids)
        assert sorted(len(group["student_ids"]) for group in plan["groups"]) == [1, 2, 2]
        assert plan["max_group_size"] == 2
        assert client.get(f"/courses/{course_id}/group-plans").json() == []
        saved = client.post(
            f"/courses/{course_id}/group-plans/confirm",
            json={
                "name": plan["name"],
                "max_group_size": plan["max_group_size"],
                "groups": plan["groups"],
            },
        ).json()
        assert saved["name"] == plan["name"]
        assert saved["groups"] == plan["groups"]

    def test_manual_group_plan_rejects_more_groups_than_students(self, client: TestClient):
        course_id = new_course(client, "Curso con pocos estudiantes")
        client.post(
            f"/courses/{course_id}/students",
            json={"external_ref": "GM1", "display_name": "Persona 1"},
        )

        response = client.post(
            f"/courses/{course_id}/group-plans/manual",
            json={"group_count": 2},
        )
        assert response.status_code == 400

    def test_enroll_is_idempotent_by_external_ref(self, client: TestClient):
        course_id = client.post("/courses", json={"name": "Curso idempotencia"}).json()["id"]

        first = client.post(
            f"/courses/{course_id}/students",
            json={"external_ref": "dup-1", "display_name": "Primero"},
        )
        second = client.post(
            f"/courses/{course_id}/students",
            json={"external_ref": "dup-1", "display_name": "Segundo intento"},
        )

        assert first.json()["id"] == second.json()["id"]
        assert first.json()["account_username"] == "dup-1"
        assert first.json()["temporary_password"]
        assert second.json()["temporary_password"] is None

        students = client.get(f"/courses/{course_id}/students").json()
        assert len(students) == 1

    def test_unknown_method_returns_400(self, client: TestClient):
        course_id = client.post("/courses", json={"name": "Curso 2"}).json()["id"]
        student_id = client.post(
            f"/courses/{course_id}/students",
            json={"external_ref": "X", "display_name": "X"},
        ).json()["id"]

        resp = client.post(
            f"/courses/{course_id}/sessions/select",
            json={"present_student_ids": [student_id], "k": 1, "method": "no_existe"},
        )
        assert resp.status_code == 400

    def test_invalid_method_params_return_400(self, client: TestClient):
        course_id = client.post("/courses", json={"name": "Curso parámetros"}).json()["id"]
        student_id = client.post(
            f"/courses/{course_id}/students",
            json={"external_ref": "P1", "display_name": "Estudiante"},
        ).json()["id"]

        resp = client.post(
            f"/courses/{course_id}/sessions/select",
            json={
                "present_student_ids": [student_id],
                "k": 1,
                "method": "bayesian_fairness",
                "method_params": {
                    "additionalProp1": 0,
                    "additionalProp2": 0,
                    "additionalProp3": 0,
                },
            },
        )

        assert resp.status_code == 400
        assert "additionalProp1" in resp.json()["detail"]

    def test_invalid_class_session_id_is_rejected(self, client: TestClient):
        course_id = client.post("/courses", json={"name": "Curso sesión"}).json()["id"]
        student_id = client.post(
            f"/courses/{course_id}/students",
            json={"external_ref": "S1", "display_name": "Estudiante"},
        ).json()["id"]
        endpoint = f"/courses/{course_id}/sessions/select"
        payload = {"present_student_ids": [student_id], "k": 1, "method": "roulette"}

        zero_id_resp = client.post(endpoint, json={**payload, "class_session_id": 0})
        missing_id_resp = client.post(endpoint, json={**payload, "class_session_id": 999999})

        assert zero_id_resp.status_code == 422
        assert missing_id_resp.status_code == 404

    def test_selecting_unregistered_students_returns_404(self, client: TestClient):
        course_id = client.post("/courses", json={"name": "Curso 3"}).json()["id"]
        resp = client.post(
            f"/courses/{course_id}/sessions/select",
            json={"present_student_ids": [999999], "k": 1, "method": "roulette"},
        )
        assert resp.status_code == 404

    def test_missing_student_state_returns_404(self, client: TestClient):
        resp = client.get("/students/999999/state")
        assert resp.status_code == 404

    def test_missing_course_returns_404(self, client: TestClient):
        resp = client.get("/courses/999999")
        assert resp.status_code == 404


# --------------------------------------------------------------------------
# Sprint 1: HU-C1 (lista por Excel), HU-S1 (iniciar sesión), HU-S2 (asistencia)
# --------------------------------------------------------------------------

import io  # noqa: E402
import sqlite3  # noqa: E402

from openpyxl import Workbook  # noqa: E402

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def make_xlsx(rows) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(["MATRICULADOS - TE111-U"])
    for row in rows:
        ws.append(row)
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def upload(client: TestClient, course_id: int, rows, filename: str = "lista.xlsx"):
    return client.post(
        f"/courses/{course_id}/students/import",
        files={"file": (filename, make_xlsx(rows), XLSX_MIME)},
    )


def new_course(client: TestClient, name: str = "Curso S1") -> int:
    return client.post("/courses", json={"name": name}).json()["id"]


class TestImportacionExcel:
    def test_import_creates_students_and_lists_them(self, client: TestClient):
        course_id = new_course(client)
        resp = upload(client, course_id, [["codigo", "nombre"], ["A1", "Ana"], ["A2", "Luis"]])

        assert resp.status_code == 200
        body = resp.json()
        assert (body["total_rows"], body["created"], body["updated"], body["errors"]) == (2, 2, 0, [])

        students = client.get(f"/courses/{course_id}/students").json()
        assert [s["display_name"] for s in students] == ["Ana", "Luis"]
        assert all(s["active"] for s in students)

    def test_invalid_rows_are_reported_with_row_number(self, client: TestClient):
        course_id = new_course(client)
        resp = upload(client, course_id, [["codigo", "nombre"], ["A1", "Ana"], ["A2", None], ["A1", "Dup"]])

        body = resp.json()
        assert resp.status_code == 200
        assert body["created"] == 1
        assert sorted(e["row"] for e in body["errors"]) == [4, 5]

    def test_reimport_updates_names_without_duplicating(self, client: TestClient):
        course_id = new_course(client)
        upload(client, course_id, [["codigo", "nombre"], ["A1", "Ana"]])
        body = upload(client, course_id, [["codigo", "nombre"], ["A1", "Ana María"]]).json()

        assert (body["created"], body["updated"]) == (0, 1)
        students = client.get(f"/courses/{course_id}/students").json()
        assert [s["display_name"] for s in students] == ["Ana María"]

    def test_cycle_roster_import_is_rejected_after_first_success(self, client: TestClient):
        cycle = client.post("/cycles", json={"name": "2026-II"}).json()
        course = client.post(
            "/courses", json={"name": "Curso ciclo", "cycle_id": cycle["id"]}
        ).json()
        rows = [["codigo", "nombre"], ["A1", "Ana"]]

        first = upload(client, course["id"], rows)
        second = upload(client, course["id"], rows)

        assert first.status_code == 200
        assert second.status_code == 409
        assert client.get(f"/courses/{course['id']}").json()["roster_imported"] is True

    def test_imports_contact_fields_and_preserves_them_when_columns_are_absent(self, client: TestClient):
        course_id = new_course(client)
        upload(
            client,
            course_id,
            [["codigo", "nombre", "celular", "correo"], ["A1", "Ana", "987654321", "ana@example.com"]],
        )

        body = upload(client, course_id, [["codigo", "nombre"], ["A1", "Ana María"]]).json()
        student = client.get(f"/courses/{course_id}/students").json()[0]

        assert body["updated"] == 1
        assert (student["phone_number"], student["email"]) == ("987654321", "ana@example.com")
        assert student["display_name"] == "Ana María"

    def test_imports_all_roster_metadata_and_returns_new_account_once(self, client: TestClient):
        course_id = new_course(client)
        response = upload(
            client,
            course_id,
            [
                ["NRO", "CÓDIGO", "ALUMNO", "ESP", "CONDICION", "CORREO UNI", "VECES REPETIDAS"],
                [5, "A1", "Ana Torres", "I2", "Regular", "ANA@UNI.EDU.PE", 1],
            ],
        )
        body = response.json()
        student = client.get(f"/courses/{course_id}/students").json()[0]

        assert response.headers["cache-control"] == "no-store"
        assert body["created"] == 1
        assert len(body["created_accounts"]) == 1
        account = body["created_accounts"][0]
        assert account["email"] == "ana@uni.edu.pe"
        assert len(account["temporary_password"]) >= 12
        assert (student["roster_number"], student["specialty"]) == ("5", "I2")
        assert (student["student_condition"], student["times_repeated"]) == ("Regular", "1")
        assert student["user_id"] is not None

        second_course = new_course(client, "Otro curso")
        second = upload(
            client,
            second_course,
            [["CODIGO", "ALUMNO", "CORREO UNI"], ["B1", "Ana Torres", "ana@uni.edu.pe"]],
        ).json()
        second_student = client.get(f"/courses/{second_course}/students").json()[0]
        assert second["created_accounts"] == []
        assert second_student["user_id"] == student["user_id"]

    def test_wrong_structure_returns_400_and_saves_nothing(self, client: TestClient):
        course_id = new_course(client)
        resp = upload(client, course_id, [["foo", "bar"], ["A1", "Ana"]])
        assert resp.status_code == 400
        assert client.get(f"/courses/{course_id}/students").json() == []

    def test_non_xlsx_file_returns_400(self, client: TestClient):
        course_id = new_course(client)
        resp = client.post(
            f"/courses/{course_id}/students/import",
            files={"file": ("lista.csv", b"codigo,nombre\nA1,Ana\n", "text/csv")},
        )
        assert resp.status_code == 400
        corrupt = client.post(
            f"/courses/{course_id}/students/import",
            files={"file": ("lista.xlsx", b"no soy un excel", XLSX_MIME)},
        )
        assert corrupt.status_code == 400

    def test_unknown_course_returns_404(self, client: TestClient):
        resp = upload(client, 999999, [["codigo", "nombre"], ["A1", "Ana"]])
        assert resp.status_code == 404


class TestEdicionDeLista:
    def _course_with_students(self, client: TestClient):
        course_id = new_course(client)
        upload(client, course_id, [["codigo", "nombre"], ["A1", "Ana"], ["A2", "Luis"]])
        return course_id, client.get(f"/courses/{course_id}/students").json()

    def test_rename_student(self, client: TestClient):
        _, students = self._course_with_students(client)
        resp = client.patch(f"/students/{students[0]['id']}", json={"display_name": "Ana María"})
        assert resp.status_code == 200
        assert resp.json()["display_name"] == "Ana María"

    def test_teacher_can_reset_password_from_course_student_record(self, client: TestClient):
        course_id = new_course(client)
        upload(
            client,
            course_id,
            [["codigo", "nombre", "CORREO UNI"], ["A1", "Ana", "ana@example.edu"]],
        )
        student = client.get(f"/courses/{course_id}/students").json()[0]
        teachers = client.get("/admin/teachers").json()
        assigned = client.put(
            f"/admin/teachers/{teachers[0]['id']}/courses",
            json={"course_ids": [course_id]},
        )
        assert assigned.status_code == 200

        client.cookies.clear()
        login = client.post(
            "/auth/login",
            json={"username": "teacher", "password": "test-teacher-password-123"},
        )
        assert login.status_code == 200
        reset = client.post(f"/students/{student['id']}/reset-password")
        assert reset.status_code == 200
        assert reset.headers["cache-control"] == "no-store"

        client.cookies.clear()
        student_login = client.post(
            "/auth/login",
            json={
                "username": "ANA@example.edu",
                "password": reset.json()["temporary_password"],
            },
        )
        assert student_login.status_code == 200
        assert student_login.json()["must_change_password"] is True

    def test_enroll_and_edit_contact_information(self, client: TestClient):
        course_id = new_course(client)
        created = client.post(
            f"/courses/{course_id}/students",
            json={
                "external_ref": "A1",
                "display_name": "Ana",
                "phone_number": "987654321",
                "email": "ana@example.com",
            },
        )
        assert created.status_code == 201
        student_id = created.json()["id"]
        assert (created.json()["phone_number"], created.json()["email"]) == (
            "987654321",
            "ana@example.com",
        )

        updated = client.patch(
            f"/students/{student_id}",
            json={"phone_number": "", "email": "ana.nueva@example.com"},
        )
        assert updated.status_code == 200
        assert (updated.json()["phone_number"], updated.json()["email"]) == (
            None,
            "ana.nueva@example.com",
        )

    def test_withdraw_hides_from_default_list_but_not_from_include_inactive(self, client: TestClient):
        course_id, students = self._course_with_students(client)
        client.patch(f"/students/{students[0]['id']}", json={"active": False})

        assert len(client.get(f"/courses/{course_id}/students").json()) == 1
        everyone = client.get(f"/courses/{course_id}/students?include_inactive=true").json()
        assert len(everyone) == 2
        # su historial sigue accesible
        assert client.get(f"/students/{students[0]['id']}/state").status_code == 200

    def test_duplicate_code_returns_409_and_empty_body_returns_422(self, client: TestClient):
        _, students = self._course_with_students(client)
        dup = client.patch(f"/students/{students[0]['id']}", json={"external_ref": "A2"})
        empty = client.patch(f"/students/{students[0]['id']}", json={})
        missing = client.patch("/students/999999", json={"display_name": "X"})
        assert (dup.status_code, empty.status_code, missing.status_code) == (409, 422, 404)


class TestSesionesYAsistencia:
    def _course(self, client: TestClient, n: int = 4):
        course_id = new_course(client)
        upload(client, course_id, [["codigo", "nombre"], *[[f"A{i}", f"Estudiante {i}"] for i in range(n)]])
        ids = [s["id"] for s in client.get(f"/courses/{course_id}/students").json()]
        return course_id, ids

    def test_list_courses(self, client: TestClient):
        first = new_course(client, "Uno")
        second = new_course(client, "Dos")
        ids = [c["id"] for c in client.get("/courses").json()]
        assert ids[-2:] == [first, second]

    def test_proposal_without_and_with_syllabus(self, client: TestClient):
        course_id, _ = self._course(client)
        empty = client.get(f"/courses/{course_id}/class-sessions/proposal").json()
        assert empty["suggested_topic"] is None and empty["session_date"]

        client.post(f"/courses/{course_id}/syllabus", json={"session_date": "2026-10-12", "topic": "Límites"})
        proposal = client.get(
            f"/courses/{course_id}/class-sessions/proposal", params={"session_date": "2026-10-12"}
        ).json()
        assert proposal == {"session_date": "2026-10-12", "suggested_topic": "Límites"}

    def test_start_session_confirms_or_corrects_topic_and_registers_attendance(self, client: TestClient):
        course_id, ids = self._course(client)
        client.post(f"/courses/{course_id}/syllabus", json={"session_date": "2026-10-12", "topic": "Límites"})

        proposed = client.post(
            f"/courses/{course_id}/class-sessions", json={"session_date": "2026-10-12"}
        )
        corrected = client.post(
            f"/courses/{course_id}/class-sessions",
            json={"session_date": "2026-10-12", "topic": "Repaso de límites", "present_student_ids": ids[:2]},
        )

        assert proposed.status_code == 201
        assert proposed.json()["topic"] == "Límites"
        assert proposed.json()["present_count"] == 4  # por defecto, todos presentes
        body = corrected.json()
        assert body["topic"] == "Repaso de límites"
        assert (body["present_count"], body["total_count"]) == (2, 4)

    def test_start_session_validations(self, client: TestClient):
        course_id, ids = self._course(client)
        assert client.post("/courses/999999/class-sessions", json={}).status_code == 404
        foreign = client.post(f"/courses/{course_id}/class-sessions", json={"present_student_ids": [999999]})
        assert foreign.status_code == 400

    def test_update_attendance_and_read_back(self, client: TestClient):
        course_id, ids = self._course(client)
        session_id = client.post(f"/courses/{course_id}/class-sessions", json={}).json()["id"]

        resp = client.put(
            f"/class-sessions/{session_id}/attendance",
            json={"attendance": [{"student_id": ids[0], "present": False}, {"student_id": ids[1], "present": False}]},
        )
        assert resp.status_code == 200
        assert resp.json()["present_count"] == 2

        detail = client.get(f"/class-sessions/{session_id}").json()
        by_id = {a["student_id"]: a["present"] for a in detail["attendance"]}
        assert by_id[ids[0]] is False and by_id[ids[2]] is True

        listing = client.get(f"/courses/{course_id}/class-sessions").json()
        assert [s["id"] for s in listing] == [session_id]

    def test_update_attendance_errors(self, client: TestClient):
        course_id, ids = self._course(client)
        session_id = client.post(f"/courses/{course_id}/class-sessions", json={}).json()["id"]
        bad_student = client.put(
            f"/class-sessions/{session_id}/attendance",
            json={"attendance": [{"student_id": 999999, "present": True}]},
        )
        missing_session = client.put(
            "/class-sessions/999999/attendance",
            json={"attendance": [{"student_id": ids[0], "present": True}]},
        )
        empty = client.put(f"/class-sessions/{session_id}/attendance", json={"attendance": []})
        assert (bad_student.status_code, missing_session.status_code, empty.status_code) == (400, 404, 422)

    def test_selection_uses_session_attendance(self, client: TestClient):
        course_id, ids = self._course(client, n=6)
        session_id = client.post(
            f"/courses/{course_id}/class-sessions", json={"present_student_ids": ids[:3]}
        ).json()["id"]

        resp = client.post(
            f"/courses/{course_id}/sessions/select",
            json={"class_session_id": session_id, "k": 3, "method": "roulette"},
        )

        assert resp.status_code == 201
        body = resp.json()
        assert set(body["considered_student_ids"]) == set(ids[:3])
        assert body["class_session_id"] == session_id

    def test_selection_requires_ids_or_session(self, client: TestClient):
        course_id, _ = self._course(client)
        resp = client.post(f"/courses/{course_id}/sessions/select", json={"k": 1, "method": "roulette"})
        assert resp.status_code == 422

    def test_selection_with_session_of_another_course_returns_404(self, client: TestClient):
        course_a, ids_a = self._course(client)
        course_b, _ = self._course(client)
        foreign_session = client.post(f"/courses/{course_b}/class-sessions", json={}).json()["id"]
        resp = client.post(
            f"/courses/{course_a}/sessions/select",
            json={"present_student_ids": ids_a, "class_session_id": foreign_session, "k": 1, "method": "roulette"},
        )
        assert resp.status_code == 404


class TestStudentAccountsAndPortal:
    def test_admin_can_register_list_and_reset_student_account(self, client: TestClient):
        created = client.post(
            "/admin/students",
            json={"username": "2024001", "full_name": "Ana Torres", "email": " ANA@UNI.EDU.PE "},
        )
        assert created.status_code == 201
        assert created.headers["cache-control"] == "no-store"
        account = created.json()
        assert account["username"] == "2024001"
        assert account["email"] == "ana@uni.edu.pe"
        assert account["role"] == "estudiante"
        assert "temporary_password" in account
        assert "temporary_password" not in client.get("/admin/students").text
        duplicate_username = client.post(
            "/admin/students",
            json={"username": "2024001", "full_name": "Otra Ana", "email": "otra@uni.edu.pe"},
        )
        assert duplicate_username.status_code == 400

        reset = client.post(f"/admin/students/{account['id']}/reset-password")
        assert reset.status_code == 200
        assert reset.headers["cache-control"] == "no-store"
        client.cookies.clear()
        login = client.post(
            "/auth/login",
            json={
                "username": account["username"],
                "password": reset.json()["temporary_password"],
            },
        )
        assert login.status_code == 200
        assert login.json()["must_change_password"] is True
        assert client.get("/admin/students").status_code == 403

    def test_student_sees_only_enrolled_courses_and_sessions_in_16_weeks(self, client: TestClient):
        cycle = client.post(
            "/cycles", json={"name": "2030-I", "starts_on": "2030-03-01"}
        ).json()
        course = client.post(
            "/courses", json={"name": "Biología", "cycle_id": cycle["id"]}
        ).json()
        other_course = new_course(client, "Curso ajeno")
        imported = upload(
            client,
            course["id"],
            [["codigo", "nombre", "CORREO UNI"], ["A1", "Ana Torres", "ana@example.edu"]],
        ).json()
        credential = imported["created_accounts"][0]

        for session_date in ("2030-03-01", "2030-03-08", "2030-06-14", "2030-06-21"):
            response = client.post(
                f"/courses/{course['id']}/class-sessions",
                json={"session_date": session_date, "topic": f"Clase {session_date}"},
            )
            assert response.status_code == 201

        client.cookies.clear()
        login = client.post(
            "/auth/login",
            json={"username": credential["username"], "password": credential["temporary_password"]},
        )
        assert login.status_code == 200
        assert login.json()["must_change_password"] is True
        changed = client.post(
            "/auth/change-password", json={"new_password": "ana-student-password-123"}
        )
        assert changed.status_code == 200
        assert changed.json()["role"] == "estudiante"

        courses = client.get("/student/courses")
        assert courses.status_code == 200
        assert [item["course_id"] for item in courses.json()] == [course["id"]]
        assert client.get("/courses").status_code == 403
        assert client.get(f"/courses/{course['id']}/students").status_code == 403
        assert client.get(f"/student/courses/{other_course}/weeks").status_code == 404
        weeks = client.get(f"/student/courses/{course['id']}/weeks")
        assert weeks.status_code == 200
        body = weeks.json()
        assert len(body["weeks"]) == 16
        assert body["weeks"][0]["sessions"][0]["topic"] == "Clase 2030-03-01"
        assert body["weeks"][1]["sessions"][0]["topic"] == "Clase 2030-03-08"
        assert body["weeks"][15]["sessions"][0]["topic"] == "Clase 2030-06-14"
        assert [item["topic"] for item in body["unassigned_sessions"]] == [
            "Clase 2030-06-21"
        ]
        assert client.post(f"/courses/{course['id']}/class-sessions", json={}).status_code == 403

    def test_import_creates_code_login_even_without_roster_email(self, client: TestClient):
        course_id = new_course(client, "Curso sin correos")
        imported = upload(
            client, course_id, [["CODIGO", "ALUMNO"], ["000123", "Ana Torres"]]
        )

        assert imported.status_code == 200
        assert imported.headers["cache-control"] == "no-store"
        credential = imported.json()["created_accounts"][0]
        assert credential["username"] == "000123"
        assert credential["email"] is None
        assert credential["temporary_password"]
        client.cookies.clear()
        login = client.post(
            "/auth/login",
            json={"username": "000123", "password": credential["temporary_password"]},
        )
        assert login.status_code == 200

    def test_import_reuses_email_account_and_sets_roster_code_as_username(self, client: TestClient):
        created = client.post(
            "/admin/students",
            json={"username": "old-random-user", "full_name": "Ana Torres", "email": "ana@uni.edu"},
        ).json()
        course_id = new_course(client, "Curso de cuenta existente")
        imported = upload(
            client,
            course_id,
            [["CODIGO", "ALUMNO", "CORREO UNI"], ["2024001", "Ana Torres", "ANA@UNI.EDU"]],
        )

        assert imported.status_code == 200
        assert imported.json()["created_accounts"] == []
        assert imported.json()["updated_accounts"][0]["username"] == "2024001"
        students = client.get("/admin/students").json()
        linked_account = next(item for item in students if item["id"] == created["id"])
        assert linked_account["username"] == "2024001"


class TestMigracionDeBaseAnterior:
    def test_database_created_before_sprint_1_is_upgraded_in_place(self, monkeypatch, tmp_path):
        """Una base SQLite creada con el esquema anterior (sin `students.active`,
        `class_sessions.session_date` ni `class_sessions.topic`) debe seguir
        funcionando al arrancar la app, conservando sus datos."""
        db_path = tmp_path / "old.db"
        conn = sqlite3.connect(db_path)
        conn.executescript(
            """
            CREATE TABLE courses (id INTEGER PRIMARY KEY, name VARCHAR(255) NOT NULL, created_at DATETIME);
            CREATE TABLE students (
                id INTEGER PRIMARY KEY, course_id INTEGER NOT NULL REFERENCES courses(id),
                external_ref VARCHAR(255) NOT NULL, display_name VARCHAR(255) NOT NULL, created_at DATETIME,
                CONSTRAINT uq_student_course_external_ref UNIQUE (course_id, external_ref));
            CREATE TABLE class_sessions (
                id INTEGER PRIMARY KEY, course_id INTEGER NOT NULL REFERENCES courses(id),
                label VARCHAR(255), created_at DATETIME);
            INSERT INTO courses (id, name) VALUES (1, 'Curso viejo');
            INSERT INTO students (id, course_id, external_ref, display_name) VALUES (1, 1, 'OLD1', 'Estudiante previo');
            INSERT INTO class_sessions (id, course_id, label) VALUES (1, 1, 'clase vieja');
            """
        )
        conn.commit()
        conn.close()
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
        monkeypatch.delenv("ADMIN_USERNAME", raising=False)
        monkeypatch.delenv("ADMIN_PASSWORD", raising=False)

        from src.api.main import app

        with TestClient(app) as client:
            auth_service = app.state.app_context.auth_service
            with auth_service._session_factory() as session:
                administrator_role_id = session.execute(
                    select(RoleORM.id).where(RoleORM.name == "administrador")
                ).scalar_one()
                session.add(
                    UserORM(
                        username="migration-admin",
                        full_name="Migration Admin",
                        password_hash=hash_password("migration-admin-password-123"),
                        role_id=administrator_role_id,
                    )
                )
                session.commit()
            login = client.post(
                "/auth/login",
                json={"username": "migration-admin", "password": "migration-admin-password-123"},
            )
            assert login.status_code == 200

            students = client.get("/courses/1/students").json()
            assert [(s["display_name"], s["active"]) for s in students] == [("Estudiante previo", True)]
            created = client.post("/courses/1/class-sessions", json={"topic": "Tema nuevo"})
            assert created.status_code == 201
            assert created.json()["topic"] == "Tema nuevo"


class TestRegistroParticipaciones:
    def _decision(self, client: TestClient):
        course_id = new_course(client, "Curso con notas")
        student_ids = [
            client.post(
                f"/courses/{course_id}/students",
                json={"external_ref": f"P{i}", "display_name": f"Persona {i}"},
            ).json()["id"]
            for i in range(3)
        ]
        decision = client.post(
            f"/courses/{course_id}/sessions/select",
            json={"present_student_ids": student_ids, "k": 2, "method": "roulette"},
        ).json()
        return course_id, student_ids, decision

    def test_records_grade_and_attendance_and_lists_course_history(self, client: TestClient):
        course_id, student_ids, decision = self._decision(client)
        selected = decision["selected_student_ids"]
        payload = {
            "participations": [
                {"student_id": selected[0], "score": 4.5, "present": True},
                {"student_id": selected[1], "score": 0, "present": False},
            ]
        }

        saved = client.post(
            f"/courses/{course_id}/decision-runs/{decision['decision_run_id']}/participations",
            json=payload,
        )
        history = client.get(f"/courses/{course_id}/participations")

        assert saved.status_code == 201
        assert {item["student_id"] for item in saved.json()} == set(selected)
        assert history.status_code == 200
        assert len(history.json()) == 2
        assert {item["score"] for item in history.json()} == {4.5, 0}
        assert {item["present"] for item in history.json()} == {True, False}
        assert {item["external_ref"] for item in history.json()} == {
            f"P{student_ids.index(item['student_id'])}" for item in history.json()
        }

    def test_records_question_and_comment_and_they_are_optional(self, client: TestClient):
        course_id, _, decision = self._decision(client)
        selected = decision["selected_student_ids"]
        saved = client.post(
            f"/courses/{course_id}/decision-runs/{decision['decision_run_id']}/participations",
            json={
                "participations": [
                    {"student_id": selected[0], "score": 4, "present": True,
                     "question": "  ¿Qué es una derivada?  ", "comment": "Respondió con seguridad"},
                    {"student_id": selected[1], "score": 2, "present": True},
                ]
            },
        )
        history = client.get(f"/courses/{course_id}/participations").json()
        by_student = {item["student_id"]: item for item in history}

        assert saved.status_code == 201
        assert by_student[selected[0]]["question"] == "¿Qué es una derivada?"
        assert by_student[selected[0]]["comment"] == "Respondió con seguridad"
        assert by_student[selected[1]]["question"] is None
        assert by_student[selected[1]]["comment"] is None

    def test_requires_all_and_only_selected_students_for_decision(self, client: TestClient):
        course_id, student_ids, decision = self._decision(client)
        selected = decision["selected_student_ids"]
        endpoint = (
            f"/courses/{course_id}/decision-runs/{decision['decision_run_id']}/participations"
        )
        partial = client.post(
            endpoint,
            json={"participations": [{"student_id": selected[0], "score": 3, "present": True}]},
        )
        unselected = next(student_id for student_id in student_ids if student_id not in selected)
        invalid = client.post(
            endpoint,
            json={
                "participations": [
                    {"student_id": selected[0], "score": 3, "present": True},
                    {"student_id": unselected, "score": 2, "present": True},
                ]
            },
        )
        assert partial.status_code == 400
        assert invalid.status_code == 400

    def test_grade_must_be_between_zero_and_five(self, client: TestClient):
        course_id, _, decision = self._decision(client)
        selected = decision["selected_student_ids"]
        resp = client.post(
            f"/courses/{course_id}/decision-runs/{decision['decision_run_id']}/participations",
            json={
                "participations": [
                    {"student_id": student_id, "score": 5.1, "present": True}
                    for student_id in selected
                ]
            },
        )
        assert resp.status_code == 422
