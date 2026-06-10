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
 * Fetch with cache-first strategy:
 * 1. Return cached data immediately if available
 * 2. Fetch from network in background
 * 3. Update cache with fresh data
 */
export async function fetchWithCache(key, apiCall, ttlMs) {
  // Return cached data immediately
  const cached = await cacheGet(key);
  if (cached) {
    // Refresh in background
    apiCall()
      .then((fresh) => cacheSet(key, fresh, ttlMs))
      .catch(() => {}); // silent fail - keep stale cache
    return cached;
  }

  // No cache — fetch and store
  const data = await apiCall();
  await cacheSet(key, data, ttlMs);
  return data;
}
