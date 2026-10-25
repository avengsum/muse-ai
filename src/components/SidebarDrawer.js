import { useEffect, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Modal,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import {
  Gesture,
  GestureDetector,
  GestureHandlerRootView,
} from "react-native-gesture-handler";
import Animated, {
  cancelAnimation,
  Easing,
  runOnJS,
  useAnimatedStyle,
  useSharedValue,
  withSpring,
  withTiming,
} from "react-native-reanimated";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { router } from "expo-router";
import {
  deleteConversation,
  getConversations,
  renameConversation,
} from "../services/api";
import { useConversation } from "../context/ConversationContext";
import { useAppTheme } from "../context/ThemeContext";

const DRAWER_OFFSCREEN_DISTANCE = 360;
const DRAWER_CLOSE_DISTANCE = 36;
const DRAWER_FLING_VELOCITY = -250;
const DRAWER_PROJECTION_TIME = 0.12;

export default function SidebarDrawer({
  visible,
  onClose,
  onSettingsPress,
}) {
  const { colors } = useAppTheme();
  const [conversations, setConversations] = useState([]);
  const [searchText, setSearchText] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  const drawerTranslateX = useSharedValue(0);

  // Rename & Delete state
  const [editingId, setEditingId] = useState(null);
  const [editingTitle, setEditingTitle] = useState("");
  const [savingId, setSavingId] = useState(null);
  const [deletingId, setDeletingId] = useState(null);

  const {
    conversationId,
    setConversationId,
    refreshKey,
    refreshConversations,
    agentName = "Cooper",
  } = useConversation();

  useEffect(() => {
    if (!visible) {
      drawerTranslateX.set(0);
    }
  }, [visible, drawerTranslateX]);

  useEffect(() => {
    if (!visible) {
      return;
    }

    let isActive = true;

    async function loadConversations() {
      setIsLoading(true);
      setErrorMessage("");

      try {
        const savedConversations = await getConversations();

        if (isActive) {
          setConversations(savedConversations);
        }
      } catch (error) {
        if (isActive) {
          setErrorMessage(error.message || "Could not load conversations");
        }
      } finally {
        if (isActive) {
          setIsLoading(false);
        }
      }
    }

    loadConversations();

    return () => {
      isActive = false;
    };
  }, [visible, refreshKey]);

  const filteredConversations = conversations.filter((conversation) =>
    conversation.title.toLowerCase().includes(searchText.toLowerCase())
  );

  function finishClosingDrawer() {
    setEditingId(null);
    setEditingTitle("");
    onClose();
  }

  function closeDrawer() {
    finishClosingDrawer();
  }

  function openSettings() {
    setEditingId(null);
    setEditingTitle("");
    onSettingsPress();
  }

  function selectConversation(selectedConversationId) {
    if (editingId === selectedConversationId) {
      return;
    }
    setConversationId(selectedConversationId);
    router.replace("/(tabs)/chat");
    closeDrawer();
  }

  function openMainChat() {
    if (conversations.length > 0) {
      setConversationId(conversations[0].id);
    } else {
      setConversationId(null);
    }

    router.replace("/(tabs)/chat");
    closeDrawer();
  }

  function startNewChat() {
    setConversationId(null);
    router.replace("/(tabs)/chat");
    closeDrawer();
  }

  function startRename(conversation) {
    setEditingId(conversation.id);
    setEditingTitle(conversation.title);
    setErrorMessage("");
  }

  function cancelRename() {
    setEditingId(null);
    setEditingTitle("");
  }

  async function submitRename(targetId) {
    const cleanTitle = editingTitle.trim();
    if (!cleanTitle || savingId) {
      cancelRename();
      return;
    }

    setSavingId(targetId);
    setErrorMessage("");

    try {
      const updated = await renameConversation(targetId, cleanTitle);
      setConversations((current) =>
        current.map((item) =>
          item.id === targetId
            ? { ...item, title: updated?.title || cleanTitle }
            : item
        )
      );
      setEditingId(null);
      setEditingTitle("");
      refreshConversations();
    } catch (error) {
      setErrorMessage(error.message || "Could not rename chat");
    } finally {
      setSavingId(null);
    }
  }

  function confirmDeleteChat(conversation) {
    if (Platform.OS === "web") {
      const confirmed = window.confirm(
        `Are you sure you want to delete "${conversation.title}"?`
      );
      if (confirmed) {
        performDeleteChat(conversation.id);
      }
      return;
    }

    Alert.alert(
      "Are you sure?",
      `Do you want to permanently delete "${conversation.title}"?`,
      [
        {
          text: "Cancel",
          style: "cancel",
        },
        {
          text: "Delete",
          style: "destructive",
          onPress: () => performDeleteChat(conversation.id),
        },
      ],
      { cancelable: true }
    );
  }

  async function performDeleteChat(targetId) {
    if (deletingId) {
      return;
    }

    setDeletingId(targetId);
    setErrorMessage("");

    try {
      await deleteConversation(targetId);
      setConversations((current) =>
        current.filter((item) => item.id !== targetId)
      );

      if (conversationId === targetId) {
        setConversationId(null);
      }
      refreshConversations();
    } catch (error) {
      setErrorMessage(error.message || "Could not delete chat");
    } finally {
      setDeletingId(null);
    }
  }

  const drawerAnimatedStyle = useAnimatedStyle(() => ({
    transform: [{ translateX: drawerTranslateX.get() }],
  }));

  const closeDrawerGesture = Gesture.Pan()
    .enabled(visible)
    .activeOffsetX(-4)
    .failOffsetY([-40, 40])
    .onBegin(() => {
      cancelAnimation(drawerTranslateX);
    })
    .onUpdate((event) => {
      drawerTranslateX.set(
        Math.max(
          -DRAWER_OFFSCREEN_DISTANCE,
          Math.min(0, event.translationX),
        ),
      );
    })
    .onEnd((event) => {
      const projectedPosition =
        event.translationX + event.velocityX * DRAWER_PROJECTION_TIME;
      const shouldClose =
        projectedPosition <= -DRAWER_CLOSE_DISTANCE ||
        event.velocityX <= DRAWER_FLING_VELOCITY;

      if (shouldClose) {
        drawerTranslateX.set(
          withTiming(
            -DRAWER_OFFSCREEN_DISTANCE,
            {
              duration: 140,
              easing: Easing.out(Easing.cubic),
            },
            (finished) => {
              if (finished) {
                runOnJS(finishClosingDrawer)();
              }
            },
          ),
        );
        return;
      }

      drawerTranslateX.set(
        withSpring(0, {
          stiffness: 300,
          damping: 30,
          mass: 0.8,
          overshootClamping: true,
        }),
      );
    })
    .onFinalize((_event, success) => {
      if (!success) {
        drawerTranslateX.set(
          withSpring(0, {
            stiffness: 300,
            damping: 30,
            mass: 0.8,
            overshootClamping: true,
          }),
        );
      }
    });

  return (
    <Modal
      visible={visible}
      transparent
      animationType="none"
      onRequestClose={closeDrawer}
      statusBarTranslucent
    >
      <GestureHandlerRootView style={styles.modalGestureRoot}>
        <View style={[styles.modal, { backgroundColor: colors.overlay }]}>
          <GestureDetector gesture={closeDrawerGesture}>
            <Animated.View
              style={[
                styles.drawerShell,
                { backgroundColor: colors.elevated },
                drawerAnimatedStyle,
              ]}
            >
            <SafeAreaView style={[styles.drawer, { backgroundColor: colors.elevated }]}>
            <View style={styles.header}>
              <Text style={[styles.title, { color: colors.text }]}>Conversations</Text>

              <Pressable style={[styles.closeButton, { backgroundColor: colors.surfaceTertiary }]} onPress={closeDrawer}>
                <Ionicons name="close" size={22} color={colors.text} />
              </Pressable>
            </View>

          <Pressable style={[styles.mainChat, { backgroundColor: colors.primarySoft }]} onPress={openMainChat}>
            <View style={[styles.mainIcon, { backgroundColor: colors.surfaceTertiary }]}>
              <Ionicons name="chatbubble" size={19} color={colors.primary} />
            </View>

            <View style={styles.chatText}>
              <Text style={[styles.mainTitle, { color: colors.text }]}>Main chat</Text>
              <Text style={[styles.mainSubtitle, { color: colors.textSecondary }]}>
                Continue with {agentName}
              </Text>
            </View>
          </Pressable>

          <Text style={[styles.sectionLabel, { color: colors.textMuted }]}>SIDE CHATS</Text>

          <ScrollView
            style={styles.conversationList}
            showsVerticalScrollIndicator={false}
            keyboardShouldPersistTaps="handled"
          >
            {isLoading && (
              <ActivityIndicator
                style={styles.loader}
                size="small"
                color={colors.primary}
              />
            )}

            {Boolean(errorMessage) && (
              <Text style={[styles.errorText, { color: colors.danger }]}>{errorMessage}</Text>
            )}

            {!isLoading && filteredConversations.length === 0 && (
              <Text style={[styles.emptyText, { color: colors.textMuted }]}>No conversations yet</Text>
            )}

            {filteredConversations.map((conversation) => {
              const isEditing = editingId === conversation.id;
              const isSaving = savingId === conversation.id;
              const isDeleting = deletingId === conversation.id;
              const isActive = conversation.id === conversationId;

              if (isEditing) {
                return (
                  <View
                    key={conversation.id}
                    style={[
                      styles.conversation,
                      styles.editingRow,
                      { backgroundColor: colors.surfaceSecondary, borderColor: colors.border },
                    ]}
                  >
                    <TextInput
                      style={[styles.renameInput, { color: colors.text }]}
                      value={editingTitle}
                      onChangeText={setEditingTitle}
                      placeholder="Chat title"
                      placeholderTextColor={colors.textMuted}
                      autoFocus
                      returnKeyType="done"
                      onSubmitEditing={() => submitRename(conversation.id)}
                    />

                    <Pressable
                      style={styles.iconActionBtn}
                      onPress={() => submitRename(conversation.id)}
                      disabled={isSaving}
                      hitSlop={6}
                    >
                      {isSaving ? (
                        <ActivityIndicator size="small" color={colors.primary} />
                      ) : (
                        <Ionicons
                          name="checkmark"
                          size={18}
                          color="#16A34A"
                        />
                      )}
                    </Pressable>

                    <Pressable
                      style={styles.iconActionBtn}
                      onPress={cancelRename}
                      disabled={isSaving}
                      hitSlop={6}
                    >
                      <Ionicons name="close" size={18} color={colors.textSecondary} />
                    </Pressable>
                  </View>
                );
              }

              return (
                <Pressable
                  key={conversation.id}
                  style={({ pressed }) => [
                    styles.conversation,
                    isActive && { backgroundColor: colors.primarySoft },
                    pressed && { backgroundColor: colors.pressed },
                  ]}
                  onPress={() => selectConversation(conversation.id)}
                >
                  <Ionicons
                    name="chatbox-outline"
                    size={18}
                    color={isActive ? colors.primary : colors.textSecondary}
                  />

                  <Text
                    numberOfLines={1}
                    style={[
                      styles.conversationText,
                      { color: isActive ? colors.text : colors.textSecondary },
                      isActive && styles.activeConversationText,
                    ]}
                  >
                    {conversation.title}
                  </Text>

                  <View style={styles.rowActions}>
                    <Pressable
                      style={({ pressed }) => [
                        styles.iconActionBtn,
                        pressed && { backgroundColor: colors.surfaceTertiary },
                      ]}
                      onPress={(e) => {
                        e?.stopPropagation?.();
                        startRename(conversation);
                      }}
                      hitSlop={6}
                    >
                      <Ionicons
                        name="pencil-outline"
                        size={15}
                        color={colors.textSecondary}
                      />
                    </Pressable>

                    <Pressable
                      style={({ pressed }) => [
                        styles.iconActionBtn,
                        pressed && { backgroundColor: colors.surfaceTertiary },
                      ]}
                      onPress={(e) => {
                        e?.stopPropagation?.();
                        confirmDeleteChat(conversation);
                      }}
                      disabled={isDeleting}
                      hitSlop={6}
                    >
                      {isDeleting ? (
                        <ActivityIndicator size="small" color={colors.danger} />
                      ) : (
                        <Ionicons
                          name="trash-outline"
                          size={15}
                          color={colors.danger}
                        />
                      )}
                    </Pressable>
                  </View>
                </Pressable>
              );
            })}
          </ScrollView>

            <View style={[styles.bottomSection, { borderTopColor: colors.divider }]}>
              <View style={[styles.search, { backgroundColor: colors.surfaceTertiary }]}>
                <Ionicons
                  name="search-outline"
                  size={18}
                  color={colors.textMuted}
                />

                <TextInput
                  style={[styles.searchInput, { color: colors.text }]}
                  placeholder="Search chats"
                  placeholderTextColor={colors.textMuted}
                  value={searchText}
                  onChangeText={setSearchText}
                />
              </View>

              <Pressable
                style={[styles.settingsButton, { backgroundColor: colors.surfaceTertiary }]}
                onPress={openSettings}
              >
                <Ionicons
                  name="settings-outline"
                  size={21}
                  color={colors.text}
                />
              </Pressable>

              <Pressable style={[styles.newChatButton, { backgroundColor: colors.primary }]} onPress={startNewChat}>
                <Ionicons name="create-outline" size={21} color="#FFFFFF" />
              </Pressable>
            </View>
            </SafeAreaView>
            </Animated.View>
          </GestureDetector>

          <Pressable style={styles.backdrop} onPress={closeDrawer} />
        </View>
      </GestureHandlerRootView>
    </Modal>
  );
}

const styles = StyleSheet.create({
  modalGestureRoot: {
    flex: 1,
  },

  modal: {
    flex: 1,
    flexDirection: "row",
    backgroundColor: "rgba(15, 23, 42, 0.45)",
  },

  drawerShell: {
    width: "86%",
    maxWidth: 360,
    backgroundColor: "#FFFFFF",
  },

  drawer: {
    flex: 1,
    paddingHorizontal: 18,
    backgroundColor: "#FFFFFF",
  },

  backdrop: {
    flex: 1,
  },

  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingTop: 12,
    paddingBottom: 18,
  },

  title: {
    color: "#1E2022",
    fontSize: 23,
    fontWeight: "700",
  },

  closeButton: {
    width: 40,
    height: 40,
    borderRadius: 20,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "#F1F5F9",
  },

  mainChat: {
    flexDirection: "row",
    alignItems: "center",
    padding: 13,
    borderRadius: 15,
    backgroundColor: "#EFF6FF",
  },

  mainIcon: {
    width: 42,
    height: 42,
    marginRight: 12,
    borderRadius: 12,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "#DBEAFE",
  },

  chatText: {
    flex: 1,
  },

  mainTitle: {
    color: "#1E2022",
    fontSize: 15,
    fontWeight: "700",
  },

  mainSubtitle: {
    marginTop: 3,
    color: "#64748B",
    fontSize: 12,
  },

  sectionLabel: {
    marginTop: 24,
    marginBottom: 8,
    color: "#94A3B8",
    fontSize: 11,
    fontWeight: "800",
  },

  conversationList: {
    flex: 1,
  },

  loader: {
    marginTop: 20,
  },

  emptyText: {
    marginTop: 20,
    color: "#94A3B8",
    fontSize: 13,
    textAlign: "center",
  },

  errorText: {
    marginVertical: 14,
    color: "#DC2626",
    fontSize: 12,
    textAlign: "center",
  },

  conversation: {
    minHeight: 50,
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: 10,
    borderRadius: 10,
    marginBottom: 2,
  },

  editingRow: {
    backgroundColor: "#F8FAFC",
    borderWidth: 1,
    borderColor: "#BFDBFE",
  },

  pressed: {
    backgroundColor: "#F8FAFC",
  },

  activeConversation: {
    backgroundColor: "#EFF6FF",
  },

  conversationText: {
    flex: 1,
    marginLeft: 10,
    marginRight: 6,
    color: "#475569",
    fontSize: 13.5,
    fontWeight: "500",
  },

  activeConversationText: {
    fontWeight: "700",
  },

  rowActions: {
    flexDirection: "row",
    alignItems: "center",
    gap: 2,
  },

  iconActionBtn: {
    width: 28,
    height: 28,
    borderRadius: 7,
    alignItems: "center",
    justifyContent: "center",
  },

  actionBtnPressed: {
    backgroundColor: "#E2E8F0",
  },

  renameInput: {
    flex: 1,
    height: 36,
    paddingHorizontal: 8,
    color: "#1E2022",
    fontSize: 13.5,
    fontWeight: "600",
  },

  bottomSection: {
    flexDirection: "row",
    alignItems: "center",
    paddingTop: 12,
    paddingBottom: 10,
    borderTopWidth: 1,
    borderTopColor: "#F1F5F9",
  },

  search: {
    flex: 1,
    height: 42,
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: 11,
    borderRadius: 12,
    backgroundColor: "#F1F5F9",
  },

  searchInput: {
    flex: 1,
    marginLeft: 7,
    color: "#1E2022",
    fontSize: 13,
  },

  settingsButton: {
    width: 42,
    height: 42,
    marginLeft: 7,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 12,
    backgroundColor: "#F1F5F9",
  },

  newChatButton: {
    width: 42,
    height: 42,
    marginLeft: 7,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 12,
    backgroundColor: "#2563EB",
  },
});
