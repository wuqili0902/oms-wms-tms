/**
 * Home Screen — 作业台 / warehouse workbench.
 *
 * The entry point after login.  It exists because every PDA screen works
 * inside one warehouse and takes `warehouse_id` as a route parameter, and
 * nothing used to link to them: an operator logged in, saw the order list, and
 * could not reach 入库 / 盘点 / 收货 / 调拨 at all — which also meant the
 * offline queue and its banner were unreachable, since only those screens
 * queue anything.
 *
 * The chosen warehouse is remembered across launches: a PDA works in one
 * warehouse per shift, and re-picking it after every app restart is how
 * operators end up booking stock in the wrong building.
 */
import { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator, Alert, FlatList, StyleSheet, Text, TouchableOpacity, View,
} from "react-native";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { useNavigation } from "@react-navigation/native";
import { api, getConnectionState, subscribeConnection } from "../api/client";
import { fetchWithCache } from "../api/cache";

const WAREHOUSE_KEY = "selected_warehouse_id";

// Socket state → what the operator reads.  "未连接" is not an error state on a
// PDA: offline work is supported, and saying so is what makes 待同步 counts
// believable instead of mysterious.
const LINK_STATE = {
  online: { label: "🟢 已连接", color: "#166534" },
  connecting: { label: "🟡 连接中…", color: "#854d0e" },
  offline: { label: "⚪ 未连接（离线可作业）", color: "#b91c1c" },
};

const ACTIONS = [
  { screen: "StockIn", label: "📥 入库", needsWarehouse: true },
  { screen: "ReceiveGoods", label: "📦 采购收货", needsWarehouse: true },
  { screen: "StockCount", label: "🧮 盘点", needsWarehouse: true },
  { screen: "TransferOrder", label: "🔁 调拨", needsWarehouse: true },
  { screen: "PackingRecord", label: "🎁 打包", needsWarehouse: false },
  { screen: "Picking", label: "🎯 拣货波次", needsWarehouse: false },
  { screen: "Inventory", label: "📚 库存", needsWarehouse: false },
  { screen: "Orders", label: "📋 订单", needsWarehouse: false },
];

export default function HomeScreen() {
  const navigation = useNavigation();
  const [warehouses, setWarehouses] = useState([]);
  const [warehouseId, setWarehouseId] = useState("");
  const [loading, setLoading] = useState(true);
  const [connection, setConnection] = useState(getConnectionState());

  // The offline banner only appears once something is queued, so an operator
  // with a dead link and an empty queue is told nothing at all — right up to
  // the moment they scan ten pallets and have to guess.  The socket is the
  // app's actual link to the server, so its state belongs on the screen the
  // shift starts on.
  useEffect(() => subscribeConnection(setConnection), []);

  const loadWarehouses = useCallback(async (forceRefresh = false) => {
    try {
      const data = await fetchWithCache(
        "warehouses:list",
        () => api.listWarehouses(1, 100),
        5 * 60 * 1000,
        { forceRefresh }
      );
      const items = data?.items ?? (Array.isArray(data) ? data : []);
      setWarehouses(items);

      const remembered = await AsyncStorage.getItem(WAREHOUSE_KEY);
      // A warehouse that no longer exists must not stay selected: every screen
      // downstream books stock against it.
      const valid = items.some((wh) => String(wh.id) === remembered);
      const next = valid ? remembered : (items[0]?.id ? String(items[0].id) : "");
      setWarehouseId(next);
      if (valid) await AsyncStorage.setItem(WAREHOUSE_KEY, next);
    } catch (err) {
      // Offline is a normal state here: the cache above already answered when
      // there was one, and the operator can still queue work.
      console.warn("warehouse list unavailable:", err?.message ?? err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadWarehouses();
  }, [loadWarehouses]);

  async function chooseWarehouse(id) {
    const next = String(id);
    setWarehouseId(next);
    await AsyncStorage.setItem(WAREHOUSE_KEY, next);
  }

  function openAction(action) {
    if (action.needsWarehouse && !warehouseId) {
      // This screen *is* the warehouse picker, so there is nowhere to send
      // them.  Say what is missing instead of opening a screen that shows a
      // spinner on "请先选择仓库".
      Alert.alert("提示", "请先在上方选择仓库");
      return;
    }
    navigation.navigate(action.screen, action.needsWarehouse ? { warehouse_id: warehouseId } : undefined);
  }

  const selected = warehouses.find((wh) => String(wh.id) === warehouseId);

  return (
    <View style={styles.container}>
      <Text style={styles.title}>🏭 仓库作业台</Text>

      {loading ? (
        <View style={styles.center}><ActivityIndicator size="large" color="#0ea5a3" /></View>
      ) : (
        <>
          {warehouses.length === 0 ? (
            <Text style={styles.empty}>
              没有可用仓库，或离线且无缓存。请检查网络后下拉刷新。
            </Text>
          ) : (
            <FlatList
              horizontal
              showsHorizontalScrollIndicator={false}
              data={warehouses}
              keyExtractor={(wh) => String(wh.id)}
              onRefresh={() => loadWarehouses(true)}
              refreshing={false}
              renderItem={({ item }) => (
                <TouchableOpacity
                  onPress={() => chooseWarehouse(item.id)}
                  style={[styles.whChip, String(item.id) === warehouseId ? styles.whChipActive : null]}
                >
                  <Text style={[styles.whText, String(item.id) === warehouseId ? styles.whTextActive : null]}>
                    {item.name || item.code}
                  </Text>
                  <Text style={[styles.whSub, String(item.id) === warehouseId ? styles.whTextActive : null]}>
                    {item.code}
                  </Text>
                </TouchableOpacity>
              )}
            />
          )}

          <View style={styles.statusRow}>
            <Text style={styles.subtitle}>
              {selected ? `当前仓库：${selected.name || selected.code}` : "尚未选择仓库"}
            </Text>
            <Text style={[styles.linkText, { color: LINK_STATE[connection]?.color ?? "#475569" }]}>
              {LINK_STATE[connection]?.label ?? "连接状态未知"}
            </Text>
          </View>

          <View style={styles.grid}>
            {ACTIONS.map((action) => {
              const blocked = action.needsWarehouse && !warehouseId;
              return (
                <TouchableOpacity
                  key={action.screen}
                  onPress={() => openAction(action)}
                  style={[styles.tile, blocked && styles.tileBlocked]}
                >
                  <Text style={styles.tileText}>{action.label}</Text>
                </TouchableOpacity>
              );
            })}
          </View>
        </>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, padding: 16, backgroundColor: "#f5f7fa" },
  center: { flex: 1, justifyContent: "center", alignItems: "center" },
  title: { fontSize: 22, fontWeight: "600", color: "#0f172a", marginBottom: 12 },
  empty: { color: "#64748b", fontSize: 14, paddingVertical: 16 },
  whChip: {
    paddingHorizontal: 14, paddingVertical: 10, marginRight: 8,
    backgroundColor: "#e2e8f0", borderRadius: 10, minWidth: 130,
  },
  whChipActive: { backgroundColor: "#1e293b" },
  whText: { fontSize: 14, fontWeight: "600", color: "#1e293b" },
  whTextActive: { color: "#f8fafc" },
  whSub: { fontSize: 11, color: "#64748b", marginTop: 2 },
  statusRow: { marginTop: 12, flexDirection: "row", alignItems: "center", gap: 12 },
  subtitle: { fontSize: 13, color: "#334155", flexShrink: 1 },
  linkText: { fontSize: 13, fontWeight: "600" },
  grid: { flexDirection: "row", flexWrap: "wrap", marginTop: 16, gap: 12 },
  tile: {
    width: "47%", paddingVertical: 22, backgroundColor: "#0ea5a3",
    borderRadius: 12, alignItems: "center",
  },
  tileBlocked: { backgroundColor: "#94a3b8" },
  tileText: { color: "#fff", fontSize: 15, fontWeight: "600" },
});
