"""Pricing + cost-recording tests.

Covers the price book (``app.pricing.compute_cost_usd``) and the fix that
``record_cost_event`` now derives a real ``cost_usd`` from the model + tokens
when the caller passes no explicit cost (previously always recorded 0).
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.cost import record_cost_event
from app.db.base import Base
from app.db.models.tenant import Tenant
from app.pricing import compute_cost_usd


def test_llm_cost_is_priced_from_tokens() -> None:
    # 1,000,000 input @ $0.10/M + 1,000,000 output @ $0.40/M = $0.50
    assert compute_cost_usd("gemini-2.5-flash-lite", 1_000_000, 1_000_000) == Decimal("0.500000")


def test_small_token_counts_round_to_six_dp() -> None:
    # 1000 in + 500 out: (1000*0.10 + 500*0.40)/1e6 = 0.0003
    assert compute_cost_usd("gemini-2.5-flash-lite", 1000, 500) == Decimal("0.000300")


def test_embedding_bills_input_only() -> None:
    # output rate is 0 for embedding models
    assert compute_cost_usd("gemini-embedding-001", 1_000_000, 0) == Decimal("0.150000")
    assert compute_cost_usd("gemini-embedding-001", 1_000_000, 999) == Decimal("0.150000")


def test_versioned_model_id_matches_by_prefix() -> None:
    assert compute_cost_usd("gemini-2.5-flash-lite-preview-09", 1_000_000, 0) == Decimal("0.100000")


def test_unknown_model_is_zero_not_error() -> None:
    assert compute_cost_usd("some-other-model", 1_000_000, 1_000_000) == Decimal("0")


def _sqlite():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    return async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)


@pytest.mark.asyncio
async def test_record_cost_event_derives_nonzero_cost() -> None:
    SessionLocal = _sqlite()
    tenant = uuid.uuid4()
    async with SessionLocal() as s:
        conn = await s.connection()
        tables = [t for t in Base.metadata.sorted_tables if t.name in ("tenants", "cost_events")]
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))
        s.add(Tenant(id=tenant, name="A", slug="a", status="active"))
        await s.flush()

        event = await record_cost_event(
            db=s,
            tenant_id=tenant,
            call_type="llm",
            model="gemini-2.5-flash-lite",
            input_tokens=1000,
            output_tokens=500,
        )
        # Previously this was always Decimal("0"); now it is priced.
        assert event.cost_usd == Decimal("0.000300")


@pytest.mark.asyncio
async def test_explicit_cost_usd_overrides_pricing() -> None:
    SessionLocal = _sqlite()
    tenant = uuid.uuid4()
    async with SessionLocal() as s:
        conn = await s.connection()
        tables = [t for t in Base.metadata.sorted_tables if t.name in ("tenants", "cost_events")]
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))
        s.add(Tenant(id=tenant, name="A", slug="a", status="active"))
        await s.flush()

        event = await record_cost_event(
            db=s,
            tenant_id=tenant,
            call_type="llm",
            model="gemini-2.5-flash-lite",
            input_tokens=1000,
            output_tokens=500,
            cost_usd=Decimal("9.999999"),
        )
        assert event.cost_usd == Decimal("9.999999")
