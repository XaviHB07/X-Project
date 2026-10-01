"""Eventos de dominio y un bus de eventos in-process (patrón Observer).

Esto NO es necesario para que el sistema funcione — `SelectionService`
funcionaría igual sin esto. Se incluye porque es el punto de extensión
natural para todo lo que hoy no pediste pero es previsible que aparezca
en una app real y que NO debería obligar a modificar `SelectionService`:

    - Notificar a otro sistema cuando un estudiante es seleccionado
      (p. ej. enviarle una notificación push).
    - Invalidar una cache de métricas de equidad cuando cambia el estado.
    - Emitir el evento a un tópico de Kafka / cola de mensajes para
      integrarlo con otros microservicios.
    - Registrar auditoría adicional fuera de la base de datos transaccional.

`SelectionService` solo conoce `EventBus.publish(...)`; quien quiera
reaccionar a un `DecisionRunCompleted` se suscribe desde fuera, sin tocar
la lógica de selección. Esto es el mismo principio que ya usaba el
proyecto original con `BaseSelector` (Strategy): añadir un comportamiento
nuevo sin modificar el código existente (principio abierto/cerrado).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Dict, List, Type


@dataclass(frozen=True)
class DecisionRunCompleted:
    """Se publica una vez que una decisión de selección quedó
    persistida (commit exitoso). Contiene lo mínimo para que un
    suscriptor decida si le interesa, sin tener que volver a consultar
    la base de datos.
    """

    decision_run_id: int
    class_session_id: int
    method_name: str
    considered_student_ids: List[int]
    selected_student_ids: List[int]
    occurred_at: datetime


DomainEvent = DecisionRunCompleted


class EventBus:
    """Bus de eventos in-process minimalista: sin colas, sin async, sin
    dependencias externas. Es intencionalmente simple — si el proyecto
    crece hasta necesitar entrega garantizada, reintentos o eventos
    entre procesos, este es el lugar a reemplazar por algo como
    Redis Streams, RabbitMQ o Kafka, sin tocar el resto del sistema
    (`SelectionService` seguiría llamando solo a `publish`).
    """

    def __init__(self) -> None:
        self._subscribers: Dict[Type[DomainEvent], List[Callable[[DomainEvent], None]]] = (
            defaultdict(list)
        )

    def subscribe(self, event_type: Type[DomainEvent], handler: Callable[[DomainEvent], None]) -> None:
        self._subscribers[event_type].append(handler)

    def publish(self, event: DomainEvent) -> None:
        for handler in self._subscribers.get(type(event), []):
            # Deliberadamente no envolvemos en try/except: si un
            # suscriptor falla, preferimos que sea ruidoso durante
            # desarrollo. En producción, cada handler es responsable de
            # su propio manejo de errores (p. ej. reintentos al enviar
            # a una cola externa).
            handler(event)


def logging_subscriber(event: DomainEvent) -> None:
    """Suscriptor de referencia: registra cada decisión en el logger
    estándar de Python. Se conecta en `services/bootstrap.py` como
    ejemplo de cómo engancharse al bus sin tocar `SelectionService`.
    """
    import logging

    logger = logging.getLogger("seleccion_bayesiana.decisions")
    if isinstance(event, DecisionRunCompleted):
        logger.info(
            "decision_run=%s session=%s method=%s considerados=%d seleccionados=%s",
            event.decision_run_id,
            event.class_session_id,
            event.method_name,
            len(event.considered_student_ids),
            event.selected_student_ids,
        )
