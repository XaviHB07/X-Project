"""Implementación de persistencia respaldada por estructuras en memoria
(diccionarios de Python), protegida con un `threading.Lock` para simular
la misma garantía de "no lost updates" que la implementación SQLAlchemy
logra con `SELECT ... FOR UPDATE`.

Uso previsto:

- `src/simulation/`: el motor de simulación Monte Carlo corre miles de
  "trials" sin necesitar una base de datos real; usar SQLite en disco
  para eso sería lento y innecesario.
- `tests/`: los tests unitarios de `SelectionService` corren contra esta
  implementación para ser rápidos y no depender de un archivo de base de
  datos temporal (salvo los tests que específicamente validan el
  comportamiento de SQLAlchemy).

Es la prueba en código de la idea central del rediseño: el mismo
`SelectionService` y las mismas estrategias (`BaseSelector`) funcionan
sin cambios sobre esta implementación o sobre la de SQLAlchemy, porque
ambas cumplen el mismo contrato (`src/repositories/interfaces.py`).
"""
