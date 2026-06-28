import hashlib
import hmac
import json
import logging
import secrets
from datetime import datetime, timezone
from uuid import UUID

import razorpay
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.dependencies import get_current_user, get_db, require_role
from app.models import Payment, Registration, User
from app.schemas import InitiatePaymentRequest, InitiatePaymentResponse, PaymentVerifiedResponse, VerifyPaymentRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/payments", tags=["payments"])

razorpay_client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))


def verify_razorpay_signature(order_id: str, payment_id: str, signature: str) -> bool:
    """Verify payment signature using HMAC-SHA256 as per Razorpay spec."""
    msg = f"{order_id}|{payment_id}".encode()
    expected = hmac.new(
        settings.RAZORPAY_KEY_SECRET.encode(),
        msg,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


async def confirm_payment_and_generate_ticket(
    registration_id: str, payment: Payment, db: AsyncSession
) -> Registration:
    qr_token = secrets.token_urlsafe(32)

    count_result = await db.execute(
        select(func.count(Registration.id)).where(Registration.status == "CONFIRMED")
    )
    count = count_result.scalar() or 0
    ticket_number = f"TF2026-{str(count + 1).zfill(6)}"

    payment.status = "SUCCESS"
    payment.confirmed_at = datetime.now(timezone.utc)

    reg = await db.get(Registration, registration_id)
    reg.status = "CONFIRMED"
    reg.qr_token = qr_token
    reg.ticket_number = ticket_number

    await db.flush()
    return reg


@router.post("/initiate", response_model=InitiatePaymentResponse)
async def initiate_payment(
    body: InitiatePaymentRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("student")),
):
    """Create a Razorpay order for a pending registration."""
    reg = await db.get(Registration, str(body.registration_id))
    if not reg or reg.user_id != current_user.id:
        raise HTTPException(404, "Registration not found")
    if reg.status == "PAYMENT_PENDING":
        raise HTTPException(409, "Payment already initiated")
    if reg.status == "CONFIRMED":
        raise HTTPException(400, "Registration already confirmed")
    if reg.status != "PENDING":
        raise HTTPException(400, "Registration is not in a payable state")

    from app.models import Event
    event = await db.get(Event, str(reg.event_id))

    # Free events skip Razorpay entirely
    if event.price == 0:
        payment = Payment(
            registration_id=reg.id,
            amount=0,
            razorpay_order_id=f"FREE-{reg.id}",
            status="INITIATED",
        )
        db.add(payment)
        await db.flush()
        confirmed_reg = await confirm_payment_and_generate_ticket(str(reg.id), payment, db)
        return PaymentVerifiedResponse(
            ticket_number=confirmed_reg.ticket_number,
            status="CONFIRMED",
            message="Free event — registered and confirmed",
        )

    order = razorpay_client.order.create({
        "amount": int(event.price * 100),
        "currency": "INR",
        "receipt": str(reg.id),
    })

    payment = Payment(
        registration_id=reg.id,
        amount=float(event.price),
        razorpay_order_id=order["id"],
        status="INITIATED",
    )
    db.add(payment)
    reg.status = "PAYMENT_PENDING"
    await db.flush()

    return InitiatePaymentResponse(
        razorpay_order_id=order["id"],
        amount=float(event.price),
        key_id=settings.RAZORPAY_KEY_ID,
    )


@router.post("/verify", response_model=PaymentVerifiedResponse)
async def verify_payment(
    body: VerifyPaymentRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("student")),
):
    """Verify Razorpay signature and confirm the registration."""
    reg = await db.get(Registration, str(body.registration_id))
    if not reg or reg.user_id != current_user.id:
        raise HTTPException(404, "Registration not found")

    result = await db.execute(
        select(Payment).where(Payment.registration_id == reg.id)
    )
    payment = result.scalar_one_or_none()
    if not payment:
        raise HTTPException(404, "Payment record not found")

    if not verify_razorpay_signature(
        body.razorpay_order_id, body.razorpay_payment_id, body.razorpay_signature
    ):
        logger.error(f"Payment verification failed for registration {reg.id}: invalid signature")
        raise HTTPException(400, "Invalid payment signature")

    payment.razorpay_payment_id = body.razorpay_payment_id
    payment.razorpay_signature = body.razorpay_signature
    confirmed_reg = await confirm_payment_and_generate_ticket(str(reg.id), payment, db)

    from workers.tasks import send_ticket_email
    send_ticket_email.delay(str(confirmed_reg.id))

    logger.info(f"Payment confirmed for registration {reg.id}, ticket {confirmed_reg.ticket_number}")
    return PaymentVerifiedResponse(
        ticket_number=confirmed_reg.ticket_number,
        status="CONFIRMED",
        message="Payment verified and ticket confirmed",
    )


@router.post("/webhook")
async def razorpay_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    # Razorpay retries on non-200 responses — always return 200, log errors internally
    try:
        body = await request.body()
        signature_header = request.headers.get("X-Razorpay-Signature", "")
        event_id = request.headers.get("X-Razorpay-Event-Id", "")

        expected = hmac.new(
            settings.RAZORPAY_WEBHOOK_SECRET.encode(), body, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected, signature_header):
            raise HTTPException(400, "Invalid webhook signature")

        payload = json.loads(body)
        if payload.get("event") != "payment.captured":
            return {"status": "ignored"}

        # Idempotency — skip if we've already processed this webhook event
        existing = await db.execute(
            select(Payment).where(Payment.webhook_event_id == event_id)
        )
        if existing.scalar_one_or_none():
            return {"status": "already processed"}

        order_id = payload["payload"]["payment"]["entity"]["order_id"]
        result = await db.execute(
            select(Payment).where(Payment.razorpay_order_id == order_id)
        )
        payment = result.scalar_one_or_none()
        if not payment:
            logger.error(f"Webhook: no payment found for order {order_id}")
            return {"status": "payment not found"}

        payment.webhook_event_id = event_id
        confirmed_reg = await confirm_payment_and_generate_ticket(
            str(payment.registration_id), payment, db
        )

        from workers.tasks import send_ticket_email
        send_ticket_email.delay(str(confirmed_reg.id))

        logger.info(f"Webhook confirmed ticket {confirmed_reg.ticket_number} for order {order_id}")
        return {"status": "ok"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Webhook processing error: {e}")
        return {"status": "error", "detail": str(e)}
