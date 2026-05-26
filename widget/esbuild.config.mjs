// Build script for the Albert widget.
// Produces two artifacts under widget/dist/:
//   - widget.js                — public loader (no React, ≤ 4 KB minified)
//   - bundle-<sha>.js          — iframe contents (React + chat UI, ≤ 110 KB minified)
//
// The bundle filename embeds a content hash so it can be cached as immutable
// while the (short-cached) iframe HTML references the current sha.

import { build } from "esbuild";
import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
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

// 2. Iframe bundle (React + UI).
const bundleTmp = resolve(DIST, "bundle.tmp.js");
await build({
  entryPoints: [resolve(ROOT, "src/iframe-bootstrap.tsx")],
  bundle: true,
  minify: true,
  format: "esm",
  target: ["es2020"],
  jsx: "automatic",
  outfile: bundleTmp,
  logLevel: "info",
});

// Hash + rename bundle so the URL is immutable.
const bytes = readFileSync(bundleTmp);
const sha = createHash("sha256").update(bytes).digest("hex").slice(0, 10);
const bundleFinal = resolve(DIST, `bundle-${sha}.js`);
renameSync(bundleTmp, bundleFinal);

// Sidecar manifest so the backend knows the current bundle filename.
writeFileSync(
  resolve(DIST, "bundle-manifest.json"),
  JSON.stringify({ sha, filename: `bundle-${sha}.js` }, null, 2)
);

console.log(`built loader (widget.js) and bundle-${sha}.js`);
