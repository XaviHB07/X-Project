"""Instrumentación liviana de peticiones (Plan de optimización, tareas 1.4 y 4.4).

El plan gratuito de Render no ofrece métricas de latencia por ruta ni de
la base de datos, así que la propia aplicación las mide:

* Cada respuesta lleva `X-Request-ID` y un encabezado `Server-Timing`
  con el tiempo total, el de autenticación y el de base de datos
  (cantidad de consultas y milisegundos). Se ve en la pestaña "Red" del
  navegador sin herramientas extra, y k6/Locust pueden leerlo.
* Se registra una línea de log por petición lenta (umbral configurable
  con `SLOW_REQUEST_MS`, 1000 ms por defecto) con ruta, estado y tiempos.
  NUNCA se registran tokens, cookies, contraseñas ni cuerpos.
* `RouteStats` guarda en memoria las últimas N duraciones por ruta para
  calcular p50/p95/p99; el endpoint `/admin/metrics` (solo administrador)
  las expone junto con el estado del pool de conexiones.

Los datos viven en el proceso: con varios procesos cada uno informa los
suyos. Es suficiente para comparar "antes/después" en una prueba de carga
controlada, que es el objetivo del plan; no reemplaza un APM.
"""

from __future__ import annotations

import os
import threading
import time
import uuid
from collections import deque
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Deque, Dict, Optional

from sqlalchemy import event


@dataclass
class RequestMetrics:
    request_id: str
    started: float = field(default_factory=time.perf_counter)
    auth_ms: float = 0.0
    db_queries: int = 0
    db_ms: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add_query(self, elapsed_ms: float) -> None:
        with self._lock:
            self.db_queries += 1
            self.db_ms += elapsed_ms

    def total_ms(self) -> float:
        return (time.perf_counter() - self.started) * 1000


# Se fija en el middleware. Los endpoints `def` corren en el threadpool de
# AnyIO, que copia el contexto al despachar: el hilo ve el MISMO objeto y
# los contadores de SQL llegan a la petición correcta.
current_request: ContextVar[Optional[RequestMetrics]] = ContextVar(
    "current_request_metrics", default=None
)


def new_request_metrics(incoming_id: Optional[str]) -> RequestMetrics:
    # Se acepta un id entrante (p. ej. de un balanceador) solo si es corto
    # y simple, para no reflejar contenido arbitrario en logs/encabezados.
    if incoming_id and len(incoming_id) <= 64 and incoming_id.replace("-", "").isalnum():
        request_id = incoming_id
    else:
        request_id = uuid.uuid4().hex[:16]
    return RequestMetrics(request_id=request_id)


def install_sql_timing(engine) -> None:
    """Cuenta y cronometra cada consulta SQL de la petición en curso."""
    if getattr(engine, "_xproject_sql_timing", False):
        return

    @event.listens_for(engine, "before_cursor_execute")
    def _before(conn, cursor, statement, parameters, context, executemany):
        conn.info.setdefault("_xproject_query_start", []).append(time.perf_counter())

    @event.listens_for(engine, "after_cursor_execute")
    def _after(conn, cursor, statement, parameters, context, executemany):
        starts = conn.info.get("_xproject_query_start")
        if not starts:
            return
        elapsed_ms = (time.perf_counter() - starts.pop()) * 1000
        metrics = current_request.get()
        if metrics is not None:
            metrics.add_query(elapsed_ms)

    engine._xproject_sql_timing = True


def _percentile(sorted_values, fraction: float) -> float:
    if not sorted_values:
        return 0.0
    index = min(len(sorted_values) - 1, max(0, round(fraction * (len(sorted_values) - 1))))
    return sorted_values[index]


class RouteStats:
    """Últimas `window` duraciones por ruta (plantilla, no URL concreta)."""

    def __init__(self, window: int = 1000):
        self._window = window
        self._lock = threading.Lock()
        self._durations: Dict[str, Deque[float]] = {}
        self._counts: Dict[str, int] = {}
        self._errors: Dict[str, int] = {}
        self._started_at = time.time()

    def record(self, route: str, status_code: int, elapsed_ms: float) -> None:
        with self._lock:
            bucket = self._durations.get(route)
            if bucket is None:
                bucket = self._durations[route] = deque(maxlen=self._window)
            bucket.append(elapsed_ms)
            self._counts[route] = self._counts.get(route, 0) + 1
            if status_code >= 500:
                self._errors[route] = self._errors.get(route, 0) + 1

    def snapshot(self) -> dict:
        with self._lock:
            data = {route: sorted(values) for route, values in self._durations.items()}
            counts = dict(self._counts)
            errors = dict(self._errors)
        routes = []
        for route, values in data.items():
            routes.append({
                "route": route,
                "requests": counts.get(route, 0),
                "errors_5xx": errors.get(route, 0),
                "window": len(values),
                "p50_ms": round(_percentile(values, 0.50), 1),
                "p95_ms": round(_percentile(values, 0.95), 1),
                "p99_ms": round(_percentile(values, 0.99), 1),
                "max_ms": round(values[-1], 1) if values else 0.0,
            })
        routes.sort(key=lambda item: item["requests"], reverse=True)
        return {"uptime_s": round(time.time() - self._started_at), "routes": routes}

    def reset(self) -> None:
        with self._lock:
            self._durations.clear()
            self._counts.clear()
            self._errors.clear()
            self._started_at = time.time()


def pool_status(engine) -> dict:
    pool = engine.pool
    status = {"class": type(pool).__name__}
    for name in ("size", "checkedin", "checkedout", "overflow"):
        method = getattr(pool, name, None)
        if callable(method):
            try:
                status[name] = method()
            except Exception:  # pragma: no cover - depende del tipo de pool
                pass
    timeout = getattr(pool, "_timeout", None)
    if timeout is not None:
        status["timeout_s"] = timeout
    return status


def slow_request_threshold_ms() -> float:
    try:
        return float(os.environ.get("SLOW_REQUEST_MS", "1000"))
    except ValueError:
        return 1000.0
