# Informe de optimización y estabilización — X-Project

Implementación del documento *Plan de optimización y estabilización
(4 integrantes)*. Rama: `claude/optimizacion-rendimiento`, creada desde
`main` en `62a67aa`.

Principio aplicado: **medir → optimizar → volver a medir**. Todas las cifras
de este informe salen de `scripts/benchmark_live.py`, ejecutado con el mismo
escenario sobre la versión base (`main`) y sobre esta rama.

---

## 1. Resultados medidos (antes / después)

Escenario D del plan: 1 docente proyectando + N estudiantes, 3 preguntas
(12 s de pregunta + 8 s de resultados) y podio final; docente consulta cada
1 s, estudiantes cada 1.5 s, cada estudiante responde una vez por pregunta.
PostgreSQL 16 local, un proceso uvicorn (igual que `render.yaml`), dos
repeticiones por versión. Commit base: `62a67aa` (`main`).

**Latencia de `GET /student/quick-activities/{id}/live` (la ruta más usada):**

| Estudiantes | Versión | Corrida | Peticiones totales | p50 (ms) | p95 (ms) | p99 (ms) | máx. (ms) | p95 docente (ms) | p95 enviar respuesta (ms) | Errores | En vuelo máx. | Respuestas registradas |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 40 | base | 1 | 1863 | 70.9 | 454.1 | 508.6 | 615.0 | 191.7 | 189.5 | 0 | 40 | 120/120 |
| 40 | base | 2 | 1866 | 83.2 | 370.0 | 487.8 | 515.9 | 206.1 | 202.9 | 0 | 38 | 120/120 |
| 40 | **optimizada** | 1 | 1984 | **18.4** | **40.7** | **59.8** | 131.9 | **55.8** | **70.9** | 0 | **8** | 120/120 |
| 40 | **optimizada** | 2 | 1984 | **19.2** | **51.3** | **78.1** | 218.6 | **53.8** | **71.7** | 0 | **12** | 120/120 |
| 60 | base | 1 | 2621 | 232.2 | 608.6 | 703.6 | 864.9 | 376.1 | 361.4 | 0 | 56 | 180/180 |
| 60 | base | 2 | 2594 | 214.1 | 655.1 | 870.6 | 942.8 | 353.1 | 432.0 | 0 | 60 | 180/180 |
| 60 | **optimizada** | 1 | 2937 | **17.7** | **58.8** | **88.8** | 182.0 | **59.7** | **55.1** | 0 | **10** | 180/180 |
| 60 | **optimizada** | 2 | 2940 | **17.7** | **50.9** | **76.1** | 126.7 | **52.3** | **55.2** | 0 | **8** | 180/180 |

* p95 del estudiante: **~8× menor con 40** (412 → 46 ms de media) y **~12×
  menor con 60** (632 → 55 ms). Con la versión base la latencia crecía con la
  cantidad de usuarios (p50 71 → 223 ms al pasar de 40 a 60); con la
  optimizada se mantiene plana (~18 ms).
* En el mismo tiempo se atendieron **6–13 % más peticiones**, porque cada
  respuesta llega antes y el siguiente ciclo empieza antes.
* «En vuelo máx.» = peticiones simultáneas esperando respuesta: la base
  llegaba a tener a **todos** los estudiantes en cola a la vez.
* Integridad: todas las respuestas enviadas se registraron exactamente una
  vez, sin errores HTTP ni timeouts en ninguna corrida.

**Consultas SQL por petición** (contadas con un listener de SQLAlchemy):

| Endpoint | Base | Optimizada |
|---|---|---|
| Autenticación de cualquier petición (`GET /auth/me`) | 3 | **1** |
| Estado del estudiante (fase `finished`, caché fría) | 11 | **8** (7 con la caché del ranking caliente) |
| Estado del docente (fase `finished`) | 10 | **5** |
| Listado de actividades del docente (1 actividad; antes crecía +1 por actividad) | 7 | **5** (fijo) |

**Lectura:** el cuello de botella principal era la **autenticación síncrona
dentro del middleware `async`**: cada petición bloqueaba el event loop mientras
consultaba PostgreSQL (3 consultas), así que las peticiones de los 40
estudiantes se atendían en fila. La columna «en vuelo máx.» lo muestra: con la
versión base llegaban a acumularse decenas de peticiones esperando a la vez.
A eso se sumaba el ranking recalculado en cada consulta.

Limitaciones de la medición (no ocultarlas):

* PostgreSQL 16 **local**, sin la latencia de red de Render ni sus límites
  de CPU del plan gratuito. Las cifras absolutas en Render serán mayores; lo
  que se compara es la **mejora relativa** con el mismo escenario.
* CPU, memoria y conexiones de PostgreSQL en Render: **no disponible** en
  esta medición. Ahora se pueden ver con `/admin/metrics` (estado del pool)
  y en el panel de Render.
* El cliente de carga simula el patrón de tráfico de la versión base
  (consulta cada 1 s / 1.5 s aunque la anterior no haya terminado), así que
  la mejora del frontend (sección 3) se suma aparte a estas cifras.

---

## 2. Integrante 1 — Backend y autenticación

| Hallazgo del plan | Verificación | Cambio |
|---|---|---|
| `authenticate_requests` es `async` y llama a `user_for_token` | **Confirmado**: I/O síncrono a PostgreSQL dentro del event loop | Se ejecuta con `run_in_threadpool` (`src/api/main.py`). No se convirtió nada a async: el ORM y el driver son síncronos (regla del plan §9). |
| `user_for_token` | **3 consultas** por petición (sesión + usuario + rol por carga perezosa). Valida expiración y usuario activo. | `joinedload` → **1 consulta** por la clave primaria (`src/services/auth_service.py`). |
| Tiempos por etapa (1.4) | No había ninguna medición | Encabezados `X-Request-ID` y `Server-Timing` (total, autenticación, SQL: cantidad y ms) en cada respuesta; log de peticiones lentas (`SLOW_REQUEST_MS`). Nunca se registran tokens, cookies ni datos personales. |
| Errores y timeouts (1.6) | Un pool agotado dejaba la petición esperando hasta 30 s | `pool_timeout` 10 s y respuesta **503 + `Retry-After`** con mensaje claro, también si ocurre durante la autenticación. El frontend lo muestra y reintenta con backoff. |
| Endpoints de Cacería (1.5) | Son `def` (corren en el threadpool): correcto. Sin otras llamadas bloqueantes en handlers `async`. | Sin cambios. |

Regresión (1.7): login, logout, rutas públicas, rutas protegidas, cambio de
contraseña obligatorio y roles cubiertos por las pruebas existentes y por
`tests/test_performance_optimizations.py::TestAuthentication`.

## 3. Integrante 2 — Frontend y Cacería en Vivo

Archivo: `src/api/static/live-quiz.js` (nuevo `createLivePoller`).

* **2.2 Sin solicitudes solapadas:** `setInterval` reemplazado por
  `setTimeout` agendado al terminar cada consulta. Una sola consulta de
  estado en vuelo por pantalla; `refreshNow()` no duplica una en curso.
* **2.3 Ciclo de vida:** al cerrar el modal, salir, cambiar de actividad,
  cerrar sesión o terminar el quiz se detiene el ciclo y se **aborta** la
  consulta en curso (`AbortController`). El intervalo del cronómetro (250 ms)
  ya no queda corriendo para siempre.
* **2.4 Backoff:** ante errores el intervalo se duplica (con jitter) hasta
  15 s y vuelve al normal al recuperarse. Se muestra «Sin conexión…
  Reintentando en N s».
* **2.5 Frecuencia:** se mantienen 1 s (docente) y 1.5 s (estudiante), que
  ahora son un *máximo* real. Con la pestaña oculta se consulta cada 5 s y al
  volver se consulta al instante. El cronómetro sigue siendo local.
* **2.6 Menos renderizado:** en la pregunta y la sala de espera solo se
  actualizan los contadores; antes se reconstruía el panel entero (y la
  imagen del QR) cada segundo.
* **2.7 Envío de respuestas:** botón bloqueado mientras se envía, sin doble
  POST, timeout de 10 s con mensaje recuperable; las consultas que salieron
  antes de responder se descartan (evita que reaparezcan los botones).
  Reintentar es seguro: la base tiene restricción única por pregunta.
* **Docente:** las consultas en vuelo al pulsar «Avanzar» se descartan (antes
  podían devolver la fase anterior y hacer parpadear la pantalla).
* **2.8 Redes lentas:** toda consulta de estado se aborta a los 8 s; la
  interfaz nunca queda «cargando» indefinidamente.
* Otros ciclos de baja frecuencia (ranking 10 s, actividades 15 s, estado de
  la API 30 s) no consultan con la pestaña oculta.

Pruebas automatizadas en navegador real (Chromium):
`tests/test_live_poller_frontend.py` — nunca más de una consulta en vuelo con
un servidor 6× más lento que el intervalo, backoff y recuperación, `stop()`
aborta y no agenda nada, timeout.

## 4. Integrante 3 — PostgreSQL y acceso a datos

| Punto | Antes | Después |
|---|---|---|
| `_leaderboard` (3.3) | Cargaba todos los envíos, respuestas y estudiantes como objetos ORM (3 consultas) y sumaba en Python | **1 consulta agregada** (`GROUP BY` del envío) en PostgreSQL |
| Recalcular sin cambios (3.4) | Se recalculaba en cada consulta de cada estudiante en `reveal`/`finished` y en cada consulta del docente | **Caché por actividad** validada por una *huella* de datos (participantes, respuestas, últimos ids, nº de preguntas). Se invalida sola al entrar una respuesta o un participante, y es correcta con varios procesos. Con 40 estudiantes mirando resultados se calcula 1 vez, no 40. |
| Estado del docente | Cargaba todas las respuestas de la pregunta como objetos y repetía el conteo de participantes | Conteo agrupado por alternativa; el conteo se reutiliza del ranking |
| Listado de actividades (3.5) | **N+1**: un `count(*)` por actividad del curso | Un solo conteo agrupado |
| Pool (3.7) | `create_engine` sin parámetros (5 + 10, espera 30 s, sin comprobación de conexión) | Mismos tamaños por defecto (no se subieron sin evidencia), `pool_pre_ping`, `pool_recycle` 30 min, espera 10 s, todo configurable por variables `DB_*` (ver `.env.example`). `DB_STATEMENT_TIMEOUT_MS` opcional. |
| Índices (3.6) | — | **No se crearon índices nuevos.** Las consultas críticas ya usan índices existentes: `auth_sessions` por clave primaria, `quick_activity_responses.activity_id`, `quick_activity_answers (response_id, question_id)` (restricción única), `students.user_id`. Crear índices sin un plan de consulta que los pida contradice el plan. |
| Transacciones (3.8) | Las sesiones se abren con `with` y se cierran siempre | Sin cambios; ninguna operación externa (correo) ocurre con transacción abierta en estas rutas. |

**Exactitud del ranking (criterio de aceptación):** la prueba
`test_aggregated_ranking_matches_legacy_algorithm` compara el ranking nuevo
con una copia literal del algoritmo anterior sobre datos con empates de
puntaje y tiempo, `points`/`response_ms` nulos, `is_correct` nulo y
estudiantes sin respuestas: los resultados son idénticos. Otras pruebas
verifican la invalidación de la caché.

**Pool en Render:** el plan gratuito de PostgreSQL de Render admite un número
limitado de conexiones. Con un solo proceso uvicorn (configuración actual)
el máximo es 15. Si se agregan procesos (`--workers`), recalcular:
`(DB_POOL_SIZE + DB_MAX_OVERFLOW) × procesos < max_connections`.

## 5. Integrante 4 — QA, observabilidad y carga

* `scripts/benchmark_live.py`: prueba de carga reproducible del escenario D
  del plan (1 docente + N estudiantes): levanta la API real con uvicorn,
  siembra datos ficticios, reproduce el patrón de tráfico, mide
  p50/p95/p99/máx., errores, timeouts y peticiones en vuelo, verifica que
  cada respuesta se registró una sola vez y cuenta consultas SQL por
  endpoint. **Se niega a correr contra hosts que no sean localhost**
  (borra las tablas). Funciona contra cualquier checkout (`--app-dir`), así
  se compara la versión base con la optimizada.
* `/admin/metrics` (solo administrador): p50/p95/p99/máx. y errores 5xx por
  ruta, y estado del pool. `?reset=true` antes de cada corrida.
* Cómo repetir la medición:

```bash
git worktree add /tmp/xproject-base main
python scripts/benchmark_live.py --app-dir /tmp/xproject-base --database-url postgresql+psycopg://bench:bench@localhost/bench --students 40 --output base.json
python scripts/benchmark_live.py --database-url postgresql+psycopg://bench:bench@localhost/bench --students 40 --output nuevo.json
```

## 6. Otras mejoras de buenas prácticas

* **Gzip** para HTML/JS/CSS/JSON > 1 KB (audio, imágenes y respuestas
  parciales quedan excluidos). Medido: la página completa pasa de **532 KB a
  118 KB** en la primera carga (`app.js`: 239 KB → 54 KB). Con 40 celulares
  entrando a la vez son ~16 MB menos de tráfico.
* **Caché revalidable de `/assets`:** antes `no-store` (descarga completa en
  cada carga). Ahora `no-cache`: el navegador guarda el archivo y pregunta si
  cambió (respuesta 304 sin cuerpo, **0 bytes**); un despliegue nuevo se ve
  al instante.
* **Seguridad:** `.env.example` contenía una cuenta y una contraseña de
  aplicación SMTP reales; se reemplazaron por marcadores. **La contraseña
  sigue en el historial de git: hay que revocarla en la cuenta de Google y
  generar una nueva**, guardándola solo en el gestor de secretos de Render.

## 7. Pendientes y riesgos

* Repetir `benchmark_live.py` contra una **instancia de pruebas en Render**
  (no producción) para tener cifras con la red y CPU reales del plan
  gratuito.
* Tres pruebas de `tests/test_integral_demo.py` **ya fallaban en `main`**
  antes de estos cambios (docente sin cursos aceptado con 201; dos pruebas
  dependientes de estado compartido). No se tocaron: son funcionales y ajenas
  a este plan.
* `test_finished_live_quiz_includes_full_ranking_and_answer_stats` es
  **inestable también en `main`** (falló 9 de 12 veces en la versión base):
  dos estudiantes empatan con 0 puntos y el desempate es aleatorio por
  diseño (`_random_tie_key` sobre el código del quiz, que es aleatorio), pero
  la prueba exige un orden fijo. El ranking nuevo da el mismo orden que el
  anterior (ver prueba de equivalencia); la corrección es que la prueba
  acepte cualquier orden entre empatados.
* Las pruebas del navegador (`tests/test_live_poller_frontend.py`) requieren
  `pip install playwright` y Chromium; si no están, se omiten.
* `_live_participant` todavía hace 5 consultas por estado del estudiante
  (actividad, preguntas, matrícula, envío, respuestas); podría bajarse a 3
  si las mediciones en Render lo justifican.
* `src/app.js`, `src/styles.css` e `src/index.html` son copias antiguas que
  no se sirven; conviene eliminarlas.
