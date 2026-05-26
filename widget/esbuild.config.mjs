// Build script for the Albert widget.
// Produces three artifacts under widget/dist/:
//   - widget.js                — public loader (no React, ≤ 4 KB minified)
//   - bundle-<sha>.js          — iframe contents (React + chat UI)
//   - bundle-<sha>.css         — iframe styles (referenced from embed.html)
//
// The bundle filename embeds a content hash so it can be cached as immutable
// while the (short-cached) iframe HTML references the current sha.

import { build } from "esbuild";
import { createHash } from "node:crypto";
import {
  existsSync,
  mkdirSync,
  readFileSync,
  renameSync,
  unlinkSync,
  writeFileSync,
} from "node:fs";
import { resolve } from "node:path";

const ROOT = resolve(import.meta.dirname);
const DIST = resolve(ROOT, "dist");
mkdirSync(DIST, { recursive: true });

// 1. Loader (no React).
await build({
  entryPoints: [resolve(ROOT, "src/loader.ts")],
  bundle: true,
  minify: true,
  format: "iife",
  target: ["es2020"],
  outfile: resolve(DIST, "widget.js"),
  logLevel: "info",
});

// 2. Iframe bundle (React + UI). CSS is emitted as a sidecar file.
// NODE_ENV=production strips ~30 KB of dev-only React warnings/assertions.
const bundleTmp = resolve(DIST, "bundle.tmp.js");
const cssTmp = resolve(DIST, "bundle.tmp.css");
await build({
  entryPoints: [resolve(ROOT, "src/iframe-bootstrap.tsx")],
  bundle: true,
  minify: true,
  format: "esm",
  target: ["es2020"],
  jsx: "automatic",
  define: {
    "process.env.NODE_ENV": JSON.stringify("production"),
  },
  outfile: bundleTmp,
  logLevel: "info",
});

// Hash + rename bundle so the URL is immutable. The CSS sidecar gets the
// same hash so a single sha identifies one (js, css) pair.
const bytes = readFileSync(bundleTmp);
const sha = createHash("sha256").update(bytes).digest("hex").slice(0, 10);
const bundleFinal = resolve(DIST, `bundle-${sha}.js`);
const cssFinal = resolve(DIST, `bundle-${sha}.css`);
renameSync(bundleTmp, bundleFinal);
if (existsSync(cssTmp)) {
  renameSync(cssTmp, cssFinal);
}

// Clean up any older hashed bundles so the dist folder doesn't accumulate.
import { readdirSync } from "node:fs";
for (const name of readdirSync(DIST)) {
  if (
    /^bundle-[0-9a-f]{10}\.(js|css)$/.test(name) &&
    name !== `bundle-${sha}.js` &&
    name !== `bundle-${sha}.css`
  ) {
    try {
      unlinkSync(resolve(DIST, name));
    } catch {
      /* ignore */
    }
  }
}

// Sidecar manifest so the backend knows the current bundle filename(s).
writeFileSync(
  resolve(DIST, "bundle-manifest.json"),
  JSON.stringify(
    {
      sha,
      filename: `bundle-${sha}.js`,
      css: existsSync(cssFinal) ? `bundle-${sha}.css` : null,
    },
    null,
    2,
  ),
);

console.log(
  `built loader (widget.js), bundle-${sha}.js${
    existsSync(cssFinal) ? ` and bundle-${sha}.css` : ""
  }`,
);
