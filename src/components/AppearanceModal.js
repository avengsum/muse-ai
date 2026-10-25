import { Modal, Pressable, StyleSheet, Text, View } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { useAppTheme } from "../context/ThemeContext";

const OPTIONS = [
  {
    id: "system",
    icon: "phone-portrait-outline",
    title: "System",
    subtitle: "Match this device",
  },
  {
    id: "light",
    icon: "sunny-outline",
    title: "Light",
    subtitle: "Always use light appearance",
  },
  {
    id: "dark",
    icon: "moon-outline",
    title: "Dark",
    subtitle: "Always use dark appearance",
  },
];

export default function AppearanceModal({ visible, onClose }) {
  const { colors, themePreference, setThemePreference } = useAppTheme();

  async function selectTheme(nextTheme) {
    await setThemePreference(nextTheme);
    onClose();
  }

  return (
    <Modal
      visible={visible}
      transparent
      animationType="fade"
      onRequestClose={onClose}
      statusBarTranslucent
    >
      <View style={[styles.overlay, { backgroundColor: colors.overlay }]}>
        <Pressable style={StyleSheet.absoluteFill} onPress={onClose} />

        <View
          style={[
            styles.sheet,
            {
              backgroundColor: colors.elevated,
              borderColor: colors.border,
            },
          ]}
        >
          <View style={styles.header}>
            <View>
              <Text style={[styles.title, { color: colors.text }]}>Appearance</Text>
              <Text style={[styles.subtitle, { color: colors.textSecondary }]}>
                Choose how Muse looks on this device.
              </Text>
            </View>

            <Pressable
              accessibilityLabel="Close appearance settings"
              accessibilityRole="button"
              style={[styles.closeButton, { backgroundColor: colors.surfaceTertiary }]}
              onPress={onClose}
            >
              <Ionicons name="close" size={20} color={colors.text} />
            </Pressable>
          </View>

          {OPTIONS.map((option) => {
            const selected = themePreference === option.id;

            return (
              <Pressable
                key={option.id}
                accessibilityRole="radio"
                accessibilityState={{ checked: selected }}
                style={({ pressed }) => [
                  styles.option,
                  {
                    borderColor: selected ? colors.primary : colors.border,
                    backgroundColor: selected
                      ? colors.primarySoft
                      : colors.surface,
                  },
                  pressed && { backgroundColor: colors.pressed },
                ]}
                onPress={() => selectTheme(option.id)}
              >
                <View
                  style={[
                    styles.optionIcon,
                    { backgroundColor: colors.surfaceTertiary },
                  ]}
                >
                  <Ionicons name={option.icon} size={21} color={colors.text} />
                </View>

                <View style={styles.optionCopy}>
                  <Text style={[styles.optionTitle, { color: colors.text }]}>
                    {option.title}
                  </Text>
                  <Text
                    style={[styles.optionSubtitle, { color: colors.textSecondary }]}
                  >
                    {option.subtitle}
                  </Text>
                </View>

                <Ionicons
                  name={selected ? "radio-button-on" : "radio-button-off"}
                  size={22}
                  color={selected ? colors.primary : colors.textMuted}
                />
              </Pressable>
            );
          })}
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  overlay: {
    flex: 1,
    justifyContent: "center",
    paddingHorizontal: 22,
  },
  sheet: {
    width: "100%",
    maxWidth: 460,
    alignSelf: "center",
    padding: 18,
    borderWidth: 1,
    borderRadius: 22,
  },
  header: {
    flexDirection: "row",
    alignItems: "flex-start",
    justifyContent: "space-between",
    marginBottom: 16,
  },
  title: {
    fontSize: 20,
    fontWeight: "800",
  },
  subtitle: {
    marginTop: 4,
    fontSize: 13,
  },
  closeButton: {
    width: 36,
    height: 36,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 18,
  },
  option: {
    minHeight: 72,
    flexDirection: "row",
    alignItems: "center",
    marginTop: 9,
    paddingHorizontal: 13,
    borderWidth: 1,
    borderRadius: 15,
  },
  optionIcon: {
    width: 40,
    height: 40,
    alignItems: "center",
    justifyContent: "center",
    marginRight: 12,
    borderRadius: 12,
  },
  optionCopy: {
    flex: 1,
  },
  optionTitle: {
    fontSize: 14.5,
    fontWeight: "700",
  },
  optionSubtitle: {
    marginTop: 3,
    fontSize: 12,
  },
});
