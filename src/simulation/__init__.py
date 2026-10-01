"""Motor de simulación Monte Carlo (modo investigación/benchmark).

Esta es la respuesta, en código, a la pregunta original del usuario:
"¿el mismo proyecto sirve para simulación Y para producción?". Sí --
`engine.run_single_trial` NO reimplementa la lógica bayesiana ni el
ciclo asistencia/selección/actualización: llama exactamente al mismo
`SelectionService` (`src/services/selection_service.py`) y a las mismas
estrategias (`src/strategies/`) que usa `src/api/main.py`, solo que
respaldado por `InMemoryUnitOfWork` (`src/repositories/in_memory/`) en
vez de `SqlAlchemyUnitOfWork`.

La única responsabilidad propia de este paquete es lo que es
genuinamente específico de una simulación y no tiene sentido en
producción: sortear asistencia sintética, repetir el experimento miles
de veces con distintas semillas, y consolidar resultados en un
`DataFrame` para análisis y graficación.
"""
