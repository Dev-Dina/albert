"""Static-inspection guard for the platform surface (T030, FR-018, SC-005).

The tenant_manager pages MUST NEVER touch a tenant-content endpoint. This test
greps every module under ``admin/app/pages_platform/`` for the forbidden path
fragments and fails the build on any match — a structural guarantee that the
platform surface cannot read tenant content, independent of runtime behavior.
"""

from __future__ import annotations

from pathlib import Path

_PAGES_DIR = Path(__file__).resolve().parents[1] / "app" / "pages_platform"

_FORBIDDEN_FRAGMENTS = (
    "/widgets",
    "/allowed-origins",
    "/guardrail-config",
    "/signing-key",
    "/leads",
    "/members",
    "/widget/chat",
    "/widget/session",
)


def test_pages_platform_directory_exists() -> None:
    assert _PAGES_DIR.is_dir()


def test_no_platform_page_references_tenant_content_endpoints() -> None:
    offenders: list[str] = []
    for path in _PAGES_DIR.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for fragment in _FORBIDDEN_FRAGMENTS:
            if fragment in text:
                offenders.append(f"{path.name}: {fragment}")
    assert not offenders, (
        "Platform pages must not reference tenant-content endpoints: "
        + ", ".join(offenders)
    )
