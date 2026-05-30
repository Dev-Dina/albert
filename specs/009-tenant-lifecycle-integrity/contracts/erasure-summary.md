# Contract: `erase_tenant()` audit summary (post-change)

`erase_tenant(db, actor_user_id, tenant_id) -> dict[str, int]` — unchanged signature,
write/delete-only on tenant content, does not commit (caller owns the transaction).

## Summary keys (MUST be present)

Postgres, one per covered table (each = rows deleted for the target tenant):

```
postgres.cost_events
postgres.leads
postgres.messages
postgres.escalations            # NEW
postgres.conversations
postgres.child_chunks
postgres.parent_chunks
postgres.cms_pages
postgres.widget_configs
postgres.tenant_guardrail_configs
postgres.widget_allowed_origins
postgres.widget_signing_key_versions
postgres.widget_guardrail_configs
postgres.widgets
postgres.tenant_memberships     # NEW
postgres.content_chunks         # optional legacy (0 if table absent)
```

Other stores (unchanged): `pgvector.child_chunks`, `pgvector.parent_chunks`,
`pgvector.content_chunks`, `minio.objects`, `redis.sessions`, `traces`.

## Behavioral guarantees

- **G1**: After erasure, **zero** rows remain for the target tenant in every table above.
- **G2**: `summary["postgres.escalations"]` equals the number of escalation rows the
  target tenant had at erasure start (counted by an explicit delete that runs **before**
  `conversations`, not by the FK cascade).
- **G3**: `summary["postgres.tenant_memberships"]` equals the number of membership rows
  deleted; corresponding `users` rows are **not** deleted.
- **G4**: No other tenant's rows are read, deleted, or affected (cross-tenant isolation).
- **G5**: Works under a non-superuser / NOBYPASSRLS role with `FORCE RLS` enforced.
- **G6**: Re-erasing an already-erased tenant is safe and returns zero counts.

## Coverage guard contract

A test MUST fail (naming the table) if any table with a `tenant_id` column is **not** in
`_TENANT_TABLES ∪ _OPTIONAL_LEGACY_TABLES`. Source of truth: SQLAlchemy `Base.metadata`
(primary) and live `information_schema` (secondary, in the Postgres eval).
