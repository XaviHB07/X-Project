"""Pruebas de regresión del Plan de optimización y estabilización.

Cubren lo que el plan exige como criterio de aceptación:

* El ranking optimizado (agregación SQL + caché) produce EXACTAMENTE los
  mismos resultados que el algoritmo anterior para los mismos datos, y la
  caché se invalida cuando entra una respuesta o un participante nuevo
  (Integrante 3, tareas 3.3–3.5).
* La autenticación de cada petición es una sola consulta y no se ejecuta
  en el event loop (Integrante 1, tareas 1.2–1.3).
* Cada respuesta trae `X-Request-ID` y `Server-Timing`; `/admin/metrics`
  es solo para administradores (Integrante 4, tarea 4.4).
* Un pool agotado se traduce en 503 rápido, no en una espera indefinida
  (Integrante 1, tarea 1.6).
* La configuración del pool es explícita y configurable (tarea 3.7).
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from src.api.observability import RouteStats, current_request, install_sql_timing, new_request_metrics
from src.repositories.sqlalchemy.models import (
    Base,
    CourseORM,
    QuickActivityAnswerORM,
    QuickActivityORM,
    QuickActivityQuestionORM,
    QuickActivityResponseORM,
    StudentORM,
)
from src.repositories.sqlalchemy.unit_of_work import build_session_factory, engine_options
from src.services.quick_activity_service import QuickActivityService
from tests.test_api import _login_as_admin, _login_as_teacher, client  # noqa: F401


# --------------------------------------------------------------------------
# Auxiliares
# --------------------------------------------------------------------------


@pytest.fixture
def session_factory(tmp_path):
    factory = build_session_factory(f"sqlite:///{tmp_path / 'perf.db'}")
    Base.metadata.create_all(factory.engine)
    return factory


class _QueryCounter:
    def __init__(self, engine):
        self.count = 0
        event.listen(engine, "before_cursor_execute", self._on_query)
        self._engine = engine

    def _on_query(self, *args, **kwargs):
        self.count += 1

    def close(self):
        event.remove(self._engine, "before_cursor_execute", self._on_query)


def _seed_live_activity(session_factory, *, students=25, questions=6, seed=7) -> int:
    """Quiz en vivo con datos variados: empates de puntaje y de tiempo,
    respuestas sin `points`/`response_ms`, `is_correct` nulo y estudiantes
    que no respondieron nada (casos borde del ranking)."""
    rng = random.Random(seed)
    with session_factory() as session:
        course = CourseORM(name="Curso de carga")
        session.add(course)
        session.flush()
        activity = QuickActivityORM(
            course_id=course.id, title="Cacería", status="published", mode="live",
            join_code="PERF01", question_seconds=20, live_phase="reveal", live_position=questions,
        )
        activity.questions = [
            QuickActivityQuestionORM(
                position=index, prompt=f"P{index}", options=["a", "b", "c", "d"], correct_option=0
            )
            for index in range(1, questions + 1)
        ]
        session.add(activity)
        session.flush()
        for number in range(students):
            student = StudentORM(
                course_id=course.id, external_ref=f"2026{number:04d}", display_name=f"Estudiante {number:02d}"
            )
            session.add(student)
            session.flush()
            response = QuickActivityResponseORM(
                activity_id=activity.id, student_id=student.id, user_id=1000 + number, attempt=1
            )
            session.add(response)
            session.flush()
            if number % 7 == 3:
                continue  # se unió pero no respondió nada
            for question in activity.questions:
                if rng.random() < 0.2:
                    continue
                correct = rng.choice([True, True, False, None])
                session.add(QuickActivityAnswerORM(
                    response_id=response.id,
                    question_id=question.id,
                    selected_option=0 if correct else 1,
                    is_correct=correct,
                    # Puntajes y tiempos en pocos valores para forzar empates.
                    points=rng.choice([None, 500, 750, 1000]) if correct else rng.choice([0, None]),
                    response_ms=rng.choice([None, 2000, 4000]),
                ))
        session.commit()
        return activity.id


def _legacy_leaderboard(service: QuickActivityService, session, activity) -> list:
    """Copia literal del algoritmo ANTERIOR (cargar objetos ORM y sumar en
    Python). Sirve como oráculo: el nuevo debe dar lo mismo."""
    from sqlalchemy.orm import selectinload

    rows = session.execute(
        select(QuickActivityResponseORM)
        .where(QuickActivityResponseORM.activity_id == activity.id)
        .options(
            selectinload(QuickActivityResponseORM.answers),
            selectinload(QuickActivityResponseORM.student),
        )
    ).scalars().all()
    board = []
    for row in rows:
        board.append({
            "student_id": row.student_id,
            "student_name": row.student.display_name,
            "student_code": row.student.external_ref,
            "points": sum(answer.points or 0 for answer in row.answers),
            "correct": sum(1 for answer in row.answers if answer.is_correct),
            "incorrect": sum(1 for answer in row.answers if not answer.is_correct),
            "unanswered": max(0, len(activity.questions) - len(row.answers)),
            "time_ms": sum(answer.response_ms or 0 for answer in row.answers if answer.is_correct),
        })
    board.sort(key=lambda item: (
        -item["points"],
        item["time_ms"],
        service._random_tie_key(activity.join_code or str(activity.id), item["student_id"]),
    ))
    for index, item in enumerate(board, start=1):
        item["rank"] = index
    return board


def _load_activity(session, activity_id):
    from sqlalchemy.orm import selectinload

    return session.execute(
        select(QuickActivityORM)
        .where(QuickActivityORM.id == activity_id)
        .options(selectinload(QuickActivityORM.questions))
    ).scalar_one()


# --------------------------------------------------------------------------
# Ranking (Integrante 3)
# --------------------------------------------------------------------------


class TestLeaderboard:
    @pytest.mark.parametrize("seed", [1, 7, 42])
    def test_aggregated_ranking_matches_legacy_algorithm(self, session_factory, seed):
        activity_id = _seed_live_activity(session_factory, students=30, seed=seed)
        service = QuickActivityService(session_factory)
        with session_factory() as session:
            activity = _load_activity(session, activity_id)
            assert service._compute_leaderboard(session, activity) == _legacy_leaderboard(
                service, session, activity
            )
            assert service._leaderboard(session, activity) == _legacy_leaderboard(
                service, session, activity
            )

    def test_cache_hit_skips_ranking_query_and_invalidates_on_new_answer(self, session_factory):
        activity_id = _seed_live_activity(session_factory, students=10, seed=3)
        service = QuickActivityService(session_factory)
        counter = _QueryCounter(session_factory.engine)
        try:
            with session_factory() as session:
                activity = _load_activity(session, activity_id)
                counter.count = 0
                first = service._leaderboard(session, activity)
                assert counter.count == 2  # huella + agregación
                counter.count = 0
                second = service._leaderboard(session, activity)
                assert counter.count == 1  # solo la huella: ranking desde caché
                assert second == first

                # Mutar el resultado devuelto no debe corromper la caché.
                second[0]["points"] = -1
                assert service._leaderboard(session, activity) == first

                # Respuesta nueva -> la huella cambia -> se recalcula.
                laggard = next(row for row in first if row["unanswered"] > 0)
                response = session.execute(
                    select(QuickActivityResponseORM).where(
                        QuickActivityResponseORM.activity_id == activity_id,
                        QuickActivityResponseORM.student_id == laggard["student_id"],
                    )
                ).scalar_one()
                answered = {
                    answer.question_id for answer in session.execute(
                        select(QuickActivityAnswerORM).where(
                            QuickActivityAnswerORM.response_id == response.id
                        )
                    ).scalars()
                }
                free_question = next(q for q in activity.questions if q.id not in answered)
                session.add(QuickActivityAnswerORM(
                    response_id=response.id, question_id=free_question.id, selected_option=0,
                    is_correct=True, points=99_999, response_ms=1,
                ))
                session.commit()
                counter.count = 0
                updated = service._leaderboard(session, activity)
                assert counter.count == 2
                assert updated[0]["student_id"] == laggard["student_id"]
                assert updated == _legacy_leaderboard(service, session, activity)
        finally:
            counter.close()

    def test_cache_invalidates_when_a_participant_joins(self, session_factory):
        activity_id = _seed_live_activity(session_factory, students=5, seed=9)
        service = QuickActivityService(session_factory)
        with session_factory() as session:
            activity = _load_activity(session, activity_id)
            assert len(service._leaderboard(session, activity)) == 5
            student = StudentORM(course_id=activity.course_id, external_ref="NUEVO", display_name="Nuevo")
            session.add(student)
            session.flush()
            session.add(QuickActivityResponseORM(
                activity_id=activity_id, student_id=student.id, user_id=1, attempt=1
            ))
            session.commit()
            board = service._leaderboard(session, activity)
            assert len(board) == 6
            assert board == _legacy_leaderboard(service, session, activity)

    def test_student_state_during_reveal_reuses_cached_ranking(self, session_factory):
        """Con muchos estudiantes mirando el resultado, el ranking se arma
        una vez y las demás consultas lo reutilizan."""
        activity_id = _seed_live_activity(session_factory, students=12, seed=5)
        service = QuickActivityService(session_factory)
        with session_factory() as session:
            responses = session.execute(
                select(QuickActivityResponseORM.user_id, StudentORM.id)
                .join(StudentORM, StudentORM.id == QuickActivityResponseORM.student_id)
                .where(QuickActivityResponseORM.activity_id == activity_id)
            ).all()
        # `_live_participant` busca la matrícula por user_id.
        with session_factory() as session:
            for user_id, student_id in responses:
                session.get(StudentORM, student_id).user_id = user_id
            session.commit()
        calls = {"n": 0}
        original = service._compute_leaderboard

        def spy(session, activity):
            calls["n"] += 1
            return original(session, activity)

        service._compute_leaderboard = spy
        states = [service.live_state_for_student(user_id, activity_id) for user_id, _ in responses]
        assert calls["n"] == 1
        assert {state["phase"] for state in states} == {"reveal"}
        ranks = sorted(state["rank"] for state in states)
        assert ranks == list(range(1, len(responses) + 1))
        assert {state["participant_count"] for state in states} == {len(responses)}


# --------------------------------------------------------------------------
# Autenticación y middleware (Integrante 1)
# --------------------------------------------------------------------------


class TestAuthentication:
    def test_user_for_token_is_a_single_query(self, client: TestClient):
        _login_as_teacher(client)
        context = client.app.state.app_context
        counter = _QueryCounter(context.engine)
        try:
            user = context.auth_service.user_for_token(client.cookies.get("aula_session"))
            assert user is not None and user.role
            assert counter.count == 1
        finally:
            counter.close()

    def test_authentication_runs_outside_the_event_loop(self, client: TestClient, monkeypatch):
        import threading

        _login_as_teacher(client)
        auth = client.app.state.app_context.auth_service
        original = auth.user_for_token
        seen = {}

        def spy(token):
            seen["thread"] = threading.current_thread().name
            import asyncio

            try:
                asyncio.get_running_loop()
                seen["in_loop"] = True
            except RuntimeError:
                seen["in_loop"] = False
            return original(token)

        monkeypatch.setattr(auth, "user_for_token", spy)
        assert client.get("/auth/me").status_code == 200
        assert seen["in_loop"] is False

    def test_protected_routes_keep_their_behaviour(self, client: TestClient):
        client.post("/auth/logout")
        assert client.get("/courses").status_code == 401
        assert client.get("/health").status_code == 200  # ruta pública
        _login_as_teacher(client)
        assert client.get("/courses").status_code == 200
        assert client.post("/auth/logout").status_code in (200, 204)
        assert client.get("/courses").status_code == 401


# --------------------------------------------------------------------------
# Observabilidad y errores (Integrantes 1 y 4)
# --------------------------------------------------------------------------


class TestObservability:
    def test_every_response_carries_request_id_and_server_timing(self, client: TestClient):
        _login_as_teacher(client)
        response = client.get("/courses", headers={"X-Request-ID": "prueba-carga-01"})
        assert response.headers["x-request-id"] == "prueba-carga-01"
        timing = response.headers["server-timing"]
        assert "total;dur=" in timing and "auth;dur=" in timing and "db;dur=" in timing
        # Un id entrante con caracteres raros no se refleja tal cual.
        weird = client.get("/health", headers={"X-Request-ID": "<script>"})
        assert weird.headers["x-request-id"] != "<script>"

    def test_metrics_endpoint_is_admin_only_and_reports_percentiles(self, client: TestClient):
        _login_as_teacher(client)
        assert client.get("/admin/metrics").status_code == 403
        _login_as_admin(client)
        client.get("/admin/metrics?reset=true")
        for _ in range(3):
            client.get("/courses")
        data = client.get("/admin/metrics").json()
        route = next(item for item in data["routes"] if item["route"] == "GET /courses")
        assert route["requests"] == 3
        assert route["p50_ms"] <= route["p95_ms"] <= route["p99_ms"] <= route["max_ms"]
        assert data["db_pool"]["class"]

    def test_sql_queries_are_attributed_to_the_current_request(self, session_factory):
        install_sql_timing(session_factory.engine)
        metrics = new_request_metrics(None)
        token = current_request.set(metrics)
        try:
            with session_factory() as session:
                session.execute(select(CourseORM.id)).all()
                session.execute(select(StudentORM.id)).all()
        finally:
            current_request.reset(token)
        assert metrics.db_queries == 2

    def test_route_stats_percentiles(self):
        stats = RouteStats(window=100)
        for value in range(1, 101):
            stats.record("GET /x", 200, float(value))
        stats.record("GET /x", 503, 1.0)
        route = stats.snapshot()["routes"][0]
        assert route["requests"] == 101 and route["errors_5xx"] == 1
        assert route["window"] == 100
        assert 45 <= route["p50_ms"] <= 55 and route["p95_ms"] >= 90

    def test_pool_exhaustion_returns_503_instead_of_hanging(self, client: TestClient, monkeypatch):
        _login_as_teacher(client)
        courses = client.app.state.app_context.auth_service

        def exhausted(*args, **kwargs):
            raise PoolTimeoutError("QueuePool limit reached")

        monkeypatch.setattr(courses, "course_ids_for_user", exhausted)
        response = client.get("/courses")
        assert response.status_code == 503
        assert response.headers["retry-after"] == "2"

        monkeypatch.setattr(courses, "user_for_token", exhausted)
        response = client.get("/auth/me")
        assert response.status_code == 503


# --------------------------------------------------------------------------
# Pool de conexiones (Integrante 3, tarea 3.7)
# --------------------------------------------------------------------------


class TestPoolConfiguration:
    def test_sqlite_keeps_previous_behaviour(self):
        assert engine_options("sqlite:///x.db") == {"connect_args": {"check_same_thread": False}}

    def test_postgres_defaults_match_sqlalchemy_sizes_with_safer_timeouts(self, monkeypatch):
        for name in ("DB_POOL_SIZE", "DB_MAX_OVERFLOW", "DB_POOL_TIMEOUT", "DB_POOL_RECYCLE",
                     "DB_STATEMENT_TIMEOUT_MS"):
            monkeypatch.delenv(name, raising=False)
        options = engine_options("postgresql+psycopg://u@h/db")
        assert options == {
            "pool_size": 5, "max_overflow": 10, "pool_timeout": 10,
            "pool_recycle": 1800, "pool_pre_ping": True,
        }

    def test_postgres_options_are_configurable(self, monkeypatch):
        monkeypatch.setenv("DB_POOL_SIZE", "8")
        monkeypatch.setenv("DB_MAX_OVERFLOW", "4")
        monkeypatch.setenv("DB_STATEMENT_TIMEOUT_MS", "15000")
        options = engine_options("postgresql+psycopg://u@h/db")
        assert options["pool_size"] == 8 and options["max_overflow"] == 4
        assert options["connect_args"] == {"options": "-c statement_timeout=15000"}

    def test_invalid_value_fails_loudly(self, monkeypatch):
        monkeypatch.setenv("DB_POOL_SIZE", "muchos")
        with pytest.raises(ValueError, match="DB_POOL_SIZE"):
            engine_options("postgresql+psycopg://u@h/db")
