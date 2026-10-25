import { Pressable, StyleSheet, Text, View } from "react-native";
import { Image } from "expo-image";
import { Ionicons } from "@expo/vector-icons";
import { usePathname } from "expo-router";
import { useAppTheme } from "../context/ThemeContext";

export default function AppHeader({
  agentName = "Cooper",
  accentColor = "#2563EB",
  onMenuPress,
  onMorePress,
}) {
  const { colors } = useAppTheme();
  const pathname = usePathname();
  const isChatTab = !pathname || pathname === "/chat" || pathname.endsWith("/chat");

  return (
    <View style={[styles.header, { backgroundColor: colors.background }]}>
      <Pressable
        style={({ pressed }) => [
          styles.circleButton,
          {
            backgroundColor: colors.elevated,
            shadowColor: colors.shadow,
          },
          pressed && { backgroundColor: colors.pressed },
        ]}
        onPress={onMenuPress}
      >
        <Ionicons name="menu" size={24} color={colors.text} />
        <View
          style={[
            styles.statusDot,
            { backgroundColor: accentColor, borderColor: colors.background },
          ]}
        />
      </Pressable>

      <View style={styles.centerSection}>
        <Image
          source={require("../../assets/cooper_mascot.jpg")}
          style={[styles.avatar, { backgroundColor: colors.surfaceTertiary }]}
          contentFit="cover"
        />

        <View
          style={[
            styles.namePill,
            { backgroundColor: colors.elevated, shadowColor: colors.shadow },
          ]}
        >
          <Text style={[styles.agentName, { color: accentColor }]}>
            {agentName}
          </Text>
        </View>
      </View>

      {isChatTab ? (
        <Pressable
          style={({ pressed }) => [
            styles.circleButton,
            {
              backgroundColor: colors.elevated,
              shadowColor: colors.shadow,
            },
            pressed && { backgroundColor: colors.pressed },
          ]}
          onPress={onMorePress}
        >
          <Ionicons
            name="ellipsis-horizontal"
            size={24}
            color={colors.text}
          />
        </Pressable>
      ) : (
        <View style={styles.rightSpacer} />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  header: {
    height: 92,
    paddingHorizontal: 20,
    paddingTop: 8,
    paddingBottom: 6,
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "flex-start",
    backgroundColor: "#FFFFFF",
    zIndex: 10,
  },

  circleButton: {
    width: 48,
    height: 48,
    borderRadius: 24,
    justifyContent: "center",
    alignItems: "center",
    backgroundColor: "#FFFFFF",

    shadowColor: "#000000",
    shadowOffset: {
      width: 0,
      height: 3,
    },
    shadowOpacity: 0.08,
    shadowRadius: 8,
    elevation: 3,
  },

  rightSpacer: {
    width: 48,
    height: 48,
  },

  buttonPressed: {
    backgroundColor: "#F8FAFC",
    transform: [{ scale: 0.96 }],
  },

  statusDot: {
    position: "absolute",
    top: 4,
    right: 4,
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: "#2563EB",
    borderWidth: 1.5,
    borderColor: "#FFFFFF",
  },

  centerSection: {
    alignItems: "center",
  },

  avatar: {
    width: 54,
    height: 54,
    borderRadius: 27,
    backgroundColor: "#F1F5F9",
  },

  namePill: {
    marginTop: 4,
    paddingVertical: 5,
    paddingHorizontal: 16,
    borderRadius: 20,
    backgroundColor: "#FFFFFF",

    shadowColor: "#000000",
    shadowOffset: {
      width: 0,
      height: 2,
    },
    shadowOpacity: 0.07,
    shadowRadius: 6,
    elevation: 2,
  },

  agentName: {
    color: "#1E2022",
    fontSize: 14,
    fontWeight: "700",
  },
});
