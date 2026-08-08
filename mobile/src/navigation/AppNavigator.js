import React from "react";
import { NavigationContainer } from "@react-navigation/native";
import { createNativeStackNavigator } from "@react-navigation/native-stack";

import LoginScreen from "../screens/LoginScreen";
import OrderListScreen from "../screens/OrderListScreen";
import OrderDetailScreen from "../screens/OrderDetailScreen";
import ScannerScreen from "../screens/ScannerScreen";
import PickingScreen from "../screens/PickingScreen";
import InventoryScreen from "../screens/InventoryScreen";

// New screens for PDA operations
import StockInScreen from "../screens/StockInScreen";
import StockCountScreen from "../screens/StockCountScreen";
import PackingRecordScreen from "../screens/PackingRecordScreen";
import ReceiveGoodsScreen from "../screens/ReceiveGoodsScreen";
import TransferOrderScreen from "../screens/TransferOrderScreen";

const Stack = createNativeStackNavigator();

export default function AppNavigator({ isLoggedIn, onLogin }) {
  return (
    <NavigationContainer>
      <Stack.Navigator
        screenOptions={{
          headerStyle: { backgroundColor: "#1e293b" },
          headerTintColor: "#f1f5f9",
          headerTitleStyle: { fontWeight: "600" },
        }}
      >
        {!isLoggedIn ? (
          <Stack.Screen name="Login" options={{ title: "Sign In" }}>
            {(props) => <LoginScreen {...props} onLogin={onLogin} />}
          </Stack.Screen>
        ) : (
          <>
            {/* Orders */}
            <Stack.Screen name="Orders" component={OrderListScreen} options={{ title: "Orders" }} />
            <Stack.Screen name="OrderDetail" component={OrderDetailScreen} options={{ title: "Order Detail" }} />

            {/* Barcode Scanner (shared across all screens) */}
            <Stack.Screen name="Scanner" component={ScannerScreen} options={{ title: "Scan Barcode" }} />

            {/* Picking Operations */}
            <Stack.Screen name="Picking" component={PickingScreen} options={{ title: "Picking Waves" }} />
            <Stack.Screen name="StockCount" component={StockCountScreen} options={{ title: "Inventory Count" }} />
            <Stack.Screen name="TransferOrder" component={TransferOrderScreen} options={{ title: "Transfer Order" }} />

            {/* Stock Management */}
            <Stack.Screen name="StockIn" component={StockInScreen} options={{ title: "Stock In" }} />
            <Stack.Screen name="Inventory" component={InventoryScreen} options={{ title: "Inventory" }} />

            {/* Packing & Shipping */}
            <Stack.Screen name="PackingRecord" component={PackingRecordScreen} options={{ title: "Packing Record" }} />

            {/* Procurement (Receive Goods) */}
            <Stack.Screen name="ReceiveGoods" component={ReceiveGoodsScreen} options={{ title: "Receive Goods" }} />

            {/* Warehouse List (for selection) */}
            <Stack.Screen name="WarehouseList" component={InventoryScreen} options={{ title: "Select Warehouse" }} />
          </>
        )}
      </Stack.Navigator>
    </NavigationContainer>
  );
}
