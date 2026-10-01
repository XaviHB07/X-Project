"""Paquete raíz del sistema de Selección Inteligente (Bayesian Fairness Bandit).

Este proyecto pasó de ser una simulación Monte Carlo de "una sola corrida"
a un sistema pensado para producción, donde el estado de cada estudiante
persiste entre requests y a lo largo del tiempo. La arquitectura está
organizada en capas con responsabilidades claras (más detalle en el
README.md de la raíz del proyecto):

- domain/         Entidades y value objects, sin dependencias externas.
- strategies/      Algoritmos de selección (patrón Strategy) + registro
                    dinámico (patrón Factory/Registry).
- repositories/    Acceso a datos (patrón Repository) + transacciones
                    atómicas (patrón Unit of Work). Dos implementaciones
                    intercambiables: SQLAlchemy (producción) e in-memory
                    (simulación / tests).
- services/        Casos de uso de negocio (orquestan strategies + repos).
- metrics/         Métricas de equidad (Gini, CV, std, cobertura).
- api/             Capa HTTP (FastAPI) que expone el sistema a clientes
                    externos.
- simulation/       Motor de simulación Monte Carlo, reconstruido sobre
                    las mismas piezas de dominio/estrategias que la API
                    de producción (usando el repositorio in-memory).
- visualization/   Gráficos comparativos para el modo simulación.

La idea central de este rediseño es que **la lógica bayesiana (Strategy)
no sabe ni le importa de dónde vienen los datos ni a dónde van**: recibe
"Candidate" (un value object plano) y devuelve decisiones + deltas de
actualización. Eso es lo que permite que el mismo código sirva tanto para
correr miles de simulaciones en memoria como para atender selecciones
reales sobre una base de datos compartida por múltiples requests.
"""
