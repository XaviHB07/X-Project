"""Tests de integración de la API HTTP (`src/api/main.py`), de punta a
punta contra una base de datos SQLite temporal real (no in-memory): esta
es la única suite que ejercita la implementación de persistencia de
SQLAlchemy (`src/repositories/sqlalchemy/`), incluyendo la creación de
tablas y el ciclo completo request -> transacción -> respuesta.
"""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch, tmp_path):
    db_path = tmp_path / "test_api.db"
    # `DATABASE_URL` tiene prioridad sobre config/default.yaml (ver
    # `services/bootstrap.load_config`): así cada test usa su propia
    # base de datos SQLite temporal y no interfiere con los demás.
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    from src.api.main import app

    with TestClient(app) as test_client:
        yield test_client


class TestInfraestructura:
    def test_frontend_and_assets_are_served(self, client: TestClient):
        page = client.get("/")
        script = client.get("/assets/app.js")
        styles = client.get("/assets/styles.css")

        assert page.status_code == 200
        assert 'id="course-title"' in page.text
        assert script.status_code == 200
        assert "/sessions/select" in script.text
        assert styles.status_code == 200

    def test_health(self, client: TestClient):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_list_methods_includes_defaults(self, client: TestClient):
        resp = client.get("/methods")
        assert resp.status_code == 200
        methods = set(resp.json()["methods"])
        assert {"roulette", "weighted_softmax", "bayesian_fairness"}.issubset(methods)


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
        assert sorted(e["row"] for e in body["errors"]) == [3, 4]

    def test_reimport_updates_names_without_duplicating(self, client: TestClient):
        course_id = new_course(client)
        upload(client, course_id, [["codigo", "nombre"], ["A1", "Ana"]])
        body = upload(client, course_id, [["codigo", "nombre"], ["A1", "Ana María"]]).json()

        assert (body["created"], body["updated"]) == (0, 1)
        students = client.get(f"/courses/{course_id}/students").json()
        assert [s["display_name"] for s in students] == ["Ana María"]

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

        from src.api.main import app

        with TestClient(app) as client:
            students = client.get("/courses/1/students").json()
            assert [(s["display_name"], s["active"]) for s in students] == [("Estudiante previo", True)]
            created = client.post("/courses/1/class-sessions", json={"topic": "Tema nuevo"})
            assert created.status_code == 201
            assert created.json()["topic"] == "Tema nuevo"
