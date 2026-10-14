"""Verifica que el esquema y las consultas funcionan contra PostgreSQL de verdad.

POR QUE ESTE SCRIPT EXISTE

Todos los tests del proyecto corren sobre SQLite. Eso esta bien para
despues-rapido, pero deja un agujero: el despliegue real en Render usa
PostgreSQL, y hay diferencias que solo aparecen al ejecutar contra el.

Los tres casos concretos que este script cubre, y por que importan:

1. **Indices parciales.** Definimos `ix_participations_sesion` con
   `postgresql_where="anulada = false"` y `sqlite_where="anulada = 0"`. Si la
   sintaxis estuviera cruzada, PostgreSQL rechaza el `CREATE TABLE` y el
   despliegue muere en el arranque, con un error de esquema que no aparece en
   ningun test local.

2. **DateTime con timezone.** `DateTime(timezone=True)` en PostgreSQL devuelve
   datetimes CON tzinfo; SQLite devuelve naive (o None si la fila se inserto a
   mano). Un `asked_at` naive en Postgres hace fallar cualquier operacion que
   lo compare con `datetime.now(timezone.utc)`.

3. **Booleanos.** PostgreSQL tiene un tipo `boolean` real; SQLite guarda 0/1.
   Un filtro escrito para un motor puede no filtrar en el otro.

COMO EJECUTARLO

  Docker (la forma mas simple, si tenes Docker):
      docker run -d -p 5432:5432 -e POSTGRES_PASSWORD=test postgres:16
      $env:TEST_DATABASE_URL="postgresql+psycopg://postgres:test@localhost:5432/postgres"
      python scripts/check_postgres.py

  Contra el Postgres de Render (despues del primer deploy, desde Render Shell
  o desde tu maquina apuntando a la cadena interna):
      $env:TEST_DATABASE_URL="<la Internal Database URL>"
      python scripts/check_postgres.py

  Sin ninguna de las dos: sale con codigo 2 y explica como configurarlo. No
  falla de forma silenciosa, porque un "OK" sin haber probado nada seria peor
  que un "no se pudo comprobar".
"""
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))


def main() -> int:
    url = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")

    if not url or not url.startswith("postgresql"):
        print("No hay una URL de PostgreSQL para comprobar.")
        print()
        print("Como ejecutar esto:")
        print("  docker run -d -p 5432:5432 -e POSTGRES_PASSWORD=test postgres:16")
        print('  $env:TEST_DATABASE_URL="postgresql+psycopg://postgres:test@localhost:5432/postgres"')
        print("  python scripts/check_postgres.py")
        print()
        print("Sin esto no se afirma nada sobre PostgreSQL: solo sobre SQLite,")
        print("que es lo que cubren los tests del proyecto.")
        return 2

    os.environ["DATABASE_URL"] = url

    from sqlalchemy import create_engine, inspect, text

    from src.repositories.sqlalchemy.models import Base

    engine = create_engine(url, future=True)
    fallos: list[str] = []

    def paso(n: int, titulo: str) -> None:
        print(f"{n}. {titulo}")

    def comprobar(ok: bool, mensaje: str) -> None:
        print(("   OK   " if ok else "   FALLO") + " " + mensaje)
        if not ok:
            fallos.append(mensaje)

    paso(1, "Creando el esquema")
    Base.metadata.create_all(engine)
    insp = inspect(engine)
    tablas = sorted(insp.get_table_names())
    print("   tablas:", ", ".join(tablas))
    comprobar("participations" in tablas, "existe la tabla participations")

    paso(2, "Índices de participations")
    for ix in insp.get_indexes("participations"):
        print(f"   {ix['name']}: {ix['column_names']}")

    paso(3, "Insertar y leer una participación")
    with engine.begin() as c:
        curso_id = c.execute(
            text("INSERT INTO courses (name, created_at) VALUES ('Test', NOW()) RETURNING id")
        ).scalar_one()
        est_id = c.execute(
            text("INSERT INTO students (course_id, external_ref, display_name, "
                 "created_at, active) VALUES (:c,'A1','Ana',NOW(),true) RETURNING id"),
            {"c": curso_id},
        ).scalar_one()
        ses_id = c.execute(
            text("INSERT INTO class_sessions (course_id, created_at) VALUES (:c,NOW()) "
                 "RETURNING id"),
            {"c": curso_id},
        ).scalar_one()
        pid = c.execute(
            text("INSERT INTO participations (class_session_id, student_id, question, "
                 "asked_at, present, anulada) VALUES (:s,:e,:q,:t,true,false) RETURNING id"),
            {"s": ses_id, "e": est_id, "q": "¿Qué es liderazgo?",
             "t": datetime.now(timezone.utc)},
        ).scalar_one()
    print(f"   participación #{pid} insertada")
    comprobar(pid is not None, "INSERT funciona")

    paso(4, "Filtro de no anuladas (el que usa el historial)")
    with engine.begin() as c:
        visibles = c.execute(
            text("SELECT COUNT(*) FROM participations WHERE anulada = false")
        ).scalar_one()
    comprobar(visibles == 1, f"filtra correctamente (visibles={visibles}, esperado 1)")

    paso(5, "Anulación lógica")
    with engine.begin() as c:
        c.execute(
            text("UPDATE participations SET anulada=true, motivo_anulacion='prueba' WHERE id=:i"),
            {"i": pid},
        )
        visibles = c.execute(
            text("SELECT COUNT(*) FROM participations WHERE anulada = false")
        ).scalar_one()
        total = c.execute(text("SELECT COUNT(*) FROM participations")).scalar_one()
    comprobar(visibles == 0, "la anulada sale del historial")
    comprobar(total == 1, "pero la fila sigue en la base")

    paso(6, "DateTime con timezone")
    with engine.begin() as c:
        t = c.execute(text("SELECT asked_at FROM participations LIMIT 1")).scalar_one()
    comprobar(t.tzinfo is not None,
               f"asked_at vuelve con tzinfo (viene {t!r})")

    paso(7, "Limpieza")
    with engine.begin() as c:
        c.execute(text("DELETE FROM participations"))
        c.execute(text("DELETE FROM class_sessions"))
        c.execute(text("DELETE FROM students"))
        c.execute(text("DELETE FROM courses"))
    print("   datos de prueba borrados")

    print()
    if fallos:
        print(f"FALLARON {len(fallos)} comprobaciones:")
        for f in fallos:
            print(f"  - {f}")
        return 1

    print("OK: el esquema y las consultas funcionan contra PostgreSQL.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
