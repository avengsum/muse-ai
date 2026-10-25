import { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Platform,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { router, useFocusEffect } from "expo-router";

import { useAuth } from "../../context/AuthContext";
import { useConversation } from "../../context/ConversationContext";
import { useAppTheme } from "../../context/ThemeContext";
import {
  deleteUserMemory,
  getSettings,
  getUserMemories,
} from "../../services/api";
import AppearanceModal from "../../components/AppearanceModal";

const settings = [
  {
    id: "tools",
    icon: "extension-puzzle-outline",
    title: "Tools & connections",
    subtitle: "Connect Gmail, Calendar, Slack, and more",
  },
  {
    id: "billing",
    icon: "card-outline",
    title: "Plans and billing",
    subtitle: "Manage your subscription",
  },
  {
    id: "notifications",
    icon: "notifications-outline",
    title: "Notifications",
    subtitle: "Control reminders and alerts",
  },
  {
    id: "appearance",
    icon: "color-palette-outline",
    title: "Appearance",
    subtitle: "Theme and display preferences",
  },
  {
    id: "help",
    icon: "help-circle-outline",
    title: "Help and feedback",
    subtitle: "Get support or report a problem",
  },
];

const CATEGORY_STYLES = {
  dietary: { bg: "#ECFDF5", text: "#059669" },
  location: { bg: "#EFF6FF", text: "#2563EB" },
  preference: { bg: "#F5F3FF", text: "#7C3AED" },
  work: { bg: "#FFFBEB", text: "#D97706" },
  personal: { bg: "#FFF1F2", text: "#E11D48" },
};

function normalizeQuotaStatus(value) {
  if (!value || value.limit_enabled !== true) {
    return null;
  }

  const limit = Math.max(0, Number(value.questions_limit) || 0);
  const used = Math.min(limit, Math.max(0, Number(value.questions_used) || 0));
  const remaining = Math.max(
    0,
    Number.isFinite(Number(value.questions_remaining))
      ? Number(value.questions_remaining)
      : limit - used
  );
  const percentUsed = Math.min(
    100,
    Math.max(
      0,
      Number.isFinite(Number(value.percent_used))
        ? Number(value.percent_used)
        : limit > 0
          ? Math.round((used / limit) * 100)
          : 0
    )
  );

  return { limit, used, remaining, percentUsed };
}

export default function SettingsScreen() {
  const { signOut } = useAuth();
  const { agentName = "Cooper", setConversationId } = useConversation();
  const {
    colors,
    resolvedTheme,
    themePreference,
  } = useAppTheme();

  const [memories, setMemories] = useState([]);
  const [isLoadingMemories, setIsLoadingMemories] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [deletingId, setDeletingId] = useState(null);
  const [memoryError, setMemoryError] = useState("");
  const [appearanceVisible, setAppearanceVisible] = useState(false);
  const [quotaStatus, setQuotaStatus] = useState(null);

  const appearanceSubtitle =
    themePreference === "system"
      ? `System (${resolvedTheme})`
      : themePreference === "dark"
        ? "Dark"
        : "Light";

  const loadMemories = useCallback(async (showSpinner = false) => {
    if (showSpinner) {
      setIsLoadingMemories(true);
    }
    setMemoryError("");

    try {
      const data = await getUserMemories();
      setMemories(Array.isArray(data) ? data : []);
    } catch (error) {
      setMemoryError(error.message || "Could not load memories");
    } finally {
      setIsLoadingMemories(false);
    }
  }, []);

  const loadQuotaStatus = useCallback(async () => {
    try {
      const data = await getSettings();
      setQuotaStatus(normalizeQuotaStatus(data && data.quota));
    } catch {
      setQuotaStatus(null);
    }
  }, []);

  const handleRefresh = useCallback(async () => {
    setIsRefreshing(true);
    await Promise.all([loadMemories(false), loadQuotaStatus()]);
    setIsRefreshing(false);
  }, [loadMemories, loadQuotaStatus]);

  useEffect(() => {
    const initialLoad = setTimeout(() => loadMemories(true), 0);
    return () => clearTimeout(initialLoad);
  }, [loadMemories]);

  useFocusEffect(
    useCallback(() => {
      loadQuotaStatus();
    }, [loadQuotaStatus])
  );

  function handleBinPress(memory) {
    // Web confirmation dialog
    if (Platform.OS === "web") {
      const confirmed = window.confirm(
        `Are you sure you want to delete this memory?\n\n"${memory.fact}"`
      );
      if (confirmed) {
        performDeleteMemory(memory.id);
      }
      return;
    }

    // Native iOS / Android "Are you sure?" popup
    Alert.alert(
      "Are you sure?",
      `Do you want ${agentName} to forget this memory?\n\n"${memory.fact}"`,
      [
        {
          text: "Cancel",
          style: "cancel",
        },
        {
          text: "Delete",
          style: "destructive",
          onPress: () => performDeleteMemory(memory.id),
        },
      ],
      { cancelable: true }
    );
  }

  async function performDeleteMemory(memoryId) {
    if (deletingId !== null) {
      return;
    }

    setDeletingId(memoryId);
    setMemoryError("");

    try {
      await deleteUserMemory(memoryId);
      setMemories((current) =>
        current.filter((item) => item.id !== memoryId)
      );
    } catch (error) {
      const msg = error.message || "Could not delete memory";
      if (Platform.OS === "web") {
        window.alert(msg);
      } else {
        Alert.alert("Delete failed", msg);
      }
    } finally {
      setDeletingId(null);
    }
  }

  async function handleSignOut() {
    try {
      setConversationId(null);
      await signOut();
    } catch (error) {
      console.warn(error);
    }
  }

  return (
    <>
      <ScrollView
      style={[styles.container, { backgroundColor: colors.background }]}
      contentContainerStyle={styles.content}
      showsVerticalScrollIndicator={false}
      refreshControl={
        <RefreshControl
          refreshing={isRefreshing}
          tintColor={colors.primary}
          colors={[colors.primary]}
          onRefresh={handleRefresh}
        />
      }
    >
      <Text style={[styles.title, { color: colors.text }]}>Settings</Text>

      {quotaStatus && (
        <View
          style={[
            styles.planCard,
            {
              backgroundColor: colors.surfaceSecondary,
              borderColor: colors.border,
            },
          ]}
        >
          <View style={styles.planHeader}>
            <View>
              <Text style={[styles.planLabel, { color: colors.primary }]}>CURRENT PLAN</Text>
              <Text style={[styles.planName, { color: colors.text }]}>Free plan</Text>
            </View>

            <Text style={[styles.percent, { color: colors.textSecondary }]}>
              {quotaStatus.percentUsed}% used
            </Text>
          </View>

          <View
            style={[styles.progressBackground, { backgroundColor: colors.border }]}
          >
            <View
              style={[
                styles.progress,
                {
                  width: `${quotaStatus.percentUsed}%`,
                  backgroundColor: colors.primary,
                },
              ]}
            />
          </View>

          <Text style={[styles.remaining, { color: colors.textSecondary }]}>
            {quotaStatus.remaining} of {quotaStatus.limit} questions remaining
          </Text>
        </View>
      )}

      <Text style={[styles.sectionLabel, { color: colors.textMuted }]}>ACCOUNT</Text>

      <View style={[styles.settingsGroup, { borderColor: colors.border }]}>
        {settings.map((item) => (
          <Pressable
            key={item.id}
            style={({ pressed }) => [
              styles.settingRow,
              {
                backgroundColor: colors.surface,
                borderBottomColor: colors.divider,
              },
              pressed && { backgroundColor: colors.pressed },
            ]}
            onPress={() => {
              if (item.id === "tools") {
                router.push("/tools");
                return;
              }

              if (item.id === "appearance") {
                setAppearanceVisible(true);
                return;
              }

              console.log(item.title);
            }}
          >
            <View
              style={[
                styles.iconContainer,
                { backgroundColor: colors.surfaceTertiary },
              ]}
            >
              <Ionicons name={item.icon} size={21} color={colors.text} />
            </View>

            <View style={styles.settingText}>
              <Text style={[styles.settingTitle, { color: colors.text }]}>{item.title}</Text>
              <Text style={[styles.settingSubtitle, { color: colors.textMuted }]}>
                {item.id === "appearance" ? appearanceSubtitle : item.subtitle}
              </Text>
            </View>

            <Ionicons name="chevron-forward" size={18} color={colors.textMuted} />
          </Pressable>
        ))}
      </View>

      {/* MEMORIES SECTION */}
      <View style={styles.memoriesHeader}>
        <View style={{ flex: 1 }}>
          <Text style={[styles.sectionLabel, { color: colors.textMuted }]}>
            SAVED MEMORIES ({memories.length})
          </Text>
          <Text style={[styles.memoriesSubtitle, { color: colors.textSecondary }]}>
            Things {agentName} remembers from your chats
          </Text>
        </View>

        <Pressable
          style={({ pressed }) => [
            styles.refreshButton,
            {
              backgroundColor: colors.surfaceSecondary,
              borderColor: colors.border,
            },
            pressed && { backgroundColor: colors.pressed },
          ]}
          onPress={() => loadMemories(true)}
        >
          <Ionicons name="refresh-outline" size={17} color={colors.textSecondary} />
        </Pressable>
      </View>

      {Boolean(memoryError) && (
        <Text style={styles.errorText}>{memoryError}</Text>
      )}

      {isLoadingMemories ? (
        <View
          style={[
            styles.emptyMemoriesBox,
            { backgroundColor: colors.surfaceSecondary, borderColor: colors.border },
          ]}
        >
          <ActivityIndicator size="small" color={colors.primary} />
          <Text style={[styles.emptyMemoriesSub, { color: colors.textSecondary }]}>Loading memories...</Text>
        </View>
      ) : memories.length === 0 ? (
        <View
          style={[
            styles.emptyMemoriesBox,
            { backgroundColor: colors.surfaceSecondary, borderColor: colors.border },
          ]}
        >
          <Ionicons name="sparkles-outline" size={24} color={colors.textMuted} />
          <Text style={[styles.emptyMemoriesTitle, { color: colors.text }]}>No memories yet</Text>
          <Text style={[styles.emptyMemoriesSub, { color: colors.textSecondary }]}>
            Tell {agentName} your dietary preferences, favorite places, or work
            habits in chat and they will appear here.
          </Text>
        </View>
      ) : (
        <View
          style={[
            styles.memoriesList,
            { backgroundColor: colors.surface, borderColor: colors.border },
          ]}
        >
          {memories.map((memory, index) => {
            const categoryKey = String(
              memory.category || "preference"
            ).toLowerCase();
            const badgeStyle = CATEGORY_STYLES[categoryKey] || {
              bg: "#F1F5F9",
              text: "#475569",
            };
            const isDeleting = deletingId === memory.id;

            return (
              <View
                key={String(memory.id)}
                style={[
                  styles.memoryItem,
                  { borderBottomColor: colors.divider },
                  index === memories.length - 1 && { borderBottomWidth: 0 },
                ]}
              >
                <View style={styles.memoryInfo}>
                  <View
                    style={[
                      styles.categoryBadge,
                      { backgroundColor: badgeStyle.bg },
                    ]}
                  >
                    <Text
                      style={[
                        styles.categoryText,
                        { color: badgeStyle.text },
                      ]}
                    >
                      {categoryKey.toUpperCase()}
                    </Text>
                  </View>

                  <Text style={[styles.memoryFact, { color: colors.text }]}>{memory.fact}</Text>
                </View>

                <Pressable
                  style={({ pressed }) => [
                    styles.binButton,
                    { backgroundColor: colors.dangerSoft },
                    pressed && styles.binButtonPressed,
                  ]}
                  onPress={() => handleBinPress(memory)}
                  disabled={isDeleting}
                  hitSlop={8}
                >
                  {isDeleting ? (
                    <ActivityIndicator size="small" color={colors.danger} />
                  ) : (
                    <Ionicons
                      name="trash-outline"
                      size={19}
                      color={colors.danger}
                    />
                  )}
                </Pressable>
              </View>
            );
          })}
        </View>
      )}

      <Pressable
        style={[styles.signOutButton, { backgroundColor: colors.dangerSoft }]}
        onPress={handleSignOut}
      >
        <Ionicons name="log-out-outline" size={20} color={colors.danger} />
        <Text style={[styles.signOutText, { color: colors.danger }]}>Sign out</Text>
      </Pressable>
      </ScrollView>

      <AppearanceModal
        visible={appearanceVisible}
        onClose={() => setAppearanceVisible(false)}
      />
    </>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: "#FFFFFF",
  },

  content: {
    paddingHorizontal: 20,
    paddingTop: 12,
    paddingBottom: 35,
  },

  title: {
    marginBottom: 18,
    color: "#1E2022",
    fontSize: 28,
    fontWeight: "700",
  },

  planCard: {
    padding: 18,
    marginBottom: 26,
    borderWidth: 1,
    borderColor: "#E2E8F0",
    borderRadius: 16,
    backgroundColor: "#F8FAFC",
  },

  planHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
  },

  planLabel: {
    color: "#2563EB",
    fontSize: 10,
    fontWeight: "800",
  },

  planName: {
    marginTop: 3,
    color: "#1E2022",
    fontSize: 20,
    fontWeight: "700",
  },

  percent: {
    color: "#64748B",
    fontSize: 13,
    fontWeight: "600",
  },

  progressBackground: {
    height: 8,
    marginTop: 16,
    overflow: "hidden",
    borderRadius: 4,
    backgroundColor: "#E2E8F0",
  },

  progress: {
    height: "100%",
    borderRadius: 4,
    backgroundColor: "#2563EB",
  },

  remaining: {
    marginTop: 10,
    color: "#64748B",
    fontSize: 12,
  },

  sectionLabel: {
    marginBottom: 4,
    color: "#94A3B8",
    fontSize: 11,
    fontWeight: "800",
  },

  settingsGroup: {
    marginTop: 4,
    marginBottom: 26,
    borderWidth: 1,
    borderColor: "#F1F5F9",
    borderRadius: 16,
    overflow: "hidden",
  },

  settingRow: {
    minHeight: 72,
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: 14,
    borderBottomWidth: 1,
    borderBottomColor: "#F1F5F9",
    backgroundColor: "#FFFFFF",
  },

  pressed: {
    backgroundColor: "#F8FAFC",
  },

  iconContainer: {
    width: 40,
    height: 40,
    marginRight: 12,
    borderRadius: 11,
    justifyContent: "center",
    alignItems: "center",
    backgroundColor: "#F1F5F9",
  },

  settingText: {
    flex: 1,
  },

  settingTitle: {
    color: "#1E2022",
    fontSize: 14.5,
    fontWeight: "700",
  },

  settingSubtitle: {
    marginTop: 3,
    color: "#94A3B8",
    fontSize: 12,
  },

  memoriesHeader: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: 10,
  },

  memoriesSubtitle: {
    color: "#64748B",
    fontSize: 12,
  },

  refreshButton: {
    width: 34,
    height: 34,
    borderRadius: 10,
    alignItems: "center",
    justifyContent: "center",
    borderWidth: 1,
    borderColor: "#E2E8F0",
    backgroundColor: "#F8FAFC",
  },

  errorText: {
    marginBottom: 10,
    color: "#DC2626",
    fontSize: 12.5,
  },

  emptyMemoriesBox: {
    padding: 22,
    borderWidth: 1,
    borderColor: "#E2E8F0",
    borderRadius: 16,
    backgroundColor: "#F8FAFC",
    alignItems: "center",
  },

  emptyMemoriesTitle: {
    marginTop: 8,
    color: "#1E2022",
    fontSize: 14.5,
    fontWeight: "700",
  },

  emptyMemoriesSub: {
    marginTop: 5,
    color: "#64748B",
    fontSize: 12.5,
    textAlign: "center",
    lineHeight: 18,
  },

  memoriesList: {
    borderWidth: 1,
    borderColor: "#F1F5F9",
    borderRadius: 16,
    backgroundColor: "#FFFFFF",
    overflow: "hidden",
  },

  memoryItem: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingVertical: 14,
    paddingHorizontal: 14,
    borderBottomWidth: 1,
    borderBottomColor: "#F1F5F9",
  },

  memoryInfo: {
    flex: 1,
    paddingRight: 12,
  },

  categoryBadge: {
    alignSelf: "flex-start",
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 6,
    marginBottom: 6,
  },

  categoryText: {
    fontSize: 10,
    fontWeight: "800",
  },

  memoryFact: {
    color: "#1E2022",
    fontSize: 14,
    lineHeight: 20,
    fontWeight: "500",
  },

  binButton: {
    width: 38,
    height: 38,
    borderRadius: 10,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "#FEF2F2",
  },

  binButtonPressed: {
    opacity: 0.7,
    transform: [{ scale: 0.95 }],
  },

  signOutButton: {
    flexDirection: "row",
    justifyContent: "center",
    alignItems: "center",
    marginTop: 26,
    paddingVertical: 14,
    borderRadius: 14,
    backgroundColor: "#FEF2F2",
  },

  signOutText: {
    marginLeft: 7,
    color: "#EF4444",
    fontSize: 14,
    fontWeight: "700",
  },
});
