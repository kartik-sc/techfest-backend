import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, require_role
from app.models import CheckIn, Event, Registration, User
from app.schemas import CheckInStats, ScanRequest, ScanResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/checkin", tags=["checkin"])


@router.post("/scan", response_model=ScanResponse)
async def scan_qr(
    body: ScanRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("volunteer")),
):
    """Scan a student QR code and mark them as checked in."""
    result = await db.execute(select(Registration).where(Registration.qr_token == body.qr_token))
    reg = result.scalar_one_or_none()
    if not reg:
        raise HTTPException(404, "Invalid QR code")

    if reg.status == "CHECKED_IN":
        raise HTTPException(409, "Student already checked in")
    if reg.status != "CONFIRMED":
        raise HTTPException(400, "Payment not confirmed for this ticket")

    student = await db.get(User, reg.user_id)
    event = await db.get(Event, reg.event_id)

    checkin = CheckIn(registration_id=reg.id, volunteer_id=current_user.id, gate=body.gate)
    db.add(checkin)
    try:
        await db.flush()
    except IntegrityError:
        # Another volunteer scanned the same QR milliseconds ago
        await db.rollback()
        raise HTTPException(409, "Student already checked in")

    reg.status = "CHECKED_IN"
    logger.info(f"Check-in: ticket {reg.ticket_number} at gate {body.gate} by volunteer {current_user.id}")

    return ScanResponse(
        student_name=student.name,
        ticket_number=reg.ticket_number,
        event_name=event.name,
        college=student.college,
    )


@router.get("/stats/{event_id}", response_model=CheckInStats)
async def checkin_stats(
    event_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("volunteer")),
):
    """Live attendance breakdown for an event."""
    event = await db.get(Event, event_id)
    if not event:
        raise HTTPException(404, "Event not found")

    result = await db.execute(
        select(
            func.count(Registration.id).label("total"),
            func.sum(case((Registration.status == "CONFIRMED", 1), else_=0)).label("confirmed"),
            func.sum(case((Registration.status == "CHECKED_IN", 1), else_=0)).label("checked_in"),
            func.sum(case((Registration.status == "PENDING", 1), else_=0)).label("pending"),
        ).where(Registration.event_id == event_id)
    )
    row = result.one()

    return CheckInStats(
        event_name=event.name,
        capacity=event.capacity,
        confirmed=row.confirmed or 0,
        checked_in=row.checked_in or 0,
        pending=row.pending or 0,
    )
