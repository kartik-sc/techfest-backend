import logging
import smtplib
from email.mime.text import MIMEText

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, joinedload

from app.config import settings
from app.models import Registration
from workers.celery_app import celery_app

# Note: this task runs in a separate process, so it uses sync SQLAlchemy
# psycopg2-binary must be in requirements.txt (add it alongside asyncpg)
_sync_engine = create_engine(settings.DATABASE_URL.replace("+asyncpg", "+psycopg2"))

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def send_ticket_email(self, registration_id: str):
    with Session(_sync_engine) as db:
        reg = (
            db.query(Registration)
            .options(joinedload(Registration.user), joinedload(Registration.event))
            .get(registration_id)
        )

    if not reg:
        logger.error(f"send_ticket_email: registration {registration_id} not found")
        return

    if not settings.SMTP_HOST:
        logger.info(
            f"[DEV] Would send ticket email to {reg.user.email} — ticket {reg.ticket_number}"
        )
        return

    subject = f"Your TechFest 2026 Ticket — {reg.ticket_number}"
    body = (
        f"Hi {reg.user.name},\n\n"
        f"You're confirmed for {reg.event.name}!\n\n"
        f"Ticket number : {reg.ticket_number}\n"
        f"Event date    : {reg.event.date}\n"
        f"Venue         : {reg.event.venue}\n\n"
        f"Show your QR code at the gate. Download it from the app under 'My Registrations'.\n\n"
        f"See you there!\n"
        f"— IEEE RVCE TechFest 2026"
    )

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = settings.FROM_EMAIL
    msg["To"] = reg.user.email

    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as smtp:
            smtp.starttls()
            smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            smtp.send_message(msg)
        logger.info(f"Ticket email sent to {reg.user.email} ({reg.ticket_number})")
    except Exception as exc:
        logger.error(f"Failed to send email to {reg.user.email}: {exc}")
        raise self.retry(exc=exc)
