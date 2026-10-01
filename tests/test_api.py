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
