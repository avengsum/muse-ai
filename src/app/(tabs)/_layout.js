import { useState } from "react";
import { Alert, PanResponder, Platform, StyleSheet, View } from "react-native";
import { Tabs, router } from "expo-router";
import { Ionicons } from "@expo/vector-icons";

import AppHeader from "../../components/AppHeader";
import SidebarDrawer from "../../components/SidebarDrawer";
import MoreMenuModal from "../../components/MoreMenuModal";
import AgentEditorModal from "../../components/AgentEditorModal";
import { useConversation } from "../../context/ConversationContext";
import { useAppTheme } from "../../context/ThemeContext";
import { deleteConversation } from "../../services/api";
import {
  SafeAreaView,
  useSafeAreaInsets,
} from "react-native-safe-area-context";

const tabs = {
  chat: {
    icon: "chatbubble-outline",
    activeIcon: "chatbubble",
  },
  feed: {
    icon: "newspaper-outline",
    activeIcon: "newspaper",
  },
  ideas: {
    icon: "bulb-outline",
    activeIcon: "bulb",
  },
  tasks: {
    icon: "checkbox-outline",
    activeIcon: "checkbox",
  },
  settings: {
    icon: "settings-outline",
    activeIcon: "settings",
  },
};

const DRAWER_EDGE_WIDTH = 28;
const DRAWER_OPEN_DISTANCE = 56;
const DRAWER_FLING_DISTANCE = 20;
const DRAWER_FLING_VELOCITY = 0.45;

function isDrawerOpeningGesture(gesture) {
  const isHorizontal = Math.abs(gesture.dx) > Math.abs(gesture.dy) * 1.25;

  return (
    Platform.OS !== "web" &&
    gesture.x0 <= DRAWER_EDGE_WIDTH &&
    gesture.dx > 10 &&
    isHorizontal
  );
}

export default function TabsLayout() {
  return <TabsContent />;
}

function TabsContent() {
  const insets = useSafeAreaInsets();
  const { colors } = useAppTheme();
  const [sidebarVisible, setSidebarVisible] = useState(false);
  const [menuVisible, setMenuVisible] = useState(false);
  const [editorVisible, setEditorVisible] = useState(false);
  const [openDrawerPanResponder] = useState(() =>
    PanResponder.create({
      onMoveShouldSetPanResponder: (_event, gesture) =>
        isDrawerOpeningGesture(gesture),
      onMoveShouldSetPanResponderCapture: (_event, gesture) =>
        isDrawerOpeningGesture(gesture),
      onPanResponderRelease: (_event, gesture) => {
        const crossedDistance = gesture.dx >= DRAWER_OPEN_DISTANCE;
        const wasFlungOpen =
          gesture.dx >= DRAWER_FLING_DISTANCE &&
          gesture.vx >= DRAWER_FLING_VELOCITY;

        if (crossedDistance || wasFlungOpen) {
          setSidebarVisible(true);
        }
      },
    }),
  );
  const {
    conversationId,
    setConversationId,
    refreshConversations,
    agentName,
    accentColor,
    updateSettings,
  } = useConversation();

  function openSidebar() {
    setSidebarVisible(true);
  }

  function openMoreMenu() {
    setMenuVisible(true);
  }

  function openSettings() {
    setSidebarVisible(false);
    router.replace("/(tabs)/settings");
  }

  async function saveAgent(newName, newColor) {
    try {
      await updateSettings({
        agent_name: newName,
        accent_color: newColor,
      });
      setEditorVisible(false);
    } catch (error) {
      Alert.alert("Could not save agent", error.message);
    }
  }

  function confirmAction(title, message, action) {
    if (Platform.OS === "web") {
      if (window.confirm(String(title) + "\n\n" + String(message))) {
        action();
      }
      return;
    }

    Alert.alert(title, message, [
      { text: "Cancel", style: "cancel" },
      { text: "Continue", style: "destructive", onPress: action },
    ]);
  }

  function removeChat() {
    if (!conversationId) {
      return;
    }

    confirmAction(
      "Delete chat?",
      "This removes the chat and its messages.",
      async () => {
        try {
          await deleteConversation(conversationId);
          setConversationId(null);
          refreshConversations();
          router.replace("/(tabs)/chat");
        } catch (error) {
          Alert.alert("Could not delete chat", error.message);
        }
      },
    );
  }

  return (
    <SafeAreaView
      style={[styles.safeArea, { backgroundColor: colors.background }]}
      edges={["top", "left", "right"]}
      {...openDrawerPanResponder.panHandlers}
    >
      <AppHeader
        agentName={agentName}
        accentColor={accentColor}
        onMenuPress={openSidebar}
        onMorePress={openMoreMenu}
      />

      <View
        style={[styles.screenContainer, { backgroundColor: colors.background }]}
      >
        <Tabs
          screenOptions={({ route }) => {
            const currentTab = tabs[route.name] ? tabs[route.name] : tabs.chat;

            return {
              headerShown: false,
              tabBarShowLabel: false,
              tabBarHideOnKeyboard: true,
              tabBarStyle: [
                styles.tabBar,
                {
                  backgroundColor: colors.surface,
                  borderTopColor: colors.border,
                },
                Platform.OS === "android" && {
                  height: 60 + insets.bottom,
                  paddingBottom: 10 + insets.bottom,
                },
              ],

              tabBarIcon: ({ focused }) => (
                <View
                  style={[
                    styles.iconPill,
                    focused && styles.activePill,
                    focused && { backgroundColor: colors.surfaceTertiary },
                  ]}
                >
                  <Ionicons
                    name={focused ? currentTab.activeIcon : currentTab.icon}
                    size={22}
                    color={focused ? colors.text : colors.textSecondary}
                  />
                </View>
              ),
            };
          }}
        >
          <Tabs.Screen
            name="index"
            options={{
              href: null,
            }}
          />

          <Tabs.Screen name="chat" />
          <Tabs.Screen name="feed" />
          <Tabs.Screen name="ideas" />
          <Tabs.Screen name="tasks" />
          <Tabs.Screen name="settings" />
        </Tabs>
      </View>

      <SidebarDrawer
        visible={sidebarVisible}
        onClose={() => setSidebarVisible(false)}
        onSettingsPress={openSettings}
      />

      <MoreMenuModal
        visible={menuVisible}
        onClose={() => setMenuVisible(false)}
        onEditAgent={() => setEditorVisible(true)}
        onDelete={removeChat}
      />

      <AgentEditorModal
        key={String(agentName) + "-" + String(accentColor)}
        visible={editorVisible}
        initialName={agentName}
        initialColor={accentColor}
        onClose={() => setEditorVisible(false)}
        onSave={saveAgent}
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: "#FFFFFF",
  },
  screenContainer: {
    flex: 1,
    backgroundColor: "#FFFFFF",
  },
  tabBar: {
    height: Platform.OS === "ios" ? 84 : 60,
    paddingTop: 8,
    paddingBottom: Platform.OS === "ios" ? 22 : 10,
    backgroundColor: "#FFFFFF",
    borderTopColor: "#F0F0F2",
    elevation: 0,
  },
  iconPill: {
    width: 58,
    height: 42,
    borderRadius: 21,
    justifyContent: "center",
    alignItems: "center",
  },
  activePill: {
    backgroundColor: "#E6E8EA",
  },
});
