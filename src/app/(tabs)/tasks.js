import { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Platform,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Switch,
  Text,
  View,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import NewTaskModal from "../../components/NewTaskModal";
import { useConversation } from "../../context/ConversationContext";
import { useAppTheme } from "../../context/ThemeContext";
import * as api from "../../services/api";

export default function TasksScreen() {
  const { agentName = "Cooper" } = useConversation();
  const { colors } = useAppTheme();
  const [tasks, setTasks] = useState([]);
  const [isLoading, setIsLoading] = useState(typeof api.getTasks === "function");
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [runningTaskId, setRunningTaskId] = useState(null);
  const [deletingTaskId, setDeletingTaskId] = useState(null);
  const [newTaskVisible, setNewTaskVisible] = useState(false);
  const [errorText, setErrorText] = useState("");

  const loadTasks = useCallback(async (showSpinner = false) => {
    if (showSpinner) setIsLoading(true);
    setErrorText("");
    try {
      if (typeof api.getTasks === "function") {
        const data = await api.getTasks();
        setTasks(Array.isArray(data) ? data : []);
      }
    } catch (error) {
      setErrorText(error.message || "Could not load scheduled tasks");
    } finally {
      setIsLoading(false);
      setIsRefreshing(false);
    }
  }, []);

  async function handleRefresh() {
    if (isRefreshing || isLoading) return;
    setIsRefreshing(true);
    await loadTasks(false);
  }

  useEffect(() => {
    let active = true;
    if (typeof api.getTasks === "function") {
      api
        .getTasks()
        .then((data) => {
          if (active) {
            setTasks(Array.isArray(data) ? data : []);
            setIsLoading(false);
          }
        })
        .catch((error) => {
          if (active) {
            setErrorText(error.message || "Could not load scheduled tasks");
            setIsLoading(false);
          }
        });
    }
    return () => {
      active = false;
    };
  }, []);

  async function handleCreateTask(newTaskPayload) {
    try {
      if (typeof api.createTask === "function") {
        const created = await api.createTask({
          title: newTaskPayload.title,
          schedule: newTaskPayload.schedule,
          prompt: newTaskPayload.prompt || newTaskPayload.title,
          timezone:
            Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
          execution_mode: newTaskPayload.execution_mode || "assistant",
        });
        setTasks((current) => [created, ...current]);
      } else {
        setTasks((current) => [newTaskPayload, ...current]);
      }
      setNewTaskVisible(false);
    } catch (error) {
      Alert.alert("Could not create task", error.message);
    }
  }

  async function handleToggleTask(taskId) {
    try {
      if (typeof api.toggleTask === "function") {
        const updated = await api.toggleTask(taskId);
        setTasks((current) =>
          current.map((t) => (t.id === taskId ? updated : t))
        );
      } else {
        setTasks((current) =>
          current.map((t) =>
            t.id === taskId ? { ...t, active: !t.active } : t
          )
        );
      }
    } catch (error) {
      Alert.alert("Could not update task", error.message);
    }
  }

  async function handleRunNow(taskId) {
    if (runningTaskId) return;
    setRunningTaskId(taskId);
    try {
      if (typeof api.runTask === "function") {
        await api.runTask(taskId);
        setTimeout(() => loadTasks(false), 2000);
      }
    } catch (error) {
      Alert.alert("Run failed", error.message || "Could not start task run");
    } finally {
      setRunningTaskId(null);
    }
  }

  function handleDeleteTask(task) {
    if (deletingTaskId !== null) return;

    if (Platform.OS === "web") {
      const confirmed = window.confirm(
        `Are you sure you want to permanently delete "${task.title}"?`
      );
      if (confirmed) performDeleteTask(task.id);
      return;
    }

    Alert.alert(
      "Delete task?",
      `This will permanently delete "${task.title}".`,
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Delete",
          style: "destructive",
          onPress: () => performDeleteTask(task.id),
        },
      ],
      { cancelable: true }
    );
  }

  async function performDeleteTask(taskId) {
    if (deletingTaskId !== null) return;
    setDeletingTaskId(taskId);

    try {
      await api.deleteTask(taskId);
      setTasks((current) => current.filter((item) => item.id !== taskId));
    } catch (error) {
      const message = error.message || "Could not delete task";
      if (Platform.OS === "web") {
        window.alert(message);
      } else {
        Alert.alert("Delete failed", message);
      }
    } finally {
      setDeletingTaskId(null);
    }
  }

  return (
    <ScrollView
      style={[styles.container, { backgroundColor: colors.background }]}
      contentContainerStyle={styles.content}
      showsVerticalScrollIndicator={false}
      refreshControl={
        <RefreshControl
          refreshing={isRefreshing}
          onRefresh={handleRefresh}
          tintColor={colors.primary}
          colors={[colors.primary]}
        />
      }
    >
      <View style={styles.headerRow}>
        <View style={styles.heading}>
          <Text style={[styles.title, { color: colors.text }]}>Tasks & Goals</Text>
          <Text style={[styles.subtitle, { color: colors.textSecondary }]}>
            Autonomous routines {agentName} runs in the background.
          </Text>
        </View>

        <View style={styles.headerActions}>
          <Pressable
            accessibilityLabel="Refresh tasks"
            accessibilityRole="button"
            style={({ pressed }) => [
              styles.refreshButton,
              { backgroundColor: colors.surfaceTertiary },
              pressed && styles.buttonPressed,
            ]}
            onPress={handleRefresh}
            disabled={isRefreshing || isLoading}
          >
            {isRefreshing ? (
              <ActivityIndicator size="small" color={colors.textSecondary} />
            ) : (
              <Ionicons name="refresh-outline" size={19} color={colors.textSecondary} />
            )}
          </Pressable>

          <Pressable
            style={({ pressed }) => [
              styles.newButton,
              pressed && styles.buttonPressed,
            ]}
            onPress={() => setNewTaskVisible(true)}
          >
            <Ionicons name="add" size={17} color="#FFFFFF" />
            <Text style={styles.newButtonText}>New</Text>
          </Pressable>
        </View>
      </View>

      {Boolean(errorText) && <Text style={[styles.errorText, { color: colors.danger }]}>{errorText}</Text>}

      {isLoading ? (
        <ActivityIndicator
          style={{ marginTop: 32 }}
          size="large"
          color={colors.primary}
        />
      ) : tasks.length === 0 ? (
        <View style={[styles.emptyCard, { backgroundColor: colors.surfaceSecondary, borderColor: colors.border }]}>
          <Ionicons name="sparkles-outline" size={28} color={colors.primary} />
          <Text style={[styles.emptyTitle, { color: colors.text }]}>No scheduled routines yet</Text>
          <Text style={[styles.emptySubtitle, { color: colors.textSecondary }]}>
            Tap &quot;New&quot; or ask {agentName} in chat to schedule a daily
            briefing, price check, or inbox summary.
          </Text>
        </View>
      ) : (
        tasks.map((task) => (
          <View key={String(task.id)} style={[styles.taskCard, { borderBottomColor: colors.divider }]}>
            <View
              style={[
                styles.taskIcon,
                { backgroundColor: task.active ? colors.primarySoft : colors.surfaceTertiary },
              ]}
            >
              <Ionicons
                name={
                  task.execution_mode === "browser"
                    ? "globe-outline"
                    : "flag-outline"
                }
                size={21}
                color={task.active ? colors.primary : colors.textMuted}
              />
            </View>

            <View style={styles.taskContent}>
              <Text
                style={[
                  styles.taskTitle,
                  { color: task.active ? colors.text : colors.textMuted },
                ]}
              >
                {task.title}
              </Text>

              <View style={styles.detailRow}>
                <Ionicons name="time-outline" size={13} color={colors.textMuted} />
                <Text style={[styles.detailText, { color: colors.textSecondary }]}>{task.schedule}</Text>
              </View>

              <Text style={[styles.runsText, { color: colors.textMuted }]}>
                {task.runs || 0} runs • {task.active ? "Active" : "Paused"}
                {task.last_run_status ? ` • Last: ${task.last_run_status}` : ""}
              </Text>

              {Boolean(task.last_run_result) && (
                <View style={[styles.resultBox, { backgroundColor: colors.surfaceSecondary, borderColor: colors.border }]}>
                  <Text style={[styles.resultText, { color: colors.textSecondary }]} numberOfLines={3}>
                    {task.last_run_result}
                  </Text>
                </View>
              )}

              <View style={styles.taskActions}>
                <Pressable
                  style={[styles.runButton, { backgroundColor: colors.primarySoft }]}
                  onPress={() => handleRunNow(task.id)}
                  disabled={runningTaskId === task.id}
                >
                  {runningTaskId === task.id ? (
                    <ActivityIndicator size="small" color={colors.primary} />
                  ) : (
                    <>
                      <Ionicons name="play" size={12} color={colors.primary} />
                      <Text style={[styles.runText, { color: colors.primary }]}>Run now</Text>
                    </>
                  )}
                </Pressable>

                <Pressable
                  accessibilityLabel={`Delete ${task.title}`}
                  accessibilityRole="button"
                  style={[styles.deleteButton, { backgroundColor: colors.dangerSoft }]}
                  onPress={() => handleDeleteTask(task)}
                  disabled={deletingTaskId !== null}
                >
                  {deletingTaskId === task.id ? (
                    <ActivityIndicator size="small" color={colors.danger} />
                  ) : (
                    <>
                      <Ionicons
                        name="trash-outline"
                        size={13}
                        color={colors.danger}
                      />
                      <Text style={[styles.deleteText, { color: colors.danger }]}>Delete</Text>
                    </>
                  )}
                </Pressable>
              </View>
            </View>

            <Switch
              value={Boolean(task.active)}
              onValueChange={() => handleToggleTask(task.id)}
              trackColor={{
                false: colors.border,
                true: "#93C5FD",
              }}
              thumbColor={task.active ? colors.primary : colors.surfaceSecondary}
            />
          </View>
        ))
      )}

      <NewTaskModal
        visible={newTaskVisible}
        onClose={() => setNewTaskVisible(false)}
        onCreate={handleCreateTask}
      />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#FFFFFF" },
  content: { paddingHorizontal: 20, paddingTop: 12, paddingBottom: 30 },
  headerRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: 18,
  },
  heading: { flex: 1, paddingRight: 10 },
  title: { color: "#1E2022", fontSize: 28, fontWeight: "700" },
  subtitle: { marginTop: 4, color: "#64748B", fontSize: 14 },
  headerActions: { flexDirection: "row", alignItems: "center" },
  refreshButton: {
    width: 40,
    height: 40,
    marginRight: 8,
    borderRadius: 12,
    justifyContent: "center",
    alignItems: "center",
    backgroundColor: "#F1F5F9",
  },
  newButton: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: 13,
    paddingVertical: 9,
    borderRadius: 12,
    backgroundColor: "#2563EB",
  },
  buttonPressed: { opacity: 0.75 },
  newButtonText: {
    marginLeft: 3,
    color: "#FFFFFF",
    fontSize: 13,
    fontWeight: "700",
  },
  errorText: { marginBottom: 12, color: "#DC2626", fontSize: 13 },
  emptyCard: {
    marginTop: 20,
    padding: 24,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: "#E2E8F0",
    backgroundColor: "#F8FAFC",
    alignItems: "center",
  },
  emptyTitle: {
    marginTop: 10,
    color: "#1E2022",
    fontSize: 16,
    fontWeight: "700",
  },
  emptySubtitle: {
    marginTop: 6,
    color: "#64748B",
    fontSize: 13.5,
    textAlign: "center",
    lineHeight: 20,
  },
  taskCard: {
    flexDirection: "row",
    alignItems: "flex-start",
    paddingVertical: 18,
    borderBottomWidth: 1,
    borderBottomColor: "#F1F5F9",
  },
  taskIcon: {
    width: 44,
    height: 44,
    marginRight: 13,
    borderRadius: 12,
    justifyContent: "center",
    alignItems: "center",
    backgroundColor: "#EFF6FF",
  },
  inactiveIcon: { backgroundColor: "#F1F5F9" },
  taskContent: { flex: 1, paddingRight: 8 },
  taskTitle: {
    color: "#1E2022",
    fontSize: 15.5,
    lineHeight: 21,
    fontWeight: "700",
  },
  inactiveText: { color: "#94A3B8" },
  detailRow: { flexDirection: "row", alignItems: "center", marginTop: 6 },
  detailText: { marginLeft: 4, color: "#64748B", fontSize: 12.5 },
  runsText: { marginTop: 5, color: "#94A3B8", fontSize: 12 },
  resultBox: {
    marginTop: 8,
    padding: 10,
    borderRadius: 10,
    backgroundColor: "#F8FAFC",
    borderWidth: 1,
    borderColor: "#E2E8F0",
  },
  resultText: { color: "#334155", fontSize: 12.5, lineHeight: 18 },
  taskActions: {
    flexDirection: "row",
    alignItems: "center",
    flexWrap: "wrap",
    marginTop: 10,
  },
  runButton: {
    alignSelf: "flex-start",
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 8,
    backgroundColor: "#EFF6FF",
  },
  runText: {
    marginLeft: 4,
    color: "#2563EB",
    fontSize: 12,
    fontWeight: "700",
  },
  deleteButton: {
    alignSelf: "flex-start",
    flexDirection: "row",
    alignItems: "center",
    marginLeft: 8,
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 8,
    backgroundColor: "#FEF2F2",
  },
  deleteText: {
    marginLeft: 4,
    color: "#DC2626",
    fontSize: 12,
    fontWeight: "700",
  },
});
