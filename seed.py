# Run this after migrations: python seed.py
import asyncio
from datetime import datetime, timedelta, timezone

from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models import Event, User

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


async def main():
    async with AsyncSessionLocal() as db:
        await seed_event(db)
        await seed_volunteer(db)
        await db.commit()
    print("✓ Seed complete. Run the API and use these credentials to test.")


async def seed_event(db: AsyncSession):
    existing = await db.scalar(select(Event).where(Event.name == "IEEE TechFest 2026"))
    if existing:
        print("  Event already exists — skipping")
        return

    print("  Creating event: IEEE TechFest 2026 (capacity: 500, price: ₹199.00)")
    event = Event(
        name="IEEE TechFest 2026",
        description="Annual technical festival by IEEE RVCE Student Branch.",
        venue="RV College of Engineering, Bengaluru",
        start_time=datetime.now(timezone.utc) + timedelta(days=30),
        registration_deadline=datetime.now(timezone.utc) + timedelta(days=7),
        capacity=500,
        price=199.00,
        is_active=True,
    )
    db.add(event)
    await db.flush()
    print("  ✓ Event created")


async def seed_volunteer(db: AsyncSession):
    existing = await db.scalar(select(User).where(User.email == "volunteer@techfest.com"))
    if existing:
        print("  Volunteer already exists — skipping")
        return

    print("  Creating volunteer account: volunteer@techfest.com")
    volunteer = User(
        name="TechFest Volunteer",
        email="volunteer@techfest.com",
        phone="9999999999",
        college="RV College of Engineering",
        password_hash=pwd_context.hash("volunteer123"),
        role="volunteer",
    )
    db.add(volunteer)
    await db.flush()
    print("  ✓ Volunteer created (password: volunteer123)")


if __name__ == "__main__":
    asyncio.run(main())
