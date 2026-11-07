/**
 * Shared error presentation for PDA mutations.
 *
 * `request()` queues a mutation it could not deliver and throws with
 * `queued: true`.  Presenting that as 失败 is the one wrong thing to say: the
 * operator would rescan, and the replay would book the movement twice.
 */
import { Alert } from "react-native";

export function alertMutationError(err, fallback = "操作失败") {
  if (err?.queued) {
    return Alert.alert("⏸ 已离线保存", err.message || "将在网络恢复后自动同步");
  }
  return Alert.alert("✗", err?.message || fallback);
}
