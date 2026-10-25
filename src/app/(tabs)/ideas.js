import { useEffect, useState } from "react";
import {
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { router } from "expo-router";
import { useConversation } from "../../context/ConversationContext";
import { useAppTheme } from "../../context/ThemeContext";
import { getDailyIdeas } from "../../services/api";

const FALLBACK_IDEAS = [
  {
    id: "1",
    icon: "🏆",
    title: "Build your AI competition entry",
    description:
      "Research the rules and create your submission, demo script, and deadline checklist.",
    prompt:
      "Help me research an AI competition and create my submission, demo script, and deadline checklist.",
  },
  {
    id: "2",
    icon: "🗂️",
    title: "Create a money-making apps leaderboard",
    description:
      "Track app names, links, categories, and reported earnings in one place.",
    prompt:
      "Help me create a leaderboard of money-making apps with names, links, categories, and reported earnings.",
  },
  {
    id: "3",
    icon: "📹",
    title: "Turn your app build into a Shorts series",
    description:
      "Create episode ideas, video hooks, and shoot-ready scripts.",
    prompt:
      "Turn my app-building journey into a Shorts series with episode ideas, hooks, and shoot-ready scripts.",
  },
  {
    id: "4",
    icon: "🚀",
    title: "Build your launch post and assets",
    description:
      "Generate launch copy, headlines, screenshots, and community responses.",
    prompt:
      "Help me build a launch post with copy, headlines, screenshot ideas, and community responses.",
  },
];

export default function IdeasScreen() {
  const { agentName = "Cooper" } = useConversation();
  const { colors } = useAppTheme();
  const [ideas, setIdeas] = useState(FALLBACK_IDEAS);

  useEffect(() => {
    let isMounted = true;

    async function loadDailyIdeas() {
      try {
        const dailyIdeas = await getDailyIdeas();
        const hasFourValidIdeas =
          Array.isArray(dailyIdeas) &&
          dailyIdeas.length === 4 &&
          dailyIdeas.every(
            (idea) =>
              idea &&
              typeof idea.id === "string" &&
              typeof idea.title === "string" &&
              typeof idea.description === "string" &&
              typeof idea.prompt === "string"
          );

        if (isMounted && hasFourValidIdeas) {
          setIdeas(dailyIdeas);
        }
      } catch {
        // Keep the built-in ideas when the API is unavailable.
      }
    }

    loadDailyIdeas();

    return () => {
      isMounted = false;
    };
  }, []);

  function handleIdeaPress(idea) {
    router.navigate({
      pathname: "/(tabs)/chat",
      params: {
        prefill: idea.prompt,
      },
    });
  }

  return (
    <ScrollView
      style={[styles.container, { backgroundColor: colors.background }]}
      contentContainerStyle={styles.content}
      showsVerticalScrollIndicator={false}
    >
      <Text style={[styles.title, { color: colors.text }]}>Ideas</Text>
      <Text style={[styles.subtitle, { color: colors.textSecondary }]}>
        Ready-made things {agentName} can help you complete.
      </Text>

      {ideas.map((idea) => (
        <Pressable
          key={idea.id}
          style={({ pressed }) => [
            styles.ideaRow,
            { borderBottomColor: colors.divider },
            pressed && styles.pressed,
          ]}
          onPress={() => handleIdeaPress(idea)}
        >
          <View style={[styles.iconContainer, { backgroundColor: colors.surfaceSecondary }]}>
            <Text style={styles.emoji}>{idea.icon}</Text>
          </View>

          <View style={styles.textContainer}>
            <Text style={[styles.ideaTitle, { color: colors.text }]}>{idea.title}</Text>
            <Text style={[styles.description, { color: colors.textSecondary }]}>
              {idea.description}
            </Text>

            <View style={styles.tryRow}>
              <Text style={[styles.tryText, { color: colors.primary }]}>Try this idea</Text>
              <Ionicons
                name="arrow-forward"
                size={15}
                color={colors.primary}
              />
            </View>
          </View>
        </Pressable>
      ))}
    </ScrollView>
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
    paddingBottom: 30,
  },

  title: {
    color: "#1E2022",
    fontSize: 28,
    fontWeight: "700",
  },

  subtitle: {
    marginTop: 4,
    marginBottom: 12,
    color: "#64748B",
    fontSize: 14,
  },

  ideaRow: {
    flexDirection: "row",
    paddingVertical: 18,
    borderBottomWidth: 1,
    borderBottomColor: "#F1F5F9",
  },

  pressed: {
    opacity: 0.7,
  },

  iconContainer: {
    width: 48,
    height: 48,
    marginRight: 14,
    borderRadius: 14,
    justifyContent: "center",
    alignItems: "center",
    backgroundColor: "#F8FAFC",
  },

  emoji: {
    fontSize: 25,
  },

  textContainer: {
    flex: 1,
  },

  ideaTitle: {
    color: "#1E2022",
    fontSize: 16,
    lineHeight: 22,
    fontWeight: "700",
  },

  description: {
    marginTop: 5,
    color: "#64748B",
    fontSize: 14,
    lineHeight: 20,
  },

  tryRow: {
    flexDirection: "row",
    alignItems: "center",
    marginTop: 9,
  },

  tryText: {
    marginRight: 4,
    color: "#2563EB",
    fontSize: 12,
    fontWeight: "700",
  },
});
