# Quickstart: Memory and Router

## Prerequisites

- Docker stack running (`docker compose up -d`)
- Redis running (included in docker-compose)
- Backend running with `uv run uvicorn app.main:app --reload`
- `.env` has `REDIS_URL=redis://localhost:6379`

## Test 1 — Context-aware conversation

```bash
# Turn 1
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -H "X-Tenant-Id: tenant-abc" \
  -d '{"conversation_id": "conv-001", "message": "What are your opening hours?"}'

# Turn 2 (same conversation_id — agent should have context)
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -H "X-Tenant-Id: tenant-abc" \
  -d '{"conversation_id": "conv-001", "message": "And on Sundays?"}'
```

**Expected**: Second reply references "opening hours" context without the visitor repeating it.

## Test 2 — Router short-circuits a greeting

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -H "X-Tenant-Id: tenant-abc" \
  -d '{"conversation_id": "conv-002", "message": "hello"}'
```

**Expected**: `routed_to: "router"`, fast response, no RAG call.

## Test 3 — Router falls back when classifier is down

Stop the model-server, then send any message. **Expected**: `routed_to: "agent"` (fallback), no 500 error.

## Test 4 — Session expiry

```bash
# Set a very short TTL in .env: REDIS_SESSION_TTL=5
# Send a message, wait 6 seconds, send a follow-up
# Expected: second message has no memory of the first
```

## Test 5 — Tenant isolation

```bash
# Send message on tenant-abc
curl -X POST http://localhost:8000/chat \
  -H "X-Tenant-Id: tenant-abc" \
  -d '{"conversation_id": "conv-001", "message": "My name is Alice"}'

# Attempt to read as tenant-xyz (different conversation_id won't help — key is scoped)
curl -X POST http://localhost:8000/chat \
  -H "X-Tenant-Id: tenant-xyz" \
  -d '{"conversation_id": "conv-001", "message": "What is my name?"}'
```

**Expected**: `tenant-xyz` has no memory of "Alice" — completely fresh session.

## Run eval harness

```bash
cd backend
PYTHONPATH=.. uv run python -m evals.tool_selection_eval --golden ../evals/tool_selection.jsonl
```

**Expected**: Accuracy meets `agent_tool_selection.accuracy_min` in the root
`eval_thresholds.yaml`, exit code 0. If accuracy drops below threshold, exit code 1.
