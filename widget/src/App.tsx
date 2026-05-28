// Root component: acquires a session token, then renders the chat surface.

import { useEffect, useState } from "react";
import { exchangeSession } from "./api";
import { setSession } from "./session";
import type { WidgetPublicView } from "./api";
import { Chat } from "./ui/Chat";
import "./ui/styles.css";

function getWidgetIdFromLocation(): string | null {
  const params = new URLSearchParams(window.location.search);
  const id = params.get("widget_id");
  return id && /^[A-Za-z0-9]{22}$/.test(id) ? id : null;
}

const HEX_PATTERN = /^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/;

function darken(hex: string, amount = 0.12): string {
  // Naive darken: clamp each channel toward 0 by ``amount``. Good enough
  // for hover states without pulling in a color library.
  const m = hex.match(/^#([0-9a-fA-F]{6})$/);
  if (!m) return hex;
  const num = parseInt(m[1], 16);
  const r = Math.max(0, Math.round(((num >> 16) & 0xff) * (1 - amount)));
  const g = Math.max(0, Math.round(((num >> 8) & 0xff) * (1 - amount)));
  const b = Math.max(0, Math.round((num & 0xff) * (1 - amount)));
  return `#${[r, g, b].map((c) => c.toString(16).padStart(2, "0")).join("")}`;
}

function applyTheme(theme: Record<string, unknown>): void {
  const primary = typeof theme.primary_color === "string" ? theme.primary_color : null;
  if (!primary || !HEX_PATTERN.test(primary)) return;
  const root = document.documentElement;
  const hover = darken(primary, 0.12);
  root.style.setProperty("--albert-primary", primary);
  root.style.setProperty("--albert-primary-hover", hover);
  // Drive every surface that previously hard-coded the blue gradient so the
  // theme override is visible on header avatar, user bubbles, and the send
  // button without rebuilding.
  root.style.setProperty(
    "--albert-user-bg",
    `linear-gradient(135deg, ${primary} 0%, ${hover} 100%)`,
  );
}

export function App(): JSX.Element {
  const [widget, setWidget] = useState<WidgetPublicView | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const widgetId = getWidgetIdFromLocation();
    if (!widgetId) {
      setError("Missing widget_id");
      return;
    }
    exchangeSession({ widget_id: widgetId })
      .then((response) => {
        setSession(response.session_token, response.expires_in);
        const view =
          response.widget ?? {
            public_widget_id: widgetId,
            theme: {},
            greeting: "",
          };
        applyTheme((view.theme ?? {}) as Record<string, unknown>);
        setWidget(view);
      })
      .catch(() => setError("Could not start chat session"));
  }, []);

  if (error) {
    return <div className="albert-error">{error}</div>;
  }
  if (!widget) {
    return <div className="albert-loading">Loading…</div>;
  }
  return <Chat widget={widget} />;
}
