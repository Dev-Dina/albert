"""Per-request tenant context — thin shim over app.tenancy.rls.

This module is kept for import-compatibility only. All callers should
migrate to ``app.tenancy.rls.set_tenant_context`` /
``app.tenancy.rls.clear_tenant_context`` directly.

The variable set is ``app.current_tenant`` (matching all RLS policies).
The previous implementation incorrectly used ``app.tenant_id``.
"""

from app.tenancy.rls import clear_tenant_context, set_tenant_context

__all__ = ["clear_tenant_context", "set_tenant_context"]
