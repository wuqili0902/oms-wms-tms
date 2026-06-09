import React, { useEffect, useState, useCallback } from "react";
import {
  View,
  Text,
  FlatList,
  TouchableOpacity,
  StyleSheet,
  ActivityIndicator,
  RefreshControl,
} from "react-native";
import { useFocusEffect } from "@react-navigation/native";
import { api } from "../api/client";

const STATUS_BADGE = {
  draft: { label: "Draft", color: "#64748b", bg: "#f1f5f9" },
  confirmed: { label: "Confirmed", color: "#92400e", bg: "#fef3c7" },
  processing: { label: "Processing", color: "#1e40af", bg: "#dbeafe" },
  picking: { label: "Picking", color: "#1e40af", bg: "#dbeafe" },
  completed: { label: "Completed", color: "#166534", bg: "#dcfce7" },
  cancelled: { label: "Cancelled", color: "#991b1b", bg: "#fee2e2" },
  failed: { label: "Failed", color: "#991b1b", bg: "#fee2e2" },
};

function OrderItem({ order, onPress }) {
  const badge = STATUS_BADGE[order.status] || STATUS_BADGE.draft;
  return (
    <TouchableOpacity style={styles.orderCard} onPress={() => onPress(order)}>
      <View style={styles.orderHeader}>
        <Text style={styles.orderNo}>{order.order_no}</Text>
        <View style={[styles.badge, { backgroundColor: badge.bg }]}>
          <Text style={[styles.badgeText, { color: badge.color }]}>
            {badge.label}
          </Text>
        </View>
      </View>
      <Text style={styles.customer}>Customer: {order.customer_id || "—"}</Text>
      <Text style={styles.meta}>
        Items: {order.items?.length || 0} | Total: ${order.total_amount || "0.00"}
      </Text>
    </TouchableOpacity>
  );
}

export default function OrderListScreen({ navigation }) {
  const [orders, setOrders] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const fetchOrders = useCallback(async (isRefresh = false) => {
    if (isRefresh) setRefreshing(true);
    try {
      const data = await api.listOrders(1, 50);
      setOrders(data.items || []);
    } catch {
      // silent
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      fetchOrders();
    }, [fetchOrders])
  );

  const handleScan = () => navigation.navigate("Scanner");

  if (loading) {
    return (
      <View style={styles.center}>
        <ActivityIndicator size="large" color="#3b82f6" />
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <FlatList
        data={orders}
        keyExtractor={(item) => item.id}
        renderItem={({ item }) => (
          <OrderItem
            order={item}
            onPress={(o) => navigation.navigate("OrderDetail", { orderId: o.id })}
          />
        )}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={() => fetchOrders(true)} />
        }
        contentContainerStyle={orders.length === 0 ? styles.empty : styles.list}
        ListEmptyComponent={
          <View style={styles.emptyState}>
            <Text style={styles.emptyTitle}>No Orders</Text>
            <Text style={styles.emptyText}>Pull to refresh or create orders via the admin panel.</Text>
          </View>
        }
      />
      <TouchableOpacity style={styles.fab} onPress={handleScan}>
        <Text style={styles.fabText}>📷</Text>
      </TouchableOpacity>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#f5f7fa" },
  center: { flex: 1, justifyContent: "center", alignItems: "center" },
  list: { padding: 12 },
  empty: { flex: 1, padding: 12 },
  orderCard: {
    backgroundColor: "#fff",
    borderRadius: 10,
    padding: 14,
    marginBottom: 10,
    shadowColor: "#000",
    shadowOpacity: 0.05,
    shadowOffset: { width: 0, height: 1 },
    shadowRadius: 4,
    elevation: 2,
  },
  orderHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: 6,
  },
  orderNo: { fontSize: 16, fontWeight: "700", color: "#1e293b" },
  badge: { paddingHorizontal: 8, paddingVertical: 2, borderRadius: 12 },
  badgeText: { fontSize: 12, fontWeight: "600" },
  customer: { fontSize: 14, color: "#475569", marginBottom: 2 },
  meta: { fontSize: 13, color: "#94a3b8" },
  emptyState: { alignItems: "center", marginTop: 60 },
  emptyTitle: { fontSize: 18, fontWeight: "600", color: "#64748b" },
  emptyText: { fontSize: 14, color: "#94a3b8", marginTop: 4, textAlign: "center" },
  fab: {
    position: "absolute",
    right: 20,
    bottom: 24,
    width: 56,
    height: 56,
    borderRadius: 28,
    backgroundColor: "#3b82f6",
    justifyContent: "center",
    alignItems: "center",
    elevation: 6,
    shadowColor: "#3b82f6",
    shadowOpacity: 0.4,
    shadowOffset: { width: 0, height: 4 },
    shadowRadius: 8,
  },
  fabText: { fontSize: 22 },
});
