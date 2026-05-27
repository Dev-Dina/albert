// Iframe-local session state. Stored ONLY in module-scope memory; never in
// localStorage or cookies. Schedules a proactive re-exchange at T-120s.

import type { WidgetSessionResponse } from "./api";

let token: string | null = null;
let expiresAt = 0;
let reexchangeTimer: ReturnType<typeof setTimeout> | null = null;

const PROACTIVE_REEXCHANGE_MARGIN_SECONDS = 120;

export function getSessionToken(): string | null {
  if (!token) return null;
  if (Date.now() >= expiresAt) {
    clearSession();
    return null;
  }
  return token;
}

export function setSession(newToken: string, expiresInSeconds: number): void {
  token = newToken;
  expiresAt = Date.now() + expiresInSeconds * 1000;
  scheduleProactiveReexchange(expiresInSeconds);
}

export function clearSession(): void {
  token = null;
  expiresAt = 0;
  if (reexchangeTimer !== null) {
    clearTimeout(reexchangeTimer);
    reexchangeTimer = null;
  }
}

function scheduleProactiveReexchange(expiresInSeconds: number): void {
  if (reexchangeTimer !== null) {
    clearTimeout(reexchangeTimer);
    reexchangeTimer = null;
  }
  const delayMs = Math.max(
    0,
    (expiresInSeconds - PROACTIVE_REEXCHANGE_MARGIN_SECONDS) * 1000,
  );
  reexchangeTimer = setTimeout(() => {
    void reexchangeFromCurrentWidget();
  }, delayMs);
}

async function reexchangeFromCurrentWidget(): Promise<void> {
  const params = new URLSearchParams(window.location.search);
  const widgetId = params.get("widget_id");
  if (!widgetId) {
    clearSession();
    return;
  }
  try {
    const { exchangeSession } = await import("./api");
    const response: WidgetSessionResponse = await exchangeSession({
      widget_id: widgetId,
    });
    setSession(response.session_token, response.expires_in);
  } catch {
    clearSession();
  }
}

// Test helpers. NOT exported from the bundle entry point.
export const __test = {
  getRawExpiresAt: (): number => expiresAt,
  hasTimer: (): boolean => reexchangeTimer !== null,
};
