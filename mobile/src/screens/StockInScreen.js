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

export default function StockInScreen({ route }) {
  const warehouseId = (route?.params?.warehouse_id ?? "").trim();
  if (!warehouseId) return <View style={styles.empty}><Text>请先选择仓库</Text></View>;

  // Form state
  const [gtin, setGtin] = useState("");       // scanned barcode
  const [sku, setSku] = useState("");          // resolved SKU
  const [productName, setProductName] = useState("");
  const [batchNo, setBatchNo] = useState("");
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
    setLoading(true);
    try {
      await api.adjustInventory({
        sku, location_id: locationId, quantity: parseInt(quantity), warehouse_id: warehouseId,
        operation_type: "stock_in", batch_no: batchNo || undefined,
      });
      Alert.alert("✓", `入库成功，数量 ${quantity}`);
      // Reset form for next item
      setGtin(""); setSku(""); setProductName(""); setBatchNo(""); setLocationId(""); setQuantity("1");
    } catch (err) {
      Alert.alert("✗", err.message || "入库失败");
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
