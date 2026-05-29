"""Seed a demo tenant + admin + widget + signing key for the widget quickstart.

Idempotent: rerunning with the same --slug updates rather than duplicates.
Run from repo root:
    uv run python scripts/seed_demo_tenant.py --slug acme

Vault must be reachable (compose dev mode is fine); the first signing key is
written via the same code path admins use for rotation, so we never bypass
the audit trail.
"""

from __future__ import annotations

import argparse
import asyncio
import secrets
import string
import sys
import uuid
from pathlib import Path

# Allow running this script from repo root: add backend/ to sys.path.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.adapters.embedder import build_embedder_adapter
from app.auth.password import hash_password
from app.clients import vault_client
from app.db.models.membership import TenantMembership
from app.db.models.parent_chunk import ParentChunk
from app.db.models.tenant import Tenant
from app.db.models.user import User
from app.db.models.widget import Widget
from app.db.models.widget_allowed_origin import WidgetAllowedOrigin
from app.db.models.widget_signing_key_version import WidgetSigningKeyVersion
from app.db.session import AsyncSessionLocal
from app.repos.chunk_repo import ChildChunkRow, ChunkRepo, ParentChunkRow
from app.tenancy.rls import set_tenant_context

# Small, tenant-distinct demo knowledge base so RAG returns real per-tenant
# content (embedded via the hosted API → pgvector). Not faked: each snippet is
# tenant-scoped content that retrieval must isolate.
_RAG_CORPUS: dict[str, list[str]] = {
    "acme": [
        "Acme Corp offers managed cloud hosting, Kubernetes, and 24/7 enterprise "
        "support. Paid plans start at $99 per month.",
        "Acme support is available 24/7 via chat and email; enterprise customers "
        "get a dedicated account manager.",
        "Acme provides a 30-day free trial and a 99.9% uptime SLA on all paid plans.",
    ],
    "beta": [
        "Beta Studio is a creative agency offering brand design, web development, "
        "and motion graphics.",
        "Beta's web development packages include design, build, and three months "
        "of maintenance.",
        "Beta offers free initial consultations and returns project quotes within "
        "48 hours.",
    ],
}
_DEFAULT_CORPUS = [
    "This business offers a range of professional services. Contact us for a quote.",
]

_BASE62 = string.ascii_letters + string.digits


def _generate_public_widget_id() -> str:
    return "".join(secrets.choice(_BASE62) for _ in range(22))


async def _set_tenant_context(session: AsyncSession, tenant_id: uuid.UUID) -> None:
    """Set the per-transaction tenant context required by RLS policies.

    Tenant-scoped tables (memberships, widget origins, widgets, signing-key
    metadata) are protected by RLS. This delegates to the app's canonical helper
    so the seed uses the EXACT same tenant-context mechanism as normal requests —
    the GUC ``app.current_tenant`` (NOT ``app.tenant_id``) — instead of bypassing
    isolation. Transaction-local (``set_config(..., true)``); reverts on commit.
    """
    await set_tenant_context(session, tenant_id)


async def _get_or_create_tenant(session: AsyncSession, slug: str, name: str) -> Tenant:
    existing = (
        await session.execute(select(Tenant).where(Tenant.slug == slug))
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    tenant = Tenant(name=name, slug=slug, status="active")
    session.add(tenant)
    await session.flush()
    return tenant


async def _get_or_create_admin(session: AsyncSession, email: str, password: str) -> User:
    existing = (
        await session.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    user = User(
        email=email,
        hashed_password=hash_password(password),
        is_active=True,
        platform_role=None,
    )
    session.add(user)
    await session.flush()
    return user


async def _ensure_membership(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    role: str = "tenant_admin",
) -> None:
    existing = (
        await session.execute(
            select(TenantMembership).where(
                TenantMembership.tenant_id == tenant_id,
                TenantMembership.user_id == user_id,
            )
        )
    ).scalar_one_or_none()

    if existing is None:
        session.add(TenantMembership(tenant_id=tenant_id, user_id=user_id, role=role))


async def _ensure_allowed_origin(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    origin: str,
    actor_user_id: uuid.UUID,
) -> None:
    existing = (
        await session.execute(
            select(WidgetAllowedOrigin).where(
                WidgetAllowedOrigin.tenant_id == tenant_id,
                WidgetAllowedOrigin.origin == origin,
            )
        )
    ).scalar_one_or_none()

    if existing is None:
        session.add(
            WidgetAllowedOrigin(
                tenant_id=tenant_id,
                origin=origin,
                created_by_user_id=actor_user_id,
            )
        )


async def _ensure_widget(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    name: str,
    greeting: str,
) -> Widget:
    existing = (
        await session.execute(select(Widget).where(Widget.tenant_id == tenant_id))
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    widget = Widget(
        tenant_id=tenant_id,
        public_widget_id=_generate_public_widget_id(),
        name=name,
        theme={"primary_color": "#2563eb"},
        greeting=greeting,
        status="enabled",
    )
    session.add(widget)
    await session.flush()
    return widget


async def _ensure_signing_key(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID,
) -> int:
    """Mint the tenant's first signing key using the same path as rotation."""
    existing = (
        await session.execute(
            select(WidgetSigningKeyVersion).where(
                WidgetSigningKeyVersion.tenant_id == tenant_id,
                WidgetSigningKeyVersion.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()

    if existing is not None:
        return int(existing.version)

    material = secrets.token_bytes(32)
    version = await vault_client.write_tenant_widget_signing_key(tenant_id, material)
    if version is None:
        raise RuntimeError("failed to write signing key to Vault")

    session.add(
        WidgetSigningKeyVersion(
            tenant_id=tenant_id,
            version=version,
            is_active=True,
            created_by_user_id=actor_user_id,
        )
    )
    return version


async def _seed_rag_corpus(session: AsyncSession, tenant_id: uuid.UUID, slug: str) -> int:
    """Seed a small tenant-scoped RAG corpus with real hosted embeddings.

    Idempotent (skips if the tenant already has chunks). Runs under the tenant
    RLS context already set by the caller, so writes satisfy the per-tenant
    policy. Embeddings come from the hosted Gemini API (pgvector storage); no
    local model weights and no faked vectors.
    """
    existing = (
        await session.execute(
            select(ParentChunk).where(ParentChunk.tenant_id == tenant_id).limit(1)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return 0

    snippets = _RAG_CORPUS.get(slug, _DEFAULT_CORPUS)
    embedder = await build_embedder_adapter()
    embeddings = await embedder.embed_batch(snippets)

    repo = ChunkRepo(session)
    content_id = uuid.uuid4()
    parent_rows: list[ParentChunkRow] = []
    child_rows: list[ChildChunkRow] = []
    for idx, (snippet, emb) in enumerate(zip(snippets, embeddings)):
        parent_id = uuid.uuid4()
        parent_rows.append(
            ParentChunkRow(
                id=parent_id, tenant_id=tenant_id, content_id=content_id,
                text=snippet, chunk_index=idx,
            )
        )
        child_rows.append(
            ChildChunkRow(
                id=uuid.uuid4(), tenant_id=tenant_id, parent_id=parent_id,
                text=snippet, embedding=emb, chunk_index=0,
            )
        )
    # Flush parents before children so the child_chunks.parent_id FK is satisfied
    # (the ORM models don't declare the relationship, so insert order isn't inferred).
    await repo.write_parent_chunks(parent_rows)
    await session.flush()
    await repo.write_child_chunks(child_rows)
    await session.flush()
    return len(child_rows)


async def seed(slug: str, origin: str) -> dict[str, str]:
    async with AsyncSessionLocal() as session:
        async with session.begin():
            tenant = await _get_or_create_tenant(
                session,
                slug=slug,
                name=slug.capitalize(),
            )

            # Required for RLS-protected tenant-scoped writes below.
            await _set_tenant_context(session, tenant.id)

            admin = await _get_or_create_admin(
                session,
                email=f"admin-{slug}@example.com",
                password="admin123",
            )
            await _ensure_membership(session, tenant.id, admin.id, role="tenant_admin")
            await _ensure_allowed_origin(session, tenant.id, origin, admin.id)
            widget = await _ensure_widget(
                session,
                tenant.id,
                name=f"{tenant.name} chat",
                greeting=f"Hi! I'm {tenant.name}'s assistant.",
            )
            key_version = await _ensure_signing_key(session, tenant.id, admin.id)
            await _seed_rag_corpus(session, tenant.id, slug)

        return {
            "tenant_id": str(tenant.id),
            "tenant_slug": tenant.slug,
            "admin_email": admin.email,
            "admin_password": "admin123",
            "widget_id": widget.public_widget_id,
            "allowed_origin": origin,
            "signing_key_version": str(key_version),
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed a demo tenant for the widget.")
    parser.add_argument("--slug", default="acme", help="Tenant slug (default: acme)")
    parser.add_argument(
        "--origin",
        default="http://localhost:8080",
        help="Allowed origin for the demo host page",
    )
    args = parser.parse_args()

    summary = asyncio.run(seed(args.slug, args.origin))
    print("Seeded demo tenant:")
    for key, value in summary.items():
        print(f"  {key}: {value}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())