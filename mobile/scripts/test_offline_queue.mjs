/**
 * Node-runnable test for src/api/offline.js.
 *
 * The mobile package has no "type": "module" (Expo/Metro owns the real app), so
 * the module under test is loaded through a data: URL — that keeps offline.js
 * importable by Metro *and* checkable here without a simulator.
 *
 *   node mobile/scripts/test_offline_queue.mjs
 */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import assert from "node:assert/strict";

const modulePath = fileURLToPath(
  new URL("../src/api/offline.js", import.meta.url)
);
const source = readFileSync(modulePath, "utf8");

// The whole point of splitting the queue out is that it stays testable without
// React Native; a stray import here would break this file.
assert.deepEqual(
  source.match(/from\s+["'][^"']*(react-native|expo|async-storage)[^"']*["']/g) ?? [],
  [],
  "offline.js must not import React Native / Expo modules",
);

const {
  createOfflineQueue,
  backoffDelayMs,
  QueueFullError,
  MAX_ATTEMPTS,
  MAX_PENDING,
  QUEUE_STORAGE_KEY,
  LEGACY_STORAGE_KEY,
} = await import(`data:text/javascript;charset=utf-8,${encodeURIComponent(source)}`);

class MemoryStorage {
  constructor(initial = {}) {
    this.data = new Map(Object.entries(initial));
    this.writes = 0;
  }
  async getItem(key) {
    return this.data.has(key) ? this.data.get(key) : null;
  }
  async setItem(key, value) {
    this.data.set(key, value);
    this.writes += 1;
  }
  async removeItem(key) {
    this.data.delete(key);
  }
  raw(key) {
    return this.data.get(key);
  }
}

const queue = (opts = {}) => {
  const storage = opts.storage ?? new MemoryStorage();
  const q = createOfflineQueue({ storage, ...opts });
  return { q, storage };
};

const netError = () => Object.assign(new Error("Network request failed"), { offline: true });
const httpError = (status, message = "server error") =>
  Object.assign(new Error(message), { status });

const cases = [];
const test = (name, fn) => cases.push([name, fn]);

test("enqueue keeps FIFO order and reports stats", async () => {
  const { q } = queue();
  await q.enqueue({ path: "/a", method: "post", body: { n: 1 } });
  await q.enqueue({ path: "/b", method: "POST", body: { n: 2 } });
  const list = await q.list();
  assert.deepEqual(list.map(e => e.path), ["/a", "/b"]);
  assert.equal(list[0].method, "POST");
  const stats = q.stats();
  assert.equal(stats.pending, 2);
  assert.equal(stats.failed, 0);
  assert.equal(stats.total, 2);
});

test("migrates the pre-P1-17 pda_mutations entries", async () => {
  const legacy = JSON.stringify([
    { id: "m_1_1", path: "/old", method: "post", body: { a: 1 }, created_at: "2026-01-01T00:00:00.000Z", synced_at: null },
    { id: "m_2_2", path: "/done", method: "post", body: null, created_at: "2026-01-01T00:01:00.000Z", synced_at: "2026-01-01T00:02:00.000Z" },
  ]);
  const { q, storage } = queue({ storage: new MemoryStorage({ [LEGACY_STORAGE_KEY]: legacy }) });
  const list = await q.list();
  assert.deepEqual(list.map(e => e.path), ["/old"]);
  assert.ok(list[0].idempotency_key, "migrated entries must carry an idempotency key");
  assert.ok(storage.raw(QUEUE_STORAGE_KEY), "migration should be persisted in the new format");
});

test("flush sends every entry and drops synced ones", async () => {
  const sent = [];
  const { q, storage } = queue({ send: async e => { sent.push(e.path); } });
  await q.enqueue({ path: "/a", method: "POST" });
  await q.enqueue({ path: "/b", method: "POST" });
  const result = await q.flush();
  assert.deepEqual(sent, ["/a", "/b"]);
  assert.equal(result.synced, 2);
  assert.equal(await q.count(), 0);
  assert.deepEqual(JSON.parse(storage.raw(QUEUE_STORAGE_KEY)), []);
});

test("network failure keeps the entry and schedules a backoff", async () => {
  const { q } = queue({ send: async () => { throw netError(); } });
  await q.enqueue({ path: "/a", method: "POST" });
  const result = await q.flush();
  assert.equal(result.synced, 0);
  assert.equal(result.deferred, 1);
  const [entry] = await q.list();
  assert.equal(entry.attempts, 1);
  assert.ok(entry.next_attempt_at > Date.now(), "entry must wait before the next attempt");
  assert.equal(q.stats().retryable, 0);
});

test("an entry waiting on backoff blocks the ones behind it", async () => {
  const sent = [];
  const { q } = queue({
    send: async e => {
      sent.push(e.path);
      if (e.path === "/a") throw netError();
    },
  });
  await q.enqueue({ path: "/a", method: "POST" });
  await q.enqueue({ path: "/b", method: "POST" });
  const result = await q.flush();
  assert.deepEqual(sent, ["/a"], "must not replay out of order behind a waiting entry");
  assert.equal(result.synced, 0);
  assert.equal(result.deferred, 1);
  assert.equal(result.blocked, 1);
});

test("4xx is permanent, and only that entry is dropped out of the line", async () => {
  const sent = [];
  const { q } = queue({
    send: async e => {
      sent.push(e.path);
      if (e.path === "/bad") throw httpError(422, "sku not found");
    },
  });
  await q.enqueue({ path: "/bad", method: "POST" });
  await q.enqueue({ path: "/good", method: "POST" });
  const result = await q.flush();
  assert.deepEqual(sent, ["/bad", "/good"], "a permanent failure must not stall the queue");
  assert.equal(result.failed, 1);
  assert.equal(result.synced, 1);
  const failed = await q.list({ includeFailed: true });
  assert.equal(failed.length, 1);
  assert.equal(failed[0].path, "/bad");
  assert.equal(failed[0].status, "failed");
  assert.match(failed[0].last_error, /sku not found/);
});

test("5xx is retried, and the attempt ceiling gives up with a reason", async () => {
  const { q } = queue({ send: async () => { throw httpError(503, "service down"); } });
  await q.enqueue({ path: "/a", method: "POST" });
  let last;
  for (let i = 0; i < MAX_ATTEMPTS; i++) {
    await q.retryNow();
    last = await q.flush();
  }
  assert.equal(last.failed, 1);
  const [entry] = await q.list({ includeFailed: true });
  assert.equal(entry.status, "failed");
  assert.match(entry.last_error, /after 8 attempts/);
});

test("the same idempotency key is reused on every attempt", async () => {
  const keys = [];
  const { q } = queue({
    send: async e => {
      keys.push(e.idempotency_key);
      throw netError();
    },
  });
  await q.enqueue({ path: "/a", method: "POST" });
  for (let i = 0; i < 3; i++) {
    await q.retryNow();
    await q.flush();
  }
  assert.equal(keys.length, 3);
  assert.equal(new Set(keys).size, 1, "replays must not mint a new key");
});

test("408 and 429 are treated as retryable", async () => {
  for (const status of [408, 429]) {
    const { q } = queue({ send: async () => { throw httpError(status); } });
    await q.enqueue({ path: "/a", method: "POST" });
    const result = await q.flush();
    assert.equal(result.failed, 0, `${status} must not be permanent`);
    assert.equal(result.deferred, 1);
  }
});

test("retryFailed re-arms permanently failed entries", async () => {
  let attempts = 0;
  const { q } = queue({
    send: async () => {
      attempts += 1;
      if (attempts === 1) throw httpError(409, "stale version");
    },
  });
  await q.enqueue({ path: "/a", method: "POST" });
  await q.flush();
  assert.equal(q.stats().failed, 1);
  assert.equal(q.stats().pending, 0);

  assert.equal(await q.retryFailed(), 1);
  const result = await q.flush();
  assert.equal(result.synced, 1);
  assert.equal(await q.count(), 0);
});

test("discard removes a single stuck mutation", async () => {
  const { q } = queue({ send: async () => { throw httpError(400); } });
  const stuck = await q.enqueue({ path: "/a", method: "POST" });
  await q.enqueue({ path: "/b", method: "POST" });
  await q.flush();
  assert.equal(await q.discard(stuck.id), 1);
  assert.equal(q.stats().total, 1);
});

test("a full queue refuses the new mutation instead of dropping one", async () => {
  const storage = new MemoryStorage({
    [QUEUE_STORAGE_KEY]: JSON.stringify(
      Array.from({ length: MAX_PENDING }, (_, i) => ({
        id: `x${i}`, idempotency_key: `k${i}`, path: `/p${i}`, method: "POST",
        body: null, created_at: "2026-01-01T00:00:00.000Z", attempts: 0,
        last_error: null, last_attempt_at: null, next_attempt_at: 0, status: "pending",
      }))
    ),
  });
  const { q } = queue({ storage, send: async () => {} });
  await assert.rejects(() => q.enqueue({ path: "/new", method: "POST" }), QueueFullError);
  assert.equal(await q.count(), MAX_PENDING, "no queued mutation may be silently dropped");
});

test("corrupt queue storage does not brick the device", async () => {
  const { q } = queue({ storage: new MemoryStorage({ [QUEUE_STORAGE_KEY]: "{not json" }) });
  assert.equal(await q.count(), 0);
  await q.enqueue({ path: "/a", method: "POST" });
  assert.equal(await q.count(), 1);
});

test("backoff grows exponentially and is capped", () => {
  assert.equal(backoffDelayMs(1), 2000);
  assert.equal(backoffDelayMs(2), 4000);
  assert.equal(backoffDelayMs(3), 8000);
  assert.equal(backoffDelayMs(30), 5 * 60 * 1000);
});

test("stats exposes what the offline banner has to show", async () => {
  const { q } = queue({ send: async () => { throw netError(); } });
  await q.enqueue({ path: "/a", method: "POST" });
  await q.flush();
  await q.enqueue({ path: "/b", method: "POST" });
  const s = q.stats();
  assert.equal(s.pending, 2);
  assert.equal(s.retryable, 1); // /a is still waiting on its backoff
  assert.ok(s.oldest);
});

test("onQueueChanged fires so the UI can re-render", async () => {
  const seen = [];
  const { q } = queue({ onQueueChanged: s => seen.push(s.pending), send: async () => {} });
  await q.enqueue({ path: "/a", method: "POST" });
  await q.flush();
  assert.deepEqual(seen, [1, 0]);
});

let failures = 0;
for (const [name, fn] of cases) {
  try {
    await fn();
    console.log(`  ok   ${name}`);
  } catch (err) {
    failures += 1;
    console.error(`  FAIL ${name}\n       ${err.message}`);
  }
}

console.log(`\n${cases.length - failures}/${cases.length} offline-queue checks passed`);
process.exit(failures ? 1 : 0);
