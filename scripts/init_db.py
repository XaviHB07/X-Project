#!/usr/bin/env python3
"""Crea el esquema de base de datos de producción (todas las tablas).

Uso:
    python scripts/init_db.py
    python scripts/init_db.py --config config/default.yaml

Nota importante (leer antes de usar esto en un entorno real): este
script usa `Base.metadata.create_all(...)`, que crea las tablas que
falten pero NO sabe migrar cambios de esquema sobre una base de datos que
ya tiene datos (por ejemplo, agregar una columna nueva a una tabla
existente). Es perfecto para arrancar en desarrollo/demo. Para un
despliegue real donde el esquema va a evolucionar con el tiempo, la
recomendación estándar es introducir Alembic (la herramienta de
migraciones de SQLAlchemy) -- se deja como el siguiente paso natural,
documentado en el README, sección "De aquí a producción real".
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.services.bootstrap import DEFAULT_CONFIG_PATH, build_app_context  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    ctx = build_app_context(config_path=args.config, create_tables=True)
    print(f"Base de datos inicializada en: {ctx.config.database_url}")
    print("Tablas creadas (o ya existentes): courses, students, student_state, "
          "class_sessions, syllabus_entries, session_attendance, decision_runs, selection_events.")


if __name__ == "__main__":
    main()
