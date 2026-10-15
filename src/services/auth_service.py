"""Autenticación de cuentas y autorización de cursos asignados."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, List, Optional

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from src.repositories.sqlalchemy.models import (
    AcademicCycleORM,
    AuthSessionORM,
    CourseORM,
    RoleORM,
    StudentORM,
    TeacherCourseORM,
    UserORM,
)

SessionFactory = Callable[[], Session]
SESSION_TTL = timedelta(hours=12)
PASSWORD_ITERATIONS = 310_000
ROLE_ADMIN = "administrador"
ROLE_TEACHER = "docente"
ROLE_STUDENT = "estudiante"
_DUMMY_HASH = "pbkdf2_sha256$310000$AAAAAAAAAAAAAAAAAAAAAA==$AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="


@dataclass(frozen=True)
class AuthenticatedUser:
    id: int
    username: str
    full_name: str
    role: str
    must_change_password: bool


def hash_password(password: str) -> str:
    if len(password) < 12:
        raise ValueError("La contraseña debe tener al menos 12 caracteres.")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS
    )
    return "pbkdf2_sha256${}${}${}".format(
        PASSWORD_ITERATIONS,
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(digest).decode("ascii"),
    )


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations_raw, salt_raw, digest_raw = encoded.split("$")
        iterations = int(iterations_raw)
        salt = base64.b64decode(salt_raw, validate=True)
        expected = base64.b64decode(digest_raw, validate=True)
        if algorithm != "pbkdf2_sha256" or not 100_000 <= iterations <= 1_000_000:
            return False
    except (ValueError, TypeError):
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual, expected)


class AuthService:
    def __init__(self, session_factory: SessionFactory):
        self._session_factory = session_factory

    def login(self, username: str, password: str) -> tuple[str, AuthenticatedUser] | None:
        with self._session_factory() as session:
            row = session.execute(
                select(UserORM)
                .join(RoleORM)
                .where(UserORM.username == username, UserORM.active.is_(True))
            ).scalar_one_or_none()
            if row is None:
                row = session.execute(
                    select(UserORM)
                    .join(RoleORM)
                    .where(
                        func.lower(UserORM.email) == username.lower(),
                        UserORM.active.is_(True),
                    )
                ).scalar_one_or_none()
            if row is None:
                verify_password(password, _DUMMY_HASH)
                return None
            if not verify_password(password, row.password_hash):
                return None

            token = secrets.token_urlsafe(32)
            session.add(
                AuthSessionORM(
                    token_hash=self._hash_token(token),
                    user_id=row.id,
                    expires_at=datetime.now(timezone.utc) + SESSION_TTL,
                )
            )
            session.commit()
            return token, self._to_user(row)

    def create_teacher(
        self,
        username: str,
        full_name: str,
        email: str,
        phone_number: Optional[str],
        course_ids: List[int],
    ) -> tuple[dict, str]:
        username = username.strip()
        full_name = " ".join(full_name.split())
        email = email.strip()
        if not username or not full_name or not email:
            raise ValueError("Usuario, nombre y correo son obligatorios.")
        if not course_ids:
            raise ValueError("Asigna al menos un curso al docente.")

        temporary_password = secrets.token_urlsafe(18)
        with self._session_factory() as session:
            if session.execute(
                select(UserORM.id).where(UserORM.username == username)
            ).scalar_one_or_none() is not None:
                raise ValueError("Ese nombre de usuario ya está registrado.")
            if session.execute(
                select(UserORM.id).where(func.lower(UserORM.email) == email.lower())
            ).scalar_one_or_none() is not None:
                raise ValueError("Ese correo ya está asociado a una cuenta.")
            self._validate_course_ids(session, course_ids)
            teacher_role_id = session.execute(
                select(RoleORM.id).where(RoleORM.name == ROLE_TEACHER)
            ).scalar_one()
            teacher = UserORM(
                username=username,
                full_name=full_name,
                email=email,
                phone_number=phone_number.strip() if phone_number and phone_number.strip() else None,
                password_hash=hash_password(temporary_password),
                must_change_password=True,
                role_id=teacher_role_id,
            )
            teacher.course_assignments = [
                TeacherCourseORM(course_id=course_id) for course_id in course_ids
            ]
            session.add(teacher)
            session.commit()
            return self._teacher_response(teacher), temporary_password

    def create_student(self, username: str, full_name: str, email: str) -> tuple[dict, str]:
        username = username.strip()
        full_name = " ".join(full_name.split())
        email = email.strip().lower()
        if not username or not full_name or not email:
            raise ValueError("Código, nombre y correo son obligatorios.")
        temporary_password = secrets.token_urlsafe(18)
        with self._session_factory() as session:
            if session.execute(
                select(UserORM.id).where(UserORM.username == username)
            ).scalar_one_or_none() is not None:
                raise ValueError("Ese código ya está asociado a una cuenta.")
            if session.execute(
                select(UserORM.id).where(func.lower(UserORM.email) == email)
            ).scalar_one_or_none() is not None:
                raise ValueError("Ese correo ya está asociado a una cuenta.")
            student_role_id = session.execute(
                select(RoleORM.id).where(RoleORM.name == ROLE_STUDENT)
            ).scalar_one()
            student = UserORM(
                username=username,
                full_name=full_name,
                email=email,
                password_hash=hash_password(temporary_password),
                must_change_password=True,
                role_id=student_role_id,
            )
            session.add(student)
            session.flush()
            session.execute(
                update(StudentORM)
                .where(func.lower(StudentORM.email) == email)
                .values(user_id=student.id)
            )
            session.commit()
            return self._student_response(session, student), temporary_password

    def reset_student_password(self, student_id: int) -> str:
        temporary_password = secrets.token_urlsafe(18)
        with self._session_factory() as session:
            student = session.execute(
                select(UserORM)
                .join(RoleORM)
                .where(
                    UserORM.id == student_id,
                    RoleORM.name == ROLE_STUDENT,
                    UserORM.active.is_(True),
                )
            ).scalar_one_or_none()
            if student is None:
                raise LookupError(f"Estudiante {student_id} no encontrado.")
            student.password_hash = hash_password(temporary_password)
            student.must_change_password = True
            session.execute(delete(AuthSessionORM).where(AuthSessionORM.user_id == student_id))
            session.commit()
        return temporary_password

    def students(self) -> list[dict]:
        with self._session_factory() as session:
            students = session.execute(
                select(UserORM).join(RoleORM).where(
                    RoleORM.name == ROLE_STUDENT, UserORM.active.is_(True)
                ).order_by(UserORM.full_name, UserORM.id)
            ).scalars().all()
            result = []
            for student in students:
                course_ids = session.execute(
                    select(StudentORM.course_id)
                    .where(StudentORM.user_id == student.id, StudentORM.active.is_(True))
                    .distinct()
                    .order_by(StudentORM.course_id)
                ).scalars().all()
                result.append({
                    "id": student.id,
                    "username": student.username,
                    "full_name": student.full_name,
                    "email": student.email,
                    "role": ROLE_STUDENT,
                    "course_ids": list(course_ids),
                })
            return result

    def student_courses(self, student_id: int) -> list[dict]:
        with self._session_factory() as session:
            rows = session.execute(
                select(CourseORM, AcademicCycleORM)
                .join(StudentORM, StudentORM.course_id == CourseORM.id)
                .outerjoin(AcademicCycleORM, AcademicCycleORM.id == CourseORM.cycle_id)
                .where(
                    StudentORM.user_id == student_id,
                    StudentORM.active.is_(True),
                    CourseORM.cycle_id.is_not(None),
                )
                .distinct()
                .order_by(AcademicCycleORM.id, CourseORM.name, CourseORM.id)
            ).all()
            return [
                {
                    "course_id": course.id,
                    "course_name": course.name,
                    "cycle_id": cycle.id if cycle else None,
                    "cycle_name": cycle.name if cycle else None,
                    "cycle_starts_on": cycle.starts_on if cycle else None,
                }
                for course, cycle in rows
            ]

    def reset_teacher_password(self, teacher_id: int) -> str:
        temporary_password = secrets.token_urlsafe(18)
        with self._session_factory() as session:
            teacher = session.execute(
                select(UserORM)
                .join(RoleORM)
                .where(
                    UserORM.id == teacher_id,
                    RoleORM.name == ROLE_TEACHER,
                    UserORM.active.is_(True),
                )
            ).scalar_one_or_none()
            if teacher is None:
                raise LookupError(f"Docente {teacher_id} no encontrado.")
            teacher.password_hash = hash_password(temporary_password)
            teacher.must_change_password = True
            session.execute(
                delete(AuthSessionORM).where(AuthSessionORM.user_id == teacher_id)
            )
            session.commit()
            return temporary_password

    def change_password(
        self, user_id: int, new_password: str, session_token: Optional[str]
    ) -> AuthenticatedUser:
        password_hash = hash_password(new_password)
        with self._session_factory() as session:
            user = session.get(UserORM, user_id)
            if user is None or not user.active:
                raise LookupError("La cuenta no existe o está inactiva.")
            user.password_hash = password_hash
            user.must_change_password = False
            if session_token:
                current_token_hash = self._hash_token(session_token)
                session.execute(
                    delete(AuthSessionORM).where(
                        AuthSessionORM.user_id == user_id,
                        AuthSessionORM.token_hash != current_token_hash,
                    )
                )
            session.commit()
            return self._to_user(user)

    def user_for_token(self, token: Optional[str]) -> Optional[AuthenticatedUser]:
        if not token:
            return None
        with self._session_factory() as session:
            record = session.execute(
                select(AuthSessionORM)
                .where(
                    AuthSessionORM.token_hash == self._hash_token(token),
                    AuthSessionORM.expires_at > datetime.now(timezone.utc),
                )
            ).scalar_one_or_none()
            if record is None or not record.user.active:
                return None
            return self._to_user(record.user)

    def logout(self, token: Optional[str]) -> None:
        if not token:
            return
        with self._session_factory() as session:
            session.execute(
                delete(AuthSessionORM).where(
                    AuthSessionORM.token_hash == self._hash_token(token)
                )
            )
            session.commit()

    def has_course_access(self, user: AuthenticatedUser, course_id: int) -> bool:
        if user.role == ROLE_ADMIN:
            return True
        with self._session_factory() as session:
            if user.role == ROLE_STUDENT:
                return session.execute(
                    select(StudentORM.id).where(
                        StudentORM.user_id == user.id,
                        StudentORM.course_id == course_id,
                        StudentORM.active.is_(True),
                    )
                ).scalar_one_or_none() is not None
            return session.execute(
                select(TeacherCourseORM.teacher_id).where(
                    TeacherCourseORM.teacher_id == user.id,
                    TeacherCourseORM.course_id == course_id,
                )
            ).scalar_one_or_none() is not None

    def course_ids_for_user(self, user: AuthenticatedUser) -> List[int]:
        with self._session_factory() as session:
            query = select(CourseORM.id).order_by(CourseORM.id)
            if user.role == ROLE_STUDENT:
                query = (
                    select(StudentORM.course_id)
                    .where(StudentORM.user_id == user.id, StudentORM.active.is_(True))
                    .distinct()
                    .order_by(StudentORM.course_id)
                )
            elif user.role != ROLE_ADMIN:
                query = query.join(TeacherCourseORM).where(
                    TeacherCourseORM.teacher_id == user.id
                )
            return list(session.execute(query).scalars().all())

    def cycle_ids_for_user(self, user: AuthenticatedUser) -> List[int]:
        with self._session_factory() as session:
            query = select(AcademicCycleORM.id).join(CourseORM).distinct().order_by(
                AcademicCycleORM.id
            )
            if user.role == ROLE_STUDENT:
                query = (
                    select(AcademicCycleORM.id)
                    .join(CourseORM)
                    .join(StudentORM, StudentORM.course_id == CourseORM.id)
                    .where(StudentORM.user_id == user.id, StudentORM.active.is_(True))
                    .distinct()
                    .order_by(AcademicCycleORM.id)
                )
            elif user.role != ROLE_ADMIN:
                query = query.join(TeacherCourseORM).where(
                    TeacherCourseORM.teacher_id == user.id
                )
            return list(session.execute(query).scalars().all())

    def teachers(self) -> list[dict]:
        with self._session_factory() as session:
            teachers = session.execute(
                select(UserORM).join(RoleORM).where(
                    RoleORM.name == ROLE_TEACHER, UserORM.active.is_(True)
                ).order_by(UserORM.full_name, UserORM.id)
            ).scalars().all()
            result = []
            for teacher in teachers:
                course_ids = session.execute(
                    select(TeacherCourseORM.course_id)
                    .where(TeacherCourseORM.teacher_id == teacher.id)
                    .order_by(TeacherCourseORM.course_id)
                ).scalars().all()
                result.append({
                    "id": teacher.id,
                    "username": teacher.username,
                    "full_name": teacher.full_name,
                    "phone_number": teacher.phone_number,
                    "email": teacher.email,
                    "role": ROLE_TEACHER,
                    "course_ids": list(course_ids),
                })
            return result

    def assign_courses(self, teacher_id: int, course_ids: List[int]) -> bool:
        with self._session_factory() as session:
            teacher = session.execute(
                select(UserORM)
                .join(RoleORM)
                .where(
                    UserORM.id == teacher_id,
                    RoleORM.name == ROLE_TEACHER,
                    UserORM.active.is_(True),
                )
            ).scalar_one_or_none()
            if teacher is None:
                return False
            self._validate_course_ids(session, course_ids)
            session.execute(
                delete(TeacherCourseORM).where(TeacherCourseORM.teacher_id == teacher_id)
            )
            session.add_all(
                TeacherCourseORM(teacher_id=teacher_id, course_id=course_id)
                for course_id in course_ids
            )
            session.commit()
            return True

    @staticmethod
    def _validate_course_ids(session: Session, course_ids: List[int]) -> None:
        existing_ids = set(
            session.execute(select(CourseORM.id).where(CourseORM.id.in_(course_ids)))
            .scalars().all()
        ) if course_ids else set()
        if existing_ids != set(course_ids):
            raise ValueError("Uno o más cursos no existen.")

    @staticmethod
    def _teacher_response(teacher: UserORM) -> dict:
        return {
            "id": teacher.id,
            "username": teacher.username,
            "full_name": teacher.full_name,
            "phone_number": teacher.phone_number,
            "email": teacher.email,
            "role": ROLE_TEACHER,
            "course_ids": sorted(assignment.course_id for assignment in teacher.course_assignments),
        }

    @staticmethod
    def _student_response(session: Session, student: UserORM) -> dict:
        course_ids = session.execute(
            select(StudentORM.course_id)
            .where(StudentORM.user_id == student.id, StudentORM.active.is_(True))
            .distinct()
            .order_by(StudentORM.course_id)
        ).scalars().all()
        return {
            "id": student.id,
            "username": student.username,
            "full_name": student.full_name,
            "email": student.email,
            "role": ROLE_STUDENT,
            "course_ids": list(course_ids),
        }

    @staticmethod
    def _hash_token(token: str) -> str:
        return hashlib.sha256(token.encode("ascii")).hexdigest()

    @staticmethod
    def _to_user(row: UserORM) -> AuthenticatedUser:
        return AuthenticatedUser(
            id=row.id,
            username=row.username,
            full_name=row.full_name,
            role=row.role.name,
            must_change_password=row.must_change_password,
        )
