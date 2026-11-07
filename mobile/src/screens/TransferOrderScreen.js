/**
 * Transfer Order Screen — 跨库位/仓库调拨。
 *
 * Flow: select source → add items (scan) → confirm transfer.
 */
import React, { useState } from "react";
import { View, Text, TextInput, ScrollView, TouchableOpacity, Alert, ActivityIndicator } from "react-native";
import { api } from "../api/client";
import { alertMutationError } from "../api/errors";

export default function TransferOrderScreen({ route }) {
  const [sourceLocation, setSourceLocation] = useState("");
  const [destWarehouse, setDestWarehouse] = useState(route?.params?.warehouse_id ?? "");
  const [items, setItems] = useState([]); // [{ sku, quantity }]
  const [loading, setLoading] = useState(false);

  /** Add a scanned item to transfer. */
  function addItem(sku) {
    setItems(prev => [...prev, { sku: sku ?? "", quantity: prev.length > 0 ? prev[prev.length - 1].quantity : 1 }]);
  }

  function updateItemSku(index, sku) {
    setItems(prev => { const n = [...prev]; n[index] = { ...n[index], sku }; return n; });
  }

  function updateQty(index, qty) {
    setItems(prev => { const n = [...prev]; n[index] = { ...n[index], quantity: Number(qty) || 0 }; return n; });
  }

  /** Submit transfer order.
   *
   * The source is a warehouse, not a bin: the endpoint writes it into
   * TransferOrder.source_warehouse_id, and the field is named source_location
   * for historical reasons.  Both ends accept a warehouse id or a warehouse
   * code — a scanned code is resolved against warehouses.id/warehouses.code,
   * and a value that matches neither is refused by the field name (it used to
   * resolve to nothing and file an order with a NULL source).
   */
  async function submitTransfer() {
    if (!sourceLocation || !destWarehouse) return Alert.alert("提示", "请填写源仓库和目标仓库");
    setLoading(true);
    try {
      await api.createTransferOrder({
        source_location: sourceLocation,
        destination_warehouse_id: destWarehouse,
        items: items.map(i => ({ sku: i.sku, quantity: i.quantity })),
      });
      Alert.alert("✓", `调拨单已创建，共 ${items.length} 个 SKU`);
      setItems([]); setSourceLocation(""); setDestWarehouse(route?.params?.warehouse_id ?? "");
    } catch (err) {
      alertMutationError(err, "调拨失败");
    } finally { setLoading(false); }
  }

  return (
    <ScrollView style={styles.container} contentContainerStyle={{ paddingBottom: 60 }}>
      <Text style={styles.title}>🚛 库存调拨</Text>

      {/* Source + Destination */}
      <View style={styles.fieldRow}>
        <Text style={styles.label}>源仓库 *</Text>
        <TextInput value={sourceLocation} onChangeText={setSourceLocation} placeholder="仓库编码，如 WH-01" style={styles.input} />
      </View>

      <View style={styles.fieldRow}>
        <Text style={styles.label}>目标仓库 *</Text>
        <TextInput value={destWarehouse} onChangeText={setDestWarehouse} placeholder="仓库编码，如 WH-02" style={styles.input} />
      </View>

      {/* Items */}
      {items.map((item, i) => (
        <View key={i} style={[styles.card]}>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
            <TextInput value={item.sku} onChangeText={(v) => updateItemSku(i, v)} placeholder="扫描 SKU" style={styles.input} />
            <TextInput value={String(item.quantity)} keyboardType="numeric" onValueChange={(v) => updateQty(i, v)} style={[styles.input, { width: 60 }]} />
          </View>
        </View>
      ))}

      {/* Add item button */}
      <TouchableOpacity onPress={() => addItem("")} disabled={loading}>
        <Text style={styles.addBtn}>+ 添加 SKU</Text>
      </TouchableOpacity>

      {/* Submit */}
      <TouchableOpacity onPress={submitTransfer} disabled={loading} style={[styles.btnPrimary, loading && styles.btnDisabled]}>
        <ActivityIndicator size="small" color="#fff" animating={loading} />
        <Text style={styles.btnText}>{loading ? "提交中..." : "确认调拨"}</Text>
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
  card: { borderLeftWidth: 4, borderLeftColor: '#f59e0b', padding: 12, marginBottom: 8, backgroundColor: '#fffbe7' },
  addBtn: { color: '#0ea5a3', fontWeight: '600', marginVertical: 12 },
  btnPrimary: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', backgroundColor: '#0ea5a3', borderRadius: 8, padding: 14, marginTop: 20 },
  btnText: { color: '#fff', fontWeight: '600' },
  btnDisabled: { opacity: 0.5 },
};
