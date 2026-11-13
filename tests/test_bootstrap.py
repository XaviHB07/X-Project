import sqlite3

import pytest
from sqlalchemy import create_engine, inspect, select, text

from src.repositories.sqlalchemy.models import RoleORM, UserORM
from src.services.bootstrap import build_app_context, _migrate_review_request_targets


def test_bootstrap_provisions_initial_admin_once(monkeypatch, tmp_path):
    db_path = tmp_path / "bootstrap.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("ADMIN_USERNAME", "initial-admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "initial-admin-password-123")

    first_context = build_app_context()
    login = first_context.auth_service.login(
        "initial-admin", "initial-admin-password-123"
    )
    assert login is not None

    monkeypatch.setenv("ADMIN_PASSWORD", "replacement-password-456")
    second_context = build_app_context()
    assert second_context.auth_service.login(
        "initial-admin", "initial-admin-password-123"
    ) is not None
    assert second_context.auth_service.login(
        "initial-admin", "replacement-password-456"
    ) is None

    with second_context.auth_service._session_factory() as session:
        admins = session.execute(
            select(UserORM).join(RoleORM).where(RoleORM.name == "administrador")
        ).scalars().all()
    assert [user.username for user in admins] == ["initial-admin"]


def test_bootstrap_requires_both_admin_environment_variables(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'partial.db'}")
    monkeypatch.setenv("ADMIN_USERNAME", "initial-admin")
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)

    with pytest.raises(RuntimeError, match="deben configurarse juntos"):
        build_app_context()


def test_bootstrap_rejects_short_initial_admin_password(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'short.db'}")
    monkeypatch.setenv("ADMIN_USERNAME", "initial-admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "too-short")

    with pytest.raises(ValueError, match="al menos 12 caracteres"):
        build_app_context()


def test_review_request_migration_preserves_existing_participation_requests(tmp_path):
    db_path = tmp_path / "old-review-requests.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE courses (id INTEGER PRIMARY KEY);
        CREATE TABLE users (id INTEGER PRIMARY KEY);
        CREATE TABLE student_participations (id INTEGER PRIMARY KEY);
        CREATE TABLE student_evaluation_results (id INTEGER PRIMARY KEY);
        CREATE TABLE student_review_requests (
            id INTEGER PRIMARY KEY,
            participation_id INTEGER NOT NULL REFERENCES student_participations(id),
            student_user_id INTEGER NOT NULL REFERENCES users(id),
            course_id INTEGER NOT NULL REFERENCES courses(id),
            reason TEXT NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'pending',
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL
        );
        INSERT INTO courses (id) VALUES (7);
        INSERT INTO users (id) VALUES (9);
        INSERT INTO student_participations (id) VALUES (11);
        INSERT INTO student_review_requests
            (id, participation_id, student_user_id, course_id, reason, status, created_at, updated_at)
        VALUES
            (13, 11, 9, 7, 'Conservar esta solicitud', 'in_review', '2026-11-12', '2026-11-12');
        """
    )
    conn.commit()
    conn.close()

    engine = create_engine(f"sqlite:///{db_path}")
    _migrate_review_request_targets(engine)
    columns = {column["name"]: column for column in inspect(engine).get_columns("student_review_requests")}
    assert columns["participation_id"]["nullable"] is True
    assert columns["evaluation_result_id"]["nullable"] is True
    with engine.connect() as connection:
        row = connection.execute(text(
            "SELECT id, participation_id, evaluation_result_id, reason, status "
            "FROM student_review_requests"
        )).one()
    assert tuple(row) == (13, 11, None, "Conservar esta solicitud", "in_review")
