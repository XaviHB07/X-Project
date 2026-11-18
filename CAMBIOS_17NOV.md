# X-Project — avance del 17-nov-2026 (Sprint 7)

Base: `main` del 13-nov (merge #7, `evaluacion-y-revision-alumnos`).
Pruebas: `pytest -v` → 231 en verde (201 anteriores + 30 nuevas en
`tests/test_sprint7_and_pending.py`). Recorrido completo en navegador con
las cuentas de administrador, docente y estudiante.

## 1. Verificación de los sprints anteriores

| Sprint | HU | Estado en el repo (13-nov) | Qué se hizo |
|---|---|---|---|
| 3 | P7, ST1, ST2, inicio de sesión | Completo | — |
| 3 | A5 universidades (Rolando) | Faltaba | Implementado |
| 4 | X1, X2, X7, X3 | Completo | — |
| 4 | A6 facultades (Rolando) | Faltaba | Implementado |
| 5 | X4, X5, X6 | Completo | — |
| 5 | A7 especialidades (Rolando) | Faltaba | Implementado |
| 5 | A8 docentes (Xavi) | Parcial: nombre completo en un solo campo | Apellidos y nombres por separado |
| 6 | A4 usuarios (Rolando) | Parcial: el docente tenía usuario libre y contraseña aleatoria | Usuario = DNI, contraseña inicial = usuario |
| 6 | C2 selección encadenada (Xavi) | Faltaba | Implementado |
| 6 | C3 ciclos (Sleyther) | Completo, sin contexto institucional | Ciclo ligado a una especialidad |
| 6 | C4 cursos (Xavi) | Parcial: sin código ni estado; solo el admin creaba cursos | Código, estado, edición, eliminación y cursos creados por el docente |
| 6 | Migración MVP 1 (Xavi) | Faltaba | Implementada (corre una sola vez) |
| 6 | M1 material | Completo | — |

## 2. Sprint 7 (16–22 nov)

| HU | Responsable | Qué se hizo |
|---|---|---|
| HU-Q5 Unirse con código o QR | Sleyther | Vista "Unirse a actividad" del portal del estudiante y enlace `/?actividad=CÓDIGO`. Valida que el código esté vigente, que el estudiante pertenezca al curso y que haya un solo envío (salvo que el docente permita más). |
| HU-Q3 Registrar respuestas | Xavi | Las respuestas quedan asociadas a la cuenta del estudiante y a su matrícula. Una restricción única evita duplicados, y el docente ve las respuestas en la pestaña "Actividades rápidas". |
| HU-Q2 QR (avanzado) | (Rolando) | QR generado en el servidor junto al código y en la pantalla en vivo; botón "Escanear QR con la cámara" en el portal del estudiante. |
| Quiz en vivo (nuevo) | — | Segundo tipo de actividad, tipo Kahoot/Quizizz: pantalla para proyectar, una pregunta a la vez con tiempo, puntaje por rapidez, ranking y podio. Es una historia nueva: conviene registrarla en el backlog. |
| Base de Q1 | (Gavino) | Falta conectar la generación de preguntas con IA; solo debe enviarlas en el formato de `POST /courses/{id}/quick-activities`. |
| Prueba de concepto de HTR | Sleyther | Fuera de este repositorio: no se tocó. |

## 3. Archivos

Nuevos:
- `src/services/institution_service.py` — HU-A5, A6, A7 y validación de HU-C2
- `src/services/quick_activity_service.py` — HU-Q3, HU-Q5 y la base de Q1 y Q2
- `src/api/static/institutions.js` — página del administrador y selección encadenada
- `src/api/static/quick-activities.js` — pestaña del docente y vista del estudiante
- `src/api/static/live-quiz.js` — pantalla en vivo del docente y vista del estudiante en el celular
- `src/api/static/qr-scanner.js` — escaneo de QR con la cámara
- `src/api/static/vendor/jsQR.js` y `jsQR.LICENSE.txt` — lector de QR (Apache-2.0) para Safari/iOS y Firefox
- `tests/test_sprint7_and_pending.py` — 26 pruebas nuevas

Modificados:
- `src/repositories/sqlalchemy/models.py` — tablas `universities`, `faculties`, `specialties`, `schema_migrations` y `quick_activity_*`; columnas `academic_cycles.specialty_id`, `courses.code`, `courses.enabled`, `users.last_names` y `users.first_names`
- `src/services/bootstrap.py` — columnas nuevas, migración del MVP 1 y registro de los servicios
- `src/domain/entities.py`, `src/repositories/interfaces.py`, `src/repositories/sqlalchemy/repository_impl.py`, `src/repositories/in_memory/repository_impl.py` — curso con código, estado, edición y eliminación; ciclo con especialidad
- `src/services/auth_service.py` — docente con DNI, apellidos y nombres; usuario = DNI; cursos opcionales; el curso creado queda asignado al docente que lo crea
- `src/services/session_service.py`, `src/services/errors.py` — un curso deshabilitado no admite sesiones nuevas
- `src/api/schemas.py`, `src/api/main.py` — endpoints nuevos (ver la tabla del README)
- `src/api/static/index.html`, `app.js`, `styles.css` — pantallas nuevas y ajustes
- `requirements.txt` — nueva dependencia `segno` (genera el QR)
- `README.md` — esquema, endpoints y secciones nuevas

## 4. Decisiones que conviene revisar con el equipo

1. **HU-A4:** la contraseña inicial del docente pasa a ser igual a su usuario (el DNI), como pidió el profesor. Igual que con los estudiantes, debe cambiarla al primer ingreso. El restablecimiento de contraseña sigue generando una contraseña aleatoria.
2. **Migración:** crea "Universidad / Facultad / Especialidad (migrada del MVP 1)" y el ciclo "Histórico MVP 1". El administrador debe renombrarlos con los datos reales. Si un curso migrado ya tenía estudiantes, esa lista cuenta como su carga única por Excel.
3. **API compatible:** `POST /courses` y `POST /cycles` siguen aceptando llamadas sin `code` ni `specialty_id`, para no romper clientes ni pruebas anteriores. La interfaz sí los exige.
4. Las carpetas `src/index.html` y `src/app.js` son copias antiguas que no se sirven, así que no se tocaron. La aplicación usa `src/api/static/`.
5. **Quiz en vivo:** se sincroniza con consultas cada 1–1,5 s (sin WebSockets). Con el plan gratuito de Render conviene probarlo con el curso completo antes de usarlo en clase.
6. **Escáner con cámara:** solo funciona con HTTPS (Render ya lo da) o en localhost. Se probó con una cámara simulada en Chrome; falta probarlo en un Android y en un iPhone reales.
