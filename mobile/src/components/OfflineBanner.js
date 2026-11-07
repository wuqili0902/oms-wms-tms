/**
 * Offline banner — the operator's only signal that scans are still on the
 * device rather than in the warehouse records.
 *
 * It exists because the offline queue makes "it failed" ambiguous. A count that
 * could not be sent is *stored*, and an alert saying 失败 invites a re-scan,
 * which double-books stock the moment the network returns. The banner is the
 * place that difference is visible, and the button that closes it out.
 */
import { useEffect, useState } from "react";
import { View, Text, TouchableOpacity, ActivityIndicator } from "react-native";
import {
  discardFailedOffline,
  getOfflineStats,
  retryOfflineFailed,
  retryOfflineNow,
  subscribeOffline,
} from "../api/client";

function ageLabel(iso) {
  if (!iso) return "";
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (minutes < 1) return "刚刚";
  if (minutes < 60) return `${minutes} 分钟前`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} 小时前`;
  return `${Math.round(hours / 24)} 天前`;
}

export default function OfflineBanner() {
  const [stats, setStats] = useState(getOfflineStats());
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState(null);

  useEffect(() => subscribeOffline(setStats), []);

  if (stats.pending === 0 && stats.failed === 0) return null;

  async function syncNow() {
    setBusy(true);
    setNote(null);
    try {
      const result = await retryOfflineNow();
      setNote(`已同步 ${result.synced} 项${result.failed ? `，${result.failed} 项被拒绝` : ""}`);
    } catch (err) {
      setNote(err?.offline ? "仍然离线，稍后自动重试" : (err?.message || "同步失败"));
    } finally {
      setBusy(false);
    }
  }

  async function retryFailed() {
    setBusy(true);
    setNote(null);
    try {
      const result = await retryOfflineFailed();
      setNote(`重新提交 ${result.synced} 项`);
    } catch (err) {
      setNote(err?.offline ? "仍然离线，稍后自动重试" : (err?.message || "重试失败"));
    } finally {
      setBusy(false);
    }
  }

  async function dropFailed() {
    setBusy(true);
    const dropped = await discardFailedOffline();
    setNote(`已丢弃 ${dropped} 项（这部分作业未提交到系统）`);
    setBusy(false);
  }

  return (
    <View style={styles.banner}>
      <View style={styles.textWrap}>
        <Text style={styles.title}>
          ⏳ {stats.pending} 项待同步
          {stats.failed > 0 ? ` · ${stats.failed} 项未提交` : ""}
          {stats.pending > 0 && stats.oldest ? ` · 最久 ${ageLabel(stats.oldest)}` : ""}
        </Text>
        {note ? <Text style={styles.note}>{note}</Text> : null}
      </View>

      <View style={styles.actions}>
        {stats.pending > 0 ? (
          <TouchableOpacity onPress={syncNow} disabled={busy} style={[styles.btn, busy && styles.btnBusy]}>
            {busy
              ? <ActivityIndicator size="small" color="#fff" />
              : <Text style={styles.btnText}>立即同步</Text>}
          </TouchableOpacity>
        ) : null}

        {stats.failed > 0 ? (
          <>
            <TouchableOpacity onPress={retryFailed} disabled={busy} style={[styles.btn, styles.btnSecondary]}>
              <Text style={styles.btnText}>重新提交</Text>
            </TouchableOpacity>
            <TouchableOpacity onPress={dropFailed} disabled={busy} style={[styles.link]}>
              <Text style={styles.linkText}>丢弃</Text>
            </TouchableOpacity>
          </>
        ) : null}
      </View>
    </View>
  );
}

const styles = {
  banner: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    backgroundColor: "#7c2d12", paddingVertical: 10, paddingHorizontal: 14,
  },
  textWrap: { flex: 1, marginRight: 12 },
  title: { color: "#fed7aa", fontSize: 13, fontWeight: "600" },
  note: { color: "#fdba74", fontSize: 12, marginTop: 2 },
  actions: { flexDirection: "row", alignItems: "center", gap: 8 },
  btn: { backgroundColor: "#ea580c", borderRadius: 6, paddingHorizontal: 12, paddingVertical: 6 },
  btnSecondary: { backgroundColor: "#9a3412" },
  btnBusy: { opacity: 0.6 },
  btnText: { color: "#fff", fontSize: 13, fontWeight: "600" },
  link: { paddingHorizontal: 4, paddingVertical: 6 },
  linkText: { color: "#fdba74", fontSize: 13, textDecorationLine: "underline" },
};
