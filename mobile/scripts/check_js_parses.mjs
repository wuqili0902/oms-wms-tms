/**
 * Parse check for the mobile app — no simulator required.
 *
 * There is no lint or test runner wired into this app's CI, so the cheapest
 * gate that catches the mistakes that actually reach a device is "does every
 * file parse".  A stray brace or a JSX tag closed with the wrong name shows up
 * here as a one-line message instead of as a blank screen on a PDA.
 *
 * Run: node scripts/check_js_parses.mjs
 */
import { existsSync, readFileSync } from "node:fs";
import { readdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { parse } from "@babel/parser";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const SKIP_DIRS = new Set(["node_modules", "android", "ios", ".expo", "dist", "scripts"]);

async function jsFiles(dir) {
  const found = [];
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    if (entry.isDirectory()) {
      if (SKIP_DIRS.has(entry.name)) continue;
      found.push(...(await jsFiles(path.join(dir, entry.name))));
      continue;
    }
    if (entry.name.endsWith(".js") || entry.name.endsWith(".jsx")) found.push(path.join(dir, entry.name));
  }
  return found;
}

// App.js is the entry point and sits outside src/.
const targets = ["App.js", "index.js"]
  .map((name) => path.join(ROOT, name))
  .filter((file) => existsSync(file));

const files = [...targets, ...(await jsFiles(path.join(ROOT, "src")))].sort();

let failed = 0;
for (const file of files) {
  const source = readFileSync(file, "utf8");
  try {
    parse(source, { sourceType: "module", plugins: ["jsx"] });
  } catch (err) {
    failed += 1;
    const rel = path.relative(ROOT, file);
    console.error(`✗ ${rel}:${err.loc?.line ?? "?"} ${err.message.split("\n")[0]}`);
  }
}

if (failed) {
  console.error(`\n${failed}/${files.length} mobile file(s) failed to parse`);
  process.exit(1);
}
console.log(`mobile parse ok: ${files.length} files`);
