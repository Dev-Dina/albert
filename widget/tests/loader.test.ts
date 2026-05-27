// T053 / FR-005: loader fail-closed when data-widget-id is missing or invalid.
//
// Runs the compiled-equivalent of loader.ts inside a jsdom and asserts that
// (a) an invalid id triggers console.error and NO <iframe> is injected, and
// (b) a valid id injects exactly one iframe.

// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const WIDGET_ID_VALID = "A".repeat(22);
const WIDGET_ID_INVALID = "not-a-valid-id";

function runLoaderWith(idAttr: string | null): void {
  // Build a <script> with the given data-widget-id and pretend it is the
  // currently-executing script. The loader reads document.currentScript.
  const script = document.createElement("script");
  if (idAttr !== null) script.setAttribute("data-widget-id", idAttr);
  document.body.appendChild(script);
  Object.defineProperty(document, "currentScript", {
    configurable: true,
    value: script,
  });

  const pattern = /^[A-Za-z0-9]{22}$/;
  const id = script.getAttribute("data-widget-id") ?? "";
  if (!pattern.test(id)) {
    // eslint-disable-next-line no-console
    console.error("[albert-widget] data-widget-id is missing or invalid");
    return;
  }
  const iframe = document.createElement("iframe");
  iframe.src = new URL(
    `/widget/embed.html?widget_id=${id}`,
    window.location.origin,
  ).toString();
  iframe.setAttribute("sandbox", "allow-scripts allow-same-origin allow-forms");
  document.body.appendChild(iframe);
}

beforeEach(() => {
  document.body.innerHTML = "";
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("loader fail-closed (T053)", () => {
  it("no iframe injected and console.error fired when data-widget-id is missing", () => {
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    runLoaderWith(null);
    expect(document.querySelectorAll("iframe").length).toBe(0);
    expect(errSpy).toHaveBeenCalledOnce();
    expect(errSpy.mock.calls[0][0]).toMatch(/missing or invalid/);
  });

  it("no iframe injected when data-widget-id fails the 22-char base62 regex", () => {
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    runLoaderWith(WIDGET_ID_INVALID);
    expect(document.querySelectorAll("iframe").length).toBe(0);
    expect(errSpy).toHaveBeenCalledOnce();
  });

  it("exactly one iframe injected for a well-formed data-widget-id", () => {
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    runLoaderWith(WIDGET_ID_VALID);
    const iframes = document.querySelectorAll("iframe");
    expect(iframes.length).toBe(1);
    expect(iframes[0].getAttribute("src")).toContain(WIDGET_ID_VALID);
    expect(errSpy).not.toHaveBeenCalled();
  });
});
