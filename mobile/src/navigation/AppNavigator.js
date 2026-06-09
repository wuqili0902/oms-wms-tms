import React from "react";
import { NavigationContainer } from "@react-navigation/native";
import { createNativeStackNavigator } from "@react-navigation/native-stack";

import LoginScreen from "../screens/LoginScreen";
import OrderListScreen from "../screens/OrderListScreen";
import OrderDetailScreen from "../screens/OrderDetailScreen";
import ScannerScreen from "../screens/ScannerScreen";

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
            <Stack.Screen
              name="Orders"
              component={OrderListScreen}
              options={{ title: "Orders" }}
            />
            <Stack.Screen
              name="OrderDetail"
              component={OrderDetailScreen}
              options={{ title: "Order" }}
            />
            <Stack.Screen
              name="Scanner"
              component={ScannerScreen}
              options={{ title: "Scan Barcode" }}
            />
          </>
        )}
      </Stack.Navigator>
    </NavigationContainer>
  );
}
