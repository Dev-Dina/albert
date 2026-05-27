import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { exchangeSession, sendChat, HttpError } from "../src/api";
import { setSession, clearSession, getSessionToken } from "../src/session";

declare const global: { fetch: unknown; window: Window };

if (typeof window === "undefined") {
  // @ts-expect-error — set up a minimal global for tests run without jsdom.
  global.window = { location: { search: "?widget_id=" + "A".repeat(22), origin: "http://localhost" } };
}

const ORIGINAL_FETCH = global.fetch;

beforeEach(() => {
  clearSession();
});

afterEach(() => {
  global.fetch = ORIGINAL_FETCH;
  vi.restoreAllMocks();
});

describe("exchangeSession", () => {
  it("posts to /api/v1/widget/session with widget_id only (FR-009: no tenant_id)", async () => {
    const calls: Array<{ url: string; body: unknown }> = [];
    global.fetch = vi.fn(async (url: string, init: RequestInit) => {
      calls.push({ url, body: JSON.parse(String(init.body)) });
      return new Response(
        JSON.stringify({ session_token: "tok", expires_in: 900, ttl_seconds: 900 }),
        { status: 200 },
      );
    });
    const response = await exchangeSession({ widget_id: "A".repeat(22) });
    expect(response.session_token).toBe("tok");
    expect(calls[0].url).toBe("/api/v1/widget/session");
    expect(calls[0].body).toEqual({ widget_id: "A".repeat(22) });
    expect(calls[0].body).not.toHaveProperty("tenant_id");
  });

  it("throws HttpError(403) on disallowed origin", async () => {
    global.fetch = vi.fn(async () => new Response("forbidden", { status: 403 }));
    await expect(exchangeSession({ widget_id: "A".repeat(22) })).rejects.toBeInstanceOf(
      HttpError,
    );
  });
});

describe("sendChat", () => {
  it("attaches Authorization: Bearer <token>", async () => {
    setSession("the-token", 900);
    const calls: Array<{ url: string; headers: Record<string, string> }> = [];
    global.fetch = vi.fn(async (url: string, init: RequestInit) => {
      calls.push({ url, headers: init.headers as Record<string, string> });
      return new Response(
        JSON.stringify({ conversation_id: "c", message: "ok" }),
        { status: 200 },
      );
    });
    await sendChat({ message: "hi" });
    expect(calls[0].headers.Authorization).toBe("Bearer the-token");
  });

  it("on 401 retries exactly once after re-exchanging the session", async () => {
    setSession("first-token", 900);
    let callCount = 0;
    global.fetch = vi.fn(async (url: string) => {
      callCount += 1;
      if (url === "/api/v1/widget/chat" && callCount === 1) {
        return new Response("unauth", { status: 401 });
      }
      if (url === "/api/v1/widget/session") {
        return new Response(
          JSON.stringify({ session_token: "second-token", expires_in: 900, ttl_seconds: 900 }),
          { status: 200 },
        );
      }
      return new Response(
        JSON.stringify({ conversation_id: "c", message: "ok" }),
        { status: 200 },
      );
    });
    const response = await sendChat({ message: "hi" });
    expect(response.message).toBe("ok");
    expect(callCount).toBe(3); // chat 401 -> session -> chat retry
  });

  // T042a / FR-008c: a refused re-exchange MUST NOT trigger an unbounded
  // retry loop. The widget surfaces a "session expired" state instead.
  it("on 401 → 429 on re-exchange: no chat retry, error surfaced, session cleared (FR-008c)", async () => {
    setSession("first-token", 900);
    let chatCalls = 0;
    let sessionCalls = 0;
    global.fetch = vi.fn(async (url: string) => {
      if (url === "/api/v1/widget/chat") {
        chatCalls += 1;
        return new Response("unauth", { status: 401 });
      }
      if (url === "/api/v1/widget/session") {
        sessionCalls += 1;
        return new Response("rate limited", {
          status: 429,
          headers: { "Retry-After": "60" },
        });
      }
      throw new Error(`unexpected url ${url}`);
    });

    let caught: unknown;
    try {
      await sendChat({ message: "hi" });
    } catch (e) {
      caught = e;
    }

    expect(caught).toBeInstanceOf(HttpError);
    expect((caught as HttpError).status).toBe(401);
    expect(chatCalls).toBe(1); // No retried chat request after refused re-exchange.
    expect(sessionCalls).toBe(1); // Exactly one re-exchange attempt — no loop.
    expect(getSessionToken()).toBeNull(); // Surfaces "session expired".
  });
});
