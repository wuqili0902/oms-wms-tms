/**
 * Packing Record Screen — 打包作业。
 *
 * Flow: scan order → load items → scan each item to confirm qty → create packing.
 */
import React, { useState } from "react";
import { View, Text, TextInput, ScrollView, TouchableOpacity, Alert, ActivityIndicator } from "react-native";
import { api } from "../api/client";

export default function PackingRecordScreen({ route }) {
  const [orderId, setOrderId] = useState("");
  const [orderItems, setOrderItems] = useState([]);
  const [confirmedItems, setConfirmedItems] = useState({}); // sku → confirmed qty
  const [loading, setLoading] = useState(false);

  /** Load order items for packing. */
  async function loadOrder() {
    if (!orderId) return;
    try {
      const res = await api.getOrder(orderId); // returns OrderDetail
      setOrderItems(res?.items ?? []);
      Alert.alert("✓", `加载订单成功: ${res?.order_no}`);
    } catch (err) {
      Alert.alert("✗", "订单不存在或网络异常");
      console.error(err);
    }
  }

  /** Confirm scanned item matches the order. */
  async function confirmItem(sku, qty) {
    setConfirmedItems(prev => ({ ...prev, [sku]: qty }));
  }

  /** Submit packing record to backend. */
  async function submitPacking() {
    const confirmed = Object.entries(confirmedItems);
    if (confirmed.length === 0) return Alert.alert("提示", "请扫描至少一个 SKU");

    setLoading(true);
    try {
      await api.createPackingRecord({
        order_id: orderId,
        items: confirmed.map(([sku, qty]) => ({ sku, quantity: qty })),
      });
      Alert.alert("✓", `打包记录已提交，共 ${confirmed.length} 个 SKU`);
      // Reset for next packing
      setOrderId(""); setOrderItems([]); setConfirmedItems({});
    } catch (err) {
      Alert.alert("✗", err.message || "打包失败");
    } finally { setLoading(false); }
  }

  return (
    <ScrollView style={styles.container} contentContainerStyle={{ paddingBottom: 60 }}>
      <Text style={styles.title}>📦 打包作业</Text>

      {/* Order input */}
      <View style={styles.fieldRow}>
        <Text style={styles.label}>订单号 / ID *</Text>
        <TextInput value={orderId} onChangeText={setOrderId} placeholder="扫描 PO 或输入" style={styles.input} />
        <TouchableOpacity onPress={loadOrder} style={styles.btnSecondary}><Text style={styles.btnText}>加载</Text></TouchableOpacity>
      </View>

      {/* Order items to pack */}
      {orderItems.map(item => (
        <View key={item.sku + item.id} style={[styles.itemCard, styles.card]}>
          <View style={{ flexDirection: 'row', justifyContent: 'space-between' }}>
            <Text style={styles.sku}>{item.sku}</Text>
            <Text style={styles.qty}>需打包: {item.quantity}</Text>
          </View>
          <Text style={styles.name}>{item.product_name || item.name || ''}</Text>

          {/* Confirm qty */}
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8, marginTop: 4 }}>
            <TouchableOpacity onPress={() => confirmItem(item.sku, (confirmedItems[item.sku] || 0) - 1)} style={styles.qtyBtn}>
              <Text style={styles.qtyBtnText}>−</Text>
            </TouchableOpacity>
            <Text style={styles.confirmedQty}>{confirmedItems[item.sku] ?? 0}</Text>
            <TouchableOpacity onPress={() => confirmItem(item.sku, (confirmedItems[item.sku] || 0) + 1)} style={styles.qtyBtn}>
              <Text style={styles.qtyBtnText}>+</Text>
            </TouchableOpacity>
          </View>
        </View>
      ))}

      {/* Submit */}
      <TouchableOpacity onPress={submitPacking} disabled={loading} style={[styles.btnPrimary, loading && styles.btnDisabled]}>
        <ActivityIndicator size="small" color="#fff" animating={loading} />
        <Text style={styles.btnText}>{loading ? "提交中..." : "确认打包"}</Text>
      </TouchableOpacity>

      <View style={{ height: 40 }} />
    </ScrollView>
  );
}

const styles = {
  container: { padding: 16 },
  title: { fontSize: 24, fontWeight: '600', marginBottom: 8, color: '#333' },
  fieldRow: { flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: 12 },
  label: { width: 70, fontWeight: '600' },
  input: { flex: 1, borderWidth: 1, borderColor: '#ccc', borderRadius: 8, padding: 12, fontSize: 16 },
  card: { borderLeftWidth: 4, borderLeftColor: '#0ea5a3', padding: 12, marginBottom: 8, backgroundColor: '#f8fafc', borderRadius: 8 },
  itemCard: {},
  sku: { fontWeight: '600', fontSize: 15 },
  name: { color: '#555', fontSize: 12 },
  qty: { color: '#888' },
  confirmedQty: { fontSize: 20, fontWeight: '700', minWidth: 40, textAlign: 'center' },
  btnPrimary: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', backgroundColor: '#0ea5a3', borderRadius: 8, padding: 14, marginTop: 20 },
  btnSecondary: { paddingVertical: 10, paddingHorizontal: 16, backgroundColor: '#e2e8f0', borderRadius: 8 },
  qtyBtn: { width: 36, height: 36, borderWidth: 1, borderColor: '#ccc', borderRadius: 8, alignItems: 'center', justifyContent: 'center' },
  qtyBtnText: { color: '#333', fontSize: 20, fontWeight: '600' },
  btnText: { color: '#fff', fontWeight: '600' },
  btnDisabled: { opacity: 0.5 },
};
