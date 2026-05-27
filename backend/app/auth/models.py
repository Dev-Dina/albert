"""Role definitions for Albert.

Exactly three roles.  No configurable permission matrix; no sub-roles.
Adding a fourth role here is a spec violation — see specs/role_model.md.
"""

from enum import Enum


class Role(str, Enum):
    """The complete, fixed set of Albert roles.

    tenant_manager  — platform operator; lifecycle + aggregate power only.
                      Must NEVER get content read access (conversations/leads/CMS).
    tenant_admin    — a business's own admin; scoped to their single tenant.
    member          — end user / visitor; chat/widget access only.
    """

    tenant_manager = "tenant_manager"
    tenant_admin = "tenant_admin"
    member = "member"


# Roles that operate at the platform level (not scoped to a single tenant).
PLATFORM_ROLES: frozenset[Role] = frozenset({Role.tenant_manager})

# Roles that are always bound to a specific tenant.
TENANT_ROLES: frozenset[Role] = frozenset({Role.tenant_admin, Role.member})
