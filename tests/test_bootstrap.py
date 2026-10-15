import pytest
from sqlalchemy import select

from src.repositories.sqlalchemy.models import RoleORM, UserORM
from src.services.bootstrap import build_app_context


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
