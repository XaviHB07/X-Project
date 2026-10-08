"""Tests de la API de participaciones (HU-P4), sobre SQLite real.

Estos son distintos de los de `test_participation_service.py` a propósito:
allí la persistencia era in-memory (rápida, pero no ejercita SQL), y aquí es
SQLAlchemy sobre un SQLite de verdad. El motivo es que hay fallos que solo
aparecen con un motor real: índices parciales que SQLite no acepta igual que
PostgreSQL, `DateTime` devolviendo `None`, ordenación distinta a la esperada
por una collation...

Se prueba el ciclo completo de una clase: crear curso, matricular, abrir
sesión, marcar asistencia, sortear, registrar la participación, y ver el
historial. Ese recorrido es el criterio de éxito del MVP 1 del Roadmap
("queda un historial trazable").
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch, tmp_path):
    db_path = tmp_path / "test_participaciones_api.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    from src.api.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def escena(client):
    """Curso con 3 estudiantes y una sesión con los 3 presentes."""
    curso = client.post("/courses", json={"name": "Innovación y Gestión"}).json()
    ids = []
    for ref, nombre in [("A1", "Ana Torres"), ("A2", "Bruno Díaz"),
                        ("A3", "Carla Ruiz")]:
        s = client.post(
            f"/courses/{curso['id']}/students",
            json={"external_ref": ref, "display_name": nombre},
        ).json()
        ids.append(s["id"])

    sesion = client.post(
        f"/courses/{curso['id']}/class-sessions", json={"topic": "Liderazgo"}
    ).json()
    client.put(
        f"/class-sessions/{sesion['id']}/attendance",
        json={"attendance": [{"student_id": i, "present": True} for i in ids]},
    )
    return {"curso": curso, "sesion": sesion, "ids": ids}


class TestRegistroPorAPI:
    def test_registra_y_devuelve_201(self, client, escena):
        r = client.post(
            f"/class-sessions/{escena['sesion']['id']}/participations",
            json={
                "student_id": escena["ids"][0],
                "question": "¿Qué es liderazgo?",
                "answer": "La capacidad de influir en un grupo.",
                "created_by": "profesora",
            },
        )
        assert r.status_code == 201, r.text
        d = r.json()
        assert d["question"] == "¿Qué es liderazgo?"
        assert d["student_name"] == "Ana Torres"
        assert d["present"] is True
        assert d["anulada"] is False
        assert d["id"] > 0

    def test_pregunta_vacia_es_422(self, client, escena):
        """El schema lo rechaza antes de llegar al servicio: es una
        validación de entrada, no un error de negocio."""
        r = client.post(
            f"/class-sessions/{escena['sesion']['id']}/participations",
            json={"student_id": escena["ids"][0], "question": ""},
        )
        assert r.status_code == 422

    def test_sesion_inexistente_es_404(self, client, escena):
        r = client.post(
            "/class-sessions/99999/participations",
            json={"student_id": escena["ids"][0], "question": "¿?"},
        )
        assert r.status_code == 404

    def test_estudiante_de_otro_curso_es_400(self, client, escena):
        """No es 404: los dos existen, lo que no existe es la relación. Un 400
        dice 'tu peticion es incoherente', que es exactamente lo que es."""
        otro = client.post("/courses", json={"name": "Física"}).json()
        ajeno = client.post(
            f"/courses/{otro['id']}/students",
            json={"external_ref": "F1", "display_name": "De Otro"},
        ).json()
        r = client.post(
            f"/class-sessions/{escena['sesion']['id']}/participations",
            json={"student_id": ajeno["id"], "question": "¿?"},
        )
        assert r.status_code == 400
        assert "curso" in r.json()["detail"]


class TestHistorialPorAPI:
    def test_historial_de_sesion(self, client, escena):
        sid = escena["sesion"]["id"]
        for i, q in enumerate(["Primera", "Segunda", "Tercera"]):
            client.post(
                f"/class-sessions/{sid}/participations",
                json={"student_id": escena["ids"][i], "question": q},
            )
        r = client.get(f"/class-sessions/{sid}/participations")
        assert r.status_code == 200
        datos = r.json()
        assert len(datos) == 3
        assert [d["question"] for d in datos] == ["Primera", "Segunda", "Tercera"]
        # El historial siempre lleva el nombre al lado: sin eso no le sirve
        # de nada al docente leerlo.
        assert all(d["student_name"] for d in datos)

    def test_historial_de_estudiante(self, client, escena):
        sid, a = escena["sesion"]["id"], escena["ids"][0]
        client.post(f"/class-sessions/{sid}/participations",
                    json={"student_id": a, "question": "Vieja"})
        client.post(f"/class-sessions/{sid}/participations",
                    json={"student_id": a, "question": "Nueva"})
        datos = client.get(f"/students/{a}/participations").json()
        assert [d["question"] for d in datos] == ["Nueva", "Vieja"]

    def test_sesion_vacia(self, client, escena):
        r = client.get(f"/class-sessions/{escena['sesion']['id']}/participations")
        assert r.status_code == 200
        assert r.json() == []


class TestResumenPorAPI:
    def test_resumen(self, client, escena):
        sid = escena["sesion"]["id"]
        client.post(f"/class-sessions/{sid}/participations",
                    json={"student_id": escena["ids"][0], "question": "1"})
        client.post(f"/class-sessions/{sid}/participations",
                    json={"student_id": escena["ids"][0], "question": "2"})
        d = client.get(f"/class-sessions/{sid}/participations/summary").json()
        assert d["total"] == 2
        assert d["estudiantes_participando"] == 1
        assert d["capacidad_presentes"] == 3


class TestAnulacionPorAPI:
    def test_anular_saca_del_historial_pero_conserva_el_rastro(self, client, escena):
        sid = escena["sesion"]["id"]
        p = client.post(
            f"/class-sessions/{sid}/participations",
            json={"student_id": escena["ids"][0], "question": "¿?"},
        ).json()

        r = client.post(
            f"/participations/{p['id']}/anular",
            json={"motivo": "se eligio al estudiante equivocado"},
        )
        assert r.status_code == 200
        assert r.json()["anulada"] is True

        # Fuera del historial normal...
        assert client.get(f"/class-sessions/{sid}/participations").json() == []
        # ...pero sigue en la base, para auditar.
        incl = client.get(
            f"/class-sessions/{sid}/participations?include_anuladas=true"
        ).json()
        assert len(incl) == 1
        assert incl[0]["motivo_anulacion"] == "se eligio al estudiante equivocado"

    def test_anular_inexistente_es_404(self, client):
        r = client.post("/participations/99999/anular", json={"motivo": "x"})
        assert r.status_code == 404


class TestCicloCompletoDeUnaClase:
    """El recorrido del criterio de exito del MVP 1, de punta a punta.

    No es un test de una funcion: es el flujo que el docente va a hacer en
    clase. Si este pasa, "queda un historial trazable" se cumple.
    """

    def test_clase_de_punta_a_punta(self, client, escena):
        curso_id = escena["curso"]["id"]
        sid = escena["sesion"]["id"]

        # 1. El docente sortea entre los presentes.
        sorteo = client.post(
            f"/courses/{curso_id}/sessions/select",
            json={"class_session_id": sid, "k": 1,
                  "method": "bayesian_fairness"},
        ).json()
        elegido = sorteo["selected_student_ids"][0]

        # 2. Hace la pregunta y registra la participación.
        p = client.post(
            f"/class-sessions/{sid}/participations",
            json={
                "student_id": elegido,
                "question": "¿Qué diferencia hay entre liderazgo y gestión?",
                "answer": "El liderazgo influye; lagestion organiza.",
                "decision_run_id": sorteo["decision_run_id"],
            },
        )
        assert p.status_code == 201
        assert p.json()["decision_run_id"] == sorteo["decision_run_id"]

        # 3. Queda el historial trazable, con su sorteo asociado.
        historial = client.get(f"/class-sessions/{sid}/participations").json()
        assert len(historial) == 1
        h = historial[0]
        assert h["student_id"] == elegido
        assert h["question"].startswith("¿Qué diferencia")
        assert h["answer"].startswith("El liderazgo")

        # 4. Y el estudiante tiene su propio historial.
        propio = client.get(f"/students/{elegido}/participations").json()
        assert len(propio) == 1
        assert propio[0]["id"] == h["id"]

        # 5. El resumen cuadra.
        resumen = client.get(f"/class-sessions/{sid}/participations/summary").json()
        assert resumen["total"] == 1
        assert resumen["estudiantes_participando"] == 1

    def test_persistencia_entre_arranques(self, client, escena, monkeypatch, tmp_path):
        """Lo registrado no se pierde: la tabla existe de verdad en el
        SQLite, no en memoria del proceso."""
        db = tmp_path / "test_participaciones_api.db"
        sid = escena["sesion"]["id"]
        client.post(f"/class-sessions/{sid}/participations",
                    json={"student_id": escena["ids"][0], "question": "Persistente"})

        # Se reconstruye la app contra la MISMA base, como si el servidor
        # se reiniciara.
        from src.api.main import app

        with TestClient(app) as segundo:
            datos = segundo.get(f"/class-sessions/{sid}/participations").json()
            assert len(datos) == 1
            assert datos[0]["question"] == "Persistente"