import {
  Modal,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useConversation } from "../context/ConversationContext";
import { useAppTheme } from "../context/ThemeContext";

export default function MoreMenuModal({
  visible,
  onClose,
  onEditAgent,
  onDelete,
}) {
  const { agentName = "Cooper" } = useConversation();
  const { colors } = useAppTheme();

  const menuItems = [
    {
      id: "edit",
      title: `Edit ${agentName}`,
      icon: "person-circle-outline",
    },
    {
      id: "delete",
      title: "Delete chat",
      icon: "trash-outline",
      destructive: true,
    },
  ];

  function handlePress(item) {
    onClose();

    if (item.id === "edit") {
      onEditAgent();
    } else if (item.id === "delete") {
      onDelete?.();
    }
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
            styles.menu,
            {
              backgroundColor: colors.elevated,
              borderColor: colors.border,
              shadowColor: colors.shadow,
            },
          ]}
        >
          {menuItems.map((item) => (
            <Pressable
              key={item.id}
              style={({ pressed }) => [
                styles.menuItem,
                pressed && { backgroundColor: colors.pressed },
              ]}
              onPress={() => handlePress(item)}
            >
              <Ionicons
                name={item.icon}
                size={20}
                color={item.destructive ? colors.danger : colors.text}
              />

              <Text
                style={[
                  styles.menuText,
                  { color: item.destructive ? colors.danger : colors.text },
                ]}
              >
                {item.title}
              </Text>
            </Pressable>
          ))}
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  overlay: {
    flex: 1,
    alignItems: "flex-end",
    paddingTop: 78,
    paddingRight: 20,
    backgroundColor: "rgba(15, 23, 42, 0.18)",
  },

  menu: {
    width: 230,
    paddingVertical: 7,
    borderWidth: 1,
    borderColor: "#E2E8F0",
    borderRadius: 16,
    backgroundColor: "#FFFFFF",

    shadowColor: "#000000",
    shadowOffset: {
      width: 0,
      height: 8,
    },
    shadowOpacity: 0.15,
    shadowRadius: 18,
    elevation: 8,
  },

  menuItem: {
    minHeight: 50,
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: 15,
  },

  pressed: {
    backgroundColor: "#F8FAFC",
  },

  menuText: {
    marginLeft: 12,
    color: "#1E2022",
    fontSize: 14,
    fontWeight: "600",
  },

  destructiveText: {
    color: "#EF4444",
  },
});
