# Owner A — Step-by-Step Work Plan

**Slice:** Platform, Tenancy, Isolation & Provisioning.
**You own the graded heart of the project** — the brief calls deciding where isolation is enforced "the most senior judgment call." Get the 🔴 items right; nothing else you build matters if the wall leaks.

---

## Honesty / accuracy notes (read once)

- This plan is scoped to **Owner A only**. B/C/D tasks appear only where you depend on them.
- Code blocks show the **shape** of a solution, not verified copy-paste. Anything touching a library's exact API (`fastapi-users` method names, SQLAlchemy event hooks, Alembic op signatures) is marked **[VERIFY]** — confirm against that library's current docs before relying on it. Do not trust the skeleton's exact names.
- The **Postgres RLS / `set_config` mechanism below is verified** against Postgres documentation behavior (transaction-local `set_config(..., true)` reverts on commit/rollback). The two gotchas in Phase 2 are real, documented quirks — don't skip them.
- "No vibe coding" (brief's rule): you own every line. Use the skeletons to understand structure, then write and verify your own.

---

## Your files (the complete list)

🔴 = wall-critical, cannot be wrong.

| File | What it is | Flag |
|---|---|---|
| `api/migrations/versions/0001_init_rls.py` | Tables + `tenant_id` + RLS policies | 🔴 |
| `api/app/tenancy/models.py` | Tenant model, `tenant_id` UUID convention | 🔴 |
| `api/app/tenancy/rls.py` | `set_config` / reset + SQLAlchemy event listener | 🔴 |
| `api/app/deps.py` | Per-request `tenant_scope` dependency | 🔴 |
| `api/app/tenancy/repo.py` | Base repo with `.filter(tenant_id==)` | 🔴 |
| `api/app/auth/models.py` | User model + role enum | |
| `api/app/auth/users.py` | fastapi-users wiring (JWT, registration) | |
| `api/app/auth/roles.py` | Role checks; manager = no content bypass | 🔴 |
| `api/app/tenancy/provisioning.py` | Create tenant + invite first admin | |
| `api/app/tenancy/erasure.py` | Write/delete-only purge across all stores | 🔴 |
| `api/app/tenancy/audit.py` | Audit log, actor id on every manager action | |
| `api/app/cost.py` | Per-tenant token + $ attribution | |
| `api/app/ratelimit.py` | Per-tenant rate limiting | |
| `api/app/cache.py` | Caching decision (coordinate w/ B) | |
| `evals/isolation/test_rls_leak.py` | A≠B, pooled reset, manager no-read | 🔴 |
| `evals/isolation/test_erasure_total.py` | All stores empty + audit | 🔴 |
| `evals/conftest.py` | Shared fixtures (2 tenants, context setters) | |
| `docs/DESIGN.md` (your sections) | Isolation, roles, doorway, cost, scaling | 🔴 |
| `docs/SPEC.md` (tenant + role parts) | Written first, before code | |

---

## Build order (why this sequence)

The order follows real dependencies, not the calendar:

1. **Migration + tenant model** first — nothing exists to scope until tables + RLS policies exist.
2. **The reset mechanism** (`rls.py` + `deps.py`) next — the policy is useless until something sets the tenant variable per request and resets it.
3. **Repo scoping** — defense-in-depth on top of RLS.
4. **The leak test** — written now, because it proves 1–3 actually hold and becomes a CI gate.
5. **Auth + roles** — depends on the user/tenant tables from step 1.
6. **Provisioning + audit** — depends on roles existing.
7. **Cost + rate limiting** — independent; slot in when convenient.
8. **Erasure** — last of the code, because it must call delete-hooks that B/C/D expose. Unblock this early by agreeing hook signatures on day one.
9. **Docs** — ongoing, finalized at the end.

---

## PHASE A0 — Day-one foundation (do first, everyone blocks on you)

**Goal:** Repo skeleton boots, Vault wired, and the tenant + role model exists so B/C/D can test against a real tenant context.

### Tasks
- [ ] Scaffold repo + `docker-compose.yml` with all services (you lead this with the team Phase 0).
- [ ] Wire Vault so the app can read secrets.
- [ ] Decide the `tenant_id` convention: **UUID, on every tenant-scoped row.** Write it in `SPEC.md`. **Do not change this later** — the brief says changing it Thursday is agony.
- [ ] Publish two interfaces other owners code against today:
  - the `tenant_scope` dependency signature (so they import it)
  - the token→tenant resolution contract (so D's widget token and B's chat handler agree on where `tenant_id` comes from)

### Expected output
A booting stack and a one-paragraph `SPEC.md` entry naming the `tenant_id` convention and the three roles.

### CHECKPOINT A0
```bash
docker compose up -d
curl -s localhost:8000/health      # -> ok
```
Pass when the stack boots and the `tenant_id` convention is written down and agreed.

---

## PHASE A1 — The RLS migration 🔴

**Goal:** Every tenant-scoped table has a `tenant_id` and one RLS policy. The database itself refuses cross-tenant rows.

### Tasks
- [ ] In `models.py`: the `Tenant` model and a `tenant_id UUID` column on every tenant-scoped table (conversations, leads, content, embeddings table coordinated with B, tickets…).
- [ ] In `0001_init_rls.py`: create tables, then `ENABLE ROW LEVEL SECURITY` + one `POLICY` per table.
- [ ] Decide the "no context" behavior: an unset variable should yield **zero rows** (safe default), not all rows.

### Verified mechanism (safe to rely on)
```sql
ALTER TABLE conversations ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON conversations
  USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
```
- `current_setting('app.tenant_id', true)` — the second arg `true` means "missing → return NULL/empty instead of erroring." A NULL comparison yields no rows = safe default.
- **[VERIFY]** the exact Alembic `op.execute(...)` calls for raw SQL in your Alembic version.

### GOTCHA to handle now (documented Postgres quirk)
After a transaction-local variable has been set once on a connection, `current_setting` can later return an **empty string** rather than NULL. So your policy / any "is context set?" check must treat **empty string AND null** as "no tenant," e.g.:
```sql
USING (
  tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
)
```
Test this explicitly — it's the kind of edge case the brief probes.

### Migration-superuser note
**[VERIFY]** RLS does not apply to the table owner / superuser unless `FORCE ROW LEVEL SECURITY` is set. Run your app with a **non-superuser** DB role, or RLS silently won't enforce for that role. Confirm which role your app connects as.

### CHECKPOINT A1
```sql
SELECT relname, relrowsecurity FROM pg_class WHERE relname='conversations';  -- relrowsecurity = true
SELECT * FROM pg_policies WHERE tablename='conversations';                    -- policy present
```
Pass when RLS is enabled and a policy exists on every tenant-scoped table.

---

## PHASE A2 — The reset mechanism 🔴 (the bug they probe hardest)

**Goal:** Each request sets its tenant context and it **never leaks to the next request on a pooled connection.**

### The decision: use transaction-local config
Verified behavior: `set_config('app.tenant_id', <id>, true)` (third arg `true` = `is_local`) applies **only to the current transaction** and **reverts automatically on commit or rollback** — no stale state on a pooled connection. This is the recommended form with connection poolers.

### Tasks
- [ ] In `rls.py`: a function that runs `SELECT set_config('app.tenant_id', :tid, true)` at the start of a request's transaction.
- [ ] In `deps.py`: the `tenant_scope` dependency that resolves the tenant **from the verified token only — never from the request body** 🔴, sets the context, yields, and relies on transaction end to revert (or explicitly `RESET` if you ever use session-level `false`).
- [ ] **[VERIFY]** the SQLAlchemy mechanism you use to guarantee the `set_config` runs inside the same transaction/connection as the request's queries (event listener on transaction begin, or a dependency that owns the session). Confirm the exact hook name against SQLAlchemy docs.

### Shape (illustrative — verify the SQLAlchemy parts)
```python
async def tenant_scope(request, db):
    tid = resolve_tenant_from_verified_token(request)   # NEVER request.body["tenant_id"]
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": str(tid)},
    )
    yield
    # transaction-local (true) reverts on commit/rollback — nothing to reset manually
```

### Why this is the danger
The brief asks directly: "A request for Tenant A reuses a connection that still has Tenant B's variable set. Where do you reset it, and how do you prove the reset never gets skipped?" Your answer: transaction-local config reverts automatically; and the pooled-reuse test below proves it.

### CHECKPOINT A2 — write this test before moving on
```python
def test_pooled_connection_does_not_leak_context():
    # set A, finish its transaction, then start B on a reused connection
    run_request_as(tenant_a)            # opens + commits a txn with A's context
    ctx = read_context_on_fresh_txn()   # current_setting on a new txn
    assert ctx in (None, "")            # A's value did NOT persist

def test_tenant_id_comes_from_token_not_body():
    token = issue_token(tenant_a)
    ctx = run_chat(token=token, body={"tenant_id": str(tenant_b)})
    assert ctx == str(tenant_a)         # body value ignored
```
Pass when both tests are green. These two tests are non-negotiable.

---

## PHASE A3 — Repository-layer scoping 🔴 (defense in depth)

**Goal:** Even if RLS were misconfigured, the app still scopes every query. The brief: "RLS catches the query a tired developer forgets to scope" — but you still scope at the repo layer too.

### Tasks
- [ ] In `repo.py`: a base repository whose every read/write applies `.filter(tenant_id == current_tenant)`.
- [ ] Make it the default path so a new developer gets scoping for free.

### CHECKPOINT A3
```python
def test_tenant_a_cannot_read_tenant_b():
    set_tenant_context(tenant_a); insert_conversation(tenant_a, "from A")
    set_tenant_context(tenant_b)
    rows = repo.list_conversations()
    assert all(r.tenant_id == tenant_b for r in rows)
    assert "from A" not in [r.text for r in rows]
```
Pass when A cannot see B's rows through the repo. Commit `evals/isolation/test_rls_leak.py` with A2 + A3 tests.

---

## PHASE A4 — Auth + the three roles

**Goal:** Exactly three roles, two levels. No configurable permission matrix (brief: "resist building a configurable permission matrix").

### Tasks
- [ ] `auth/users.py`: wire `fastapi-users` — JWT, email/password registration. **[VERIFY]** its exact setup against current fastapi-users docs; do not trust remembered method names.
- [ ] `auth/models.py`: role enum — `tenant_manager`, `tenant_admin`, `member`. Nothing else.
- [ ] `auth/roles.py` 🔴: enforce that **Tenant Manager gets no content RLS bypass** — it cannot read a tenant's conversations or leads. It only provisions/suspends/erases and reads aggregate cost/usage.

### CHECKPOINT A4
```python
def test_three_roles_only():
    assert set(Role) == {"tenant_manager", "tenant_admin", "member"}

def test_tenant_manager_cannot_read_tenant_content():
    login_as(tenant_manager)
    with pytest.raises(PermissionError):
        repo.read_conversations(tenant_a)
```
Pass when roles are exactly three and the manager is blocked from reading content.

---

## PHASE A5 — Provisioning + audit log

**Goal:** The Tenant Manager creates a tenant and invites its first admin; every privileged action is logged.

### Tasks
- [ ] `provisioning.py`: Tenant Manager creates a tenant, invites the first tenant-admin. **The platform operator never logs into a tenant to set it up** (brief). The tenant configures itself from there.
- [ ] `audit.py`: log every Tenant Manager action with its **actor id** — provision, suspend, erase, aggregate-cost read.

### CHECKPOINT A5
```python
def test_provisioning_creates_tenant_and_invites_admin():
    t = provision_tenant(by=tenant_manager, name="Acme")
    assert t.id and invite_sent_to_first_admin(t)

def test_manager_action_is_audited():
    provision_tenant(by=tenant_manager, name="Beta")
    assert audit_log_last().actor == tenant_manager.id
```
Pass when provisioning works and is audited.

---

## PHASE A6 — Cost attribution + rate limiting

**Goal:** You can answer "what did Tenant X cost us this week," and one noisy tenant can't starve the others.

### Tasks
- [ ] `cost.py`: tag every LLM + embedding call with the tenant (you'll hook into B's/C's call sites — agree the tagging interface). Expose an aggregate read for the Tenant Manager.
- [ ] `ratelimit.py`: per-tenant limits; reject over-limit with a clear error, logged per tenant.
- [ ] `cache.py`: make and **document** the caching decision — what you cache (embeddings? retrieval? responses?) and what you pointedly don't. Coordinate with B since they own retrieval. The decision and its rationale go in `DESIGN.md`.

### CHECKPOINT A6
```bash
curl -s localhost:8000/admin/cost?tenant=A    # -> {"tokens":N,"usd":N}  (manager-only)
# fire requests past the limit for one tenant -> 429s logged, other tenant unaffected
```
Pass when cost is attributable per tenant and rate limiting isolates a noisy tenant.

---

## PHASE A7 — Right-to-erasure 🔴 (gated on B/C/D — unblock early)

**Goal:** A real "delete tenant" that purges every store and is audited — without the manager ever reading content.

### Cross-owner dependency — resolve on DAY ONE
Your erasure path must call delete-hooks the others expose. Agree these signatures early or this phase stalls:
- **B** → "delete all pgvector embeddings + Redis sessions for tenant X"
- **C** → "delete any model/guardrail tenant artifacts + purge tenant from traces/logs"
- **D** → the admin button that *calls* your erasure endpoint (D owns the UI; you own the purge)

### Tasks
- [ ] `erasure.py`: a narrow **write/delete-only** path (no read bypass) that purges:
  - Postgres rows
  - pgvector embeddings (via B's hook)
  - MinIO blobs
  - Redis sessions (via B's hook)
  - traces / logs (via C's hook)
- [ ] Audit-log the erasure with actor id.
- [ ] Resolve the brief's explicit tension: the manager **can destroy without ever being able to read.**

### CHECKPOINT A7
```python
def test_erasure_is_total():
    seed_tenant(tenant_x)                       # rows, embeddings, blobs, sessions
    erase_tenant(tenant_x, by=tenant_manager)
    assert postgres_rows(tenant_x) == 0
    assert pgvector_chunks(tenant_x) == 0       # "row gone but embeddings searchable" = FAIL
    assert minio_blobs(tenant_x) == 0
    assert redis_sessions(tenant_x) == 0
    assert audit_log_has(actor=tenant_manager, action="erase", target=tenant_x)
```
Pass when nothing for the erased tenant survives anywhere and the erasure is audited.

---

## PHASE A8 — Your DESIGN.md sections 🔴 (the written grade)

**Goal:** Defend your decisions in writing. This is graded, not a footnote.

### Write these sections
- [ ] **Isolation strategy** — where you enforce it (DB RLS + repo layer + B's tenant-filtered pgvector) and *what each layer catches*. Defend the choice.
- [ ] **Role model** — three roles, two levels, why no RBAC matrix.
- [ ] **The Tenant Manager doorway** — how it erases without reading; where that line is enforced in code; what one change would quietly move it.
- [ ] **Per-tenant cost story** — how you attribute, what Tenant X cost.
- [ ] **Rate limiting + caching decision** — what you cache and what you pointedly don't.
- [ ] **Scaling & failure story (one page)** — where this breaks at 10 vs 1,000 tenants and the next bottleneck. (Brief: "interviews ask exactly this.")

### CHECKPOINT A8
Read the brief's "THINK ABOUT" questions that touch your slice. For each, point to the paragraph that answers it:
- "Where exactly is the tenant filter enforced — and what happens when a new dev forgets it?"
- "Should the Tenant Manager be able to read one tenant's conversations? Where is that line enforced, and what one code change would quietly move it?"
- "You set the RLS variable per request, but connections are pooled… where do you reset it, and how do you prove the reset never gets skipped?"
- "'Delete my tenant.' Name every place that data lives… Did you get all of them?"

Pass when every one has a paragraph answering it.

---

## Your definition of done

- [ ] RLS enabled + policy on every tenant-scoped table (A1)
- [ ] Transaction-local context set per request; pooled-reuse test green (A2) 🔴
- [ ] `tenant_id` from token, never body; test green (A2) 🔴
- [ ] Repo scoping + A-can't-read-B test green (A3) 🔴
- [ ] Exactly three roles; manager-no-content-read test green (A4) 🔴
- [ ] Provisioning + audit working and tested (A5)
- [ ] Per-tenant cost + rate limiting working (A6)
- [ ] Total erasure across all stores + audit; test green (A7) 🔴
- [ ] Your DESIGN.md sections answer every relevant "THINK ABOUT" question (A8) 🔴
- [ ] Your isolation tests are wired into CI as gates (coordinate with D)

---

## The five questions you personally must answer on demo day

The brief promises any teammate can be asked about any slice — but these are *yours* and you should be airtight:

1. **Where is isolation enforced and why there?** → RLS (DB) + repo layer (app) + tenant-filtered pgvector (vector). Each catches a different failure.
2. **Pooled connection, stale tenant variable — how do you prevent it and prove it?** → transaction-local `set_config(..., true)` reverts on commit; the pooled-reuse test proves it.
3. **Can the Tenant Manager read a tenant's conversations? What one change would let it?** → No; no RLS bypass on content; the change would be granting the manager role a read path through the maintenance/erasure code.
4. **Delete a tenant — name every store.** → Postgres rows, pgvector embeddings, MinIO blobs, Redis sessions, traces/logs; the erasure test asserts each is empty.
5. **Where does it break at 1,000 tenants?** → your scaling story's stated next bottleneck.

---

**One-line version of your job:** make the database itself refuse cross-tenant rows, prove the proof can't be skipped, give the Tenant Manager a doorway not a master key, and defend all of it in DESIGN.md.
