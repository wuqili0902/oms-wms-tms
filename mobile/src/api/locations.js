/**
 * Shelf-label → location id.
 *
 * A PDA operator reads 库位 off the rack ("A-01-02", "RECV-1"), while the API
 * keys locations by UUID.  Posting the label as an id reached the backend as an
 * id it could not parse and came back as a warehouse 404 the operator could
 * not act on.
 *
 * Matching is deliberately wider than the stored code: create_location() builds
 * `code` as "<warehouse-id-prefix>-<zone>-<aisle>-<bin>", which is not what is
 * written on a shelf.  Comparing only the full code made every typed label
 * "库位不存在", so the operator had to read hex out of a barcode.
 */
import { api } from "./client";

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

const normalize = (value) => String(value ?? "").trim().toLowerCase().replace(/\s+/g, "");

/** Every name a location answers to, shortest label first. */
function locationAliases(location) {
  const code = normalize(location.location_code);
  const aliases = new Set([code]);

  // Drop the warehouse-id prefix: racks carry zone/aisle/bin, not hex.
  if (code.includes("-")) {
    const parts = code.split("-");
    aliases.add(normalize(parts.slice(1).join("-")));
    aliases.add(normalize(parts.slice(-3).join("-")));
    aliases.add(normalize(parts.slice(-2).join("-")));
  }

  const { zone, aisle, shelf, bin } = location;
  if (zone && aisle && bin) {
    aliases.add(normalize(shelf ? `${zone}-${aisle}-${shelf}-${bin}` : `${zone}-${aisle}-${bin}`));
  }
  if (location.position) aliases.add(normalize(location.position));

  aliases.delete("");
  return aliases;
}

/**
 * @returns {Promise<{ok: true, id: string, label: string} | {ok: false, error: string}>}
 *          never a half-resolved location: the caller books stock or reports the
 *          problem, and a silently unresolved label books it into nothing.
 */
export async function resolveLocationRef(warehouseId, ref) {
  const label = String(ref ?? "").trim();
  if (!label) return { ok: false, error: "库位不能为空" };
  if (UUID_RE.test(label)) return { ok: true, id: label, label };

  let locations = [];
  try {
    const res = await api.listLocations(warehouseId);
    locations = res?.items ?? (Array.isArray(res) ? res : []);
  } catch (err) {
    // Unresolvable while offline: say so, rather than reporting a label that
    // does not exist for a problem that is actually the network.
    return { ok: false, error: err?.queued ? "离线：库位无法核对，请先同步" : `库位查询失败：${err?.message ?? err}` };
  }

  const wanted = normalize(label);
  const matches = locations.filter((location) => locationAliases(location).has(wanted));

  if (matches.length === 0) {
    return { ok: false, error: `库位不存在：${label}（本仓库共 ${locations.length} 个库位）` };
  }
  if (matches.length > 1) {
    return {
      ok: false,
      error: `库位 ${label} 有 ${matches.length} 个重名，请用库位 ID`,
    };
  }
  return { ok: true, id: matches[0].id, label: matches[0].location_code || label };
}

/** Labels the operator can tap instead of typing. */
export async function locationOptions(warehouseId) {
  try {
    const res = await api.listLocations(warehouseId);
    return res?.items ?? (Array.isArray(res) ? res : []);
  } catch {
    // No locations today (offline, or none in this warehouse).  A picker that
    // fails silently is still better than one that blocks the whole screen.
    return [];
  }
}
