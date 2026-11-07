import { useEffect, useState } from "react";
import { View } from "react-native";
import { StatusBar } from "expo-status-bar";
import AppNavigator from "./src/navigation/AppNavigator";
import OfflineBanner from "./src/components/OfflineBanner";
import { getDeviceId, pdaSocket, startOfflineAutoSync } from "./src/api/client";

export default function App() {
  const [isLoggedIn, setIsLoggedIn] = useState(false);

  // The queue only drains when something asks it to.  Login first, because the
  // probe that guards a flush needs a token: flushing without one gets 401, and
  // the queue counts 401 as a permanent rejection.
  //
  // The socket belongs in the same effect.  It is not decoration: a live
  // socket is the cheapest proof that the device is reachable again, and
  // PdaSocketManager.onopen uses it to pump the queue — so a PDA sitting in
  // WiFi range with a loaded queue would otherwise wait out the slow heartbeat
  // tick before its scans went up.
  useEffect(() => {
    if (!isLoggedIn) return undefined;

    let cancelled = false;
    (async () => {
      const deviceId = await getDeviceId();
      if (!cancelled) pdaSocket.connect(deviceId);
    })();

    const stopAutoSync = startOfflineAutoSync();
    return () => {
      cancelled = true;
      stopAutoSync();
      pdaSocket.disconnect();
    };
  }, [isLoggedIn]);

  return (
    <View style={{ flex: 1 }}>
      <StatusBar style="light" />
      {isLoggedIn ? <OfflineBanner /> : null}
      <AppNavigator
        isLoggedIn={isLoggedIn}
        onLogin={() => setIsLoggedIn(true)}
      />
    </View>
  );
}
