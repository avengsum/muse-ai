import { useState } from "react";
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Modal,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useAppTheme } from "../context/ThemeContext";

function localTimezone() {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}

export default function NewTaskModal({
  visible,
  onClose,
  onCreate,
  initialTask,
}) {
  const { colors } = useAppTheme();
  const [title, setTitle] = useState(initialTask?.title || "");
  const [prompt, setPrompt] = useState(initialTask?.prompt || "");
  const [schedule, setSchedule] = useState(initialTask?.schedule || "");
  const [executionMode, setExecutionMode] = useState(
    initialTask?.execution_mode || "assistant"
  );
  const [isSaving, setIsSaving] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");

  async function handleCreate() {
    if (!title.trim() || isSaving) {
      return;
    }

    setIsSaving(true);
    setErrorMessage("");

    try {
      await onCreate({
        title: title.trim(),
        prompt: prompt.trim() || title.trim(),
        schedule: schedule.trim() || "Every day at 9:00 AM",
        timezone: initialTask?.timezone || localTimezone(),
        execution_mode: executionMode,
      });
      if (!initialTask) {
        setTitle("");
        setPrompt("");
        setSchedule("");
        setExecutionMode("assistant");
      }
    } catch (error) {
      setErrorMessage(error.message || "Could not create task");
    } finally {
      setIsSaving(false);
    }
  }

  return (
    <Modal
      visible={visible}
      transparent
      animationType="slide"
      onRequestClose={onClose}
    >
      <KeyboardAvoidingView
        style={[styles.overlay, { backgroundColor: colors.overlay }]}
        behavior={Platform.OS === "ios" ? "padding" : undefined}
      >
        <Pressable style={StyleSheet.absoluteFill} onPress={onClose} />

        <SafeAreaView style={[styles.sheet, { backgroundColor: colors.elevated }]} edges={["bottom"]}>
          <View style={[styles.handle, { backgroundColor: colors.border }]} />

          <Text style={[styles.title, { color: colors.text }]}>
            {initialTask ? "Edit task" : "Create a new task"}
          </Text>
          <Text style={[styles.subtitle, { color: colors.textSecondary }]}>
            Cooper will run these instructions on your schedule.
          </Text>

          <Text style={[styles.label, { color: colors.textSecondary }]}>TASK NAME</Text>
          <TextInput
            style={[styles.input, { backgroundColor: colors.input, borderColor: colors.border, color: colors.text }]}
            value={title}
            onChangeText={setTitle}
            placeholder="Morning news summary"
            placeholderTextColor={colors.textMuted}
          />

          <Text style={[styles.label, { color: colors.textSecondary }]}>INSTRUCTIONS</Text>
          <TextInput
            style={[styles.input, styles.promptInput, { backgroundColor: colors.input, borderColor: colors.border, color: colors.text }]}
            value={prompt}
            onChangeText={setPrompt}
            placeholder="Find the latest AI news and summarize the top five stories"
            placeholderTextColor={colors.textMuted}
            multiline
          />

          <Text style={[styles.label, { color: colors.textSecondary }]}>SCHEDULE</Text>
          <TextInput
            style={[styles.input, { backgroundColor: colors.input, borderColor: colors.border, color: colors.text }]}
            value={schedule}
            onChangeText={setSchedule}
            placeholder="Every day at 8:00 AM"
            placeholderTextColor={colors.textMuted}
          />

          <Text style={[styles.label, { color: colors.textSecondary }]}>RUN WITH</Text>
          <View style={styles.modeRow}>
            {[
              { id: "assistant", label: "AI + tools" },
              { id: "browser", label: "Browser" },
            ].map((mode) => (
              <Pressable
                key={mode.id}
                style={[
                  styles.modeButton,
                  { borderColor: colors.border },
                  executionMode === mode.id && [styles.activeMode, { backgroundColor: colors.primarySoft, borderColor: colors.primary }],
                ]}
                onPress={() => setExecutionMode(mode.id)}
              >
                <Text
                  style={[
                    styles.modeText,
                    { color: executionMode === mode.id ? colors.primary : colors.textSecondary },
                  ]}
                >
                  {mode.label}
                </Text>
              </Pressable>
            ))}
          </View>

          {Boolean(errorMessage) && (
            <Text style={[styles.errorText, { color: colors.danger }]}>{errorMessage}</Text>
          )}

          <View style={styles.actions}>
            <Pressable
              style={[styles.cancelButton, { borderColor: colors.border }]}
              onPress={onClose}
              disabled={isSaving}
            >
              <Text style={[styles.cancelText, { color: colors.textSecondary }]}>Cancel</Text>
            </Pressable>

            <Pressable
              style={[styles.createButton, isSaving && styles.disabledButton]}
              onPress={handleCreate}
              disabled={isSaving}
            >
              {isSaving ? (
                <ActivityIndicator size="small" color="#FFFFFF" />
              ) : (
                <Text style={styles.createText}>
                  {initialTask ? "Save task" : "Create task"}
                </Text>
              )}
            </Pressable>
          </View>
        </SafeAreaView>
      </KeyboardAvoidingView>
    </Modal>
  );
}

const styles = StyleSheet.create({
  overlay: {
    flex: 1,
    justifyContent: "flex-end",
    backgroundColor: "rgba(15, 23, 42, 0.45)",
  },

  sheet: {
    paddingHorizontal: 22,
    paddingTop: 10,
    paddingBottom: 12,
    borderTopLeftRadius: 26,
    borderTopRightRadius: 26,
    backgroundColor: "#FFFFFF",
  },

  handle: {
    alignSelf: "center",
    width: 42,
    height: 5,
    marginBottom: 18,
    borderRadius: 3,
    backgroundColor: "#CBD5E1",
  },

  title: {
    color: "#1E2022",
    fontSize: 22,
    fontWeight: "700",
  },

  subtitle: {
    marginTop: 5,
    marginBottom: 20,
    color: "#64748B",
    fontSize: 14,
  },

  label: {
    marginBottom: 7,
    color: "#64748B",
    fontSize: 11,
    fontWeight: "800",
  },

  input: {
    minHeight: 48,
    marginBottom: 15,
    paddingHorizontal: 14,
    paddingVertical: 12,
    borderWidth: 1,
    borderColor: "#E2E8F0",
    borderRadius: 13,
    color: "#1E2022",
    fontSize: 14,
    backgroundColor: "#F8FAFC",
  },

  promptInput: {
    minHeight: 72,
    textAlignVertical: "top",
  },

  modeRow: {
    flexDirection: "row",
    marginBottom: 14,
  },

  modeButton: {
    flex: 1,
    height: 42,
    alignItems: "center",
    justifyContent: "center",
    marginRight: 8,
    borderWidth: 1,
    borderColor: "#E2E8F0",
    borderRadius: 12,
  },

  activeMode: {
    borderColor: "#2563EB",
    backgroundColor: "#EFF6FF",
  },

  modeText: {
    color: "#64748B",
    fontSize: 13,
    fontWeight: "700",
  },

  activeModeText: {
    color: "#2563EB",
  },

  errorText: {
    marginBottom: 8,
    color: "#DC2626",
    fontSize: 12,
  },

  actions: {
    flexDirection: "row",
    marginTop: 4,
  },

  cancelButton: {
    flex: 1,
    height: 50,
    marginRight: 8,
    alignItems: "center",
    justifyContent: "center",
    borderWidth: 1,
    borderColor: "#E2E8F0",
    borderRadius: 14,
  },

  cancelText: {
    color: "#475569",
    fontWeight: "700",
  },

  createButton: {
    flex: 1.4,
    height: 50,
    marginLeft: 8,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 14,
    backgroundColor: "#2563EB",
  },

  disabledButton: {
    opacity: 0.65,
  },

  createText: {
    color: "#FFFFFF",
    fontWeight: "700",
  },
});
