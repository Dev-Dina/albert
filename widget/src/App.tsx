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
        setWidget(
          response.widget ?? {
            public_widget_id: widgetId,
            theme: {},
            greeting: "",
          },
        );
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
