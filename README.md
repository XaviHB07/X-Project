# Project X - El Lobo Feroz

## 1\. Cómo leer este proyecto (orden recomendado)

\---

1. **Este README**, completo — te da el mapa mental antes de tocar código.
2. **`src/domain/value\_objects.py`** — el "idioma común" entre capas
(`Candidate`, `PosteriorUpdate`). Todo el resto del proyecto gira
alrededor de estos dos tipos.
3. **`src/strategies/base.py`** y luego **`src/strategies/bayesian\_fairness.py`**
— el algoritmo central, ahora desacoplado de la persistencia.
4. **`src/repositories/interfaces.py`** — los contratos de persistencia
(Repository + Unit of Work), sin implementación todavía.
5. **`src/services/selection\_service.py`** — el caso de uso central:
aquí se ve el flujo completo (cargar -> elegir -> guardar) armado con
las piezas anteriores. **Lee su docstring completo**: ahí se explica
un bug real que tenía tu proyecto original y cómo se corrigió.
6. **`src/repositories/sqlalchemy/repository\_impl.py`** — cómo se
implementa, en SQL real, la actualización atómica bajo concurrencia.
7. **`src/api/main.py`** — cómo se expone todo lo anterior como una API
HTTP real.
8. **`src/simulation/engine.py`** — cómo el modo simulación reutiliza
exactamente el mismo `SelectionService` y las mismas estrategias.
9. **`tests/`** — en particular `test\_selection\_service.py` y
`test\_concurrency.py`: son la demostración ejecutable de que todo lo
anterior funciona como se describe.

Cada archivo tiene un docstring de módulo largo explicando **por qué**
existe y qué decisión de diseño representa, no solo qué hace. Está
pensado para leerse como documentación, no solo como comentarios sueltos.

\---

## 2\. Arquitectura en capas

```
┌─────────────────────────────────────────────────────────────────┐
│  src/api/            Capa HTTP (FastAPI)                        │
│  - main.py, schemas.py, dependencies.py                         │
│  - Único punto de entrada para clientes externos                │
└───────────────────────────┬───────────────────────────────────--┘
                             │ llama a
┌───────────────────────────▼───────────────────────────────────┐
│  src/services/       Casos de uso (orquestación)                │
│  - SelectionService: el caso de uso central                     │
│  - FairnessMetricsService: lectura de métricas                  │
│  - bootstrap.py: composition root (wiring de todo)               │
└──────────────┬────────────────────────────────┬─────────────────┘
               │ usa                            │ usa
┌──────────────▼─────────────────┐  ┌───────────▼─────────────────┐
│  src/strategies/                │  │  src/repositories/            │
│  - BaseSelector (Strategy)      │  │  - interfaces.py (contratos)  │
│  - Roulette / WeightedSoftmax / │  │  - sqlalchemy/ (producción)   │
│    BayesianFairnessBandit       │  │  - in\_memory/ (sim. y tests)  │
│  - SelectorRegistry (Factory)   │  │  - patrón Unit of Work        │
└──────────────┬───────────────────┘  └────────────────────────────┘
               │ opera sobre
┌──────────────▼──────────────────────────────────────────────────┐
│  src/domain/          Value objects y entidades (sin dependencias)│
│  - Candidate, PosteriorUpdate, DecisionResult, EventBus           │
└────────────────────────────────────────────────────────────────--┘

┌────────────────────────────────────────────────────────────────┐
│  src/simulation/      Modo investigación (Monte Carlo)           │
│  - engine.py: corre sobre SelectionService + repos in-memory      │
│  - experiment\_runner.py: agrega resultados en pandas             │
│  src/metrics/         Gini, CV, std, cobertura (compartido)       │
│  src/visualization/   Gráficos comparativos (solo simulación)     │
└────────────────────────────────────────────────────────────────--┘
```

**Regla de dependencia (de arriba hacia abajo, nunca al revés):**
`api` → `services` → `strategies` + `repositories` → `domain`. El
`domain` no importa nada de las capas de arriba; `strategies` no importa
SQLAlchemy ni FastAPI; ninguna capa de negocio sabe si está corriendo en
un servidor HTTP o dentro de una simulación en memoria.

### Esquema de base de datos (producción)

```
courses (1) ──< students (1) ── (1) student\_state
courses (1) ──< class\_sessions (1) ──< decision\_runs (1) ──< selection\_events >── students
courses (1) ──< syllabus\_entries
class\_sessions (1) ──< session\_attendance >── students
```

* **`courses`**: contenedor de estudiantes (permite correr varios cursos
en paralelo sobre la misma base de datos).
* **`students`**: identidad del estudiante (casi no cambia).
* **`student\_state`**: el estado bayesiano mutable — `alpha`, `beta`,
`n\_present`, `n\_selected`. Es la tabla que sufre escrituras
concurrentes; por eso está separada de `students`.
* **`class\_sessions`**: una ocurrencia real de "clase"/"evento de
selección" (antes era implícito, un `for` en la simulación).
* **`decision\_runs`**: una invocación del servicio de selección — la
unidad transaccional.
* **`syllabus\_entries`**: tema previsto por (curso, fecha); alimenta la propuesta de HU-S1.
* **`session\_attendance`**: marca presente/ausente de cada estudiante en cada sesión (HU-S2).
* **`selection\_events`**: log de auditoría, un registro por estudiante
considerado en cada `decision\_run`, con alpha/beta antes y después.

\---

## 3\. Instalación y uso

### 3.1. Instalar dependencias

```bash
python3 -m venv .venv (o python -m venv .venv )
# Windows PowerShell: .venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
# Git Bash: source .venv/Scripts/activate
pip install -r requirements.txt
```

### 3.2. Correr los tests (recomendado como primer paso)

```bash
pytest -v
```

Deberías ver todos los tests en verde: estrategias, métricas, el servicio de
selección (con y sin concurrencia), la importación del Excel de estudiantes,
las sesiones con asistencia (Sprint 1) y la API HTTP completa contra bases de
datos SQLite temporales.

### 3.3. Levantar la API de producción

```bash
export DATABASE_URL='postgresql+psycopg://seleccion_app:CAMBIAR_PASSWORD@localhost:5432/seleccion_bayesiana'
python scripts/init_db.py      # crea las tablas dentro de la base PostgreSQL
python scripts/run_api.py --reload
```

Para crear la base PostgreSQL local por primera vez, instala/inicia
PostgreSQL y ejecuta como administrador (cambia la contraseña de ejemplo):

```sql
CREATE ROLE seleccion_app WITH LOGIN PASSWORD 'CAMBIAR_PASSWORD';
CREATE DATABASE seleccion_bayesiana OWNER seleccion_app;
```

Guarda la URL con tus credenciales en tu entorno local o expórtala antes de
iniciar la API. No subas contraseñas al repositorio. `.env.example` es una
plantilla: el proyecto no carga `.env` automáticamente. Si ya tienes una base
y un usuario de PostgreSQL, omite la creación y configura `DATABASE_URL` con
los datos que te proporcionó el administrador.

Con el servidor corriendo, abrir `http://127.0.0.1:8000/docs` para la
documentación interactiva (Swagger UI), o `http://127.0.0.1:8000/` para
el panel web. Desde el panel puedes crear o cargar un curso. En
**Administrar estudiantes** se carga la lista una vez, se matriculan
estudiantes y se editan sus datos de contacto; en **Asistencia** solo se
muestran los estudiantes activos para la clase. También puedes ejecutar una
selección y consultar el estado e historial individual. Los cursos recientes se recuerdan en el
navegador; los datos del sistema quedan en la base PostgreSQL configurada.
El selector de rol de la esquina inferior izquierda permite alternar entre
Profesor y Administrador; ambos pueden administrar la matrícula en esta
versión del MVP.

También se pueden probar los endpoints directamente:

```bash
# 1. Crear un curso
curl -X POST http://127.0.0.1:8000/courses \
  -H "Content-Type: application/json" \
  -d '{"name": "Cálculo II - Sección 4"}'

# 2. Matricular un estudiante (idempotente por external_ref)
curl -X POST http://127.0.0.1:8000/courses/1/students \
  -H "Content-Type: application/json" \
  -d '{"external_ref": "2024-0001", "display_name": "Ana Torres"}'

# 3. Ejecutar una selección real (present_student_ids son IDs devueltos en el paso 2)
curl -X POST http://127.0.0.1:8000/courses/1/sessions/select \
  -H "Content-Type: application/json" \
  -d '{"present_student_ids": [1,2,3,4,5], "k": 2, "method": "bayesian_fairness"}'

# 4. Ver el estado actual de un estudiante
curl http://127.0.0.1:8000/students/1/state

# 5. Ver su historial de eventos
curl http://127.0.0.1:8000/students/1/history

# 6. Métricas de equidad del curso completo
curl http://127.0.0.1:8000/courses/1/fairness-metrics
```

#### Referencia rápida de endpoints

|Método|Ruta|Qué hace|
|-|-|-|
|GET|`/health`|Chequeo de salud|
|GET|`/methods`|Estrategias de selección disponibles|
|POST|`/courses`|Crear un curso|
|GET|`/courses`|Listar cursos (HU-S1)|
|GET|`/courses/{id}`|Obtener un curso|
|POST|`/courses/{id}/students`|Matricular estudiante (teléfono y correo opcionales)|
|POST|`/courses/{id}/students/import`|**HU-C1**: cargar/recargar la lista desde un Excel `.xlsx`|
|GET|`/courses/{id}/students`|Listar estudiantes activos (`?include_inactive=true` incluye retirados)|
|PATCH|`/students/{id}`|**HU-C1**: editar datos, retirar o reincorporar|
|GET|`/students/{id}/state`|Estado bayesiano actual (alpha, beta, contadores)|
|GET|`/students/{id}/history`|Historial de eventos de selección|
|POST|`/courses/{id}/syllabus`|Registrar el tema previsto para una fecha (insumo de HU-S1)|
|GET|`/courses/{id}/syllabus`|Listar el sílabo del curso|
|GET|`/courses/{id}/class-sessions/proposal`|**HU-S1**: fecha y tema propuestos antes de iniciar|
|POST|`/courses/{id}/class-sessions`|**HU-S1**: iniciar sesión (tema confirmado/corregido) con asistencia inicial|
|GET|`/courses/{id}/class-sessions`|Listar sesiones del curso|
|GET|`/class-sessions/{id}`|Detalle de la sesión con su asistencia|
|PUT|`/class-sessions/{id}/attendance`|**HU-S2**: marcar/desmarcar asistencia|
|POST|`/courses/{id}/sessions/select`|**Ejecutar una selección real**. Sin `present_student_ids`, usa la asistencia de `class_session_id`|
|GET|`/courses/{id}/fairness-metrics`|Gini / CV / std / cobertura del curso|

#### Sprint 1: lista por Excel, sesiones y asistencia

```bash
# HU-C1: cargar la lista (.xlsx con columnas "codigo" y "nombre")
curl -X POST http://127.0.0.1:8000/courses/1/students/import \
  -F "file=@lista.xlsx;type=application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# HU-S1: ver la propuesta de fecha/tema e iniciar la sesión
curl "http://127.0.0.1:8000/courses/1/class-sessions/proposal"
curl -X POST http://127.0.0.1:8000/courses/1/class-sessions \
  -H "Content-Type: application/json" -d '{"topic": "Límites y continuidad"}'

# HU-S2: marcar ausente a un estudiante y seleccionar solo entre los presentes
curl -X PUT http://127.0.0.1:8000/class-sessions/1/attendance \
  -H "Content-Type: application/json" \
  -d '{"attendance": [{"student_id": 3, "present": false}]}'
curl -X POST http://127.0.0.1:8000/courses/1/sessions/select \
  -H "Content-Type: application/json" \
  -d '{"class_session_id": 1, "k": 2, "method": "bayesian_fairness"}'
```

Reglas del Excel: el sistema busca el encabezado en las filas, sin asumir
un número fijo, y reconoce `codigo`/`matricula` y `nombre`/`alumno`/
`apellidos y nombres` (sin importar mayúsculas ni tildes). Las columnas
`telefono`/`celular` y `correo`/`email` son opcionales; si una reimportación
no trae esos campos, conserva el contacto que ya estaba registrado. Antes del
encabezado debe aparecer el código o el nombre del curso, por ejemplo en el
título del archivo; el código/nombre se valida como contexto y el `course_id`
de la ruta HTTP determina a qué curso se asocian los estudiantes. Así se
pueden importar listas de distintos cursos usando el mismo endpoint. Si falta
una columna obligatoria, el contexto del curso o el archivo no es `.xlsx`, se responde
400 y no se guarda nada. Si solo algunas filas son inválidas (sin nombre,
código repetido…), las válidas se guardan y las inválidas se devuelven con
su número de fila original. Volver a cargar el archivo es seguro: actualiza
nombres y contactos presentes, reactiva retirados y no duplica. La edición
manual permite corregir nombre, código, teléfono y correo; los campos de
contacto pueden dejarse vacíos.

Decisiones del Sprint 1: al iniciar una sesión todos los estudiantes activos
quedan presentes por defecto (el docente desmarca a los ausentes); retirar
a un estudiante lo oculta pero conserva su historial; el sílabo se registra
por fecha con `POST /courses/{id}/syllabus` (la carga masiva queda fuera de
este sprint).

### 3.4. Correr el modo simulación (investigación / benchmark)

```bash
python scripts/run_experiment.py
# o con parámetros distintos a config/default.yaml:
python scripts/run_experiment.py --n-trials 500 --n-classes 30 --n-students 40
```

Genera `outputs/resultados_completos.csv`, `outputs/resumen_metricas_finales.csv`
y gráficos comparativos (`outputs/evolucion_*.png`, `outputs/boxplot_final_*.png`).

\---

## 4\. Concurrencia y elección de base de datos

La API usa **PostgreSQL por defecto** para el trabajo compartido del MVP.
Configura `DATABASE\_URL` (ver `.env.example`) con usuario, contraseña y
host de tu instancia. Para tests y desarrollo aislado, SQLite sigue
disponible configurando, por ejemplo, `DATABASE\_URL=sqlite:///./local.db`;
las pruebas de API ya usan bases SQLite temporales.

```
DATABASE\_URL=postgresql+psycopg://usuario:password@host:5432/basededatos
```

La URL de conexión usa el esquema `postgresql+psycopg`, el host, el puerto
(5432 por defecto) y el nombre de la base de datos. No es necesario modificar
`src/repositories/sqlalchemy/` al cambiar de servidor.

**¿Por qué PostgreSQL para producción real?** `get\_candidates\_for\_update`
usa `SELECT ... FOR UPDATE` para tomar un bloqueo de escritura sobre las
filas de `student\_state` involucradas en una decisión, hasta que la
transacción hace commit o rollback. En PostgreSQL (y MySQL/InnoDB) esto
es un bloqueo **por fila**: dos decisiones sobre estudiantes distintos no
se bloquean entre sí. SQLite no soporta bloqueo por fila — serializa
toda la base de datos a nivel de archivo en cuanto alguien escribe — así
que `with\_for\_update()` ahí es un no-op inofensivo y la seguridad ante
concurrencia se mantiene, pero de forma más burda (todo el archivo, no
solo las filas relevantes). Para un sistema con muchos cursos/decisiones
simultáneas, esa diferencia sí importa.

La combinación de bloqueo de lectura + `UPDATE ... SET x = x + delta`
(en vez de "leer en Python, sumar, escribir") es lo que evita el
**lost update**: sin esto, dos decisiones concurrentes sobre el mismo
estudiante podrían leer el mismo `alpha` "viejo" y una de las dos
escrituras pisaría a la otra silenciosamente. `tests/test\_concurrency.py`
lo demuestra con 8 threads compitiendo por los mismos 10 estudiantes: al
final, la suma de `n\_present` y `n\_selected` de todos los estudiantes
cuadra exactamente con lo esperado — ninguna actualización se perdió.

\---

## 5\. De aquí a producción real: qué falta

Este proyecto es un backend funcionalmente completo y probado, pero
antes de exponerlo a usuarios reales en internet, considera agregar:

* **Migraciones de esquema (Alembic):** hoy `scripts/init\_db.py` usa
`Base.metadata.create\_all(...)`, que crea tablas que faltan pero no
sabe migrar cambios sobre una base con datos reales (agregar una
columna, por ejemplo). Como parche mínimo, `bootstrap.py` agrega
al arrancar las columnas nuevas del Sprint 1 (`students.active`,
`class_sessions.session_date`/`topic`) a bases anteriores; cualquier
cambio futuro debería pasar a Alembic. Alembic es la herramienta estándar de
SQLAlchemy para esto.
* **Autenticación/autorización:** la API no valida identidades ni roles.
El selector Profesor/Administrador del panel solo cambia el rol visible
localmente; no concede permisos de seguridad. No expongas la API a internet
sin añadir autenticación real.
* **Paginación:** `GET /courses/{id}/students` y `/students/{id}/history`
devuelven todo de una vez; con cursos grandes o historiales largos
convendría paginar.
* **Rate limiting / validación de tamaño de curso:** para proteger el
servicio de solicitudes de `k` o `present\_student\_ids` absurdamente
grandes.
* **Observabilidad:** hoy solo hay logging básico vía el `EventBus`
(`logging\_subscriber`); en producción real conviene métricas
(Prometheus/Grafana) y tracing distribuido si el sistema crece.
* **Índices de base de datos** explícitos sobre columnas de búsqueda
frecuente (`selection\_events.student\_id`, `students.course\_id`) si el
volumen de datos crece mucho — hoy dependen de las claves foráneas por
defecto del motor.

Ninguno de estos puntos cambia la arquitectura (capas, patrones,
contratos) descrita en este README: son extensiones sobre la misma base.

\---

## 6\. Estructura completa del proyecto

```
seleccion\_bayesiana/
├── README.md                          Este archivo
├── requirements.txt                   Dependencias Python
├── .env.example                       Variables de entorno de ejemplo
├── conftest.py                        Hace `src` importable para pytest
├── config/
│   └── default.yaml                   Configuración (BD, hiperparámetros, experimento)
├── src/
│   ├── domain/                        Entidades y value objects (sin dependencias externas)
│   │   ├── entities.py                Course, Student, StudentState, ClassSession, DecisionRun
│   │   ├── value\_objects.py           Candidate, PosteriorUpdate, DecisionResult (el "idioma común")
│   │   └── events.py                  DecisionRunCompleted + EventBus (Observer, opcional)
│   ├── strategies/                    Algoritmos de selección (Strategy) + registro (Factory)
│   │   ├── base.py                    BaseSelector (interfaz)
│   │   ├── roulette.py                Nivel 1: selección uniforme
│   │   ├── weighted\_softmax.py        Nivel 2: ponderado por historial
│   │   ├── bayesian\_fairness.py       Nivel 3: Thompson Sampling invertido (el algoritmo central)
│   │   └── registry.py                SelectorRegistry (Factory/Registry dinámico)
│   ├── repositories/                  Persistencia (Repository + Unit of Work)
│   │   ├── interfaces.py              Contratos abstractos (ningún detalle de BD aquí)
│   │   ├── sqlalchemy/                Implementación real (SQLite/PostgreSQL)
│   │   │   ├── models.py              Modelos ORM
│   │   │   ├── repository\_impl.py     Repos concretos + bloqueo/actualización atómica
│   │   │   └── unit\_of\_work.py        Transacción real
│   │   └── in\_memory/                 Implementación en memoria (simulación y tests)
│   │       ├── repository\_impl.py     Repos respaldados por diccionarios + lock
│   │       └── unit\_of\_work.py        "Transacción" in-memory
│   ├── services/                      Casos de uso (orquestan strategies + repositories)
│   │   ├── selection\_service.py       EL caso de uso central — leer esto con cuidado
│   │   ├── roster\_import.py           Lee y valida el Excel de estudiantes (HU-C1, sin BD)
│   │   ├── roster\_service.py          Importar lista, editar/retirar estudiantes (HU-C1)
│   │   ├── session\_service.py         Iniciar sesión, tema propuesto, asistencia (HU-S1, HU-S2)
│   │   ├── errors.py                  Errores de dominio de los servicios
│   │   ├── fairness\_service.py        Métricas de equidad de solo lectura
│   │   └── bootstrap.py               Composition root (arma todo el sistema)
│   ├── metrics/
│   │   └── fairness\_metrics.py        Gini, CV, std, cobertura (sin cambios de diseño)
│   ├── api/                           Capa HTTP (FastAPI)
│   │   ├── main.py                    Endpoints
│   │   ├── schemas.py                 Modelos Pydantic de request/response
│   │   ├── dependencies.py            Inyección de dependencias de FastAPI
│   │   └── static/                    Panel web servido por FastAPI
│   │       ├── index.html              Interfaz del sistema
│   │       ├── styles.css              Estilos responsive
│   │       └── app.js                  Integración con la API
│   ├── simulation/                    Modo investigación (Monte Carlo), sobre las mismas piezas
│   │   ├── engine.py                  Un trial completo, vía SelectionService + repos in-memory
│   │   └── experiment\_runner.py       Orquesta múltiples trials -> DataFrame
│   └── visualization/
│       └── plots.py                   Gráficos comparativos (solo simulación)
├── scripts/
│   ├── init\_db.py                     Crea el esquema de base de datos
│   ├── run\_api.py                     Levanta la API con uvicorn
│   └── run\_experiment.py              CLI del experimento Monte Carlo
└── tests/
    ├── test\_strategies.py             Estrategias + registro, en aislamiento
    ├── test\_metrics.py                Métricas de equidad
    ├── test\_selection\_service.py      El caso de uso central, sobre repos in-memory
    ├── test\_concurrency.py            Prueba de concurrencia (no lost updates)
    ├── test\_roster\_import.py          Parser del Excel (HU-C1)
    ├── test\_roster\_service.py         Importar/editar lista sobre repos in-memory (HU-C1)
    ├── test\_session\_service.py        Sesiones, asistencia y selección por asistencia (HU-S1/S2)
    └── test\_api.py                    Integración HTTP completa, contra SQLite temporal
```
