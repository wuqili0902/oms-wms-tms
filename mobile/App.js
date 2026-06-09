import React, { useState } from "react";
import { StatusBar } from "expo-status-bar";
import AppNavigator from "./src/navigation/AppNavigator";

export default function App() {
  const [isLoggedIn, setIsLoggedIn] = useState(false);

  return (
    <>
      <StatusBar style="light" />
      <AppNavigator
        isLoggedIn={isLoggedIn}
        onLogin={() => setIsLoggedIn(true)}
      />
    </>
  );
}
