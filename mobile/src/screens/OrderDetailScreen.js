import React, { useEffect, useState } from "react";
import {
  View,
  Text,
  ScrollView,
  StyleSheet,
  ActivityIndicator,
  TouchableOpacity,
  Alert,
} from "react-native";
import { api } from "../api/client";

const TRANSITION_ACTIONS = ["confirmed", "processing", "picking", "completed", "cancelled"];

export default function OrderDetailScreen({ route, navigation }) {
  const { orderId } = route.params;
  const [order, setOrder] = useState(null);
  const [loading, setLoading] = useState(true);
  const [updating, setUpdating] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const data = await api.getOrder(orderId);
        setOrder(data);
      } catch {
        Alert.alert("Error", "Failed to load order");
        navigation.goBack();
      } finally {
        setLoading(false);
      }
    })();
  }, [orderId]);

  const handleTransition = async (targetStatus) => {
    setUpdating(true);
    try {
      const updated = await api.updateOrderStatus(orderId, targetStatus);
      setOrder(updated);
      Alert.alert("Success", `Order status updated to ${targetStatus}`);
    } catch (err) {
      Alert.alert("Error", err.message || "Transition failed");
    } finally {
      setUpdating(false);
    }
  };

  if (loading) {
    return (
      <View style={styles.center}>
        <ActivityIndicator size="large" color="#3b82f6" />
      </View>
    );
  }

  if (!order) return null;

  const allowedTransitions = {
    draft: ["confirmed", "cancelled"],
    confirmed: ["processing", "cancelled"],
    processing: ["picking", "cancelled"],
    picking: ["completed", "cancelled"],
  };

  const nextStates = allowedTransitions[order.status] || [];

  return (
    <ScrollView style={styles.container}>
      <View style={styles.card}>
        <Text style={styles.orderNo}>{order.order_no}</Text>
        <Text style={styles.status}>{order.status}</Text>
      </View>

      <View style={styles.card}>
        <Text style={styles.sectionTitle}>Details</Text>
        <InfoRow label="Customer ID" value={order.customer_id} />
        <InfoRow label="Priority" value={order.priority} />
        <InfoRow label="Total" value={`$${order.total_amount}`} />
        <InfoRow label="Notes" value={order.notes || "—"} />
        <InfoRow label="Created" value={order.created_at} />
      </View>

      {order.items?.length > 0 && (
        <View style={styles.card}>
          <Text style={styles.sectionTitle}>Items</Text>
          {order.items.map((item, i) => (
            <View key={i} style={styles.itemRow}>
              <View style={{ flex: 1 }}>
                <Text style={styles.itemSku}>{item.sku}</Text>
                <Text style={styles.itemName}>{item.product_name || "—"}</Text>
              </View>
              <Text style={styles.itemQty}>x{item.quantity}</Text>
            </View>
          ))}
        </View>
      )}

      {nextStates.length > 0 && (
        <View style={styles.card}>
          <Text style={styles.sectionTitle}>Actions</Text>
          <View style={styles.actions}>
            {nextStates.map((state) => (
              <TouchableOpacity
                key={state}
                style={[styles.actionBtn, updating && styles.btnDisabled]}
                onPress={() => handleTransition(state)}
                disabled={updating}
              >
                <Text style={styles.actionBtnText}>
                  {updating ? "..." : `Mark ${state}`}
                </Text>
              </TouchableOpacity>
            ))}
          </View>
        </View>
      )}

      <View style={{ height: 40 }} />
    </ScrollView>
  );
}

function InfoRow({ label, value }) {
  return (
    <View style={styles.infoRow}>
      <Text style={styles.infoLabel}>{label}</Text>
      <Text style={styles.infoValue}>{value || "—"}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#f5f7fa" },
  center: { flex: 1, justifyContent: "center", alignItems: "center" },
  card: {
    backgroundColor: "#fff",
    borderRadius: 10,
    padding: 16,
    marginHorizontal: 12,
    marginTop: 12,
    shadowColor: "#000",
    shadowOpacity: 0.04,
    shadowOffset: { width: 0, height: 1 },
    shadowRadius: 4,
    elevation: 2,
  },
  orderNo: { fontSize: 20, fontWeight: "700", color: "#1e293b" },
  status: { fontSize: 14, color: "#64748b", marginTop: 4 },
  sectionTitle: { fontWeight: "600", fontSize: 15, color: "#1e293b", marginBottom: 10 },
  infoRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    paddingVertical: 6,
    borderBottomWidth: 1,
    borderBottomColor: "#f1f5f9",
  },
  infoLabel: { fontSize: 14, color: "#64748b" },
  infoValue: { fontSize: 14, color: "#1e293b", fontWeight: "500" },
  itemRow: {
    flexDirection: "row",
    alignItems: "center",
    paddingVertical: 8,
    borderBottomWidth: 1,
    borderBottomColor: "#f1f5f9",
  },
  itemSku: { fontSize: 14, fontWeight: "600", color: "#1e293b" },
  itemName: { fontSize: 12, color: "#64748b", marginTop: 2 },
  itemQty: { fontSize: 15, fontWeight: "600", color: "#3b82f6", marginLeft: 12 },
  actions: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  actionBtn: {
    backgroundColor: "#3b82f6",
    borderRadius: 8,
    paddingVertical: 10,
    paddingHorizontal: 16,
  },
  actionBtnText: { color: "#fff", fontWeight: "600", fontSize: 14 },
  btnDisabled: { opacity: 0.5 },
});
