"""Casos de uso de negocio: orquestan estrategias (`src/strategies`) y
persistencia (`src/repositories`) sin que ninguna de las dos capas se
conozca entre sí. Esta es la capa que la API HTTP (`src/api`) y el motor
de simulación (`src/simulation`) invocan; ninguna de las dos debería
llamar directamente a un repositorio o instanciar una estrategia por su
cuenta.
"""
