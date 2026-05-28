// Public loader served at /widget.js.
//
// Reads data-widget-id from the currently-executing <script> tag, validates
// it against ^[A-Za-z0-9]{22}$, and on success injects a sandboxed iframe
// pointing at /widget/embed.html?widget_id=<id>. Fail-closed on missing or
// malformed id (FR-005, US2 T060).

const WIDGET_ID_PATTERN = /^[A-Za-z0-9]{22}$/;

interface CurrentScriptHost {
  currentScript: HTMLOrSVGScriptElement | null;
}

(() => {
  const doc = (typeof document !== "undefined" ? document : undefined) as
    | (Document & CurrentScriptHost)
    | undefined;
  if (!doc) return;
  const script = doc.currentScript as HTMLScriptElement | null;
  if (!script) return;

  const id = script.getAttribute("data-widget-id") ?? "";
  if (!WIDGET_ID_PATTERN.test(id)) {
    // FR-005 fail-closed branch — render nothing, surface a console error.
    // eslint-disable-next-line no-console
    console.error("[albert-widget] data-widget-id is missing or invalid");
    return;
  }

  // Iframe base = origin where this loader script itself was served from
  // (the Albert backend), NOT the host page's origin. This is what makes
  // cross-origin embedding work: the host can be on https://customer.com
  // and the iframe still loads from https://albert.example/widget/embed.html.
  // Falls back to window.location.origin only when currentScript has no src
  // (e.g. same-origin demos / jsdom).
  const scriptSrc = script.getAttribute("src");
  const base = scriptSrc
    ? new URL(scriptSrc, window.location.origin).origin
    : window.location.origin;
  const src = new URL(`/widget/embed.html?widget_id=${id}`, base);
  const iframe = doc.createElement("iframe");
  iframe.src = src.toString();
  iframe.title = "Albert chat";
  iframe.setAttribute("allow", "clipboard-write");
  iframe.setAttribute("sandbox", "allow-scripts allow-same-origin allow-forms");
  iframe.style.cssText = [
    "position:fixed",
    "right:24px",
    "bottom:24px",
    "width:380px",
    "height:560px",
    "max-width:calc(100vw - 32px)",
    "max-height:calc(100vh - 48px)",
    "border:0",
    "border-radius:20px",
    "box-shadow:0 24px 60px rgba(15,23,42,0.18), 0 4px 12px rgba(15,23,42,0.08)",
    "z-index:2147483647",
    "background:transparent",
    "color-scheme:light",
  ].join(";");

  const append = () => doc.body.appendChild(iframe);
  if (doc.body) {
    append();
  } else {
    doc.addEventListener("DOMContentLoaded", append, { once: true });
  }
})();
