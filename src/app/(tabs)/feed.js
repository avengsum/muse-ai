import { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { Ionicons } from "@expo/vector-icons";
import { router } from "expo-router";
import { useConversation } from "../../context/ConversationContext";
import { useAppTheme } from "../../context/ThemeContext";
import * as api from "../../services/api";

const FEED_CACHE_KEY = "muse_dynamic_feed_v1";
const TWENTY_FOUR_HOURS_MS = 24 * 60 * 60 * 1000;

const fallbackBriefs = [
  {
    id: "brief-1",
    source: "Autonomous Web Research",
    category: "Deep Research",
    icon: "globe-outline",
    color: "#2563EB",
    background: "#EFF6FF",
    title: "Scan today's top tech & AI launches on the live web",
    summary:
      "Have Browser Specialist browse Hacker News and Product Hunt to compile today's top 5 launches with links.",
    prompt:
      "Use the browser to check today's top launches on Hacker News and Product Hunt, and summarize the top 5 with key takeaways.",
  },
  {
    id: "brief-2",
    source: "Workspace Sync",
    category: "Productivity",
    icon: "mail-outline",
    color: "#D97706",
    background: "#FFFBEB",
    title: "Triage unread emails & upcoming calendar events",
    summary:
      "Check your connected Gmail and Google Calendar to surface urgent threads and schedule conflicts.",
    prompt:
      "Check my unread Gmail messages and today's Google Calendar events, then give me a prioritized action plan.",
  },
  {
    id: "brief-3",
    source: "Food Specialist",
    category: "Dining",
    icon: "restaurant-outline",
    color: "#059669",
    background: "#ECFDF5",
    title: "Compare top-rated dinner options near you on Swiggy",
    summary:
      "Automatically check open restaurants, compare prices on your favorite dishes, and prepare a cart.",
    prompt:
      "Find the top 3 open restaurants near my saved Swiggy address, compare their best main course options under ₹500, and recommend the best one.",
  },
];

function extractDomain(url) {
  if (!url) return "news.ycombinator.com";
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return "web";
  }
}

async function fetchDynamicDailyBriefs() {
  const dynamicItems = [];

  // 1. Fetch Top 3 Live Hacker News Stories (Zero API Key / Zero LLM Cost)
  try {
    const topRes = await fetch(
      "https://hacker-news.firebaseio.com/v0/topstories.json"
    );
    if (topRes.ok) {
      const ids = await topRes.json();
      const topIds = Array.isArray(ids) ? ids.slice(0, 3) : [];
      const stories = await Promise.all(
        topIds.map(async (id) => {
          const itemRes = await fetch(
            `https://hacker-news.firebaseio.com/v0/item/${id}.json`
          );
          return itemRes.ok ? itemRes.json() : null;
        })
      );

      stories.filter(Boolean).forEach((story, idx) => {
        const domain = extractDomain(story.url);
        const targetUrl =
          story.url || `https://news.ycombinator.com/item?id=${story.id}`;
        dynamicItems.push({
          id: `hn-${story.id || idx}`,
          source: `Hacker News • ${domain}`,
          category: "Trending Tech",
          icon: "flame-outline",
          color: "#EA580C",
          background: "#FFF7ED",
          title: story.title,
          summary: `${story.score || 0} points • ${
            story.descendants || 0
          } comments. Tap to have Cooper read and summarize the full article & key takeaways.`,
          prompt: `Use the browser to read "${story.title}" (${targetUrl}) and give me a concise summary with the key technical takeaways.`,
        });
      });
    }
  } catch {
    // Ignore network errors and continue
  }

  // 2. Fetch Top 2 Daily Tech/AI Articles from DEV.to Public API
  try {
    const devRes = await fetch(
      "https://dev.to/api/articles?top=1&per_page=2"
    );
    if (devRes.ok) {
      const articles = await devRes.json();
      if (Array.isArray(articles)) {
        articles.forEach((article, idx) => {
          dynamicItems.push({
            id: `dev-${article.id || idx}`,
            source: `DEV Community • ${
              article.user?.name || "Developer"
            }`,
            category: article.tag_list?.[0]
              ? `#${article.tag_list[0]}`
              : "Engineering",
            icon: "code-slash-outline",
            color: "#2563EB",
            background: "#EFF6FF",
            title: article.title,
            summary:
              article.description ||
              "Read and extract actionable insights from this trending developer post.",
            prompt: `Use the browser to read "${article.title}" at ${article.url} and summarize the main points and code examples.`,
          });
        });
      }
    }
  } catch {
    // Ignore network errors and continue
  }

  // 3. Append Daily Workspace & Dining Workflows
  const todayName = new Date().toLocaleDateString("en-US", {
    weekday: "long",
  });
  dynamicItems.push(
    {
      id: "daily-workspace",
      source: `${todayName} Workspace Sync`,
      category: "Productivity",
      icon: "mail-outline",
      color: "#D97706",
      background: "#FFFBEB",
      title: `Triage your ${todayName} unread emails & calendar schedule`,
      summary:
        "Check connected Gmail and Google Calendar to surface urgent threads and meeting conflicts.",
      prompt:
        "Check my unread Gmail messages and today's Google Calendar events, then give me a prioritized action plan.",
    },
    {
      id: "daily-food",
      source: "Food Specialist",
      category: "Dining",
      icon: "restaurant-outline",
      color: "#059669",
      background: "#ECFDF5",
      title: "Compare top-rated open restaurants near you on Swiggy",
      summary:
        "Automatically check open restaurants, compare prices on your favorite dishes, and prepare a cart.",
      prompt:
        "Find the top 3 open restaurants near my saved Swiggy address, compare their best main course options under ₹500, and recommend the best one.",
    }
  );

  return dynamicItems.length > 2 ? dynamicItems : fallbackBriefs;
}

export default function FeedScreen() {
  const { agentName = "Cooper" } = useConversation();
  const { colors } = useAppTheme();
  const [notifications, setNotifications] = useState([]);
  const [briefs, setBriefs] = useState(fallbackBriefs);
  const [lastUpdatedText, setLastUpdatedText] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const [loadingBriefs, setLoadingBriefs] = useState(true);

  const loadFeed = useCallback(async (forceRefresh = false) => {
    try {
      // 1. Load at most 5 Recent Agent Activity items
      if (typeof api.getNotifications === "function") {
        const items = await api.getNotifications();
        if (Array.isArray(items)) {
          setNotifications(items.slice(0, 5));
        }
      }

      // 2. Check 24-hour cache for dynamic daily briefings
      const now = Date.now();
      if (!forceRefresh) {
        try {
          const cachedRaw = await AsyncStorage.getItem(FEED_CACHE_KEY);
          if (cachedRaw) {
            const cached = JSON.parse(cachedRaw);
            if (
              cached &&
              cached.timestamp &&
              now - cached.timestamp < TWENTY_FOUR_HOURS_MS &&
              Array.isArray(cached.items) &&
              cached.items.length > 0
            ) {
              setBriefs(cached.items);
              setLastUpdatedText(
                new Date(cached.timestamp).toLocaleDateString(undefined, {
                  month: "short",
                  day: "numeric",
                })
              );
              setLoadingBriefs(false);
              return;
            }
          }
        } catch {
          // Cache read failed; fetch fresh below
        }
      }

      const freshBriefs = await fetchDynamicDailyBriefs();
      setBriefs(freshBriefs);
      setLastUpdatedText("Today");

      try {
        await AsyncStorage.setItem(
          FEED_CACHE_KEY,
          JSON.stringify({
            timestamp: now,
            items: freshBriefs,
          })
        );
      } catch {
        // Ignore storage write error
      }
    } catch {
      // Ignore errors
    } finally {
      setLoadingBriefs(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    const initialLoad = setTimeout(() => loadFeed(false), 0);
    return () => clearTimeout(initialLoad);
  }, [loadFeed]);

  function launchPrompt(promptText) {
    router.navigate({
      pathname: "/(tabs)/chat",
      params: { prefill: promptText },
    });
  }

  return (
    <ScrollView
      style={[styles.container, { backgroundColor: colors.background }]}
      contentContainerStyle={styles.content}
      showsVerticalScrollIndicator={false}
      refreshControl={
        <RefreshControl
          refreshing={refreshing}
          tintColor={colors.primary}
          colors={[colors.primary]}
          onRefresh={() => {
            setRefreshing(true);
            loadFeed(true);
          }}
        />
      }
    >
      <View style={styles.titleWrapper}>
        <Text style={[styles.title, { color: colors.text }]}>{agentName}&apos;s Feed</Text>
        <Text style={[styles.subtitle, { color: colors.textSecondary }]}>
          Live agent updates, daily trending tech, and one-tap workflows.
        </Text>
      </View>

      {notifications.length > 0 && (
        <View style={styles.sectionBlock}>
          <Text style={[styles.sectionHeader, { color: colors.textMuted }]}>
            RECENT AGENT ACTIVITY ({notifications.length}/5)
          </Text>
          {notifications.slice(0, 5).map((note) => (
            <Pressable
              key={String(note.id)}
              style={[
                styles.activityCard,
                { backgroundColor: colors.surfaceSecondary, borderColor: colors.border },
              ]}
              onPress={() =>
                launchPrompt(
                  `Let's follow up on this update: "${note.title} - ${note.body}"`
                )
              }
            >
              <View style={[styles.featuredIcon, { backgroundColor: colors.primarySoft }]}>
                <Ionicons
                  name={
                    note.kind === "error"
                      ? "alert-circle-outline"
                      : "checkmark-done-circle-outline"
                  }
                  size={22}
                  color={note.kind === "error" ? colors.danger : colors.primary}
                />
              </View>
              <View style={styles.featuredText}>
                <Text style={[styles.featuredTitle, { color: colors.text }]}>{note.title}</Text>
                <Text style={[styles.activityBody, { color: colors.textSecondary }]} numberOfLines={3}>
                  {note.body}
                </Text>
              </View>
            </Pressable>
          ))}
        </View>
      )}

      <View style={styles.briefsHeaderRow}>
        <Text style={[styles.sectionHeader, { color: colors.textMuted }]}>
          DAILY BRIEFINGS {lastUpdatedText ? `• ${lastUpdatedText}` : ""}
        </Text>
        {loadingBriefs && (
          <ActivityIndicator
            size="small"
            color={colors.primary}
            style={{ marginRight: 20 }}
          />
        )}
      </View>

      {briefs.map((item, index) => (
        <View key={item.id}>
          <Pressable
            style={styles.newsRow}
            onPress={() => launchPrompt(item.prompt)}
          >
            <View style={[styles.icon, { backgroundColor: item.background }]}>
              <Ionicons name={item.icon} size={20} color={item.color} />
            </View>
            <View style={styles.newsContent}>
              <View style={styles.metaRow}>
                <Text style={[styles.source, { color: colors.textSecondary }]}>{item.source}</Text>
              </View>
              <Text style={[styles.newsTitle, { color: colors.text }]}>{item.title}</Text>
              <Text style={[styles.summary, { color: colors.textSecondary }]}>{item.summary}</Text>
              <View style={styles.footerRow}>
                <View
                  style={[styles.category, { backgroundColor: item.background }]}
                >
                  <Text style={[styles.categoryText, { color: item.color }]}>
                    {item.category}
                  </Text>
                </View>
                <Text style={[styles.runAction, { color: colors.primary }]}>Ask {agentName} →</Text>
              </View>
            </View>
          </Pressable>
          {index < briefs.length - 1 ? (
            <View style={[styles.divider, { backgroundColor: colors.divider }]} />
          ) : null}
        </View>
      ))}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#FFFFFF" },
  content: { paddingBottom: 24 },
  titleWrapper: { paddingHorizontal: 20, paddingTop: 12, paddingBottom: 14 },
  title: {
    color: "#1E2022",
    fontSize: 28,
    fontWeight: "700",
    letterSpacing: -0.5,
  },
  subtitle: {
    marginTop: 4,
    color: "#64748B",
    fontSize: 14,
    lineHeight: 20,
    fontWeight: "500",
  },
  sectionBlock: { marginBottom: 12 },
  briefsHeaderRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  sectionHeader: {
    paddingHorizontal: 20,
    marginTop: 6,
    marginBottom: 8,
    color: "#94A3B8",
    fontSize: 11,
    fontWeight: "800",
    letterSpacing: 0.6,
  },
  activityCard: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: 12,
    marginHorizontal: 20,
    marginBottom: 8,
    padding: 14,
    borderWidth: 1,
    borderColor: "#E2E8F0",
    borderRadius: 12,
    backgroundColor: "#F8FAFC",
  },
  featuredIcon: {
    width: 40,
    height: 40,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 10,
    backgroundColor: "#EFF6FF",
  },
  featuredText: { flex: 1 },
  featuredTitle: {
    color: "#1E2022",
    fontSize: 14.5,
    lineHeight: 20,
    fontWeight: "700",
  },
  activityBody: {
    marginTop: 4,
    color: "#64748B",
    fontSize: 13,
    lineHeight: 18,
  },
  newsRow: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: 14,
    paddingHorizontal: 20,
    paddingVertical: 18,
  },
  icon: {
    width: 44,
    height: 44,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 12,
  },
  newsContent: { flex: 1 },
  metaRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    marginBottom: 5,
  },
  source: { color: "#64748B", fontSize: 12, fontWeight: "800" },
  newsTitle: {
    color: "#1E2022",
    fontSize: 16,
    lineHeight: 22,
    fontWeight: "700",
    letterSpacing: -0.2,
  },
  summary: { marginTop: 6, color: "#64748B", fontSize: 14, lineHeight: 20 },
  footerRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 12,
    marginTop: 11,
  },
  category: { paddingHorizontal: 9, paddingVertical: 5, borderRadius: 8 },
  categoryText: { fontSize: 11, fontWeight: "800" },
  runAction: { color: "#2563EB", fontSize: 12.5, fontWeight: "700" },
  divider: { height: 1, marginHorizontal: 20, backgroundColor: "#F1F5F9" },
});
