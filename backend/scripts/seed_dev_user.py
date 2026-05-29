import asyncio
import sys
from pathlib import Path

# Make the backend package root importable when run as a script.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.auth.users import hash_password  # noqa: E402
from app.db.models.user import User  # noqa: E402
from app.db.session import AsyncSessionLocal  # noqa: E402

DEV_EMAIL = "admin@example.com"
DEV_PASSWORD = "admin123"  # local dev only — never a real secret
DEV_PLATFORM_ROLE = "tenant_manager"


async def seed() -> None:
    """Idempotently create the dev platform tenant_manager user."""
    async with AsyncSessionLocal() as session:
        existing = await session.execute(select(User).where(User.email == DEV_EMAIL))
        if existing.scalar_one_or_none() is not None:
            print(f"Dev user already exists: {DEV_EMAIL} (platform_role={DEV_PLATFORM_ROLE})")
            return
        session.add(
            User(
                email=DEV_EMAIL,
                hashed_password=hash_password(DEV_PASSWORD),
                is_active=True,
                platform_role=DEV_PLATFORM_ROLE,
            )
        )
        await session.commit()
        print(f"Created dev user: {DEV_EMAIL} (platform_role={DEV_PLATFORM_ROLE})")


if __name__ == "__main__":
    asyncio.run(seed())
