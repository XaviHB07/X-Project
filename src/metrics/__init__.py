"""Métricas de equidad, desacopladas de dónde vengan los conteos.

Este paquete no cambió de diseño respecto al proyecto original: ya
estaba correctamente aislado (recibe arrays de numpy, no sabe nada de
estudiantes, bandits, ni bases de datos), así que se conserva tal cual.
Lo único que cambia es QUIÉN lo llama: antes solo `simulation.runner`;
ahora también `services.fairness_service.FairnessMetricsService`, que
alimenta los conteos desde el estado persistido en vez de desde un
`ClassSnapshot` en memoria.
"""
