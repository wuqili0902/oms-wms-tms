/**
 * Offline mutation queue — pure JS, no React Native imports.
 *
 * Why this exists as a separate module: the old queue lived inline in
 * client.js, which meant (a) it could not be tested outside a simulator and
 * (b) replaying it re-entered `request()`, which re-queued on failure — so a
 * mutation could be duplicated every time the network flaked.
 *
 * Guarantees the PDA screens rely on:
 *   - FIFO order, so a scan-then-adjust sequence lands in the same order the
 *     operator performed it;
 *   - one idempotency key per mutation, persisted, sent on every attempt, so a
 *     replay is a no-op server-side rather than a double movement;
 *   - per-mutation exponential backoff with a hard attempt ceiling, so one
 *     rejected payload cannot stall the queue behind it;
 *   - 4xx is treated as permanent (the payload is wrong, retrying is pointless)
 *     while network errors and 5xx are retryable.
 *
 * Storage is injected (AsyncStorage-shaped: getItem/setItem) so this file runs
 * under plain Node as well as under React Native.
 */

export const QUEUE_STORAGE_KEY = "offline_mutations_v1";
export const LEGACY_STORAGE_KEY = "pda_mutations";

export const MAX_ATTEMPTS = 8;
export const BACKOFF_BASE_MS = 2000;
export const BACKOFF_MAX_MS = 5 * 60 * 1000;
/** Guard against an unbounded queue on a device that never gets service. */
export const MAX_PENDING = 500;

export class QueueFullError extends Error {
  constructor(pending) {
    super(`Offline queue is full (${pending} pending mutations)`);
    this.name = "QueueFullError";
    this.pending = pending;
  }
}

const isRetryableStatus = (status) =>
  status == null || status >= 500 || status === 408 || status === 429;

/** Exponential backoff for the nth attempt (1-based). */
export function backoffDelayMs(attempt) {
  const scaled = BACKOFF_BASE_MS * Math.pow(2, Math.max(0, attempt - 1));
  return Math.min(scaled, BACKOFF_MAX_MS);
}

let _seq = 0;

/** Idempotency key: stable for the life of the mutation, unique across them. */
function makeIdempotencyKey(now) {
  _seq += 1;
  const rand = Math.floor(Math.random() * 1e9).toString(36);
  return `mut-${now.toString(36)}-${_seq.toString(36)}-${rand}`;
}

function normalizeEntry(raw) {
  if (!raw || typeof raw !== "object") return null;
  const { path, method } = raw;
  if (typeof path !== "string" || typeof method !== "string") return null;

  const created_at = raw.created_at || new Date().toISOString();
  const attempts = Number.isFinite(raw.attempts) ? raw.attempts : 0;
  return {
    id: raw.id || makeIdempotencyKey(Date.now()),
    idempotency_key: raw.idempotency_key || raw.id || makeIdempotencyKey(Date.now()),
    path,
    method: method.toUpperCase(),
    body: raw.body ?? null,
    created_at,
    attempts,
    last_error: raw.last_error ?? null,
    last_attempt_at: raw.last_attempt_at ?? null,
    next_attempt_at: raw.next_attempt_at ?? 0,
    status: raw.status === "failed" ? "failed" : "pending",
  };
}

/** Convert the pre-P1-17 queue format to the current one. */
function migrateLegacy(raw) {
  const parsed = (() => {
    try {
      return JSON.parse(raw);
    } catch {
      return null;
    }
  })();
  if (!Array.isArray(parsed)) return [];
  // Filter on the raw shape: normalizeEntry drops synced_at, so checking it
  // afterwards would migrate entries the old queue had already synced.
  return parsed
    .filter(raw => raw && typeof raw === "object" && !raw.synced_at)
    .map(normalizeEntry);
}

/**
 * @param {Object} deps
 * @param {{getItem: Function, setItem: Function, removeItem?: Function}} deps.storage
 *        AsyncStorage-shaped store. Injected so this module has no platform coupling.
 * @param {Function} [deps.send] async (entry) => void; throws with `.status` on HTTP errors.
 * @param {Function} [deps.onQueueChanged] notified after every queue mutation.
 */
export function createOfflineQueue({ storage, send, onQueueChanged }) {
  if (!storage || typeof storage.getItem !== "function" || typeof storage.setItem !== "function") {
    throw new TypeError("offline queue requires a storage with getItem/setItem");
  }

  let entries = null; // in-memory mirror, loaded lazily

  async function load() {
    if (entries) return entries;
    const raw = await storage.getItem(QUEUE_STORAGE_KEY);
    if (raw) {
      try {
        const parsed = JSON.parse(raw);
        entries = Array.isArray(parsed) ? parsed.map(normalizeEntry).filter(Boolean) : [];
      } catch {
        entries = []; // a corrupt queue file must not brick the app
      }
    } else {
      entries = migrateLegacy(await storage.getItem(LEGACY_STORAGE_KEY));
      if (entries.length) await persist();
    }
    return entries;
  }

  async function persist() {
    await storage.setItem(QUEUE_STORAGE_KEY, JSON.stringify(entries));
    if (onQueueChanged) onQueueChanged(stats());
  }

  function stats() {
    const now = Date.now();
    const pending = entries.filter(e => e.status === "pending");
    return {
      total: entries.length,
      pending: pending.length,
      retryable: pending.filter(e => e.next_attempt_at <= now).length,
      failed: entries.filter(e => e.status === "failed").length,
      oldest: pending.length ? pending[0].created_at : null,
      nextAttemptAt: pending.length ? Math.max(...pending.map(e => e.next_attempt_at || 0)) : 0,
    };
  }

  async function enqueue({ path, method, body = null }) {
    const list = await load();
    const pending = list.filter(e => e.status === "pending");
    if (pending.length >= MAX_PENDING) throw new QueueFullError(pending.length);

    const nowMs = Date.now();
    const entry = normalizeEntry({
      id: makeIdempotencyKey(nowMs),
      idempotency_key: makeIdempotencyKey(nowMs),
      path,
      method,
      body,
      created_at: new Date(nowMs).toISOString(),
      attempts: 0,
      next_attempt_at: 0,
      status: "pending",
    });
    list.push(entry);
    await persist();
    return entry;
  }

  /** Pending mutations in the order they were performed. */
  async function list({ includeFailed = false } = {}) {
    const all = await load();
    return includeFailed ? [...all] : all.filter(e => e.status === "pending");
  }

  /**
   * Replay the queue once.
   *
   * Stops at the first entry whose backoff has not elapsed — replaying out of
   * order would let a later scan land before the adjustment it followed.
   * Returns a summary; never throws, so a caller can fire this on app resume.
   */
  async function flush() {
    const all = await load();
    if (!send) throw new TypeError("offline queue flush requires a send function");

    const now = Date.now();
    const result = { synced: 0, retried: 0, deferred: 0, failed: 0, blocked: 0 };

    for (const entry of [...all]) {
      if (entry.status !== "pending") {
        result.blocked += 1;
        continue;
      }
      if (entry.next_attempt_at > now) {
        result.deferred += 1;
        continue;
      }

      entry.attempts += 1;
      entry.last_attempt_at = new Date().toISOString();

      try {
        await send(entry);
        entry.status = "synced";
        entry.last_error = null;
        result.synced += 1;
      } catch (err) {
        const status = err?.status;
        entry.last_error = err?.message || String(err);

        if (!isRetryableStatus(status)) {
          entry.status = "failed"; // payload/permission problem — retrying won't help
          result.failed += 1;
        } else if (entry.attempts >= MAX_ATTEMPTS) {
          entry.status = "failed";
          entry.last_error = `${entry.last_error} (after ${entry.attempts} attempts)`;
          result.failed += 1;
        } else {
          entry.next_attempt_at = Date.now() + backoffDelayMs(entry.attempts);
          result.deferred += 1;
          // Keep the FIFO barrier: this entry is still waiting, so the ones
          // behind it wait too.
          result.blocked += 1;
          break;
        }
      }
    }

    // Drop everything that reached a terminal state.
    entries = entries.filter(e => e.status !== "synced");
    await persist();
    return result;
  }

  /** Reset backoff/attempt counters so the next flush tries them again. */
  async function retryFailed() {
    const all = await load();
    let reset = 0;
    for (const entry of all) {
      if (entry.status === "failed") {
        entry.status = "pending";
        entry.attempts = 0;
        entry.next_attempt_at = 0;
        reset += 1;
      }
    }
    if (reset) await persist();
    return reset;
  }

  /** Force an immediate attempt for everything still waiting on its backoff. */
  async function retryNow() {
    const all = await load();
    let released = 0;
    for (const entry of all) {
      if (entry.status === "pending" && entry.next_attempt_at > Date.now()) {
        entry.next_attempt_at = 0;
        released += 1;
      }
    }
    if (released) await persist();
    return released;
  }

  async function discard(id) {
    const all = await load();
    const before = all.length;
    entries = all.filter(e => e.id !== id);
    if (entries.length !== before) await persist();
    return before - entries.length;
  }

  async function clear() {
    entries = [];
    await persist();
    if (storage.removeItem) await storage.removeItem(LEGACY_STORAGE_KEY);
  }

  async function count() {
    return (await list()).length;
  }

  return {
    enqueue,
    list,
    stats,
    flush,
    retryFailed,
    retryNow,
    discard,
    clear,
    count,
    load,
  };
}
