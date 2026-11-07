/**
 * Guard the client ↔ screens boundary.
 *
 * `StockInScreen` called `api.adjustInventory()` for months; the method did not
 * exist, so the stock-in button threw a TypeError that looked like a network
 * failure.  Nothing in the React Native build catches that until someone taps
 * it, and the backend test suite cannot see it either — so check it statically:
 * every `api.foo(...)` used under src/ must be a key of the `api` object in
 * src/api/client.js, and every path must start with "/".
 *
 *   node mobile/scripts/check_api_surface.mjs
 */
import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../src/", import.meta.url));
const clientSource = readFileSync(`${root}api/client.js`, "utf8");

/** Keys of the exported `api` object. */
function apiMethods() {
  const start = clientSource.indexOf("export const api = {");
  if (start === -1) throw new Error("client.js no longer exports an `api` object");

  const body = clientSource.slice(start);
  const methods = new Set();
  // Top-level entries look like `name: (args) =>` or `name: value,` at the same
  // indent; nested objects (none today) would be indented deeper.
  for (const match of body.matchAll(/^  ([A-Za-z_][A-Za-z0-9_]*):/gm)) {
    methods.add(match[1]);
  }
  return methods;
}

/**
 * Paths the client can actually request, so a typo in a screen is visible.
 *
 * Both mounts count: pdaRequest() is a separate name precisely because it dials
 * /pda rather than /api/v1, and a path list that only sees one of them hides
 * half of what the phone can ask for.
 */
function requestPaths() {
  const paths = new Set();
  for (const match of clientSource.matchAll(/(?:pda)?[rR]equest\(\s*"(GET|POST|PATCH|PUT|DELETE)",\s*(`[^`]*`|"[^"]*")/g)) {
    const raw = match[2].replace(/^["`]|\s*["`]$/g, "");
    paths.add(raw.replace(/\$\{[^}]*\}/g, ":param"));
  }
  return paths;
}

function sourceFiles(dir) {
  const out = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = `${dir}${entry.name}`;
    if (entry.isDirectory()) out.push(...sourceFiles(`${full}/`));
    else if (entry.name.endsWith(".js")) out.push(full);
  }
  return out;
}

const defined = apiMethods();
const paths = requestPaths();
const problems = [];
const seen = new Set();

for (const file of sourceFiles(root)) {
  if (file.endsWith("api/client.js")) continue;
  const source = readFileSync(file, "utf8");
  for (const match of source.matchAll(/\bapi\.([A-Za-z_][A-Za-z0-9_]*)/g)) {
    const name = match[1];
    seen.add(name);
    if (!defined.has(name)) {
      const line = source.slice(0, match.index).split("\n").length;
      problems.push(`${file.replace(root, "")}:${line} calls api.${name}, which client.js does not define`);
    }
  }
}

// Note: methods the client exposes but no screen calls yet are *not* a failure.
// `heartbeat` is used by the offline flush itself, and an API method can exist
// ahead of the screen that needs it.

for (const path of paths) {
  if (!path.startsWith("/")) {
    problems.push(`request path ${path} is not absolute`);
  }
}

if (problems.length) {
  console.error(`\n${problems.length} API-surface problem(s):`);
  for (const p of problems) console.error(`  - ${p}`);
  process.exit(1);
}

console.log(`api surface ok: ${seen.size} methods used, ${paths.size} request paths`);
