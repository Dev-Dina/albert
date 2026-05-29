"""Classifier-driven cheap workflow paths (Phase 6.3).

The router classifies each visitor turn; enumerable easy cases are handled here
by a deterministic workflow that NEVER invokes the bounded LLM agent:

  - drop      → spam, dropped before any work
  - rag       → extractive answer from the tenant's own RAG corpus (no LLM)
  - lead      → capture_lead when a contact is present in the message
  - escalate  → flag the conversation for human handoff

Anything the workflow can't complete (no retrieval hit, no extractable contact)
returns ``reply=None`` so the caller falls back to the agent — the agent is the
exception for genuinely ambiguous/multi-step turns, not the default.

All tool calls remain tenant-scoped: tenant_id comes from the caller's verified
session, RAG runs under the tenant RLS context, and capture_lead keeps its
schema validation + per-conversation rate limit.
"""

from __future__ import annotations

import logging
import re
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Callable

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.embedder import EmbedderAdapter
from app.adapters.reranker import RerankerAdapter
from app.schemas.router import RouterDecision
from app.tools.capture_lead import capture_lead
from app.tools.escalate import escalate
from app.tools.rag_search import rag_search

logger = logging.getLogger(__name__)

_MAX_ANSWER_CHUNKS = 2
_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
_PHONE_RE = re.compile(r"\+?\d[\d\s().-]{6,}\d")

# Async context manager factory: given a tenant_id, yields a tenant-scoped session.
DbCtxFactory = Callable[[str], AbstractAsyncContextManager[AsyncSession]]


@dataclass(frozen=True)
class WorkflowResult:
    """Outcome of the cheap-path dispatch.

    - ``dropped`` → the turn was rejected (spam); the route returns a block.
    - ``reply`` set → handled by the workflow, no agent call.
    - ``reply is None`` and not dropped → the route must run the agent
      (handler == "agent", or a workflow path that could not complete).
    """

    reply: str | None
    handled_by: str  # "router" | "workflow" | "agent"
    dropped: bool = False


def extract_contact(message: str) -> str | None:
    """Best-effort deterministic contact extraction (email preferred, else phone)."""
    email = _EMAIL_RE.search(message)
    if email:
        return email.group(0)
    phone = _PHONE_RE.search(message)
    if phone:
        return phone.group(0).strip()
    return None


def _extractive_answer(results: list[dict]) -> str | None:
    """Build a deterministic answer from retrieved chunks — no LLM involved."""
    contents = [r.get("content", "").strip() for r in results[:_MAX_ANSWER_CHUNKS]]
    contents = [c for c in contents if c]
    if not contents:
        return None
    return "\n\n".join(contents)


async def dispatch(
    decision: RouterDecision,
    *,
    message: str,
    tenant_id: str,
    conversation_id: str,
    db_ctx: DbCtxFactory,
    redis: Redis | None,
    embedder: EmbedderAdapter | None,
    reranker: RerankerAdapter | None,
) -> WorkflowResult:
    """Run the cheap path for ``decision.handler``; signal agent fallback via reply=None."""
    handler = decision.handler

    if handler == "drop":
        return WorkflowResult(reply=None, handled_by="router", dropped=True)

    if handler == "rag":
        if embedder is None or reranker is None:
            return WorkflowResult(reply=None, handled_by="agent")
        async with db_ctx(tenant_id) as db:
            results = await rag_search(
                tenant_id=tenant_id, query=message, db=db, embedder=embedder, reranker=reranker
            )
        answer = _extractive_answer(results)
        if answer is None:
            logger.info("workflow.rag_miss tenant=%s — agent fallback", tenant_id)
            return WorkflowResult(reply=None, handled_by="agent")
        return WorkflowResult(reply=answer, handled_by="workflow")

    if handler == "lead":
        contact = extract_contact(message)
        if contact is None:
            logger.info("workflow.lead_no_contact tenant=%s — agent fallback", tenant_id)
            return WorkflowResult(reply=None, handled_by="agent")
        async with db_ctx(tenant_id) as db:
            result = await capture_lead(
                tenant_id=tenant_id,
                name="Visitor",
                contact=contact,
                intent=message[:500],
                db=db,
                redis=redis,
                conversation_id=conversation_id,
            )
        if result.get("status") == "captured":
            reply = f"Thanks — we've recorded your details and someone will reach out to {contact}."
        else:
            reply = "Thanks — we've noted your interest and someone will be in touch."
        return WorkflowResult(reply=reply, handled_by="workflow")

    if handler == "escalate":
        async with db_ctx(tenant_id) as db:
            await escalate(
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                reason=message[:1000],
                db=db,
            )
        return WorkflowResult(
            reply="I've passed this to a member of our team — they'll follow up with you shortly.",
            handled_by="workflow",
        )

    # handler == "agent" (or anything unexpected) → caller runs the agent.
    return WorkflowResult(reply=None, handled_by="agent")
