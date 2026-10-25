import { Animated, Easing, StyleSheet, View } from "react-native";
import { useEffect, useState } from "react";
import { useAppTheme } from "../context/ThemeContext";

const PLACEHOLDERS = [
  { align: "left", width: "72%", lines: ["86%", "62%"] },
  { align: "right", width: "54%", lines: ["78%"] },
  { align: "left", width: "82%", lines: ["90%", "74%", "48%"] },
  { align: "right", width: "46%", lines: ["70%"] },
];

export default function ConversationSkeleton() {
  const { colors } = useAppTheme();
  const [opacity] = useState(() => new Animated.Value(0.46));

  useEffect(() => {
    const pulse = Animated.loop(
      Animated.sequence([
        Animated.timing(opacity, {
          toValue: 1,
          duration: 720,
          easing: Easing.inOut(Easing.ease),
          useNativeDriver: true,
        }),
        Animated.timing(opacity, {
          toValue: 0.46,
          duration: 720,
          easing: Easing.inOut(Easing.ease),
          useNativeDriver: true,
        }),
      ])
    );

    pulse.start();
    return () => pulse.stop();
  }, [opacity]);

  return (
    <Animated.View
      accessibilityLabel="Loading conversation"
      accessibilityRole="progressbar"
      style={[styles.container, { opacity }]}
    >
      <View
        style={[styles.datePlaceholder, { backgroundColor: colors.skeleton }]}
      />

      {PLACEHOLDERS.map((placeholder, index) => (
        <View
          key={`${placeholder.align}-${index}`}
          style={[
            styles.row,
            placeholder.align === "right" ? styles.rightRow : styles.leftRow,
          ]}
        >
          <View
            style={[
              styles.bubble,
              placeholder.align === "right"
                ? styles.userBubble
                : styles.agentBubble,
              {
                width: placeholder.width,
                backgroundColor:
                  placeholder.align === "right"
                    ? colors.userBubble
                    : colors.agentBubble,
              },
            ]}
          >
            {placeholder.lines.map((width, lineIndex) => (
              <View
                key={`${width}-${lineIndex}`}
                style={[
                  styles.line,
                  { width, backgroundColor: colors.skeletonLine },
                ]}
              />
            ))}
          </View>
        </View>
      ))}
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    paddingTop: 14,
  },
  datePlaceholder: {
    alignSelf: "center",
    width: 58,
    height: 22,
    marginBottom: 20,
    borderRadius: 11,
    backgroundColor: "#E5E7EB",
  },
  row: {
    width: "100%",
    marginBottom: 14,
  },
  leftRow: {
    alignItems: "flex-start",
  },
  rightRow: {
    alignItems: "flex-end",
  },
  bubble: {
    gap: 9,
    paddingHorizontal: 16,
    paddingVertical: 15,
    borderRadius: 20,
  },
  agentBubble: {
    borderBottomLeftRadius: 6,
    backgroundColor: "#ECEFF2",
  },
  userBubble: {
    borderBottomRightRadius: 6,
    backgroundColor: "#E8D4CB",
  },
  line: {
    height: 10,
    borderRadius: 5,
    backgroundColor: "#D1D5DB",
  },
});
