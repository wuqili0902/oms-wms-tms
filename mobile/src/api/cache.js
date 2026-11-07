/**
 * Offline storage cache for mobile app.
 *
 * Provides AsyncStorage-based caching with TTL expiration.
 * Caches API responses so the app works with limited connectivity.
 */
import AsyncStorage from "@react-native-async-storage/async-storage";

const CACHE_PREFIX = "cache:";
const DEFAULT_TTL_MS = 5 * 60 * 1000; // 5 minutes

/**
 * Store a value in cache with TTL.
 */
export async function cacheSet(key, value, ttlMs = DEFAULT_TTL_MS) {
  const entry = {
    data: value,
    expiresAt: Date.now() + ttlMs,
  };
  await AsyncStorage.setItem(CACHE_PREFIX + key, JSON.stringify(entry));
}

/**
 * Get a cached value. Returns null if not found or expired.
 */
export async function cacheGet(key) {
  const raw = await AsyncStorage.getItem(CACHE_PREFIX + key);
  if (!raw) return null;
  try {
    const entry = JSON.parse(raw);
    if (Date.now() > entry.expiresAt) {
      await AsyncStorage.removeItem(CACHE_PREFIX + key);
      return null;
    }
    return entry.data;
  } catch {
    return null;
  }
}

/**
 * Remove a cached entry.
 */
export async function cacheRemove(key) {
  await AsyncStorage.removeItem(CACHE_PREFIX + key);
}

/**
 * Clear all cached data.
 */
export async function cacheClear() {
  const keys = await AsyncStorage.getAllKeys();
  const cacheKeys = keys.filter((k) => k.startsWith(CACHE_PREFIX));
  if (cacheKeys.length > 0) {
    await AsyncStorage.multiRemove(cacheKeys);
  }
}

/**
 * Read a cache entry without the expiry side effects, so an expired entry can
 * still be used as the fallback when the network is unreachable.
 */
async function readEntry(key) {
  const raw = await AsyncStorage.getItem(CACHE_PREFIX + key);
  if (!raw) return null;
  try {
    const entry = JSON.parse(raw);
    if (!entry || typeof entry !== "object" || !("data" in entry)) return null;
    return { data: entry.data, expired: Date.now() > entry.expiresAt };
  } catch {
    return null;
  }
}

/**
 * Fetch with cache-first strategy:
 * 1. Return cached data immediately if it is still fresh
 * 2. Fetch from the network in the background and refresh the cache
 * 3. When the network fails, fall back to the last known data — even if it has
 *    aged out — rather than showing an error to an operator who has no signal
 *
 * `forceRefresh: true` is for pull-to-refresh: the whole point of that gesture
 * is a fresh answer, so the fresh copy is served (and the aged one only backs it
 * up if the fetch fails).
 */
export async function fetchWithCache(key, apiCall, ttlMs, { forceRefresh = false } = {}) {
  const entry = await readEntry(key);

  if (entry?.data != null && !entry.expired && !forceRefresh) {
    apiCall()
      .then((fresh) => cacheSet(key, fresh, ttlMs))
      .catch(() => {}); // silent fail - keep the cached copy
    return entry.data;
  }

  try {
    const data = await apiCall();
    await cacheSet(key, data, ttlMs);
    return data;
  } catch (err) {
    if (entry?.data != null) return entry.data; // offline: stale beats nothing
    throw err;
  }
}
