import React, { useEffect, useState, useCallback } from "react";
import {
  View,
  Text,
  FlatList,
  StyleSheet,
  ActivityIndicator,
  RefreshControl,
  Alert,
} from "react-native";
import { useFocusEffect } from "@react-navigation/native";
import { api } from "../api/client";

export default function PickingScreen() {
  const [waves, setWaves] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const fetchWaves = useCallback(async (isRefresh = false) => {
    if (isRefresh) setRefreshing(true);
    try {
      const data = await api.listPickingWaves();
      setWaves(data || []);
    } catch (err) {
      Alert.alert("Error", err.message || "Failed to load picking waves");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      fetchWaves();
    }, [fetchWaves])
  );

  if (loading) {
    return (
      <View style={styles.center}>
        <ActivityIndicator size="large" color="#3b82f6" />
      </View>
    );
  }

  const renderWave = ({ item }) => (
    <View style={styles.card}>
      <Text style={styles.waveNo}>{item.wave_no || item.code || "—"}</Text>
      <Text style={styles.meta}>
        Warehouse: {item.warehouse_id || "—"}
      </Text>
      <Text style={styles.meta}>
        Orders: {Array.isArray(item.order_ids) ? item.order_ids.length : 0}
      </Text>
    </View>
  );

  return (
    <View style={styles.container}>
      <FlatList
        data={waves}
        keyExtractor={(item) => item.id || Math.random().toString()}
        renderItem={renderWave}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={() => fetchWaves(true)} />
        }
        ListEmptyComponent={
          <View style={styles.center}>
            <Text style={styles.emptyText}>No picking waves</Text>
          </View>
        }
        contentContainerStyle={waves.length === 0 ? styles.emptyContainer : undefined}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#f5f7fa" },
  center: { flex: 1, justifyContent: "center", alignItems: "center", padding: 24 },
  emptyContainer: { flex: 1 },
  emptyText: { color: "#64748b", fontSize: 16 },
  card: {
    backgroundColor: "#fff",
    borderRadius: 10,
    padding: 16,
    marginHorizontal: 16,
    marginTop: 12,
    shadowColor: "#000",
    shadowOpacity: 0.05,
    shadowOffset: { width: 0, height: 1 },
    shadowRadius: 4,
    elevation: 2,
  },
  waveNo: { fontSize: 16, fontWeight: "600", color: "#1e293b", marginBottom: 4 },
  meta: { fontSize: 13, color: "#64748b", marginTop: 2 },
});
