import { useEffect, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  AppState,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Switch,
  Text,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { router, useLocalSearchParams } from "expo-router";
import * as Linking from "expo-linking";
import * as WebBrowser from "expo-web-browser";

import {
  connectTool,
  disconnectSwiggy,
  disconnectTool,
  getSwiggyStatus,
  getTools,
  startSwiggyOAuth,
} from "../services/api";
import { useConversation } from "../context/ConversationContext";
import { useAppTheme } from "../context/ThemeContext";


function wait(milliseconds) {
  return new Promise((resolve) => {
    setTimeout(resolve, milliseconds);
  });
}


export default function ToolsScreen() {
  const { status } = useLocalSearchParams();
  const { agentName = "Cooper" } = useConversation();
  const { colors } = useAppTheme();
  const [tools, setTools] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [pendingToolId, setPendingToolId] = useState(null);
  const [errorMessage, setErrorMessage] = useState("");

  async function loadTools(showLoader = true) {
    if (showLoader) {
      setIsLoading(true);
    }

    setErrorMessage("");

    try {
      const [nextTools, swiggy] = await Promise.all([
        getTools(),
        getSwiggyStatus().catch(() => ({ connected: false })),
      ]);

      const swiggyTool = {
        id: "swiggy",
        name: "Swiggy Food",
        description: "Search restaurants, compare menus, and order food",
        icon: "fast-food-outline",
        color: "#F97316",
        connected: Boolean(swiggy && swiggy.connected),
        account: swiggy && swiggy.connected ? "Swiggy Connected" : null,
      };

      const combined = [swiggyTool, ...nextTools];
      setTools(combined);
      return combined;
    } catch (error) {
      setErrorMessage(error.message || "Could not load tools");
      return [];
    } finally {
      if (showLoader) {
        setIsLoading(false);
      }
    }
  }

  useEffect(() => {
    const initialLoad = setTimeout(() => loadTools(), 0);

    const subscription = AppState.addEventListener("change", (state) => {
      if (state === "active") {
        loadTools(false);
      }
    });

    return () => {
      clearTimeout(initialLoad);
      subscription.remove();
    };
  }, []);

  useEffect(() => {
    if (status === "success") {
      router.replace("/(tabs)/chat");
    }
  }, [status]);

  async function waitForConnection(toolId) {
    for (let attempt = 0; attempt < 10; attempt += 1) {
      const nextTools = await loadTools(false);

      const connectedTool = nextTools.find(
        (tool) => tool.id === toolId
      );

      if (connectedTool?.connected) {
        return connectedTool;
      }

      await wait(1500);
    }

    throw new Error(
      "Connection is still processing. Refresh this page in a moment."
    );
  }

  async function connect(tool) {
    if (tool.id === "swiggy") {
      const callbackUrl = Linking.createURL("/swiggy/callback");
      const auth = await startSwiggyOAuth(callbackUrl);
      if (Platform.OS === "web") {
        window.location.assign(auth.authorization_url);
        return;
      }
      const result = await WebBrowser.openAuthSessionAsync(
        auth.authorization_url,
        auth.callback_url
      );
      if (result.type === "success") {
        await loadTools(false);
        router.replace("/(tabs)/chat");
      }
      return;
    }

    const callbackUrl = Linking.createURL("/chat");
    const connection = await connectTool(tool.id, callbackUrl);

    if (Platform.OS === "web") {
      window.location.assign(connection.redirect_url);
      return;
    }

    const result = await WebBrowser.openAuthSessionAsync(
      connection.redirect_url,
      callbackUrl
    );

    if (result.type === "success") {
      await waitForConnection(tool.id);
      router.replace("/(tabs)/chat");
    }
  }

  async function disconnect(tool) {
    if (tool.id === "swiggy") {
      await disconnectSwiggy();
      setTools((currentTools) =>
        currentTools.map((t) =>
          t.id === "swiggy" ? { ...t, connected: false, account: null } : t
        )
      );
      return;
    }

    const updatedTool = await disconnectTool(tool.id);
    setTools((currentTools) =>
      currentTools.map((currentTool) =>
        currentTool.id === updatedTool.id ? updatedTool : currentTool
      )
    );
  }

  function handleBack() {
    if (router.canGoBack()) {
      router.back();
      return;
    }

    router.replace("/(tabs)/settings");
  }

  function confirmDisconnect(tool) {
    if (Platform.OS === "web") {
      return Promise.resolve(
        window.confirm(`Disconnect ${tool.name}?`)
      );
    }

    return new Promise((resolve) => {
      Alert.alert(
        `Disconnect ${tool.name}?`,
        `${agentName} will no longer be able to use this account.`,
        [
          {
            text: "Cancel",
            style: "cancel",
            onPress: () => resolve(false),
          },
          {
            text: "Disconnect",
            style: "destructive",
            onPress: () => resolve(true),
          },
        ]
      );
    });
  }

  async function toggleTool(tool) {
    if (pendingToolId) {
      return;
    }

    setPendingToolId(tool.id);
    setErrorMessage("");

    try {
      if (tool.connected) {
        const confirmed = await confirmDisconnect(tool);

        if (!confirmed) {
          return;
        }

        await disconnect(tool);
      } else {
        await connect(tool);
      }
    } catch (error) {
      setErrorMessage(
        error.message || "Could not update tool"
      );
    } finally {
      setPendingToolId(null);
    }
  }

  return (
    <SafeAreaView style={[styles.safeArea, { backgroundColor: colors.background }]}>
      <View style={[styles.header, { borderBottomColor: colors.divider }]}>
        <Pressable
          style={[styles.backButton, { backgroundColor: colors.surfaceTertiary }]}
          onPress={handleBack}
        >
          <Ionicons
            name="arrow-back"
            size={22}
            color={colors.text}
          />
        </Pressable>

        <Text style={[styles.headerTitle, { color: colors.text }]}>
          Tools & Connections
        </Text>

        <View style={styles.headerSpace} />
      </View>

      <ScrollView
        style={[styles.container, { backgroundColor: colors.background }]}
        contentContainerStyle={styles.content}
        showsVerticalScrollIndicator={false}
      >
        <Text style={[styles.title, { color: colors.text }]}>
          Connect your tools
        </Text>

        <Text style={[styles.subtitle, { color: colors.textSecondary }]}>
          {agentName} can use connected tools to complete tasks for you.
        </Text>

        {isLoading && (
          <ActivityIndicator
            style={styles.loader}
            size="large"
            color={colors.primary}
          />
        )}

        {Boolean(errorMessage) && (
          <Text style={[styles.errorText, { color: colors.danger }]}>
            {errorMessage}
          </Text>
        )}

        {tools.map((tool) => (
          <View
            key={tool.id}
            style={[
              styles.toolCard,
              { backgroundColor: colors.surface, borderColor: colors.border },
            ]}
          >
            <View
              style={[
                styles.toolIcon,
                {
                  backgroundColor: `${tool.color}18`,
                },
              ]}
            >
              <Ionicons
                name={tool.icon}
                size={23}
                color={tool.color}
              />
            </View>

            <View style={styles.toolContent}>
              <Text style={[styles.toolName, { color: colors.text }]}>
                {tool.name}
              </Text>

              <Text style={[styles.toolDescription, { color: colors.textSecondary }]}>
                {tool.description}
              </Text>

              {tool.connected && (
                <Text style={[styles.account, { color: colors.primary }]}>
                  {tool.account || "Connected"}
                </Text>
              )}
            </View>

            {pendingToolId === tool.id ? (
              <ActivityIndicator
                size="small"
                color={colors.primary}
              />
            ) : (
              <Switch
                value={tool.connected}
                onValueChange={() => toggleTool(tool)}
                trackColor={{
                  false: colors.border,
                  true: "#93C5FD",
                }}
                thumbColor={
                  tool.connected
                    ? colors.primary
                    : colors.surfaceSecondary
                }
              />
            )}
          </View>
        ))}
      </ScrollView>
    </SafeAreaView>
  );
}


const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: "#FFFFFF",
  },

  header: {
    height: 58,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: 18,
    borderBottomWidth: 1,
    borderBottomColor: "#F1F5F9",
  },

  backButton: {
    width: 40,
    height: 40,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 20,
    backgroundColor: "#F1F5F9",
  },

  headerTitle: {
    color: "#1E2022",
    fontSize: 16,
    fontWeight: "700",
  },

  headerSpace: {
    width: 40,
  },

  container: {
    flex: 1,
    backgroundColor: "#FFFFFF",
  },

  content: {
    paddingHorizontal: 20,
    paddingTop: 22,
    paddingBottom: 30,
  },

  title: {
    color: "#1E2022",
    fontSize: 26,
    fontWeight: "700",
  },

  subtitle: {
    marginTop: 6,
    marginBottom: 22,
    color: "#64748B",
    fontSize: 14,
    lineHeight: 20,
  },

  loader: {
    marginTop: 24,
  },

  errorText: {
    marginBottom: 14,
    color: "#DC2626",
    fontSize: 13,
  },

  toolCard: {
    minHeight: 84,
    flexDirection: "row",
    alignItems: "center",
    padding: 14,
    marginBottom: 10,
    borderWidth: 1,
    borderColor: "#E2E8F0",
    borderRadius: 16,
    backgroundColor: "#FFFFFF",
  },

  toolIcon: {
    width: 46,
    height: 46,
    marginRight: 13,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 13,
  },

  toolContent: {
    flex: 1,
  },

  toolName: {
    color: "#1E2022",
    fontSize: 15,
    fontWeight: "700",
  },

  toolDescription: {
    marginTop: 3,
    color: "#64748B",
    fontSize: 12.5,
  },

  account: {
    marginTop: 5,
    color: "#2563EB",
    fontSize: 11.5,
    fontWeight: "600",
  },
});
