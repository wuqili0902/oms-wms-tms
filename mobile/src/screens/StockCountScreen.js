/**
 * Stock Count Screen — PDA 盘点作业核心页面。
 *
 * Flow: select warehouse → scan location → load SKUs → compare with system qty.
 */
import React, { useState, useEffect } from "react";
import { View, Text, TextInput, ScrollView, TouchableOpacity, Alert, ActivityIndicator } from "react-native";
import { api } from "../api/client";
import { fetchWithCache } from "../api/cache";
import { alertMutationError } from "../api/errors";

export default function StockCountScreen({ route }) {
  const warehouseId = (route?.params?.warehouse_id ?? "").trim();

  if (!warehouseId) return <View style={styles.empty}><Text>请先选择仓库</Text></View>;

  // Location list loaded on mount
  const [locations, setLocations] = useState([]);
  const [selectedLocation, setSelectedLocation] = useState(null);
  const [invItems, setInvItems] = useState([]);
  const [scannedItems, setScannedItems] = useState({}); // sku → actual qty
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadLocations();
  }, []);

  // Cache-first, so a shelf with no signal still opens with the last known
  // layout.  The fresh answer lands in the cache for the next operator; this
  // render keeps showing what it had.
  async function loadLocations() {
    try {
      const res = await fetchWithCache(
        `inventory:locations:${warehouseId}`,
        () => api.queryInventory({ warehouse_id: warehouseId }),
        60 * 1000
      );
      // /warehouses/inventory answers a bare list; the {items: [...]} form is
      // what a paginated endpoint would give.  Accept both instead of silently
      // showing "暂无数据" when the server answered correctly.
      setLocations(Array.isArray(res) ? res : (res?.items ?? []));
    } catch (err) { console.error(err); }
  }

  async function startCount(location) {
    setSelectedLocation(location);
    // Load system inventory for this location
    try {
      const res = await fetchWithCache(
        // An inventory row keys its location as `location_id`; `id` is the
        // inventory record's own id.
        `inventory:location:${warehouseId}:${location.location_id}`,
        () => api.queryInventory({ warehouse_id: warehouseId, location_id: location.location_id }),
        30 * 1000
      );
      setInvItems(Array.isArray(res?.items) ? res.items : []);
    } catch (err) { console.error(err); }
  }

  function scanBarcode() {
    Alert.alert("扫描库存", "请使用条码扫描器或输入 SKU");
  }

  /** Record what the operator actually counted; 0 is a real count (盘亏). */
  function recordQty(sku, text) {
    const qty = Number(text);
    setScannedItems((prev) => {
      const next = { ...prev };
      if (text.trim() === "" || !Number.isFinite(qty) || qty < 0) delete next[sku];
      else next[sku] = qty;
      return next;
    });
  }

  /** Submit count results for this location. */
  async function submitCount() {
    const results = Object.entries(scannedItems).map(([sku, qty]) => ({ sku, actual_qty: qty }));
    if (results.length === 0) return Alert.alert("提示", "请扫描至少一个 SKU");

    try {
      await api.adjustStockCount({
        // The screen was given the warehouse id on navigation, and the inventory
        // row carries `location_id`.  Sending the inventory row's own `id` (or a
        // warehouse *code* that this warehouse never had) makes the backend
        // answer 404/422 for a count the operator really performed.
        warehouse_id: warehouseId,
        location_id: selectedLocation?.location_id ?? selectedLocation?.id,
        // Exactly the names adjust_stock_count reads.  Re-mapping them to
        // aliases that resolve to undefined would silently submit a zero count.
        count_results: results.map(r => ({ sku_code: r.sku, actual_qty: r.actual_qty })),
      });
      Alert.alert("✓", `盘点已提交，共 ${results.length} 个 SKU`);
      setScannedItems({});
    } catch (err) {
      alertMutationError(err, "提交失败");
    }
  }

  function renderDiff(item) {
    const systemQty = item.quantity ?? 0;
    const actualQty = scannedItems[item.sku] ?? 0;
    if (actualQty === 0 && systemQty > 0) return <Text style={styles.missing}>未盘点</Text>;
    if (actualQty !== systemQty) return <Text style={styles.diff}>{actualQty} vs {systemQty}</Text>;
    return <Text style={styles.match}>✓ {systemQty}</Text>;
  }

  return (
    <ScrollView style={styles.container}>
      <Text style={styles.title}>📋 库存盘点</Text>

      {!selectedLocation ? (
        <>
          <Text style={styles.subTitle}>选择库位开始盘点</Text>
          {locations.length === 0 && <View><Text style={{ color: '#666', padding: 10 }}>暂无数据 — 请先入库商品</Text></View>}
          {locations.map(loc => (
            <TouchableOpacity key={loc.id} onPress={() => startCount(loc)} style={[styles.locationCard, styles.card]}>
              <Text style={styles.locCode}>{loc.code || loc.location_id?.slice(0, 8) || '—'}</Text>
              <Text style={styles.locInfo}>库位: {loc.name || loc.zone || 'A-1'} | SKU: {loc.sku}</Text>
            </TouchableOpacity>
          ))}
        </>
      ) : (
        <>
          {/* Header: current location */}
          <View style={styles.header}>
            <Text style={styles.headerTitle}>{selectedLocation.name || '库位'}</Text>
            <TouchableOpacity onPress={() => setSelectedLocation(null)}><Text style={{ color: '#0ea5a3', fontSize: 14 }}>← 返回</Text></TouchableOpacity>
          </View>

          {/* Scan button */}
          <TouchableOpacity onPress={scanBarcode} style={[styles.btnPrimary, { marginBottom: 8 }]}>
            <Text style={styles.btnText}>📷 扫描条码 (Shift+Enter)</Text>
          </TouchableOpacity>

          {/* Inventory list */}
          {invItems.map(item => {
            const actual = scannedItems[item.sku] ?? null;
            return (
              <View key={item.id} style={[styles.invItem, styles.card, actual ? styles.scanned : {}]}>
                <Text style={styles.sku}>{item.sku}</Text>
                <Text style={styles.name}>{item.product_name || item.name || '—'}</Text>
                <View style={{ flexDirection: 'row', alignItems: 'center', gap: 12 }}>
                  <Text style={styles.systemQty}>系统: {item.quantity ?? 0}</Text>
                  {/* The submit step reads only `scannedItems`, so an unbound
                      input here would submit a count of zero for every SKU. */}
                  <TextInput
                    value={actual?.toString() ?? ''}
                    keyboardType="numeric"
                    placeholder="-"
                    onChangeText={(text) => recordQty(item.sku, text)}
                    style={styles.qtyInput}
                  />
                  {renderDiff(item)}
                </View>
              </View>
            );
          })}

          {/* Submit */}
          <TouchableOpacity onPress={submitCount} disabled={loading} style={[styles.btnPrimary, loading && styles.btnDisabled]}>
            <ActivityIndicator size="small" color="#fff" animating={loading} />
            <Text style={styles.btnText}>{loading ? "提交中..." : "提交盘点结果"}</Text>
          </TouchableOpacity>
        </>
      )}

      <View style={{ height: 40 }} />
    </ScrollView>
  );
}

const styles = {
  container: { padding: 16 },
  title: { fontSize: 24, fontWeight: '600', marginBottom: 8, color: '#333' },
  subTitle: { fontSize: 16, marginBottom: 12, color: '#555' },
  empty: { flex: 1, justifyContent: 'center', alignItems: 'center', padding: 40 },
  header: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', backgroundColor: '#f8fafc', padding: 12, borderRadius: 8, marginBottom: 8 },
  headerTitle: { fontWeight: '600' },
  card: { borderLeftWidth: 4, borderLeftColor: '#0ea5a3', padding: 12, marginBottom: 8, backgroundColor: '#f8fafc', borderRadius: 8 },
  locationCard: {},
  locCode: { fontSize: 16, fontWeight: '600' },
  locInfo: { color: '#666', fontSize: 13 },
  sku: { fontWeight: '600', fontSize: 15 },
  name: { color: '#555', fontSize: 12 },
  systemQty: { color: '#888' },
  invItem: {},
  scanned: { borderLeftColor: '#f59e0b' },
  qtyInput: { width: 60, borderWidth: 1, borderColor: '#ccc', borderRadius: 4, padding: 4, fontSize: 14, textAlign: 'center' },
  diff: { color: '#ef4444', fontWeight: '600' },
  match: { color: '#22c55e', fontWeight: '600' },
  missing: { color: '#f97316' },
  btnPrimary: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', backgroundColor: '#0ea5a3', borderRadius: 8, padding: 14, marginTop: 12 },
  btnText: { color: '#fff', fontWeight: '600' },
  btnDisabled: { opacity: 0.5 },
};
