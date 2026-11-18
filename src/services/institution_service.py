"""Estructura institucional: universidades, facultades y especialidades.

Historias cubiertas:

* HU-A5 — el administrador registra, modifica, deshabilita y elimina
  universidades.
* HU-A6 — ídem para las facultades de cada universidad.
* HU-A7 — ídem para las especialidades de cada facultad.
* HU-C2 — el docente elige universidad → facultad → especialidad (selección
  encadenada) y solo se le ofrecen elementos habilitados.

Reglas comunes de las tres entidades (criterios de aceptación del backlog):

* Cada una tiene estado habilitado / deshabilitado. Deshabilitar la da de
  baja sin borrarla: los datos ya registrados siguen disponibles, pero no se
  ofrece en selecciones nuevas.
* La eliminación definitiva solo procede si no tiene datos asociados
  (universidad sin facultades, facultad sin especialidades, especialidad sin
  ciclos académicos); en otro caso debe deshabilitarse.
* El nombre es único dentro de su padre (dos universidades pueden tener una
  "Facultad de Ciencias").

Igual que `AuthService`, este servicio trabaja directamente con la sesión de
SQLAlchemy: es configuración administrativa sin lógica que deba probarse con
el repositorio in-memory de la simulación.
"""

from __future__ import annotations

from typing import Callable, Dict, Iterable, List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.repositories.sqlalchemy.models import (
    AcademicCycleORM,
    FacultyORM,
    SpecialtyORM,
    UniversityORM,
)

SessionFactory = Callable[[], Session]


class InstitutionNotFoundError(LookupError):
    """La universidad, facultad o especialidad no existe."""


class DuplicateInstitutionError(ValueError):
    """Ya existe un elemento con ese nombre dentro del mismo padre."""


class InstitutionInUseError(ValueError):
    """Tiene datos asociados: debe deshabilitarse en vez de eliminarse."""


class InstitutionDisabledError(ValueError):
    """El elemento (o uno de sus padres) está deshabilitado."""


def _clean_name(name: Optional[str]) -> Optional[str]:
    if name is None:
        return None
    cleaned = " ".join(name.split())
    if not cleaned:
        raise ValueError("El nombre no puede quedar vacío.")
    if len(cleaned) > 255:
        raise ValueError("El nombre no puede superar los 255 caracteres.")
    return cleaned


class InstitutionService:
    def __init__(self, session_factory: SessionFactory):
        self._session_factory = session_factory

    # ------------------------------------------------------------------
    # Consulta
    # ------------------------------------------------------------------

    def tree(self, include_disabled: bool = True) -> List[dict]:
        """Universidades con sus facultades y especialidades.

        Con `include_disabled=False` (vista del docente, HU-C2) se omiten los
        elementos deshabilitados y todo lo que cuelga de ellos.
        """
        with self._session_factory() as session:
            universities = session.execute(
                select(UniversityORM).order_by(func.lower(UniversityORM.name), UniversityORM.id)
            ).scalars().all()
            faculties = session.execute(
                select(FacultyORM).order_by(func.lower(FacultyORM.name), FacultyORM.id)
            ).scalars().all()
            specialties = session.execute(
                select(SpecialtyORM).order_by(func.lower(SpecialtyORM.name), SpecialtyORM.id)
            ).scalars().all()
            cycle_counts = dict(session.execute(
                select(AcademicCycleORM.specialty_id, func.count(AcademicCycleORM.id))
                .where(AcademicCycleORM.specialty_id.is_not(None))
                .group_by(AcademicCycleORM.specialty_id)
            ).all())

        specialties_by_faculty: Dict[int, List[dict]] = {}
        for specialty in specialties:
            if not include_disabled and not specialty.enabled:
                continue
            specialties_by_faculty.setdefault(specialty.faculty_id, []).append({
                "id": specialty.id,
                "faculty_id": specialty.faculty_id,
                "name": specialty.name,
                "enabled": bool(specialty.enabled),
                "cycle_count": int(cycle_counts.get(specialty.id, 0)),
            })
        faculties_by_university: Dict[int, List[dict]] = {}
        for faculty in faculties:
            if not include_disabled and not faculty.enabled:
                continue
            children = specialties_by_faculty.get(faculty.id, [])
            faculties_by_university.setdefault(faculty.university_id, []).append({
                "id": faculty.id,
                "university_id": faculty.university_id,
                "name": faculty.name,
                "enabled": bool(faculty.enabled),
                "specialties": children,
            })
        result = []
        for university in universities:
            if not include_disabled and not university.enabled:
                continue
            result.append({
                "id": university.id,
                "name": university.name,
                "enabled": bool(university.enabled),
                "faculties": faculties_by_university.get(university.id, []),
            })
        return result

    def specialty_contexts(self, specialty_ids: Iterable[int]) -> Dict[int, dict]:
        """Nombre completo del contexto de cada especialidad, para mostrarlo
        junto a los ciclos ("UNI · FIIS · Ingeniería de Sistemas")."""
        ids = sorted({specialty_id for specialty_id in specialty_ids if specialty_id})
        if not ids:
            return {}
        with self._session_factory() as session:
            rows = session.execute(
                select(SpecialtyORM, FacultyORM, UniversityORM)
                .join(FacultyORM, FacultyORM.id == SpecialtyORM.faculty_id)
                .join(UniversityORM, UniversityORM.id == FacultyORM.university_id)
                .where(SpecialtyORM.id.in_(ids))
            ).all()
        return {
            specialty.id: {
                "university_id": university.id,
                "university_name": university.name,
                "faculty_id": faculty.id,
                "faculty_name": faculty.name,
                "specialty_id": specialty.id,
                "specialty_name": specialty.name,
                "enabled": bool(university.enabled and faculty.enabled and specialty.enabled),
            }
            for specialty, faculty, university in rows
        }

    def require_selectable_specialty(self, specialty_id: int) -> dict:
        """HU-C2: la especialidad debe existir y estar habilitada junto con su
        facultad y su universidad para usarse en un ciclo nuevo."""
        context = self.specialty_contexts([specialty_id]).get(specialty_id)
        if context is None:
            raise InstitutionNotFoundError(f"Especialidad {specialty_id} no encontrada.")
        if not context["enabled"]:
            raise InstitutionDisabledError(
                "La especialidad seleccionada (o su facultad o universidad) está "
                "deshabilitada y no se ofrece para registros nuevos."
            )
        return context

    # ------------------------------------------------------------------
    # HU-A5 — Universidades
    # ------------------------------------------------------------------

    def create_university(self, name: str) -> dict:
        name = _clean_name(name)
        with self._session_factory() as session:
            self._ensure_unique(session, UniversityORM, name)
            row = UniversityORM(name=name, enabled=True)
            session.add(row)
            session.commit()
            return self._university_dict(session, row)

    def update_university(
        self, university_id: int, name: Optional[str] = None, enabled: Optional[bool] = None
    ) -> dict:
        name = _clean_name(name)
        with self._session_factory() as session:
            row = self._get(session, UniversityORM, university_id, "Universidad")
            if name is not None and name != row.name:
                self._ensure_unique(session, UniversityORM, name, exclude_id=row.id)
                row.name = name
            if enabled is not None:
                row.enabled = enabled
            session.commit()
            return self._university_dict(session, row)

    def delete_university(self, university_id: int) -> None:
        with self._session_factory() as session:
            row = self._get(session, UniversityORM, university_id, "Universidad")
            if self._count(session, FacultyORM, FacultyORM.university_id == row.id):
                raise InstitutionInUseError(
                    "La universidad tiene facultades registradas: deshabilítala para "
                    "conservar su histórico."
                )
            session.delete(row)
            session.commit()

    # ------------------------------------------------------------------
    # HU-A6 — Facultades
    # ------------------------------------------------------------------

    def create_faculty(self, university_id: int, name: str) -> dict:
        name = _clean_name(name)
        with self._session_factory() as session:
            university = self._get(session, UniversityORM, university_id, "Universidad")
            if not university.enabled:
                raise InstitutionDisabledError(
                    f"La universidad “{university.name}” está deshabilitada y no admite "
                    "facultades nuevas."
                )
            self._ensure_unique(
                session, FacultyORM, name, parent=FacultyORM.university_id == university.id
            )
            row = FacultyORM(university_id=university.id, name=name, enabled=True)
            session.add(row)
            session.commit()
            return self._faculty_dict(session, row)

    def update_faculty(
        self, faculty_id: int, name: Optional[str] = None, enabled: Optional[bool] = None
    ) -> dict:
        name = _clean_name(name)
        with self._session_factory() as session:
            row = self._get(session, FacultyORM, faculty_id, "Facultad")
            if name is not None and name != row.name:
                self._ensure_unique(
                    session, FacultyORM, name,
                    parent=FacultyORM.university_id == row.university_id,
                    exclude_id=row.id,
                )
                row.name = name
            if enabled is not None:
                row.enabled = enabled
            session.commit()
            return self._faculty_dict(session, row)

    def delete_faculty(self, faculty_id: int) -> None:
        with self._session_factory() as session:
            row = self._get(session, FacultyORM, faculty_id, "Facultad")
            if self._count(session, SpecialtyORM, SpecialtyORM.faculty_id == row.id):
                raise InstitutionInUseError(
                    "La facultad tiene especialidades registradas: deshabilítala para "
                    "conservar su histórico."
                )
            session.delete(row)
            session.commit()

    # ------------------------------------------------------------------
    # HU-A7 — Especialidades
    # ------------------------------------------------------------------

    def create_specialty(self, faculty_id: int, name: str) -> dict:
        name = _clean_name(name)
        with self._session_factory() as session:
            faculty = self._get(session, FacultyORM, faculty_id, "Facultad")
            if not faculty.enabled:
                raise InstitutionDisabledError(
                    f"La facultad “{faculty.name}” está deshabilitada y no admite "
                    "especialidades nuevas."
                )
            self._ensure_unique(
                session, SpecialtyORM, name, parent=SpecialtyORM.faculty_id == faculty.id
            )
            row = SpecialtyORM(faculty_id=faculty.id, name=name, enabled=True)
            session.add(row)
            session.commit()
            return self._specialty_dict(session, row)

    def update_specialty(
        self, specialty_id: int, name: Optional[str] = None, enabled: Optional[bool] = None
    ) -> dict:
        name = _clean_name(name)
        with self._session_factory() as session:
            row = self._get(session, SpecialtyORM, specialty_id, "Especialidad")
            if name is not None and name != row.name:
                self._ensure_unique(
                    session, SpecialtyORM, name,
                    parent=SpecialtyORM.faculty_id == row.faculty_id,
                    exclude_id=row.id,
                )
                row.name = name
            if enabled is not None:
                row.enabled = enabled
            session.commit()
            return self._specialty_dict(session, row)

    def delete_specialty(self, specialty_id: int) -> None:
        with self._session_factory() as session:
            row = self._get(session, SpecialtyORM, specialty_id, "Especialidad")
            if self._count(session, AcademicCycleORM, AcademicCycleORM.specialty_id == row.id):
                raise InstitutionInUseError(
                    "La especialidad tiene ciclos académicos registrados: deshabilítala "
                    "para conservar su histórico."
                )
            session.delete(row)
            session.commit()

    # ------------------------------------------------------------------
    # Auxiliares
    # ------------------------------------------------------------------

    @staticmethod
    def _get(session: Session, model, item_id: int, label: str):
        row = session.get(model, item_id)
        if row is None:
            raise InstitutionNotFoundError(f"{label} {item_id} no encontrada.")
        return row

    @staticmethod
    def _count(session: Session, model, condition) -> int:
        return int(session.execute(
            select(func.count()).select_from(model).where(condition)
        ).scalar_one())

    @staticmethod
    def _ensure_unique(session: Session, model, name: str, parent=None, exclude_id=None) -> None:
        query = select(model.id).where(func.lower(model.name) == name.lower())
        if parent is not None:
            query = query.where(parent)
        if exclude_id is not None:
            query = query.where(model.id != exclude_id)
        if session.execute(query.limit(1)).scalar_one_or_none() is not None:
            raise DuplicateInstitutionError(f"Ya existe “{name}” en este nivel.")

    def _university_dict(self, session: Session, row: UniversityORM) -> dict:
        return {
            "id": row.id,
            "name": row.name,
            "enabled": bool(row.enabled),
            "faculties": [],
        }

    def _faculty_dict(self, session: Session, row: FacultyORM) -> dict:
        return {
            "id": row.id,
            "university_id": row.university_id,
            "name": row.name,
            "enabled": bool(row.enabled),
            "specialties": [],
        }

    def _specialty_dict(self, session: Session, row: SpecialtyORM) -> dict:
        return {
            "id": row.id,
            "faculty_id": row.faculty_id,
            "name": row.name,
            "enabled": bool(row.enabled),
            "cycle_count": self._count(
                session, AcademicCycleORM, AcademicCycleORM.specialty_id == row.id
            ),
        }
