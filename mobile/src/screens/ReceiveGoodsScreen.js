/**
 * Receive Goods Screen — 采购单收货。
 *
 * Flow: pick a purchase order awaiting receipt → confirm the quantity that
 * landed on each line → say which shelf it went to → submit.
 *
 * The receipt is what puts the goods into inventory.  The endpoint used to
 * accept no body at all and only set the order's status, so a delivery of 3
 * against an order of 100 was recorded exactly like a complete delivery, and
 * the 3 units in the building were invisible to every later pick.  The screen
 * now sends the landed quantities and the destination, which is what the
 * booking needs.
 */
import { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator, Alert, ScrollView, Text, TextInput, TouchableOpacity, View,
} from "react-native";
import { api } from "../api/client";
import { alertMutationError } from "../api/errors";
import { locationOptions, resolveLocationRef } from "../api/locations";
import { fetchWithCache } from "../api/cache";

const num = (value) => Number(value ?? 0) || 0;

export default function ReceiveGoodsScreen({ route }) {
  const warehouseId = (route?.params?.warehouse_id ?? "").trim();

  // Every hook runs before the "no warehouse chosen" bail-out below: returning
  // early from some renders and not others is what breaks hook order.
  const [purchaseOrders, setPurchaseOrders] = useState([]);
  const [poId, setPoId] = useState("");
  const [poLines, setPoLines] = useState([]);
  const [locationInput, setLocationInput] = useState("");
  const [locationChoices, setLocationChoices] = useState([]);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);

  const selectedPo = purchaseOrders.find((po) => String(po.id) === poId);

  const loadPOs = useCallback(async () => {
    if (!warehouseId) {
      setLoading(false);
      return;
    }
    try {
      // "pending" is what the PDA has always asked for; the API now reads it as
      // approved + partial, i.e. the orders a delivery can legally arrive against.
      const res = await fetchWithCache(
        `po:awaiting:${warehouseId}`,
        () => api.listPurchaseOrders("pending"),
        30 * 1000
      );
      const items = res?.items ?? (Array.isArray(res) ? res : []);
      setPurchaseOrders(items);
      if (items.length === 0) {
        setPoId("");
        setPoLines([]);
      } else if (!items.some((po) => String(po.id) === poId)) {
        selectPo(items[0]);
      }
    } catch (err) {
      Alert.alert("提示", err?.message || "采购单加载失败");
    } finally {
      setLoading(false);
    }
  }, [warehouseId, poId]);

  useEffect(() => {
    if (!warehouseId) {
      setLoading(false);
      return undefined;
    }
    loadPOs();
    locationOptions(warehouseId).then(setLocationChoices);
    return undefined;
  }, [loadPOs, warehouseId]);

  function selectPo(po) {
    setPoId(String(po.id));
    // Prefilled with what is still outstanding: a normal full delivery should
    // need no typing, and a short one needs only the difference.
    setPoLines((po.lines ?? []).map((line) => ({
      line_id: String(line.id),
      sku: line.sku ?? "",
      description: line.description ?? "",
      expected_qty: num(line.quantity),
      already_received: num(line.received_qty),
      received_qty: String(Math.max(num(line.quantity) - num(line.received_qty), 0)),
    })));
  }

  function updateReceived(lineId, text) {
    setPoLines((prev) => prev.map((line) =>
      line.line_id === lineId ? { ...line, received_qty: text } : line
    ));
  }

  async function submitReceive() {
    if (!selectedPo) return Alert.alert("提示", "请先选择采购单");
    if (poLines.length === 0) return Alert.alert("提示", "该采购单没有明细，无法收货");

    const lines = [];
    for (const line of poLines) {
      const qty = Number(line.received_qty);
      if (!Number.isFinite(qty) || qty < 0) {
        return Alert.alert("提示", `${line.sku || line.description || "行"} 的实收数量无效`);
      }
      if (qty > 0) {
        // line_id as well as sku: an order can carry the same SKU twice, and a
        // receipt that only names the SKU cannot say which line landed.
        lines.push({ line_id: line.line_id, sku: line.sku || undefined, received_qty: qty });
      }
    }
    if (lines.length === 0) return Alert.alert("提示", "请确认收货数量（收到 0 件不是收货）");

    setSubmitting(true);
    try {
      const resolved = await resolveLocationRef(warehouseId, locationInput);
      if (!resolved.ok) return Alert.alert("提示", resolved.error);

      const result = await api.receiveGoods(selectedPo.id, {
        warehouse_id: warehouseId,
        location_id: resolved.id,
        lines,
      });

      const total = lines.reduce((sum, line) => sum + line.received_qty, 0);
      const short = result?.status === "partial";
      Alert.alert(
        short ? "⚠ 部分收货" : "✓",
        `共收 ${total} 件 → ${resolved.label}${short ? "，仍有未收数量" : ""}`
      );
      await loadPOs();
      setLocationInput("");
    } catch (err) {
      alertMutationError(err, "收货失败");
    } finally {
      setSubmitting(false);
    }
  }

  if (!warehouseId) {
    return (
      <View style={styles.empty}>
        <Text>请先选择仓库</Text>
      </View>
    );
  }

  if (loading) {
    return (
      <View style={styles.empty}>
        <ActivityIndicator size="large" color="#0ea5a3" />
      </View>
    );
  }

  return (
    <ScrollView style={styles.container} contentContainerStyle={{ paddingBottom: 60 }}>
      <Text style={styles.title}>📥 采购收货</Text>

      {purchaseOrders.length === 0 ? (
        <View><Text style={styles.muted}>暂无待收货采购单</Text></View>
      ) : (
        <View style={styles.poRow}>
          {purchaseOrders.map((po) => (
            <TouchableOpacity
              key={String(po.id)}
              onPress={() => selectPo(po)}
              style={[styles.poChip, String(po.id) === poId ? styles.poChipActive : null]}
            >
              <Text style={[styles.poChipText, String(po.id) === poId ? styles.poChipTextActive : null]}>
                {po.po_number} · {po.status}
              </Text>
            </TouchableOpacity>
          ))}
        </View>
      )}

      {poLines.map((line) => {
        const received = Number(line.received_qty) || 0;
        const outstanding = Math.max(line.expected_qty - line.already_received, 0);
        const diff = received - outstanding;
        return (
          <View key={line.line_id} style={styles.itemCard}>
            <Text style={styles.sku}>{line.sku || "（无 SKU）"}</Text>
            <Text style={styles.name}>{line.description || "—"}</Text>
            <View style={styles.qtyRow}>
              <View>
                <Text style={styles.label}>应收</Text>
                <Text>{line.expected_qty}</Text>
                {line.already_received > 0 ? <Text style={styles.label}>已收 {line.already_received}</Text> : null}
              </View>
              <View>
                <Text style={styles.label}>实收</Text>
                {/* The total submitted is read from these inputs: an unbound box
                    confirms the receipt at zero. */}
                <TextInput
                  value={String(line.received_qty)}
                  keyboardType="numeric"
                  onChangeText={(text) => updateReceived(line.line_id, text)}
                  style={styles.input}
                />
              </View>
              {diff > 0 ? <Text style={styles.over}>超收 {diff}</Text> : null}
              {diff < 0 ? <Text style={styles.short}>少 {Math.abs(diff)}</Text> : null}
            </View>
          </View>
        );
      })}

      <View style={styles.fieldRow}>
        <Text style={styles.labelWide}>放入库位 *</Text>
        <TextInput
          value={locationInput}
          onChangeText={setLocationInput}
          placeholder="如 A-01-02 或库位 ID"
          style={styles.inputWide}
        />
      </View>

      {locationChoices.length > 0 ? (
        <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.locRow}>
          {locationChoices.map((loc) => (
            <TouchableOpacity key={loc.id} onPress={() => setLocationInput(loc.location_code)} style={styles.locChip}>
              <Text style={styles.locChipText}>{loc.location_code}</Text>
            </TouchableOpacity>
          ))}
        </ScrollView>
      ) : null}

      <TouchableOpacity
        onPress={submitReceive}
        disabled={submitting || poLines.length === 0}
        style={[styles.btnPrimary, (submitting || poLines.length === 0) && styles.btnDisabled]}
      >
        <ActivityIndicator size="small" color="#fff" animating={submitting} />
        <Text style={styles.btnText}>{submitting ? "确认中..." : "确认收货"}</Text>
      </TouchableOpacity>

      <View style={{ height: 40 }} />
    </ScrollView>
  );
}

const styles = {
  container: { flex: 1, padding: 16, backgroundColor: "#f5f7fa" },
  title: { fontSize: 24, fontWeight: "600", marginBottom: 8, color: "#333" },
  empty: { flex: 1, justifyContent: "center", alignItems: "center", padding: 40 },
  muted: { color: "#666", padding: 20 },
  poRow: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginBottom: 12 },
  poChip: { paddingHorizontal: 12, paddingVertical: 8, backgroundColor: "#e2e8f0", borderRadius: 8 },
  poChipActive: { backgroundColor: "#0ea5a3" },
  poChipText: { fontSize: 13, color: "#334155" },
  poChipTextActive: { color: "#fff", fontWeight: "600" },
  itemCard: {
    borderLeftWidth: 4, borderLeftColor: "#0ea5a3", padding: 12, marginBottom: 8,
    backgroundColor: "#fff", borderRadius: 8,
  },
  sku: { fontWeight: "600", color: "#1e293b" },
  name: { color: "#555", fontSize: 12 },
  label: { marginRight: 4, color: "#64748b", fontSize: 12 },
  labelWide: { width: 78, fontWeight: "600" },
  qtyRow: { flexDirection: "row", gap: 16, marginTop: 4, alignItems: "center" },
  input: { borderWidth: 1, borderColor: "#ccc", borderRadius: 4, padding: 8, width: 80, textAlign: "center" },
  inputWide: { flex: 1, borderWidth: 1, borderColor: "#ccc", borderRadius: 8, padding: 12, fontSize: 16 },
  fieldRow: { flexDirection: "row", alignItems: "center", marginTop: 12, gap: 8 },
  locRow: { marginTop: 8 },
  locChip: { paddingHorizontal: 10, paddingVertical: 6, backgroundColor: "#e2e8f0", borderRadius: 6, marginRight: 6 },
  locChipText: { fontSize: 12, color: "#334155" },
  over: { color: "#22c55e", fontWeight: "600" },
  short: { color: "#f97316", fontWeight: "600" },
  btnPrimary: {
    flexDirection: "row", alignItems: "center", justifyContent: "center",
    backgroundColor: "#0ea5a3", borderRadius: 8, padding: 14, marginTop: 20,
  },
  btnText: { color: "#fff", fontWeight: "600" },
  btnDisabled: { opacity: 0.5 },
};
