"""Capa de persistencia: patrón Repository + patrón Unit of Work.

`interfaces.py` define los contratos (ABCs) de los que depende el resto
del sistema (`services/`). Hay dos implementaciones intercambiables:

- `repositories/sqlalchemy/`: respaldada por una base de datos real
  (SQLite por defecto, PostgreSQL recomendado en producción — basta con
  cambiar la cadena de conexión, ver `config/default.yaml`). Usa
  `SELECT ... FOR UPDATE` + `UPDATE ... SET x = x + delta` para que las
  actualizaciones sean atómicas incluso con múltiples requests
  concurrentes.

- `repositories/in_memory/`: respaldada por diccionarios de Python en
  memoria. La usan la simulación Monte Carlo (`src/simulation/`) y los
  tests unitarios, porque son órdenes de magnitud más rápidas que tocar
  una base de datos real y no necesitan de un motor externo.

`services/selection_service.py` (y cualquier otro caso de uso) depende
solo de `interfaces.py`, nunca de una implementación concreta -- ese es
justamente el punto del patrón Repository: la lógica de negocio no sabe
ni le importa si el estado vive en Postgres o en un dict.
"""
