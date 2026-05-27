// Network layer for the iframe bundle.
// Never sends tenant_id in any request body (FR-009).

import { getSessionToken, clearSession } from "./session";

export interface WidgetPublicView {
  public_widget_id: string;
  theme: Record<string, unknown>;
  greeting: string;
}

export interface WidgetSessionResponse {
  session_token: string;
  expires_in: number;
  ttl_seconds: number;
  widget?: WidgetPublicView;
}

export interface WidgetChatResponse {
  conversation_id: string;
  message: string;
  tool_calls?: Array<Record<string, unknown>>;
}

export class HttpError extends Error {
  constructor(public readonly status: number, message: string) {
    super(message);
    this.name = "HttpError";
  }
}

async function postJson<T>(
  path: string,
  body: unknown,
  headers: Record<string, string> = {},
): Promise<T> {
  const response = await fetch(path, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...headers,
    },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw new HttpError(response.status, await response.text());
  }
  return (await response.json()) as T;
}

export async function exchangeSession(
  payload: { widget_id: string },
): Promise<WidgetSessionResponse> {
  return postJson<WidgetSessionResponse>("/api/v1/widget/session", payload);
}

export async function sendChat(
  payload: { message: string; conversation_id?: string },
): Promise<WidgetChatResponse> {
  const send = async (): Promise<WidgetChatResponse> => {
    const token = getSessionToken();
    if (!token) {
      throw new HttpError(401, "no session token");
    }
    return postJson<WidgetChatResponse>("/api/v1/widget/chat", payload, {
      Authorization: `Bearer ${token}`,
    });
  };
  try {
    return await send();
  } catch (err) {
    if (err instanceof HttpError && err.status === 401) {
      // Single-retry-on-401: clear the session and let session.ts re-exchange.
      clearSession();
      const reexchanged = await reexchangeIfWidgetIdKnown();
      if (!reexchanged) throw err;
      return await send();
    }
    throw err;
  }
}

async function reexchangeIfWidgetIdKnown(): Promise<boolean> {
  const params = new URLSearchParams(window.location.search);
  const widgetId = params.get("widget_id");
  if (!widgetId) return false;
  try {
    const { setSession } = await import("./session");
    const response = await exchangeSession({ widget_id: widgetId });
    setSession(response.session_token, response.expires_in);
    return true;
  } catch {
    return false;
  }
}
