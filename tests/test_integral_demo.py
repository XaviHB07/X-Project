"""Pruebas INTEGRALES previas a la demo: recorren, por la API real y con una
base SQLite temporal, todo lo implementado para los tres roles.

Las pruebas están numeradas y comparten un escenario que se va construyendo
en orden (ciclo -> curso -> docente -> alumnos -> sesión -> selección ->
participación -> exposiciones). Cada prueba verifica una funcionalidad.
"""

from __future__ import annotations

import io
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import select

from src.repositories.sqlalchemy.models import RoleORM, UserORM
from src.services.auth_service import hash_password

ADMIN_PASS = "admin-password-123"
STATE: dict = {}


# --------------------------------------------------------------------------
# Fixtures: tres clientes con cookies independientes (admin, docente, alumno)
# --------------------------------------------------------------------------
@pytest.fixture(scope="module")
def app_env(tmp_path_factory):
    db = tmp_path_factory.mktemp("demo") / "demo.db"
    mp = pytest.MonkeyPatch()
    mp.setenv("DATABASE_URL", f"sqlite:///{db}")
    mp.delenv("ADMIN_USERNAME", raising=False)
    mp.delenv("ADMIN_PASSWORD", raising=False)
    from src.api.main import app

    with TestClient(app) as admin:
        svc = app.state.app_context.auth_service
        with svc._session_factory() as s:
            role_id = s.execute(
                select(RoleORM.id).where(RoleORM.name == "administrador")
            ).scalar_one()
            s.add(UserORM(username="admin", full_name="Admin Demo",
                          password_hash=hash_password(ADMIN_PASS), role_id=role_id))
            s.commit()
        assert admin.post("/auth/login",
                          json={"username": "admin", "password": ADMIN_PASS}).status_code == 200
        yield {"app": app, "admin": admin,
               "teacher": TestClient(app), "student": TestClient(app),
               "anon": TestClient(app)}
    mp.undo()


@pytest.fixture()
def admin(app_env):
    return app_env["admin"]


@pytest.fixture()
def teacher(app_env):
    return app_env["teacher"]


@pytest.fixture()
def student(app_env):
    return app_env["student"]


@pytest.fixture()
def anon(app_env):
    return app_env["anon"]


def student_client(app, ref, password=None):
    """Inicia sesión como estudiante (clave inicial = código) y fija clave definitiva."""
    c = TestClient(app)
    new_pw = f"clave-{ref}-segura-1"
    r = c.post("/auth/login", json={"username": ref, "password": new_pw})
    if r.status_code == 200:
        return c
    r = c.post("/auth/login", json={"username": ref, "password": password or ref})
    assert r.status_code == 200, r.text
    ch = c.post("/auth/change-password", json={"new_password": new_pw})
    assert ch.status_code == 200, ch.text
    return c


def need(*keys):
    missing = [k for k in keys if k not in STATE]
    if missing:
        pytest.skip(f"Depende de pasos previos no completados: {missing}")


def roster_xlsx(rows):
    wb = Workbook()
    ws = wb.active
    ws.append(["Curso: MA102-U"])          # fila de identificación exigida por la importación
    ws.append(["codigo", "nombre", "correo"])
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


# ==========================================================================
# 00 · INFRAESTRUCTURA
# ==========================================================================
class Test00Infraestructura:
    def test_00_1_health(self, anon):
        r = anon.get("/health")
        assert r.status_code == 200

    def test_00_2_frontend_y_assets(self, anon):
        assert anon.get("/").status_code == 200
        assert anon.get("/assets/app.js").status_code == 200
        assert anon.get("/assets/styles.css").status_code == 200

    def test_00_3_metodos_de_seleccion_disponibles(self, admin):
        r = admin.get("/methods")
        assert r.status_code == 200
        assert set(r.json()["methods"]) >= {"roulette", "weighted_softmax", "bayesian_fairness"}


# ==========================================================================
# 01 · AUTENTICACIÓN (todos los roles)
# ==========================================================================
class Test01Autenticacion:
    def test_01_1_login_admin(self, admin):
        me = admin.get("/auth/me")
        assert me.status_code == 200 and me.json()["role"] == "administrador"

    def test_01_2_credenciales_incorrectas_401(self, anon):
        r = anon.post("/auth/login", json={"username": "admin", "password": "mala-contraseña-1"})
        assert r.status_code == 401

    def test_01_3_usuario_inexistente_401(self, anon):
        r = anon.post("/auth/login", json={"username": "nadie", "password": "x" * 12})
        assert r.status_code == 401

    def test_01_4_sin_sesion_no_accede_a_recursos_protegidos(self, anon):
        for path in ("/courses", "/cycles", "/admin/teachers", "/student/courses", "/auth/me"):
            assert anon.get(path).status_code == 401, path


# ==========================================================================
# 02 · ADMINISTRADOR
# ==========================================================================
class Test02Administrador:
    def test_02_1_crear_ciclo(self, admin):
        start = date.today() - timedelta(days=date.today().weekday())  # lunes de esta semana
        r = admin.post("/cycles", json={"name": "2026-DEMO", "starts_on": start.isoformat(),
                                        "ends_on": (start + timedelta(weeks=16)).isoformat()})
        assert r.status_code == 201, r.text
        STATE["cycle_id"] = r.json()["id"]
        STATE["cycle_start"] = start

    def test_02_2_ciclo_duplicado_409(self, admin):
        need("cycle_id")
        r = admin.post("/cycles", json={"name": "2026-DEMO"})
        assert r.status_code == 409

    def test_02_3_ciclo_fechas_invalidas_422(self, admin):
        r = admin.post("/cycles", json={"name": "X", "starts_on": "2026-05-10", "ends_on": "2026-05-01"})
        assert r.status_code == 422

    def test_02_4_editar_ciclo(self, admin):
        need("cycle_id")
        r = admin.patch(f"/cycles/{STATE['cycle_id']}", json={"name": "2026-DEMO-A"})
        assert r.status_code == 200 and r.json()["name"] == "2026-DEMO-A"

    def test_02_5_listar_ciclos(self, admin):
        need("cycle_id")
        r = admin.get("/cycles")
        assert r.status_code == 200 and any(c["id"] == STATE["cycle_id"] for c in r.json())

    def test_02_6_crear_curso_en_ciclo(self, admin):
        need("cycle_id")
        r = admin.post("/courses", json={"name": "Cálculo II - Demo", "cycle_id": STATE["cycle_id"]})
        assert r.status_code == 201, r.text
        STATE["course_id"] = r.json()["id"]
        r2 = admin.post("/courses", json={"name": "Física I - Demo", "cycle_id": STATE["cycle_id"]})
        assert r2.status_code == 201
        STATE["course2_id"] = r2.json()["id"]

    def test_02_7_curso_en_ciclo_inexistente_404(self, admin):
        assert admin.post("/courses", json={"name": "Z", "cycle_id": 99999}).status_code == 404

    def test_02_8_crear_docente_con_clave_temporal(self, admin):
        need("course_id")
        r = admin.post("/admin/teachers", json={
            "username": "prof.demo", "full_name": "Profesor Demo", "dni": "12345678",
            "email": "prof.demo@uni.edu", "phone_number": "999111222",
            "course_ids": [STATE["course_id"]]})
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["temporary_password"] and body["course_ids"] == [STATE["course_id"]]
        STATE["teacher_id"] = body["id"]
        STATE["teacher_pass"] = body["temporary_password"]

    def test_02_9_docente_duplicado_rechazado(self, admin):
        need("course_id", "teacher_id")
        r = admin.post("/admin/teachers", json={
            "username": "prof.demo", "full_name": "Otro", "dni": "87654321",
            "email": "otro@uni.edu", "course_ids": [STATE["course_id"]]})
        assert r.status_code in (400, 409)

    def test_02_10_docente_sin_cursos_rechazado(self, admin):
        r = admin.post("/admin/teachers", json={
            "username": "sin.curso", "full_name": "Sin Curso", "dni": "11112222",
            "email": "sc@uni.edu", "course_ids": []})
        assert r.status_code == 422

    def test_02_11_listar_y_editar_docente(self, admin):
        need("teacher_id")
        assert any(t["id"] == STATE["teacher_id"] for t in admin.get("/admin/teachers").json())
        r = admin.put(f"/admin/teachers/{STATE['teacher_id']}", json={
            "username": "prof.demo", "full_name": "Profesor Demo Editado", "dni": "12345678",
            "email": "prof.demo@uni.edu", "phone_number": "999000111"})
        assert r.status_code == 200 and r.json()["full_name"] == "Profesor Demo Editado"

    def test_02_12_deshabilitar_y_habilitar_docente(self, admin):
        need("teacher_id")
        tid = STATE["teacher_id"]
        r = admin.patch(f"/admin/teachers/{tid}/status", json={"active": False})
        assert r.status_code == 200 and r.json()["active"] is False
        r = admin.patch(f"/admin/teachers/{tid}/status", json={"active": True})
        assert r.status_code == 200 and r.json()["active"] is True

    def test_02_13_reasignar_cursos_al_docente(self, admin):
        need("teacher_id", "course_id", "course2_id")
        r = admin.put(f"/admin/teachers/{STATE['teacher_id']}/courses",
                      json={"course_ids": [STATE["course_id"], STATE["course2_id"]]})
        assert r.status_code == 200 and len(r.json()["course_ids"]) == 2
        r = admin.put(f"/admin/teachers/{STATE['teacher_id']}/courses",
                      json={"course_ids": [STATE["course_id"]]})
        assert r.status_code == 200 and r.json()["course_ids"] == [STATE["course_id"]]

    def test_02_14_reiniciar_clave_docente(self, admin):
        need("teacher_id")
        r = admin.post(f"/admin/teachers/{STATE['teacher_id']}/reset-password")
        assert r.status_code == 200
        STATE["teacher_pass"] = r.json()["temporary_password"]

    def test_02_15_crear_cuenta_de_estudiante(self, admin):
        r = admin.post("/admin/students", json={
            "username": "U20260001", "full_name": "Ana Cuenta", "email": "ana.cuenta@uni.edu"})
        assert r.status_code == 201, r.text
        assert r.json()["temporary_password"]
        STATE["manual_student_account_id"] = r.json()["id"]

    def test_02_16_listar_y_reiniciar_clave_de_estudiante(self, admin):
        need("manual_student_account_id")
        assert any(s["id"] == STATE["manual_student_account_id"] for s in admin.get("/admin/students").json())
        r = admin.post(f"/admin/students/{STATE['manual_student_account_id']}/reset-password")
        assert r.status_code == 200 and r.json()["temporary_password"]

    def test_02_17_ciclo_con_cursos_no_se_elimina_409(self, admin):
        need("cycle_id")
        assert admin.delete(f"/cycles/{STATE['cycle_id']}").status_code == 409

    def test_02_18_deshabilitar_ciclo_vacio_y_eliminar(self, admin):
        r = admin.post("/cycles", json={"name": "CICLO-VACIO"})
        assert r.status_code == 201
        cid = r.json()["id"]
        assert admin.patch(f"/cycles/{cid}", json={"enabled": False}).status_code == 200
        assert admin.post("/courses", json={"name": "No", "cycle_id": cid}).status_code == 409
        assert admin.delete(f"/cycles/{cid}").status_code == 204


# ==========================================================================
# 03 · DOCENTE: acceso, importación y matrícula
# ==========================================================================
class Test03DocenteAcceso:
    def test_03_1_login_docente_con_clave_temporal(self, teacher):
        need("teacher_pass")
        r = teacher.post("/auth/login", json={"username": "prof.demo", "password": STATE["teacher_pass"]})
        assert r.status_code == 200, r.text
        assert r.json()["role"] == "docente" and r.json()["must_change_password"] is True

    def test_03_2_cambio_de_clave_minimo_12_caracteres(self, teacher):
        need("teacher_pass")
        assert teacher.post("/auth/change-password", json={"new_password": "corta"}).status_code == 422

    def test_03_3_cambio_de_clave_exitoso_y_relogin(self, teacher, anon):
        need("teacher_pass")
        r = teacher.post("/auth/change-password", json={"new_password": "nueva-clave-docente-1"})
        assert r.status_code == 200 and r.json()["must_change_password"] is False
        assert anon.post("/auth/login", json={"username": "prof.demo",
                                                "password": "nueva-clave-docente-1"}).status_code == 200
        anon.post("/auth/logout")

    def test_03_4_docente_no_accede_a_administracion(self, teacher):
        need("teacher_pass")
        assert teacher.get("/admin/teachers").status_code == 403
        assert teacher.post("/courses", json={"name": "No permitido"}).status_code == 403

    def test_03_5_docente_solo_ve_sus_cursos(self, teacher):
        need("course_id")
        ids = [c["id"] for c in teacher.get("/courses").json()]
        assert STATE["course_id"] in ids and STATE["course2_id"] not in ids

    def test_03_6_docente_no_accede_a_curso_ajeno_403(self, teacher):
        need("course2_id")
        assert teacher.get(f"/courses/{STATE['course2_id']}/students").status_code == 403
        assert teacher.get(f"/courses/{STATE['course2_id']}/fairness-metrics").status_code == 403


class Test04DocenteMatricula:
    def test_04_1_importar_lista_excel(self, teacher):
        need("course_id")
        rows = [["U001", "Ana Torres", "ana@uni.edu"], ["U002", "Luis Pérez", "luis@uni.edu"],
                ["U003", "María Gómez", "maria@uni.edu"], ["U004", "Carlos Ruiz", "carlos@uni.edu"],
                ["U005", "Elena Soto", "elena@uni.edu"], ["U006", "Pedro Vela", "pedro@uni.edu"]]
        r = teacher.post(f"/courses/{STATE['course_id']}/students/import",
                         files={"file": ("lista.xlsx", roster_xlsx(rows), XLSX)})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["created"] == 6 and body["errors"] == []
        assert len(body["created_accounts"]) == 6

    def test_04_2_reimportar_en_curso_de_ciclo_409(self, teacher):
        need("course_id")
        r = teacher.post(f"/courses/{STATE['course_id']}/students/import",
                         files={"file": ("lista.xlsx", roster_xlsx([["U007", "Nuevo", "n@uni.edu"]]), XLSX)})
        assert r.status_code == 409

    def test_04_3_archivo_no_xlsx_400(self, teacher):
        need("course_id")
        r = teacher.post(f"/courses/{STATE['course_id']}/students/import",
                         files={"file": ("lista.txt", b"hola", "text/plain")})
        assert r.status_code == 400

    def test_04_4_listar_estudiantes_del_curso(self, teacher):
        need("course_id")
        r = teacher.get(f"/courses/{STATE['course_id']}/students")
        assert r.status_code == 200 and len(r.json()) == 6
        STATE["students"] = {s["external_ref"]: s["id"] for s in r.json()}

    def test_04_5_estado_inicial_bayesiano(self, teacher):
        need("students")
        r = teacher.get(f"/students/{STATE['students']['U001']}/state")
        assert r.status_code == 200
        b = r.json()
        assert b["alpha"] == 1.0 and b["beta"] == 1.0 and b["n_present"] == 0 and b["n_selected"] == 0

    def test_04_6_matricula_individual(self, teacher):
        need("course_id")
        r = teacher.post(f"/courses/{STATE['course_id']}/students", json={
            "external_ref": "U007", "display_name": "Rosa Díaz", "email": "rosa@uni.edu"})
        assert r.status_code == 201, r.text
        assert r.json()["account_username"] == "U007"
        STATE["students"]["U007"] = r.json()["id"]

    def test_04_7_editar_estudiante(self, teacher):
        need("students")
        r = teacher.patch(f"/students/{STATE['students']['U007']}", json={"display_name": "Rosa Díaz Mejía"})
        assert r.status_code == 200 and r.json()["display_name"] == "Rosa Díaz Mejía"

    def test_04_8_retirar_y_reincorporar_estudiante(self, teacher):
        need("students")
        sid = STATE["students"]["U007"]
        r = teacher.patch(f"/students/{sid}", json={"active": False})
        assert r.status_code == 200 and r.json()["active"] is False
        r = teacher.patch(f"/students/{sid}", json={"active": True})
        assert r.status_code == 200 and r.json()["active"] is True

    def test_04_9_reiniciar_clave_del_estudiante(self, teacher):
        need("students")
        r = teacher.post(f"/students/{STATE['students']['U002']}/reset-password")
        assert r.status_code == 200 and r.json()["temporary_password"]
        # se restablece al código para que el alumno entre con U002 en la prueba de estudiante
        STATE["u002_pass"] = r.json()["temporary_password"]


class Test05DocenteMateriales:
    def test_05_1_subir_material(self, teacher):
        need("course_id")
        from docx import Document
        buf = io.BytesIO()
        d = Document()
        d.add_paragraph("Límites y continuidad: apuntes de clase.")
        d.save(buf)
        r = teacher.post(f"/courses/{STATE['course_id']}/materials",
                         data={"title": "Apuntes S1", "topic": "Límites"},
                         files={"file": ("apuntes.docx", buf.getvalue(),
                                         "application/vnd.openxmlformats-officedocument.wordprocessingml.document")})
        assert r.status_code == 201, r.text
        STATE["material_id"] = r.json()["id"]

    def test_05_2_listar_y_descargar_material(self, teacher):
        need("material_id")
        lst = teacher.get(f"/courses/{STATE['course_id']}/materials")
        assert lst.status_code == 200 and len(lst.json()) == 1
        dl = teacher.get(f"/courses/{STATE['course_id']}/materials/{STATE['material_id']}/content")
        assert dl.status_code == 200 and len(dl.content) > 100

    def test_05_3_texto_extraido_del_material(self, teacher):
        need("material_id")
        r = teacher.get(f"/courses/{STATE['course_id']}/materials/{STATE['material_id']}/text")
        assert r.status_code == 200 and "Límites" in r.text

    def test_05_4_formato_no_permitido_400(self, teacher):
        need("course_id")
        r = teacher.post(f"/courses/{STATE['course_id']}/materials",
                         files={"file": ("virus.exe", b"MZ", "application/octet-stream")})
        assert r.status_code == 400

    def test_05_5_eliminar_material(self, teacher):
        need("material_id")
        assert teacher.delete(f"/courses/{STATE['course_id']}/materials/{STATE['material_id']}").status_code in (200, 204)
        assert teacher.get(f"/courses/{STATE['course_id']}/materials").json() == []


# ==========================================================================
# 06 · DOCENTE: sílabo, tiempo de exposición y sesión de clase
# ==========================================================================
class Test06Sesiones:
    def test_06_1_sílabo_y_propuesta_de_sesion(self, teacher):
        need("course_id")
        today = date.today().isoformat()
        r = teacher.post(f"/courses/{STATE['course_id']}/syllabus", json={"session_date": today, "topic": "Derivadas"})
        assert r.status_code == 201
        p = teacher.get(f"/courses/{STATE['course_id']}/class-sessions/proposal", params={"session_date": today})
        assert p.status_code == 200 and p.json()["suggested_topic"] == "Derivadas"
        assert len(teacher.get(f"/courses/{STATE['course_id']}/syllabus").json()) == 1

    def test_06_2_configurar_tiempo_de_exposicion(self, teacher):
        need("course_id")
        r = teacher.put(f"/courses/{STATE['course_id']}/exposure-time-settings",
                        json={"min_minutes": 5, "max_minutes": 10})
        assert r.status_code == 200, r.text
        g = teacher.get(f"/courses/{STATE['course_id']}/exposure-time-settings")
        assert g.status_code == 200 and (g.json()["min_minutes"], g.json()["max_minutes"]) == (5, 10)

    def test_06_3_tiempo_minimo_mayor_al_maximo_422(self, teacher):
        need("course_id")
        r = teacher.put(f"/courses/{STATE['course_id']}/exposure-time-settings",
                        json={"min_minutes": 12, "max_minutes": 10})
        assert r.status_code == 422

    def test_06_4_tiempo_fuera_de_rango_422(self, teacher):
        need("course_id")
        assert teacher.put(f"/courses/{STATE['course_id']}/exposure-time-settings",
                           json={"min_minutes": 0, "max_minutes": 10}).status_code == 422
        assert teacher.put(f"/courses/{STATE['course_id']}/exposure-time-settings",
                           json={"min_minutes": 5, "max_minutes": 999}).status_code == 422

    def test_06_5_iniciar_sesion_con_tema_del_silabo(self, teacher):
        need("course_id")
        r = teacher.post(f"/courses/{STATE['course_id']}/class-sessions", json={})
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["topic"] == "Derivadas"
        assert sum(1 for a in body["attendance"] if a["present"]) == 7
        STATE["session_id"] = body["id"]

    def test_06_6_listar_y_ver_detalle_de_sesion(self, teacher):
        need("session_id")
        assert len(teacher.get(f"/courses/{STATE['course_id']}/class-sessions").json()) >= 1
        assert teacher.get(f"/class-sessions/{STATE['session_id']}").status_code == 200

    def test_06_7_marcar_ausente_actualiza_asistencia(self, teacher):
        need("session_id", "students")
        r = teacher.put(f"/class-sessions/{STATE['session_id']}/attendance",
                        json={"attendance": [{"student_id": STATE["students"]["U006"], "present": False}]})
        assert r.status_code == 200, r.text
        det = teacher.get(f"/class-sessions/{STATE['session_id']}").json()
        absent = [a for a in det["attendance"] if not a["present"]]
        assert [a["external_ref"] for a in absent] == ["U006"]

    def test_06_8_asistencia_de_alumno_ajeno_400(self, teacher):
        need("session_id")
        r = teacher.put(f"/class-sessions/{STATE['session_id']}/attendance",
                        json={"attendance": [{"student_id": 999999, "present": True}]})
        assert r.status_code in (400, 404)


# ==========================================================================
# 07 · DOCENTE: selección y participación
# ==========================================================================
class Test07SeleccionYParticipacion:
    @pytest.mark.parametrize("method", ["roulette", "weighted_softmax", "bayesian_fairness"])
    def test_07_1_seleccion_con_cada_metodo(self, teacher, method):
        need("session_id")
        r = teacher.post(f"/courses/{STATE['course_id']}/sessions/select", json={
            "class_session_id": STATE["session_id"], "k": 2, "method": method})
        assert r.status_code == 201, r.text
        body = r.json()
        assert len(body["selected_student_ids"]) == 2
        assert len(set(body["selected_student_ids"])) == 2
        # el ausente (U006) nunca es considerado
        assert STATE["students"]["U006"] not in body["considered_student_ids"]
        STATE.setdefault("runs", {})[method] = body

    def test_07_2_metodo_desconocido_400(self, teacher):
        need("session_id")
        r = teacher.post(f"/courses/{STATE['course_id']}/sessions/select", json={
            "class_session_id": STATE["session_id"], "k": 1, "method": "inventado"})
        assert r.status_code == 400

    def test_07_3_k_invalido_422(self, teacher):
        need("session_id")
        assert teacher.post(f"/courses/{STATE['course_id']}/sessions/select", json={
            "class_session_id": STATE["session_id"], "k": 0}).status_code == 422

    def test_07_4_estado_bayesiano_se_actualiza(self, teacher):
        need("runs")
        sid = STATE["runs"]["bayesian_fairness"]["selected_student_ids"][0]
        st = teacher.get(f"/students/{sid}/state").json()
        assert st["n_selected"] >= 1 and st["n_present"] >= 3

    def test_07_5_historial_de_decisiones_del_estudiante(self, teacher):
        need("runs")
        sid = STATE["runs"]["bayesian_fairness"]["selected_student_ids"][0]
        r = teacher.get(f"/students/{sid}/history")
        assert r.status_code == 200 and len(r.json()) >= 1

    def test_07_6_registrar_participacion_con_nota_oculta(self, teacher):
        need("runs")
        run = STATE["runs"]["bayesian_fairness"]
        a, b = run["selected_student_ids"]
        r = teacher.post(f"/courses/{STATE['course_id']}/decision-runs/{run['decision_run_id']}/participations",
                         json={"participations": [
                             {"student_id": a, "score": 4.5, "present": True, "difficulty": 4,
                              "question": "¿Qué es una derivada?", "comment": "Muy bien"},
                             {"student_id": b, "score": 2.0, "present": True, "difficulty": 2,
                              "question": "Regla de la cadena", "grade_visible": False}]})
        assert r.status_code == 201, r.text
        recs = {x["student_id"]: x for x in r.json()}
        assert recs[a]["grade_visible"] is False and recs[a]["score"] == 4.5
        STATE["part_a"], STATE["part_b"] = recs[a], recs[b]
        STATE["student_a"], STATE["student_b"] = a, b

    def test_07_7_nota_fuera_de_escala_422(self, teacher):
        need("runs")
        run = STATE["runs"]["bayesian_fairness"]
        r = teacher.post(f"/courses/{STATE['course_id']}/decision-runs/{run['decision_run_id']}/participations",
                         json={"participations": [{"student_id": STATE["student_a"], "score": 9, "present": True}]})
        assert r.status_code == 422

    def test_07_8_dificultad_fuera_de_rango_422(self, teacher):
        need("runs")
        run = STATE["runs"]["bayesian_fairness"]
        r = teacher.post(f"/courses/{STATE['course_id']}/decision-runs/{run['decision_run_id']}/participations",
                         json={"participations": [{"student_id": STATE["student_a"], "score": 3,
                                                   "present": True, "difficulty": 9}]})
        assert r.status_code == 422

    def test_07_9_estudiante_repetido_en_el_lote_400(self, teacher):
        need("runs")
        run = STATE["runs"]["bayesian_fairness"]
        e = {"student_id": STATE["student_a"], "score": 3, "present": True}
        r = teacher.post(f"/courses/{STATE['course_id']}/decision-runs/{run['decision_run_id']}/participations",
                         json={"participations": [e, e]})
        assert r.status_code == 400

    def test_07_10_listar_participaciones_del_curso(self, teacher):
        need("part_a")
        r = teacher.get(f"/courses/{STATE['course_id']}/participations")
        assert r.status_code == 200 and len(r.json()) >= 2

    def test_07_11_notas_semanales_del_ciclo(self, teacher):
        need("part_a")
        r = teacher.get(f"/courses/{STATE['course_id']}/weekly-grades", params={"cycle_id": STATE["cycle_id"]})
        assert r.status_code == 200, r.text
        assert len(r.json()["students"]) >= 6

    def test_07_12_detalle_semanal_de_participaciones(self, teacher):
        need("part_a")
        r = teacher.get(f"/courses/{STATE['course_id']}/weekly-grades/details",
                        params={"cycle_id": STATE["cycle_id"], "student_id": STATE["student_a"], "week": 1})
        assert r.status_code == 200, r.text
        assert r.json()["total"] >= 1

    def test_07_13_metricas_de_equidad(self, teacher):
        need("part_a")
        r = teacher.get(f"/courses/{STATE['course_id']}/fairness-metrics")
        assert r.status_code == 200, r.text
        assert r.json()["n_students"] >= 6


# ==========================================================================
# 08 · DOCENTE: grupos y exposiciones
# ==========================================================================
class Test08GruposYExposiciones:
    def test_08_1_generar_propuesta_de_grupos(self, teacher):
        need("students")
        r = teacher.post(f"/courses/{STATE['course_id']}/group-plans", json={"max_group_size": 3, "name": "Plan A"})
        assert r.status_code == 201, r.text
        plan = r.json()
        members = [s for g in plan["groups"] for s in g["student_ids"]]
        assert len(members) == len(set(members)) == 7 and all(len(g["student_ids"]) <= 3 for g in plan["groups"])
        STATE["plan"] = plan

    def test_08_2_confirmar_y_listar_plan(self, teacher):
        need("plan")
        p = STATE["plan"]
        r = teacher.post(f"/courses/{STATE['course_id']}/group-plans/confirm", json={
            "name": p["name"], "max_group_size": p["max_group_size"], "groups": p["groups"]})
        assert r.status_code == 201, r.text
        STATE["plan_id"] = r.json()["id"]
        assert any(x["id"] == STATE["plan_id"] for x in teacher.get(f"/courses/{STATE['course_id']}/group-plans").json())

    def test_08_3_editar_plan_de_grupos(self, teacher):
        need("plan_id")
        plan = next(x for x in teacher.get(f"/courses/{STATE['course_id']}/group-plans").json()
                    if x["id"] == STATE["plan_id"])
        r = teacher.put(f"/courses/{STATE['course_id']}/group-plans/{STATE['plan_id']}", json={
            "name": "Plan A (editado)", "max_group_size": plan["max_group_size"], "groups": plan["groups"]})
        assert r.status_code == 200 and r.json()["name"] == "Plan A (editado)"

    def test_08_4_plan_manual(self, teacher):
        need("course_id")
        r = teacher.post(f"/courses/{STATE['course_id']}/group-plans/manual", json={"group_count": 2, "name": "Manual"})
        assert r.status_code == 201, r.text
        assert len(r.json()["groups"]) == 2

    def test_08_5_grupo_con_estudiante_repetido_rechazado(self, teacher):
        need("plan_id", "students")
        sid = STATE["students"]["U001"]
        r = teacher.put(f"/courses/{STATE['course_id']}/group-plans/{STATE['plan_id']}", json={
            "name": "Mal", "max_group_size": 3,
            "groups": [{"name": "G1", "student_ids": [sid]}, {"name": "G2", "student_ids": [sid]}]})
        assert r.status_code in (400, 422)

    def test_08_6_registrar_exposicion_grupal_con_duracion(self, teacher):
        need("plan_id", "students", "session_id")
        ids = [STATE["students"][k] for k in ("U001", "U002", "U003")]
        r = teacher.post(f"/courses/{STATE['course_id']}/group-expositions", json={
            "group_name": "Grupo 1", "group_score": 4.0, "group_plan_id": STATE["plan_id"],
            "class_session_id": STATE["session_id"], "duration_seconds": 420, "comment": "Buen trabajo",
            "members": [{"student_id": ids[0], "present": True, "score": 4.5, "position": 1},
                        {"student_id": ids[1], "present": True, "score": 3.5, "position": 2},
                        {"student_id": ids[2], "present": False}]})
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["duration_seconds"] == 420 and len(body["members"]) == 3
        STATE["expo_id"] = body["id"]

    def test_08_7_integrante_presente_sin_nota_rechazado(self, teacher):
        need("students", "session_id")
        r = teacher.post(f"/courses/{STATE['course_id']}/group-expositions", json={
            "group_name": "Grupo X", "group_score": 3.0, "class_session_id": STATE["session_id"],
            "members": [{"student_id": STATE["students"]["U004"], "present": True}]})
        assert r.status_code in (400, 422)

    def test_08_8_nota_grupal_fuera_de_escala_422(self, teacher):
        need("students")
        r = teacher.post(f"/courses/{STATE['course_id']}/group-expositions", json={
            "group_name": "Grupo X", "group_score": 8,
            "members": [{"student_id": STATE["students"]["U004"], "present": False}]})
        assert r.status_code == 422

    def test_08_9_listar_y_editar_exposicion(self, teacher):
        need("expo_id")
        lst = teacher.get(f"/courses/{STATE['course_id']}/group-expositions")
        assert lst.status_code == 200 and any(e["id"] == STATE["expo_id"] for e in lst.json())
        ids = [STATE["students"][k] for k in ("U001", "U002", "U003")]
        r = teacher.put(f"/courses/{STATE['course_id']}/group-expositions/{STATE['expo_id']}", json={
            "group_score": 4.5, "duration_seconds": 480,
            "members": [{"student_id": ids[0], "present": True, "score": 5.0, "position": 1},
                        {"student_id": ids[1], "present": True, "score": 4.0, "position": 2},
                        {"student_id": ids[2], "present": False}]})
        assert r.status_code == 200, r.text
        assert r.json()["group_score"] == 4.5 and r.json()["duration_seconds"] == 480

    def test_08_10_detalle_semanal_grupal(self, teacher):
        need("expo_id")
        r = teacher.get(f"/courses/{STATE['course_id']}/weekly-group-grades/details",
                        params={"cycle_id": STATE["cycle_id"], "student_id": STATE["students"]["U001"], "week": 1})
        assert r.status_code == 200, r.text
        assert r.json()["total"] >= 1

    def test_08_11_eliminar_plan(self, teacher):
        need("course_id")
        r = teacher.post(f"/courses/{STATE['course_id']}/group-plans/manual", json={"group_count": 1, "name": "Temporal"})
        draft = r.json()                      # el plan manual es un borrador (sin id) hasta confirmarlo
        c = teacher.post(f"/courses/{STATE['course_id']}/group-plans/confirm", json={
            "name": "Temporal", "max_group_size": draft["max_group_size"], "groups": draft["groups"]})
        assert c.status_code == 201, c.text
        pid = c.json()["id"]
        assert teacher.delete(f"/courses/{STATE['course_id']}/group-plans/{pid}").status_code == 204


# ==========================================================================
# 09 · ESTUDIANTE
# ==========================================================================
class Test09Estudiante:
    def test_09_1_login_con_codigo_como_clave_inicial(self, student):
        need("students")
        r = student.post("/auth/login", json={"username": "U001", "password": "U001"})
        assert r.status_code == 200, r.text
        assert r.json()["role"] == "estudiante" and r.json()["must_change_password"] is True

    def test_09_1b_bloqueado_hasta_cambiar_la_clave_inicial(self, student):
        r = student.get("/student/courses")
        assert r.status_code in (403, 428) and "contraseña nueva" in r.text

    def test_09_1c_cambio_de_clave_del_estudiante(self, student, anon):
        r = student.post("/auth/change-password", json={"new_password": "clave-alumno-segura-1"})
        assert r.status_code == 200 and r.json()["must_change_password"] is False
        assert anon.post("/auth/login", json={"username": "U001", "password": "U001"}).status_code == 401
        assert anon.post("/auth/login", json={"username": "U001",
                                                "password": "clave-alumno-segura-1"}).status_code == 200

    def test_09_2_ver_mis_cursos(self, student):
        r = student.get("/student/courses")
        assert r.status_code == 200 and [c["course_id"] for c in r.json()] == [STATE["course_id"]]

    def test_09_3_ver_semanas_y_sesiones_del_curso(self, student):
        r = student.get(f"/student/courses/{STATE['course_id']}/weeks")
        assert r.status_code == 200, r.text
        body = r.json()
        assert len(body["weeks"]) == 16
        assert sum(len(w["sessions"]) for w in body["weeks"]) + len(body["unassigned_sessions"]) >= 1

    def test_09_4_curso_no_matriculado_404(self, student):
        assert student.get(f"/student/courses/{STATE['course2_id']}/weeks").status_code == 404

    def test_09_5_historial_propio_sin_participaciones_vacio_o_propio(self, student):
        r = student.get("/student/history")
        assert r.status_code == 200
        # U001 puede o no haber sido seleccionado; en todo caso solo ve lo suyo
        assert all(h["course_id"] == STATE["course_id"] for h in r.json())

    def test_09_6_nota_oculta_no_se_envia_al_estudiante(self, app_env):
        need("part_a")
        sid_a = STATE["student_a"]
        ref = next(k for k, v in STATE["students"].items() if v == sid_a)
        c = student_client(app_env["app"], ref)
        h = c.get("/student/history").json()
        mine = [x for x in h if x["id"] == STATE["part_a"]["id"]]
        assert len(mine) == 1
        assert mine[0]["grade_visible"] is False
        assert mine[0]["score"] is None                       # el backend NO devuelve la nota
        assert "4.5" not in c.get("/student/history").text
        assert mine[0]["difficulty"] == 4 and mine[0]["question"] == "¿Qué es una derivada?"
        STATE["student_a_ref"] = ref

    def test_09_7_docente_publica_la_nota(self, teacher):
        need("part_a")
        r = teacher.patch(f"/courses/{STATE['course_id']}/participations/{STATE['part_a']['id']}/visibility",
                          json={"grade_visible": True})
        assert r.status_code == 200 and r.json()["grade_visible"] is True

    def test_09_8_estudiante_ve_la_nota_publicada(self, app_env):
        need("student_a_ref")
        ref = STATE["student_a_ref"]
        c = student_client(app_env["app"], ref)
        mine = next(x for x in c.get("/student/history").json() if x["id"] == STATE["part_a"]["id"])
        assert mine["grade_visible"] is True and mine["score"] == 4.5

    def test_09_9_docente_oculta_de_nuevo_la_nota(self, teacher, app_env):
        need("student_a_ref")
        teacher.patch(f"/courses/{STATE['course_id']}/participations/{STATE['part_a']['id']}/visibility",
                      json={"grade_visible": False})
        ref = STATE["student_a_ref"]
        c = student_client(app_env["app"], ref)
        mine = next(x for x in c.get("/student/history").json() if x["id"] == STATE["part_a"]["id"])
        assert mine["score"] is None

    def test_09_10_alumno_no_ve_participaciones_de_otro(self, app_env):
        need("part_b", "student_b")
        ref_a = STATE["student_a_ref"]
        c = student_client(app_env["app"], ref_a)
        ids = [x["id"] for x in c.get("/student/history").json()]
        assert STATE["part_b"]["id"] not in ids

    def test_09_11_estudiante_no_accede_a_endpoints_de_docente_ni_admin(self, student):
        cid = STATE["course_id"]
        for path in (f"/courses/{cid}/students", f"/courses/{cid}/participations",
                     f"/courses/{cid}/fairness-metrics", f"/courses/{cid}/group-plans",
                     "/admin/teachers", "/admin/students"):
            assert student.get(path).status_code == 403, path
        assert student.post(f"/courses/{cid}/sessions/select", json={"k": 1}).status_code == 403
        assert student.put(f"/courses/{cid}/exposure-time-settings",
                           json={"min_minutes": 1, "max_minutes": 2}).status_code == 403

    def test_09_12_estudiante_no_puede_ver_estado_de_otro_alumno(self, student):
        need("students")
        assert student.get(f"/students/{STATE['students']['U002']}/state").status_code == 403

    def test_09_13_docente_no_usa_endpoints_de_estudiante(self, teacher):
        assert teacher.get("/student/courses").status_code == 403
        assert teacher.get("/student/history").status_code == 403

    def test_09_15_cuenta_creada_por_admin_puede_ingresar(self, app_env, admin):
        need("manual_student_account_id")
        r = admin.post(f"/admin/students/{STATE['manual_student_account_id']}/reset-password")
        pw = r.json()["temporary_password"]
        c = student_client(app_env["app"], "U20260001", password=pw)
        assert c.get("/auth/me").json()["role"] == "estudiante"
        assert c.get("/student/courses").json() == []   # aún sin matricular


# ==========================================================================
# 10 · CIERRE DE SESIÓN
# ==========================================================================
class Test10Cierre:
    def test_10_1_logout_invalida_la_sesion(self, app_env):
        c = TestClient(app_env["app"])
        c.post("/auth/login", json={"username": "prof.demo", "password": "nueva-clave-docente-1"})
        assert c.get("/auth/me").status_code == 200
        assert c.post("/auth/logout").status_code == 204
        assert c.get("/auth/me").status_code == 401

    def test_10_2_docente_deshabilitado_no_puede_ingresar(self, admin, app_env):
        need("teacher_id")
        admin.patch(f"/admin/teachers/{STATE['teacher_id']}/status", json={"active": False})
        c = TestClient(app_env["app"])
        r = c.post("/auth/login", json={"username": "prof.demo", "password": "nueva-clave-docente-1"})
        assert r.status_code == 401
        admin.patch(f"/admin/teachers/{STATE['teacher_id']}/status", json={"active": True})
