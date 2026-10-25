import { StatusBar } from "expo-status-bar";
import Constants from "expo-constants";
import { ActivityIndicator, Platform, StyleSheet, View } from "react-native";
import { GestureHandlerRootView } from "react-native-gesture-handler";
import { KeyboardProvider } from "react-native-keyboard-controller";

import { AuthProvider, useAuth } from "../context/AuthContext";
import { ConversationProvider } from "../context/ConversationContext";
import { ThemeProvider, useAppTheme } from "../context/ThemeContext";
import { registerPushToken } from "../services/api";
import { Stack } from "expo-router";

const isAndroidExpoGo =
  Platform.OS === "android" && Constants.appOwnership === "expo";


function getNotificationsModule() {
  if (Platform.OS === "web" || isAndroidExpoGo) {
    return null;
  }
  try {
    return require("expo-notifications");
  } catch {
    return null;
  }
}

const Notifications = getNotificationsModule();

if (Notifications && typeof Notifications.setNotificationHandler === "function") {
  try {
    Notifications.setNotificationHandler({
      handleNotification: async () => ({
        shouldShowAlert: true,
        shouldPlaySound: true,
        shouldSetBadge: false,
      }),
    });
  } catch {
    // Ignore in unsupported environments
  }
}

function RootNavigator() {
  const { session, isLoading } = useAuth();
  const { colors, isDark, isThemeReady } = useAppTheme();

  if (isLoading || !isThemeReady) {
    return (
      <View
        style={[styles.loadingContainer, { backgroundColor: colors.background }]}
      >
        <ActivityIndicator size="large" color={colors.primary} />
      </View>
    );
  }

  return (
    <>
      <StatusBar style={isDark ? "light" : "dark"} />
      <Stack
        screenOptions={{
          headerShown: false,
          contentStyle: { backgroundColor: colors.background },
        }}
      >
        <Stack.Protected guard={!session}>
          <Stack.Screen name="index" />
        </Stack.Protected>

        <Stack.Protected guard={Boolean(session)}>
          <Stack.Screen name="(tabs)" />
          <Stack.Screen name="tools" />
        </Stack.Protected>
      </Stack>
    </>
  );
}

export default function RootLayout() {
  return (
    <GestureHandlerRootView style={styles.appRoot}>
      <KeyboardProvider>
        <ThemeProvider>
          <AuthProvider>
            <ConversationProvider>
              <RootNavigator />
            </ConversationProvider>
          </AuthProvider>
        </ThemeProvider>
      </KeyboardProvider>
    </GestureHandlerRootView>
  );
}

const styles = StyleSheet.create({
  appRoot: {
    flex: 1,
  },

  loadingContainer: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "#FFFFFF",
  },
});
