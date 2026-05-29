#!/usr/bin/env python
"""Dev/demo bootstrap — fresh-clone readiness. NOT for production.

Idempotently brings the local stack to a demo-ready state:
  1. Alembic migrations -> head (uses the admin/MIGRATION URL via alembic/env.py).
  2. Platform tenant_manager:  admin@example.com / admin123.
  3. Demo tenant `acme` + tenant_admin (admin-acme@example.com / admin123) +
     enabled widget + allowed origin (http://localhost:8080) + Vault signing key.
  4. Second tenant `beta` (origin http://localhost:9090) for the isolation demo.
  5. Prints demo URLs + credentials.

Preferred run (fresh clone):
    cp .env.example .env
    docker compose up -d
    docker compose --profile bootstrap up bootstrap

On the host (alternative):
    uv run --directory backend python ../scripts/bootstrap_dev.py

Safety: seeding runs under the runtime app role (albert_app) and uses the
canonical RLS tenant context (``app.tenancy.rls.set_tenant_context`` →
``app.current_tenant``) — it never bypasses or weakens RLS, never grants
superuser/BYPASSRLS. The signing key is written through the existing Vault path.
Dev passwords are intentionally weak and documented; no real provider keys or
service tokens are printed.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parent


def _find_app_root() -> Path:
    """Locate the backend app root (alembic.ini + app/): /app in container, backend/ on host."""
    for candidate in (Path("/app"), _REPO_ROOT / "backend"):
        if (candidate / "alembic.ini").is_file() and (candidate / "app").is_dir():
            return candidate
    raise SystemExit("bootstrap: cannot locate backend app root (alembic.ini + app/).")


_APP_ROOT = _find_app_root()
sys.path.insert(0, str(_APP_ROOT))  # enable `import app...`
# _SCRIPT_DIR is already sys.path[0] for the sibling `import seed_demo_tenant`.

import seed_demo_tenant
from sqlalchemy import select

from app.auth.password import hash_password
from app.db.models.user import User
from app.db.session import AsyncSessionLocal 

_MANAGER_EMAIL = "manager@example.com"
_DEV_PASSWORD = "admin123"  # local dev only — documented, never a real secret


def _migrate() -> None:
    print("[bootstrap] alembic upgrade head ...")
    subprocess.run(["alembic", "upgrade", "head"], cwd=str(_APP_ROOT), check=True)


async def _seed_platform_manager() -> None:
    """Idempotently create the platform tenant_manager (no tenant membership)."""
    async with AsyncSessionLocal() as session:
        existing = (
            await session.execute(select(User).where(User.email == _MANAGER_EMAIL))
        ).scalar_one_or_none()
        if existing is not None:
            print(f"[bootstrap] platform manager exists: {_MANAGER_EMAIL}")
            return
        session.add(
            User(
                email=_MANAGER_EMAIL,
                hashed_password=hash_password(_DEV_PASSWORD),
                is_active=True,
                platform_role="tenant_manager",
            )
        )
        await session.commit()
        print(f"[bootstrap] created platform manager: {_MANAGER_EMAIL}")


def _print_summary(acme: dict[str, str], beta: dict[str, str]) -> None:
    line = "=" * 64
    print(f"\n{line}")
    print("Albert dev bootstrap complete — DEV CREDENTIALS ONLY")
    print(line)
    print("Admin UI:       http://localhost:8501")
    print("Backend docs:   http://localhost:8000/docs")
    print("Jaeger:         http://localhost:16686")
    print("MinIO console:  http://localhost:9001  (minioadmin / minioadmin)")
    print("-" * 64)
    print(f"Platform manager:  {_MANAGER_EMAIL} / {_DEV_PASSWORD}  (tenant_manager)")
    print(f"Tenant admin:      {acme['admin_email']} / {_DEV_PASSWORD}  (tenant_admin)")
    print(f"Demo tenant:       {acme['tenant_slug']}")
    print(f"Demo widget_id:    {acme['widget_id']}")
    print(f"Allowed origin:    {acme['allowed_origin']}")
    print(
        f"Isolation tenant:  {beta['tenant_slug']}  "
        f"({beta['admin_email']} / {_DEV_PASSWORD}, origin {beta['allowed_origin']})"
    )
    print("-" * 64)
    print("WARNING: dev/demo credentials + dev-mode Vault. Never use in production.")
    print(line)


async def _seed_all() -> None:
    await _seed_platform_manager()
    acme = await seed_demo_tenant.seed("acme", "http://localhost:8080")
    beta = await seed_demo_tenant.seed("beta", "http://localhost:9090")
    _print_summary(acme, beta)


def main() -> None:
    _migrate()
    asyncio.run(_seed_all())


if __name__ == "__main__":
    main()
