/**
 * Receive Goods Screen — 采购单收货。
 *
 * Flow: scan PO → show expected items → confirm received qty → update status.
 */
import React, { useState, useEffect } from "react";
import { View, Text, TextInput, ScrollView, TouchableOpacity, Alert, ActivityIndicator } from "react-native";
import { api } from "../api/client";

export default function ReceiveGoodsScreen({ route }) {
  const [poId, setPoId] = useState("");
  const [poItems, setPoItems] = useState([]); // [{ sku, expected_qty, received_qty }]
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => { loadPO(); }, []);

  async function loadPO() {
    try {
      const res = await api.listPurchaseOrders("pending"); // status=pending → awaiting receipt
      if (res?.items && res.items.length > 0) {
        setPoItems(res.items[0]?.items ?? []); // first pending PO
      } else {
        Alert.alert("提示", "暂无待收货采购单");
      }
    } catch (err) { console.error(err); } finally { setLoading(false); }
  }

  /** Update received quantity for a single item. */
  function updateReceived(sku, qty) {
    setPoItems(prev => prev.map(item =>
      item.sku === sku ? { ...item, received_qty: qty != null && qty !== "" ? Number(qty) : (item.received_qty || 0) } : item
    ));
  }

  async function submitReceive() {
    const total = poItems.reduce((sum, i) => sum + (i.received_qty || 0), 0);
    if (total === 0) return Alert.alert("提示", "请确认收货数量");

    setSubmitting(true);
    try {
      await api.receiveGoods(poId, { items: poItems }); // POST /purchase-orders/{id}/receive
      Alert.alert("✓", `收货已确认，共 ${total} 件`);
      setPoItems([]); // refresh next time
    } catch (err) {
      Alert.alert("✗", err.message || "收货失败");
    } finally { setSubmitting(false); }
  }

  return (
    <ScrollView style={styles.container}>
      <Text style={styles.title}>📥 采购收货</Text>

      {/* PO info */}
      {!poItems.length ? (
        loading ? <ActivityIndicator size="large" color="#0ea5a3" /> :
          <View><Text style={{ color: '#666', padding: 20 }}>暂无待收货采购单</Text></View>
      ) : (
        poItems.map(item => {
          const diff = item.received_qty - item.expected_qty;
          return (
            <View key={item.sku} style={[styles.card, styles.itemCard]}>
              <Text style={styles.sku}>{item.sku}</Text>
              <Text style={styles.name}>{item.product_name || '—'}</Text>
              <View style={{ flexDirection: 'row', gap: 12, marginTop: 4 }}>
                <View><Text style={styles.label}>应收:</Text><Text>{item.expected_qty}</Text></View>
                <View><Text style={styles.label}>实收:</Text>
                  <TextInput value={String(item.received_qty)} keyboardType="numeric" style={styles.input} />
                </View>
                {diff > 0 ? <Text style={{ color: '#22c55e', fontWeight: '600' }}>✓ 已超</Text> : null}
                {diff < 0 && item.received_qty > 0 ? <Text style={{ color: '#f97316', fontWeight: '600' }}>{diff}</Text> : null}
              </View>
            </View>
          );
        })
      )}

      {/* Submit */}
      <TouchableOpacity onPress={submitReceive} disabled={submitting} style={[styles.btnPrimary, submitting && styles.btnDisabled]}>
        <ActivityIndicator size="small" color="#fff" animating={submitting} />
        <Text style={styles.btnText}>{submitting ? "确认中..." : "确认收货"}</Text>
      </TouchableOpacity>

      <View style={{ height: 40 }} />
    </ScrollView>
  );
}

const styles = {
  container: { padding: 16 },
  title: { fontSize: 24, fontWeight: '600', marginBottom: 8, color: '#333' },
  card: {},
  itemCard: { borderLeftWidth: 4, borderLeftColor: '#0ea5a3', padding: 12, marginBottom: 8, backgroundColor: '#f8fafc', borderRadius: 8 },
  sku: { fontWeight: '600' },
  name: { color: '#555', fontSize: 12 },
  label: { marginRight: 4 },
  input: { borderWidth: 1, borderColor: '#ccc', borderRadius: 4, padding: 8, width: 80, textAlign: 'center' },
  btnPrimary: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', backgroundColor: '#0ea5a3', borderRadius: 8, padding: 14, marginTop: 20 },
  btnText: { color: '#fff', fontWeight: '600' },
  btnDisabled: { opacity: 0.5 },
};
