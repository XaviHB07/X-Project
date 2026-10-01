"""Implementación de persistencia respaldada por una base de datos real
vía SQLAlchemy 2.0.

Por defecto el proyecto usa SQLite (cero configuración, un solo archivo
`.db`), pero todo el código aquí es agnóstico al dialecto concreto: para
pasar a PostgreSQL en producción basta con cambiar la cadena de conexión
en `config/default.yaml` (o la variable de entorno `DATABASE_URL`) a algo
como `postgresql+psycopg://usuario:password@host:5432/basededatos`. Ver
el README para más detalle sobre por qué se recomienda PostgreSQL para
producción real (soporte completo de `SELECT ... FOR UPDATE`).
"""
