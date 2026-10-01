# Selección Inteligente — Bayesian Fairness Bandit (versión producción)

Este proyecto rediseña por completo tu entregable original de simulación
para convertirlo en un **sistema de producción real**: uno donde el
estado de cada estudiante persiste entre requests, sobrevive reinicios,
soporta múltiples cursos y múltiples decisiones concurrentes, y queda
completamente auditado.

No incluye frontend ni UI. Es 100% lógica de negocio, persistencia y una
API HTTP — el "backend" que un frontend, una app móvil o el sistema de
asistencia de un colegio consumirían.

\---

## 0\. La pregunta que originó este rediseño (y su respuesta corta)

Preguntaste, en esencia: *"en mi simulación el 'historial' de cada
estudiante parece guardarse porque todo pasa en una sola corrida — pero
en producción no hay una sola corrida, hay muchos requests a lo largo
del tiempo. ¿Cómo persisto eso de verdad?"*

La respuesta corta, ya implementada en este proyecto:

1. **No se persiste "una corrida".** Se persiste el **estado bayesiano
acumulado** de cada estudiante (`alpha`, `beta`, `n\_present`,
`n\_selected`) en una tabla (`student\_state`), más un **log de
eventos** (`selection\_events`) para auditoría/trazabilidad completa.
2. Los **algoritmos de selección no cambian de forma matemática** —
siguen siendo Strategy — pero dejaron de mutar arrays en memoria:
ahora reciben un *snapshot* inmutable del estado (`Candidate`) y
devuelven *qué cambios habría que aplicar* (`PosteriorUpdate`), sin
aplicarlos ellos mismos.
3. Quien aplica esos cambios es la capa de persistencia, con
**actualizaciones atómicas** (`UPDATE ... SET alpha = alpha + delta`)
dentro de una **transacción** que primero toma un bloqueo de lectura
(`SELECT ... FOR UPDATE`) — así es como se evita que dos requests
simultáneos sobre el mismo estudiante se "pisen" y se pierda una
actualización.
4. La simulación Monte Carlo **no desaparece**: se reconstruyó para
correr sobre las mismas piezas (mismas estrategias, mismo servicio de
aplicación) respaldadas por un almacenamiento en memoria en vez de una
base de datos real. Es la prueba de que el diseño es correcto: la
lógica de negocio no sabe (ni le importa) si el estado vive en un
diccionario de Python o en PostgreSQL.

El resto de este documento explica en detalle cómo se logró esto.

\---

## 1\. Cómo leer este proyecto (orden recomendado)

No leas las carpetas en orden alfabético. Este es el orden pensado para
entender el proyecto de la forma más eficiente:

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
* **`selection\_events`**: log de auditoría, un registro por estudiante
considerado en cada `decision\_run`, con alpha/beta antes y después.

\---

## 3\. Patrones de diseño aplicados (y por qué)

|Patrón|Dónde|Para qué|
|-|-|-|
|**Strategy**|`src/strategies/`|Ya existía en tu proyecto original; se conserva y se limpia: los algoritmos ahora son puros (reciben `Candidate`, devuelven decisiones + deltas, no mutan nada).|
|**Factory / Registry**|`src/strategies/registry.py`|Reemplaza el `if/elif`/dict manual de `build\_selectors`. Cada estrategia se auto-registra con un decorador; agregar un método nuevo no toca ningún otro archivo.|
|**Repository**|`src/repositories/interfaces.py` + 2 implementaciones|Desacopla la lógica de negocio de dónde vive el estado. Permite que `SelectionService` funcione igual sobre SQLite/PostgreSQL o sobre un diccionario en memoria.|
|**Unit of Work**|`UnitOfWork` (interfaz) + `SqlAlchemyUnitOfWork` / `InMemoryUnitOfWork`|Garantiza que "leer con bloqueo + decidir + actualizar + registrar evento" se confirme o se descarte como una sola unidad atómica.|
|**Dependency Injection**|`SelectionService.\_\_init\_\_(uow\_factory, ...)`, `Depends(...)` en FastAPI|Nada se instancia "a mano" dentro de la lógica de negocio; todo se inyecta desde `services/bootstrap.py` (composition root).|
|**Value Object / DTO**|`src/domain/value\_objects.py`|`Candidate`, `PosteriorUpdate`, `DecisionResult` son el "idioma común" inmutable entre capas, evitando que se filtren detalles de un ORM o de un esquema HTTP hacia la lógica de negocio.|
|**Observer (event bus ligero)**|`src/domain/events.py`|Punto de extensión opcional: hoy solo hay un `logging\_subscriber`, pero se puede enganchar notificaciones, invalidación de cache, etc. sin tocar `SelectionService`.|
|**Adapter** (implícito)|`repository\_impl.py` (ambas variantes)|Traducen entre el modelo de almacenamiento concreto (filas ORM / diccionarios) y los value objects del dominio.|

**Paradigma:** Programación Orientada a Objetos en toda la capa de
dominio/estrategias/repositorios (clases, herencia de `ABC` para los
contratos, encapsulamiento de estado), combinada con un estilo
funcional/inmutable en los value objects (`@dataclass(frozen=True)`) para
evitar mutaciones accidentales de estado compartido — deliberadamente
importante en un sistema con concurrencia.

\---

## 4\. Bugs encontrados y corregidos

Durante el análisis del proyecto original se encontraron tres problemas
reales, no solo de forma sino de fondo. Se corrigieron y se documentan
aquí (y en el docstring del código correspondiente) para que quede
constancia de qué cambió y por qué:

### 4.1. Selección duplicada dentro de una misma clase

`src/simulation/classroom.py` (original) seleccionaba de a un estudiante
por vez, en un bucle `for \_ in range(k\_per\_class)`, llamando a
`selector.select(present\_students, 1, rng)` sin remover al estudiante ya
elegido de `present\_students` para la siguiente vuelta. Esto hacía
posible que **un mismo estudiante fuera seleccionado más de una vez en
la misma clase** (particularmente visible en `roulette`, que no tiene
ninguna razón interna para evitarlo).

**Corrección:** `SelectionService.run\_selection` llama a
`selector.select(candidates, k, rng)` **una sola vez, con el k completo**
— exactamente como ya soportaba `BayesianFairnessBandit.select`
internamente (`argsort` + top-k) y como el propio README original
describe matemáticamente. Un top-k de una sola pasada nunca puede repetir
a nadie. Ver `tests/test\_selection\_service.py::test\_no\_student\_selected\_twice\_within\_one\_session`.

### 4.2. Sobre-conteo de `alpha` por "slot" en vez de por clase

Como consecuencia del mismo bucle, `update(...)` se llamaba una vez por
cada cupo de la clase, y cada vez incrementaba `alpha` en 1 para **todo**
estudiante presente que no fuera el elegido *en esa vuelta* —
incluyendo a quien ya había sido elegido en una vuelta anterior de la
misma clase. Con `k\_per\_class = 6`, un estudiante presente pero nunca
elegido podía acumular `alpha += 6` en una sola clase, en vez de `+= 1`.

**Corrección:** al aplicar `compute\_posterior\_updates` una sola vez por
clase (ver 4.1), cada estudiante considerado recibe **exactamente un**
delta (`alpha += 1` o `beta += 1`), nunca más de uno. Ver
`tests/test\_strategies.py::TestBayesianFairnessBandit::test\_posterior\_updates\_cover\_every\_considered\_candidate\_exactly\_once`.

### 4.3. Dependencia accidental de PySpark

`src/simulation/runner.py` (original) importaba y usaba
`pyspark.sql.SparkSession` para consolidar resultados — una dependencia
pesada (requiere JVM) que ni el `README.md` ni el `requirements.txt`
originales mencionaban, y que no aporta nada con los volúmenes de datos
del experimento (unos pocos miles de filas). Se interpreta como código
de otro experimento pegado por error.

**Corrección:** `src/simulation/experiment\_runner.py` usa `pandas` puro,
consistente con el resto del proyecto y con las librerías que sí estaban
declaradas originalmente.

\---

## 5\. Instalación y uso

### 5.1. Instalar dependencias

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\\Scripts\\activate     # Bash: source .venv/Scripts/activate
pip install -r requirements.txt
```

### 5.2. Correr los tests (recomendado como primer paso)

```bash
pytest -v
```

Deberías ver 44 tests en verde: estrategias, métricas, el servicio de
selección (con y sin concurrencia) y la API HTTP completa contra una
base de datos SQLite real.

### 5.3. Levantar la API de producción

```bash
python scripts/init\_db.py      # crea las tablas (SQLite local por defecto)
python scripts/run\_api.py --reload
```

Con el servidor corriendo, abrir `http://127.0.0.1:8000/docs` para la
documentación interactiva (Swagger UI), o probar directamente:

```bash
# 1. Crear un curso
curl -X POST http://127.0.0.1:8000/courses \\
  -H "Content-Type: application/json" \\
  -d '{"name": "Cálculo II - Sección 4"}'

# 2. Matricular un estudiante (idempotente por external\_ref)
curl -X POST http://127.0.0.1:8000/courses/1/students \\
  -H "Content-Type: application/json" \\
  -d '{"external\_ref": "2024-0001", "display\_name": "Ana Torres"}'

# 3. Ejecutar una selección real (present\_student\_ids son ids devueltos en el paso 2)
curl -X POST http://127.0.0.1:8000/courses/1/sessions/select \\
  -H "Content-Type: application/json" \\
  -d '{"present\_student\_ids": \[1,2,3,4,5], "k": 2, "method": "bayesian\_fairness"}'

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
|GET|`/courses/{id}`|Obtener un curso|
|POST|`/courses/{id}/students`|Matricular estudiante (idempotente)|
|GET|`/courses/{id}/students`|Listar estudiantes del curso|
|GET|`/students/{id}/state`|Estado bayesiano actual (alpha, beta, contadores)|
|GET|`/students/{id}/history`|Historial de eventos de selección|
|POST|`/courses/{id}/sessions/select`|**Ejecutar una selección real** (el caso de uso central)|
|GET|`/courses/{id}/fairness-metrics`|Gini / CV / std / cobertura del curso|

### 5.4. Correr el modo simulación (investigación / benchmark)

```bash
python scripts/run\_experiment.py
# o con parámetros distintos a config/default.yaml:
python scripts/run\_experiment.py --n-trials 500 --n-classes 30 --n-students 40
```

Genera `outputs/resultados\_completos.csv`, `outputs/resumen\_metricas\_finales.csv`
y gráficos comparativos (`outputs/evolucion\_\*.png`, `outputs/boxplot\_final\_\*.png`).

\---

## 6\. Concurrencia y elección de base de datos

El proyecto usa **SQLite por defecto** (cero configuración, un archivo
`.db`), ideal para desarrollo local, demos y para correr los tests. Para
un despliegue real se recomienda **PostgreSQL**: basta con cambiar
`DATABASE\_URL` (ver `.env.example`) a algo como

```
DATABASE\_URL=postgresql+psycopg://usuario:password@host:5432/basededatos
```

sin tocar ni una línea de `src/repositories/sqlalchemy/`.

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

## 7\. De aquí a producción real: qué falta

Este proyecto es un backend funcionalmente completo y probado, pero
antes de exponerlo a usuarios reales en internet, considera agregar:

* **Migraciones de esquema (Alembic):** hoy `scripts/init\_db.py` usa
`Base.metadata.create\_all(...)`, que crea tablas que faltan pero no
sabe migrar cambios sobre una base con datos reales (agregar una
columna, por ejemplo). Alembic es la herramienta estándar de
SQLAlchemy para esto.
* **Autenticación/autorización:** la API no tiene ningún control de
acceso hoy — cualquiera que le llegue puede crear cursos, matricular
estudiantes o disparar selecciones. Para un despliegue real hace falta
algún esquema de autenticación (API keys, OAuth2, JWT, según el
contexto) en `src/api/`.
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

## 8\. Estructura completa del proyecto

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
│   │   ├── fairness\_service.py        Métricas de equidad de solo lectura
│   │   └── bootstrap.py               Composition root (arma todo el sistema)
│   ├── metrics/
│   │   └── fairness\_metrics.py        Gini, CV, std, cobertura (sin cambios de diseño)
│   ├── api/                           Capa HTTP (FastAPI)
│   │   ├── main.py                    Endpoints
│   │   ├── schemas.py                 Modelos Pydantic de request/response
│   │   └── dependencies.py            Inyección de dependencias de FastAPI
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
    └── test\_api.py                    Integración HTTP completa, contra SQLite real
```

