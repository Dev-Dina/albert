import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getSessionToken, setSession, clearSession, __test } from "../src/session";

declare const global: { window: Window };

if (typeof window === "undefined") {
  // @ts-expect-error — minimal global for non-jsdom runs.
  global.window = { location: { search: "?widget_id=" + "A".repeat(22) } };
}

beforeEach(() => {
  clearSession();
  vi.useFakeTimers();
});

afterEach(() => {
  clearSession();
  vi.useRealTimers();
});

describe("session", () => {
  it("returns the current token until it expires", () => {
    setSession("abc", 900);
    expect(getSessionToken()).toBe("abc");
    vi.setSystemTime(Date.now() + 901_000);
    expect(getSessionToken()).toBeNull();
  });

  it("schedules a proactive re-exchange at T-120s", () => {
    setSession("abc", 900);
    expect(__test.hasTimer()).toBe(true);
    // 780s in: timer should still be pending (not yet fired).
    vi.advanceTimersByTime(779_000);
    expect(__test.hasTimer()).toBe(true);
  });

  it("clearSession removes the token and the pending timer", () => {
    setSession("abc", 900);
    expect(__test.hasTimer()).toBe(true);
    clearSession();
    expect(getSessionToken()).toBeNull();
    expect(__test.hasTimer()).toBe(false);
  });
});
