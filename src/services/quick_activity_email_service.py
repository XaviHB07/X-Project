"""Notificaciones de resultados del quiz en vivo por correo SMTP seguro."""

from __future__ import annotations

import logging
import os
import smtplib
import ssl
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formataddr, parseaddr
from pathlib import Path
from typing import Callable, Optional

from sqlalchemy import select, update
from sqlalchemy.orm import Session, selectinload

from src.repositories.sqlalchemy.models import (
    QuickActivityORM,
    QuickActivityResponseORM,
    StudentORM,
    UserORM,
)

LOGGER = logging.getLogger(__name__)
SENDER_ADDRESS = "loboferez.notificaciones@gmail.com"
PAW_ART_PATH = (
    Path(__file__).resolve().parents[1]
    / "api"
    / "static"
    / "assets"
    / "wolf-paw-card.jpg"
)

SessionFactory = Callable[[], Session]
SmtpFactory = Callable[..., smtplib.SMTP]


@dataclass(frozen=True)
class ResultsEmailSettings:
    enabled: bool
    host: str
    port: int
    username: str
    password: str

    @classmethod
    def from_environment(cls) -> "ResultsEmailSettings":
        enabled = os.environ.get("LIVE_RESULTS_EMAILS_ENABLED", "").strip().lower() in {
            "1", "true", "yes", "on",
        }
        username = os.environ.get("SMTP_USERNAME", "").strip()
        password = os.environ.get("SMTP_PASSWORD", "")
        host = os.environ.get("SMTP_HOST", "smtp.gmail.com").strip()
        port = int(os.environ.get("SMTP_PORT", "587"))
        if enabled and (not username or not password):
            raise RuntimeError(
                "LIVE_RESULTS_EMAILS_ENABLED requiere SMTP_USERNAME y SMTP_PASSWORD."
            )
        if enabled and not host:
            raise RuntimeError("LIVE_RESULTS_EMAILS_ENABLED requiere SMTP_HOST.")
        if not 1 <= port <= 65535:
            raise RuntimeError("SMTP_PORT debe estar entre 1 y 65535.")
        return cls(
            enabled=enabled,
            host=host,
            port=port,
            username=username,
            password=password,
        )


class QuickActivityResultsEmailService:
    """Reclama una sola vez los resultados y los entrega a la matrícula activa."""

    def __init__(
        self,
        session_factory: SessionFactory,
        settings: Optional[ResultsEmailSettings] = None,
        smtp_factory: Optional[SmtpFactory] = None,
    ):
        self._session_factory = session_factory
        self.settings = settings or ResultsEmailSettings.from_environment()
        self._smtp_factory = smtp_factory or smtplib.SMTP

    def notify_finished(self, course_id: int, activity_id: int) -> dict:
        if not self.settings.enabled:
            return self._summary("disabled")

        with self._session_factory() as session:
            activity = session.execute(
                select(QuickActivityORM)
                .where(
                    QuickActivityORM.id == activity_id,
                    QuickActivityORM.course_id == course_id,
                )
                .options(selectinload(QuickActivityORM.questions))
            ).scalar_one_or_none()
            if activity is None:
                raise LookupError("No se encontró el quiz en el curso indicado.")
            if (
                activity.mode != "live"
                or activity.status != "closed"
                or activity.live_phase != "finished"
            ):
                return self._summary("disabled")

            claim = session.execute(
                update(QuickActivityORM)
                .where(
                    QuickActivityORM.id == activity_id,
                    QuickActivityORM.course_id == course_id,
                    QuickActivityORM.live_phase == "finished",
                    QuickActivityORM.status == "closed",
                    QuickActivityORM.results_email_claimed_at.is_(None),
                )
                .values(results_email_claimed_at=datetime.now(timezone.utc))
            )
            if claim.rowcount != 1:
                return self._summary("already_sent")

            students = session.execute(
                select(StudentORM, UserORM.email)
                .join(
                    UserORM,
                    UserORM.id == StudentORM.user_id,
                    isouter=True,
                )
                .where(
                    StudentORM.course_id == course_id,
                    StudentORM.active.is_(True),
                )
                .order_by(StudentORM.id)
            ).all()
            response_rows = session.execute(
                select(QuickActivityResponseORM, StudentORM)
                .join(StudentORM, StudentORM.id == QuickActivityResponseORM.student_id)
                .where(
                    QuickActivityResponseORM.activity_id == activity_id,
                    StudentORM.active.is_(True),
                )
                .options(selectinload(QuickActivityResponseORM.answers))
                .order_by(QuickActivityResponseORM.attempt)
            ).all()

            latest_by_student = {}
            for response, student in response_rows:
                latest_by_student[student.id] = response

            ranked = []
            for student, account_email in students:
                response = latest_by_student.get(student.id)
                answers = list(response.answers) if response is not None else []
                ranked.append({
                    "response": response,
                    "student": student,
                    "email": (student.email or account_email or "").strip(),
                    "participated": bool(answers),
                    "points": sum(answer.points or 0 for answer in answers),
                    "correct": sum(1 for answer in answers if answer.is_correct),
                    "time_ms": sum(
                        answer.response_ms or 0 for answer in answers if answer.is_correct
                    ),
                    "answers": {answer.question_id: answer for answer in answers},
                })
            ranked.sort(key=lambda item: (
                -item["points"], item["time_ms"], item["student"].display_name
            ))

            deliveries = []
            skipped = 0
            for rank, item in enumerate(ranked, start=1):
                address = item["email"]
                parsed_address = parseaddr(address)[1]
                if parsed_address != address or "@" not in address or any(ch.isspace() for ch in address):
                    skipped += 1
                    continue
                deliveries.append({
                    "email": address,
                    "student_name": item["student"].display_name,
                    "points": item["points"],
                    "rank": rank,
                    "correct": item["correct"],
                    "participated": item["participated"],
                    "question_count": len(activity.questions),
                    "questions": [
                        self._question_result(question, item["answers"].get(question.id))
                        for question in activity.questions
                    ],
                })
            title = activity.title
            session.commit()

        if not deliveries:
            return self._summary("no_recipients", skipped=skipped)

        try:
            sent, failed = self._send_messages(title, deliveries)
        except (OSError, smtplib.SMTPException):
            LOGGER.exception(
                "No se pudo enviar el correo de resultados del quiz id=%s.", activity_id
            )
            return self._summary("failed", skipped=skipped, failed=len(deliveries))

        status = "sent" if failed == 0 else "partial_failure"
        return self._summary(status, sent=sent, skipped=skipped, failed=failed)

    @staticmethod
    def _question_result(question, answer) -> dict:
        options = question.options or []
        selected = answer.selected_option if answer is not None else None
        correct = question.correct_option
        return {
            "prompt": question.prompt,
            "selected": (
                options[selected] if selected is not None and 0 <= selected < len(options)
                else "Sin respuesta"
            ),
            "correct": options[correct] if correct is not None and 0 <= correct < len(options) else "—",
            "is_correct": bool(answer and answer.is_correct),
            "points": answer.points or 0 if answer is not None else 0,
        }

    def _send_messages(self, activity_title: str, recipients: list[dict]) -> tuple[int, int]:
        sent = 0
        failed = 0
        with self._smtp_factory(
            self.settings.host, self.settings.port, timeout=20
        ) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            smtp.login(self.settings.username, self.settings.password)
            for recipient in recipients:
                message = self._build_message(activity_title, recipient)
                try:
                    refused = smtp.send_message(message)
                except (OSError, smtplib.SMTPException):
                    LOGGER.exception(
                        "Falló la entrega de resultados a participante rank=%s.",
                        recipient["rank"],
                    )
                    failed += 1
                else:
                    if refused:
                        failed += 1
                    else:
                        sent += 1
        return sent, failed

    @staticmethod
    def _build_message(activity_title: str, recipient: dict) -> EmailMessage:
        import html

        name = html.escape(recipient["student_name"])
        title = html.escape(activity_title)
        points = recipient["points"]
        rank = recipient["rank"]
        correct = recipient["correct"]
        count = recipient["question_count"]
        rate = correct / count if count else 0
        if not recipient["participated"]:
            badge = "Próxima cacería"
            recognition = (
                "No registramos respuestas esta vez: obtuviste 0 puntos. "
                "¡Te esperamos en la próxima cacería!"
            )
        elif rate >= 0.8:
            badge = "Instinto Alfa"
            recognition = "¡Demostraste que eres un verdadero Lobo Feroz!"
        elif rate >= 0.5:
            badge = "Lobo en ascenso"
            recognition = "Tu instinto crece con cada desafío. ¡Sigue avanzando!"
        else:
            badge = "Espíritu de la manada"
            recognition = "Cada desafío te hace más fuerte. ¡La próxima será tuya!"

        question_rows = []
        plain_rows = []
        for index, result in enumerate(recipient["questions"], start=1):
            outcome = (
                "Correcta" if result["is_correct"]
                else "Sin respuesta" if result["selected"] == "Sin respuesta"
                else "Incorrecta"
            )
            question_rows.append(
                "<tr>"
                f'<td style="padding:10px;border-bottom:1px solid #29375c;color:#f5f7ff">{index}. '
                f'{html.escape(result["prompt"])}</td>'
                f'<td style="padding:10px;border-bottom:1px solid #29375c;color:#cbd5f5">'
                f'{html.escape(result["selected"])}</td>'
                f'<td style="padding:10px;border-bottom:1px solid #29375c;color:#f5c45e">'
                f'{html.escape(outcome)} · {result["points"]} pts</td>'
                "</tr>"
            )
            plain_rows.append(
                f'{index}. {result["prompt"]} — respuesta: {result["selected"]}; '
                f'{outcome.lower()} ({result["points"]} pts)'
            )

        message = EmailMessage()
        message["Subject"] = f"Resultados de {activity_title} | Cacería en vivo"
        message["From"] = formataddr(("Lobo Feroz", SENDER_ADDRESS))
        message["To"] = recipient["email"]
        message.set_content(
            f"Hola {recipient['student_name']},\n\n"
            f"Terminó {activity_title}. Obtuviste {points} puntos y el puesto {rank}. "
            f"Aciertos: {correct} de {count}. {recognition}\n\n"
            + "\n".join(plain_rows)
        )
        message.add_alternative(
            f"""\
            <html><body style="margin:0;background:#080d22;color:#f5f7ff;font-family:Arial,sans-serif">
              <div style="max-width:640px;margin:0 auto;padding:30px 20px">
                <div style="padding:26px;border:1px solid #352a73;border-radius:20px;background:linear-gradient(145deg,#111a3d,#24144f)">
                  <p style="margin:0;color:#c7a6ff;font-size:12px;letter-spacing:3px">CACERÍA EN VIVO · LOBO FEROZ</p>
                  <h1 style="margin:12px 0;color:#fff;font-size:30px">¡Bien hecho, {name}!</h1>
                  <p style="color:#d8dcf5">{recognition}</p>
                  <div style="display:flex;gap:12px;margin:24px 0">
                    <div style="flex:1;padding:14px;border-radius:12px;background:#ffffff12">
                      <small style="color:#c7a6ff">PUNTOS</small><br><strong style="font-size:24px">{points}</strong>
                    </div>
                    <div style="flex:1;padding:14px;border-radius:12px;background:#ffffff12">
                      <small style="color:#c7a6ff">POSICIÓN</small><br><strong style="font-size:24px">#{rank}</strong>
                    </div>
                    <div style="flex:1;padding:14px;border-radius:12px;background:#ffffff12">
                      <small style="color:#c7a6ff">RANGO</small><br><strong>{badge}</strong>
                    </div>
                  </div>
                  <p style="color:#d8dcf5">Resultados de <strong>{title}</strong> · {correct}/{count} aciertos</p>
                  <table style="width:100%;border-collapse:collapse;text-align:left">
                    <thead><tr style="color:#c7a6ff"><th>Pregunta</th><th>Tu respuesta</th><th>Resultado</th></tr></thead>
                    <tbody>{''.join(question_rows)}</tbody>
                  </table>
                  <img src="cid:wolf-paw-card" alt="Demuestra que eres un verdadero Lobo Feroz"
                    style="display:block;width:100%;max-width:470px;margin:24px auto 0;border-radius:12px" />
                </div>
                <p style="color:#8e9abb;font-size:12px;text-align:center">Lobo Feroz · Aprende, participa y vuelve a la cacería.</p>
              </div>
            </body></html>
            """,
            subtype="html",
        )
        html_part = message.get_payload()[-1]
        html_part.add_related(
            PAW_ART_PATH.read_bytes(),
            maintype="image",
            subtype="jpeg",
            cid="<wolf-paw-card>",
            filename=PAW_ART_PATH.name,
        )
        return message

    @staticmethod
    def _summary(
        status: str, sent: int = 0, skipped: int = 0, failed: int = 0
    ) -> dict:
        return {
            "result_email_status": status,
            "result_emails_sent": sent,
            "result_emails_skipped": skipped,
            "result_emails_failed": failed,
        }
