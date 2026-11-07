/**
 * Stock In Screen — receive goods into warehouse.
 *
 * Flow: scan barcode → auto-fill SKU + batch → select location → confirm qty → submit.
 */
import React, { useState } from "react";
import {
  View, Text, TextInput, StyleSheet, ScrollView, Alert, TouchableOpacity, ActivityIndicator,
} from "react-native";
import { api } from "../api/client";
import { alertMutationError } from "../api/errors";
import { resolveLocationRef } from "../api/locations";

export default function StockInScreen({ route }) {
  const warehouseId = (route?.params?.warehouse_id ?? "").trim();
  if (!warehouseId) return <View style={styles.empty}><Text>请先选择仓库</Text></View>;

  // Form state
  const [gtin, setGtin] = useState("");       // scanned barcode
  const [sku, setSku] = useState("");          // resolved SKU
  const [productName, setProductName] = useState("");
  const [batchNo, setBatchNo] = useState("");
  const [expiryDate, setExpiryDate] = useState("");
  const [locationId, setLocationId] = useState("");
  const [quantity, setQuantity] = useState("1");
  const [loading, setLoading] = useState(false);

  /** Resolve barcode to SKU (uses backend validation). */
  async function resolveBarcode() {
    if (!gtin.trim()) return;
    try {
      const res = await api.validateBarcode(gtin); // returns { sku, name }
      setSku(res?.sku ?? "");
      setProductName(res?.name ?? "");
      Alert.alert("✓", `条码识别成功: ${res?.sku}`);
    } catch (err) {
      Alert.alert("✗", "条码无效");
      console.error(err);
    }
  }

  async function submitStockIn() {
    if (!sku || !locationId) return Alert.alert("提示", "请填入 SKU 和库位");
    // parseInt("") is NaN, and JSON.stringify(NaN) is null — the request would
    // go out as a missing quantity and the operator would get a 422 they cannot
    // act on.  Reject it here, where the field is.
    const qty = Number(quantity);
    if (!Number.isInteger(qty) || qty <= 0) return Alert.alert("提示", "数量必须是正整数");

    // FEFO only works if intake records an expiry: with expiry NULL the picking
    // strategy degenerates to FIFO and the nearest-expiry batch is picked last.
    const expiry = expiryDate.trim();
    if (expiry && !/^\d{4}-\d{2}-\d{2}$/.test(expiry)) {
      return Alert.alert("提示", "有效期格式应为 YYYY-MM-DD");
    }

    setLoading(true);
    try {
      // 库位 is typed as a shelf label (A-01-02) but the API keys locations by
      // id; sending the label reaches the backend as an id it cannot parse and
      // comes back as a warehouse 404 the operator cannot make sense of.
      const resolved = await resolveLocationRef(warehouseId, locationId);
      if (!resolved.ok) return Alert.alert("提示", resolved.error);

      await api.adjustInventory({
        sku,
        location_id: resolved.id,
        quantity: qty,
        warehouse_id: warehouseId,
        // The batch the operator actually scanned: adjust_inventory keys
        // inventory by batch, so dropping it lands the stock on "DEFAULT".
        batch_no: batchNo.trim() || undefined,
        expiry_date: expiry || undefined,
        reason: "pda_stock_in",
      });
      // The label is repeated back: the operator should be able to check that
      // the stock landed on the shelf they were standing in front of.
      Alert.alert("✓", `入库成功：${qty} 件 → ${resolved.label}${batchNo ? ` (批次 ${batchNo})` : ""}`);
      // Reset form for next item
      setGtin(""); setSku(""); setProductName(""); setBatchNo(""); setExpiryDate(""); setLocationId(""); setQuantity("1");
    } catch (err) {
      alertMutationError(err, "入库失败");
    } finally { setLoading(false); }
  }

  return (
    <ScrollView style={styles.container} contentContainerStyle={{ paddingBottom: 60 }}>
      <Text style={styles.title}>📥 商品入库</Text>

      <View style={styles.fieldRow}>
        <Text style={styles.label}>扫描条码 / GTIN</Text>
        <TextInput value={gtin} onChangeText={setGtin} placeholder="扫码或手动输入" style={styles.input} />
        <TouchableOpacity onPress={resolveBarcode} style={styles.btnSecondary}><Text style={styles.btnText}>识别</Text></TouchableOpacity>
      </View>

      <View style={styles.fieldRow}>
        <Text style={styles.label}>SKU *</Text>
        <TextInput value={sku} onChangeText={setSku} placeholder="自动填充" editable={!productName} style={styles.input} />
      </View>

      {productName ? (
        <View><Text style={styles.info}>商品: {productName}</Text></View>
      ) : null}

      <View style={styles.fieldRow}>
        <Text style={styles.label}>库位 *</Text>
        <TextInput value={locationId} onChangeText={setLocationId} placeholder="如 A-01-02" style={styles.input} />
      </View>

      <View style={styles.fieldRow}>
        <Text style={styles.label}>批次号</Text>
        <TextInput value={batchNo} onChangeText={setBatchNo} placeholder="可选" style={styles.input} />
      </View>

      <View style={styles.fieldRow}>
        <Text style={styles.label}>有效期</Text>
        <TextInput value={expiryDate} onChangeText={setExpiryDate} placeholder="YYYY-MM-DD" style={styles.input} />
      </View>

      <View style={styles.fieldRow}>
        <Text style={styles.label}>数量 *</Text>
        <TextInput value={quantity} onChangeText={setQuantity} keyboardType="numeric" style={styles.input} />
      </View>

      <TouchableOpacity onPress={submitStockIn} disabled={loading} style={[styles.btnPrimary, loading && styles.btnDisabled]}>
        <ActivityIndicator size="small" color="#fff" animating={loading} />
        <Text style={styles.btnText}>{loading ? "提交中..." : "确认入库"}</Text>
      </TouchableOpacity>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { padding: 20 },
  title: { fontSize: 24, fontWeight: '600', marginBottom: 16, color: '#333' },
  empty: { flex: 1, justifyContent: 'center', alignItems: 'center', padding: 40 },
  fieldRow: { flexDirection: 'row', alignItems: 'center', marginBottom: 12, gap: 8 },
  label: { width: 70, fontWeight: '600' },
  input: { flex: 1, borderWidth: 1, borderColor: '#ccc', borderRadius: 8, padding: 12, fontSize: 16 },
  info: { color: '#555', fontStyle: 'italic', marginBottom: 8 },
  btnPrimary: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', backgroundColor: '#0ea5a3', borderRadius: 8, padding: 14, marginTop: 20 },
  btnSecondary: { paddingVertical: 10, paddingHorizontal: 16, backgroundColor: '#e2e8f0', borderRadius: 8 },
  btnText: { color: '#fff', fontWeight: '600' },
  btnDisabled: { opacity: 0.5 },
});
