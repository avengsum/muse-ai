import { useState } from "react";
import {
  Modal,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { Image } from "expo-image";
import { SafeAreaView } from "react-native-safe-area-context";
import { useAppTheme } from "../context/ThemeContext";

const colors = [
  "#2563EB",
  "#4F46E5",
  "#059669",
  "#D97706",
  "#7C3AED",
  "#E11D48",
];

export default function AgentEditorModal({
  visible,
  initialName,
  initialColor,
  onClose,
  onSave,
}) {
  const { colors: themeColors } = useAppTheme();
  const [name, setName] = useState(initialName);
  const [selectedColor, setSelectedColor] = useState(
    initialColor || "#2563EB"
  );

  function handleSave() {
    const cleanName = name.trim() || "Cooper";
    onSave(cleanName, selectedColor);
  }

  return (
    <Modal
      visible={visible}
      transparent
      animationType="slide"
      onRequestClose={onClose}
      statusBarTranslucent
    >
      <View style={[styles.overlay, { backgroundColor: themeColors.overlay }]}>
        <Pressable style={StyleSheet.absoluteFill} onPress={onClose} />

        <SafeAreaView style={[styles.sheet, { backgroundColor: themeColors.elevated }]} edges={["bottom"]}>
          <View style={[styles.handle, { backgroundColor: themeColors.border }]} />

          <Text style={[styles.title, { color: themeColors.text }]}>Customize your agent</Text>
          <Text style={[styles.subtitle, { color: themeColors.textSecondary }]}>
            Change the name and accent color.
          </Text>

          <View
            style={[
              styles.avatarGlow,
              { backgroundColor: `${selectedColor}20` },
            ]}
          >
            <Image
              source={require("../../assets/cooper_mascot.jpg")}
              style={styles.avatar}
              contentFit="cover"
            />
          </View>

          <Text style={[styles.label, { color: themeColors.textSecondary }]}>AGENT NAME</Text>

          <TextInput
            style={[styles.input, { backgroundColor: themeColors.input, borderColor: themeColors.border, color: themeColors.text }]}
            value={name}
            onChangeText={setName}
            placeholder="Agent name"
            placeholderTextColor={themeColors.textMuted}
            maxLength={20}
          />

          <Text style={[styles.label, { color: themeColors.textSecondary }]}>ACCENT COLOR</Text>

          <View style={styles.colorRow}>
            {colors.map((color) => (
              <Pressable
                key={color}
                style={[
                  styles.colorButton,
                  { backgroundColor: color },
                  selectedColor === color && styles.selectedColor,
                ]}
                onPress={() => setSelectedColor(color)}
              />
            ))}
          </View>

          <View style={styles.actions}>
            <Pressable style={[styles.cancelButton, { borderColor: themeColors.border }]} onPress={onClose}>
              <Text style={[styles.cancelText, { color: themeColors.textSecondary }]}>Cancel</Text>
            </Pressable>

            <Pressable style={styles.saveButton} onPress={handleSave}>
              <Text style={styles.saveText}>Save changes</Text>
            </Pressable>
          </View>
        </SafeAreaView>
      </View>
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
    color: "#64748B",
    fontSize: 14,
  },

  avatarGlow: {
    alignSelf: "center",
    padding: 12,
    marginVertical: 22,
    borderRadius: 50,
  },

  avatar: {
    width: 78,
    height: 78,
    borderRadius: 39,
  },

  label: {
    marginBottom: 7,
    color: "#64748B",
    fontSize: 11,
    fontWeight: "800",
  },

  input: {
    height: 50,
    marginBottom: 20,
    paddingHorizontal: 14,
    borderWidth: 1,
    borderColor: "#E2E8F0",
    borderRadius: 13,
    color: "#1E2022",
    fontSize: 15,
    backgroundColor: "#F8FAFC",
  },

  colorRow: {
    flexDirection: "row",
    marginBottom: 25,
  },

  colorButton: {
    width: 34,
    height: 34,
    marginRight: 13,
    borderRadius: 17,
  },

  selectedColor: {
    borderWidth: 4,
    borderColor: "#DBEAFE",
  },

  actions: {
    flexDirection: "row",
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
    fontSize: 14,
    fontWeight: "700",
  },

  saveButton: {
    flex: 1.5,
    height: 50,
    marginLeft: 8,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 14,
    backgroundColor: "#2563EB",
  },

  saveText: {
    color: "#FFFFFF",
    fontSize: 14,
    fontWeight: "700",
  },
});
