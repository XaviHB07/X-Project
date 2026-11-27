"""Prueba de carga reproducible de «Cacería en Vivo» (Plan de optimización, Integrante 4).

Simula una clase: 1 docente proyectando el quiz y N estudiantes en sus
celulares. Levanta la API real con uvicorn (un proceso, igual que en
Render), siembra datos ficticios y reproduce el patrón de tráfico del
frontend: el docente consulta el estado cada 1 s, cada estudiante cada
1.5 s, los estudiantes responden con una demora humana aleatoria y el
docente cierra la pregunta y avanza. Mide por endpoint: cantidad, p50,
p95, p99, máximo, errores y timeouts. Además cuenta cuántas consultas SQL
hace cada endpoint (en proceso, con un listener de SQLAlchemy).

Sirve para comparar versiones con EXACTAMENTE el mismo escenario:

    # versión optimizada (este checkout)
    python scripts/benchmark_live.py --database-url postgresql+psycopg://bench:bench@localhost/bench_live

    # versión base: el mismo script contra otro checkout (git worktree)
    git worktree add /tmp/xproject-base main
    python scripts/benchmark_live.py --app-dir /tmp/xproject-base --database-url ...

Seguridad (tarea 4.1): BORRA y recrea todas las tablas de la base indicada,
por eso se niega a correr contra un host que no sea localhost salvo con
`--allow-remote`. Nunca lo apuntes a producción.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import secrets
import socket
import statistics
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--app-dir", default=str(ROOT), help="Checkout cuya API se mide.")
    parser.add_argument("--students", type=int, default=40)
    parser.add_argument("--questions", type=int, default=3)
    parser.add_argument("--question-seconds", type=int, default=12)
    parser.add_argument("--reveal-seconds", type=int, default=8)
    parser.add_argument("--teacher-poll", type=float, default=1.0)
    parser.add_argument("--student-poll", type=float, default=1.5)
    parser.add_argument("--timeout", type=float, default=10.0, help="Timeout del cliente (s).")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--label", default="")
    parser.add_argument("--output", help="Guarda el resultado en JSON.")
    parser.add_argument("--allow-remote", action="store_true")
    return parser.parse_args()


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _check_safe(url: str, allow_remote: bool) -> None:
    host = urlparse(url.replace("+psycopg", "")).hostname or ""
    if url.startswith("sqlite") or host in {"localhost", "127.0.0.1", "::1"} or allow_remote:
        return
    raise SystemExit(f"Rehúso borrar tablas en el host remoto {host!r}. Usa --allow-remote si es una base de pruebas.")


def reset_schema(database_url: str) -> None:
    from sqlalchemy import create_engine
    from src.repositories.sqlalchemy.models import Base

    engine = create_engine(database_url)
    Base.metadata.drop_all(engine)
    engine.dispose()


def seed(database_url: str, students: int, questions: int, question_seconds: int) -> dict:
    """Datos ficticios: 1 docente, 1 curso, N estudiantes ya unidos al quiz."""
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker
    from src.repositories.sqlalchemy.models import (
        AuthSessionORM, CourseORM, QuickActivityORM, QuickActivityQuestionORM,
        QuickActivityResponseORM, RoleORM, StudentORM, TeacherCourseORM, UserORM,
    )
    from src.services.auth_service import AuthService, hash_password

    engine = create_engine(database_url)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    expires = datetime.now(timezone.utc) + timedelta(hours=4)
    password = hash_password("benchmark-password-123")
    tokens: dict = {"students": []}
    with Session() as session:
        roles = dict(session.execute(select(RoleORM.name, RoleORM.id)).all())
        teacher = UserORM(username="bench.teacher", full_name="Docente Bench",
                          password_hash=password, role_id=roles["docente"])
        session.add(teacher)
        course = CourseORM(name="Curso Bench", code="BENCH1")
        session.add(course)
        session.flush()
        session.add(TeacherCourseORM(teacher_id=teacher.id, course_id=course.id))
        activity = QuickActivityORM(
            course_id=course.id, title="Cacería Bench", status="published", mode="live",
            join_code="BENCH" + secrets.token_hex(2).upper(), question_seconds=question_seconds,
            live_phase="lobby", published_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=2), created_by_user_id=teacher.id,
        )
        activity.questions = [
            QuickActivityQuestionORM(position=i, prompt=f"Pregunta {i}",
                                     options=["A", "B", "C", "D"], correct_option=i % 4)
            for i in range(1, questions + 1)
        ]
        session.add(activity)
        session.flush()
        token = secrets.token_urlsafe(32)
        session.add(AuthSessionORM(token_hash=AuthService._hash_token(token), user_id=teacher.id, expires_at=expires))
        tokens["teacher"] = token
        for number in range(students):
            code = f"B{number:05d}"
            user = UserORM(username=code, full_name=f"Estudiante {number}", password_hash=password,
                           role_id=roles["estudiante"])
            session.add(user)
            session.flush()
            student = StudentORM(course_id=course.id, external_ref=code,
                                 display_name=f"Estudiante {number:02d}", user_id=user.id)
            session.add(student)
            session.flush()
            session.add(QuickActivityResponseORM(activity_id=activity.id, student_id=student.id,
                                                 user_id=user.id, attempt=1))
            token = secrets.token_urlsafe(32)
            session.add(AuthSessionORM(token_hash=AuthService._hash_token(token), user_id=user.id, expires_at=expires))
            tokens["students"].append(token)
        session.commit()
        info = {"course_id": course.id, "activity_id": activity.id, "tokens": tokens}
    engine.dispose()
    return info


def percentile(values, fraction):
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(fraction * (len(ordered) - 1)))]


class Recorder:
    def __init__(self):
        self.latencies = defaultdict(list)
        self.status = defaultdict(lambda: defaultdict(int))
        self.timeouts = defaultdict(int)
        self.max_in_flight = 0
        self._in_flight = 0

    async def call(self, client, name, method, url, token, **kwargs):
        self._in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self._in_flight)
        started = time.perf_counter()
        try:
            response = await client.request(method, url, headers={"Cookie": f"aula_session={token}"}, **kwargs)
            self.status[name][response.status_code] += 1
            return response
        except Exception as exc:  # timeout o red
            self.timeouts[name] += 1
            self.status[name][type(exc).__name__] += 1
            return None
        finally:
            self.latencies[name].append((time.perf_counter() - started) * 1000)
            self._in_flight -= 1

    def summary(self):
        rows = {}
        for name, values in self.latencies.items():
            ok = sum(count for code, count in self.status[name].items() if isinstance(code, int) and code < 400)
            rows[name] = {
                "requests": len(values),
                "ok": ok,
                "errors": len(values) - ok,
                "timeouts": self.timeouts[name],
                "status": {str(k): v for k, v in self.status[name].items()},
                "p50_ms": round(percentile(values, .50), 1),
                "p95_ms": round(percentile(values, .95), 1),
                "p99_ms": round(percentile(values, .99), 1),
                "max_ms": round(max(values), 1),
                "mean_ms": round(statistics.fmean(values), 1),
            }
        return rows


async def run_load(base_url: str, info: dict, args) -> dict:
    import httpx

    rng = random.Random(args.seed)
    rec = Recorder()
    course, activity = info["course_id"], info["activity_id"]
    teacher_token = info["tokens"]["teacher"]
    teacher_url = f"/courses/{course}/quick-activities/{activity}/live"
    student_url = f"/student/quick-activities/{activity}/live"
    stop = asyncio.Event()
    question_state = {"id": None, "open": False}
    answered = set()

    limits = httpx.Limits(max_connections=args.students + 10, max_keepalive_connections=args.students + 10)
    async with httpx.AsyncClient(base_url=base_url, timeout=args.timeout, limits=limits) as client:
        async def teacher_poll():
            while not stop.is_set():
                await rec.call(client, "GET docente /live", "GET", teacher_url, teacher_token)
                await asyncio.sleep(args.teacher_poll)

        async def student_loop(index, token):
            await asyncio.sleep(rng.random() * args.student_poll)  # desfase natural
            while not stop.is_set():
                response = await rec.call(client, "GET estudiante /live", "GET", student_url, token)
                if response is not None and response.status_code == 200:
                    data = response.json()
                    qid = (data.get("question") or {}).get("id")
                    key = (index, qid)
                    if data.get("phase") == "question" and qid and not data.get("answered") and key not in answered:
                        answered.add(key)
                        asyncio.create_task(answer(token, qid, key))
                await asyncio.sleep(args.student_poll)

        async def answer(token, qid, key):
            await asyncio.sleep(rng.uniform(0.5, args.question_seconds * 0.6))
            await rec.call(client, "POST estudiante /live/answers", "POST", f"{student_url}/answers", token,
                           json={"question_id": qid, "selected_option": rng.randrange(4)})

        tasks = [asyncio.create_task(teacher_poll())]
        tasks += [asyncio.create_task(student_loop(i, t)) for i, t in enumerate(info["tokens"]["students"])]
        await asyncio.sleep(3)  # sala de espera
        started = time.perf_counter()
        for _ in range(args.questions):
            await rec.call(client, "POST docente /live/advance", "POST", f"{teacher_url}/advance", teacher_token)
            # El docente cierra la pregunta justo antes de que expire (si
            # expira sola, «avanzar» saltaría directo a la siguiente).
            await asyncio.sleep(max(1, args.question_seconds - 1))
            await rec.call(client, "POST docente /live/advance", "POST", f"{teacher_url}/advance", teacher_token)
            await asyncio.sleep(args.reveal_seconds)
        await rec.call(client, "POST docente /live/advance", "POST", f"{teacher_url}/advance", teacher_token)
        await asyncio.sleep(args.reveal_seconds)  # podio final
        stop.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        duration = time.perf_counter() - started
    result = {"duration_s": round(duration, 1), "max_in_flight": rec.max_in_flight, "endpoints": rec.summary()}
    result["answers_registered"] = count_answers(args.database_url, activity)
    result["answers_attempted"] = len(answered)
    return result


def count_answers(database_url, activity_id) -> int:
    from sqlalchemy import create_engine, func, select
    from src.repositories.sqlalchemy.models import QuickActivityAnswerORM, QuickActivityResponseORM

    engine = create_engine(database_url)
    with engine.connect() as conn:
        total = conn.execute(
            select(func.count(QuickActivityAnswerORM.id))
            .join(QuickActivityResponseORM)
            .where(QuickActivityResponseORM.activity_id == activity_id)
        ).scalar_one()
    engine.dispose()
    return int(total)


def queries_per_endpoint(app_dir: str, database_url: str, info: dict) -> dict:
    """Cuenta las consultas SQL de cada endpoint, en un subproceso que
    importa la API del checkout medido (así sirve para la versión base)."""
    code = f"""
import json, sys
sys.path.insert(0, {app_dir!r})
from fastapi.testclient import TestClient
from sqlalchemy import event
from src.api.main import app
info = json.loads({json.dumps(json.dumps(info))})
out = {{}}
with TestClient(app) as client:
    engine = app.state.app_context.auth_service._session_factory.engine
    counter = {{"n": 0}}
    event.listen(engine, "before_cursor_execute", lambda *a, **k: counter.__setitem__("n", counter["n"] + 1))
    c, a = info["course_id"], info["activity_id"]
    def measure(name, method, url, token, **kw):
        counter["n"] = 0
        r = client.request(method, url, cookies={{"aula_session": token}}, **kw)
        out[name] = {{"queries": counter["n"], "status": r.status_code}}
    t = info["tokens"]["teacher"]; s = info["tokens"]["students"][0]
    measure("GET /auth/me", "GET", "/auth/me", s)
    measure("GET estudiante /live (finished)", "GET", f"/student/quick-activities/{{a}}/live", s)
    measure("GET docente /live (finished)", "GET", f"/courses/{{c}}/quick-activities/{{a}}/live", t)
    measure("GET docente /quick-activities", "GET", f"/courses/{{c}}/quick-activities", t)
print(json.dumps(out))
"""
    env = {**os.environ, "DATABASE_URL": database_url}
    proc = subprocess.run([sys.executable, "-c", code], cwd=app_dir, env=env, capture_output=True, text=True)
    if proc.returncode != 0:
        return {"error": proc.stderr[-2000:]}
    return json.loads(proc.stdout.strip().splitlines()[-1])


def main() -> None:
    args = parse_args()
    _check_safe(args.database_url, args.allow_remote)
    reset_schema(args.database_url)

    port = _free_port()
    env = {**os.environ, "DATABASE_URL": args.database_url, "LOG_LEVEL": "WARNING", "PYTHONPATH": args.app_dir}
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "src.api.main:app", "--host", "127.0.0.1", "--port", str(port),
         "--log-level", "warning", "--no-access-log"],
        cwd=args.app_dir, env=env,
    )
    try:
        import httpx

        for _ in range(120):
            try:
                if httpx.get(f"http://127.0.0.1:{port}/health", timeout=1).status_code == 200:
                    break
            except Exception:
                pass
            time.sleep(0.5)
        else:
            raise SystemExit("La API no arrancó.")
        info = seed(args.database_url, args.students, args.questions, args.question_seconds)
        result = asyncio.run(run_load(f"http://127.0.0.1:{port}", info, args))
    finally:
        server.terminate()
        server.wait(timeout=20)
    result["queries_per_request"] = queries_per_endpoint(args.app_dir, args.database_url, info)
    result["scenario"] = {k: v for k, v in vars(args).items() if k not in {"database_url"}}
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=args.app_dir,
                            capture_output=True, text=True).stdout.strip()
    result["commit"] = commit
    text = json.dumps(result, indent=2, ensure_ascii=False)
    print(text)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
