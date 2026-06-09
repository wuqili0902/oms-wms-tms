import React, { useState, useEffect, useRef } from "react";
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  Alert,
  ActivityIndicator,
} from "react-native";
import { CameraView, useCameraPermissions } from "expo-camera";
import { api } from "../api/client";

export default function ScannerScreen({ navigation }) {
  const [permission, requestPermission] = useCameraPermissions();
  const [scanning, setScanning] = useState(true);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const scannedRef = useRef(false);

  useEffect(() => {
    if (!permission?.granted) {
      requestPermission();
    }
  }, [permission]);

  const handleBarCodeScanned = async ({ data }) => {
    if (scannedRef.current) return;
    scannedRef.current = true;
    setScanning(false);

    setLoading(true);
    try {
      const scanResult = await api.recordScan({ gtin: data, scanned_by: "mobile" });
      setResult({ gtin: data, scan: scanResult });
    } catch (err) {
      // GTIN not found — still show the scanned code
      setResult({ gtin: data, scan: null, error: err.message });
    } finally {
      setLoading(false);
    }
  };

  const resetScanner = () => {
    scannedRef.current = false;
    setResult(null);
    setScanning(true);
  };

  if (!permission?.granted) {
    return (
      <View style={styles.center}>
        <Text style={{ color: "#64748b", marginBottom: 12 }}>
          Camera permission required for barcode scanning.
        </Text>
        <TouchableOpacity style={styles.button} onPress={requestPermission}>
          <Text style={styles.buttonText}>Grant Permission</Text>
        </TouchableOpacity>
      </View>
    );
  }

  return (
    <View style={styles.container}>
      {scanning ? (
        <CameraView
          style={StyleSheet.absoluteFillObject}
          facing="back"
          barcodeScannerSettings={{ barcodeTypes: ["ean13", "ean8", "code128", "qr"] }}
          onBarcodeScanned={handleBarCodeScanned}
        >
          <View style={styles.overlay}>
            <View style={styles.viewport} />
            <Text style={styles.hint}>Point camera at a barcode</Text>
          </View>
        </CameraView>
      ) : (
        <View style={styles.resultContainer}>
          {loading ? (
            <ActivityIndicator size="large" color="#3b82f6" />
          ) : (
            <>
              <Text style={styles.resultLabel}>Scanned Code</Text>
              <Text style={styles.resultGtin}>{result?.gtin}</Text>
              {result?.scan ? (
                <Text style={styles.resultSuccess}>Scan recorded</Text>
              ) : (
                <Text style={styles.resultWarn}>
                  {result?.error || "Unknown code"}
                </Text>
              )}
              <TouchableOpacity style={styles.button} onPress={resetScanner}>
                <Text style={styles.buttonText}>Scan Again</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[styles.button, styles.buttonSecondary]}
                onPress={() => navigation.goBack()}
              >
                <Text style={[styles.buttonText, { color: "#3b82f6" }]}>
                  Back to Orders
                </Text>
              </TouchableOpacity>
            </>
          )}
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#000" },
  center: { flex: 1, justifyContent: "center", alignItems: "center", padding: 24 },
  overlay: { flex: 1, justifyContent: "center", alignItems: "center" },
  viewport: {
    width: 250,
    height: 250,
    borderWidth: 2,
    borderColor: "#3b82f6",
    borderRadius: 12,
    backgroundColor: "transparent",
  },
  hint: {
    color: "#fff",
    fontSize: 14,
    marginTop: 20,
    opacity: 0.7,
  },
  resultContainer: {
    flex: 1,
    justifyContent: "center",
    alignItems: "center",
    padding: 24,
    backgroundColor: "#f5f7fa",
  },
  resultLabel: { fontSize: 14, color: "#64748b", marginBottom: 4 },
  resultGtin: { fontSize: 28, fontWeight: "700", color: "#1e293b", marginBottom: 12 },
  resultSuccess: { fontSize: 16, color: "#166534", marginBottom: 24 },
  resultWarn: { fontSize: 16, color: "#92400e", marginBottom: 24 },
  button: {
    backgroundColor: "#3b82f6",
    borderRadius: 8,
    paddingVertical: 12,
    paddingHorizontal: 32,
    marginBottom: 12,
    width: "100%",
    maxWidth: 280,
    alignItems: "center",
  },
  buttonSecondary: {
    backgroundColor: "#fff",
    borderWidth: 1,
    borderColor: "#3b82f6",
  },
  buttonText: { color: "#fff", fontSize: 16, fontWeight: "600" },
});
