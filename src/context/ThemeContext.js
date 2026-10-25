import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { Appearance, useColorScheme } from "react-native";
import AsyncStorage from "@react-native-async-storage/async-storage";

const THEME_STORAGE_KEY = "muse_theme_preference";
const VALID_PREFERENCES = new Set(["system", "light", "dark"]);

const LIGHT_COLORS = Object.freeze({
  background: "#FFFFFF",
  surface: "#FFFFFF",
  surfaceSecondary: "#F8FAFC",
  surfaceTertiary: "#F1F5F9",
  elevated: "#FFFFFF",
  text: "#1E2022",
  textStrong: "#0F172A",
  textSecondary: "#64748B",
  textMuted: "#94A3B8",
  border: "#E2E8F0",
  divider: "#F1F5F9",
  pressed: "#F8FAFC",
  input: "#F3F4F6",
  primary: "#2563EB",
  primarySoft: "#EFF6FF",
  agentBubble: "#EEF0F2",
  userBubble: "#E8C4B4",
  userText: "#3B2318",
  danger: "#DC2626",
  dangerSoft: "#FEF2F2",
  success: "#15803D",
  overlay: "rgba(15, 23, 42, 0.45)",
  shadow: "#000000",
  skeleton: "#E5E7EB",
  skeletonLine: "#D1D5DB",
});

const DARK_COLORS = Object.freeze({
  background: "#090D13",
  surface: "#111722",
  surfaceSecondary: "#161E2B",
  surfaceTertiary: "#1D2735",
  elevated: "#182130",
  text: "#F1F5F9",
  textStrong: "#F8FAFC",
  textSecondary: "#B4C0D0",
  textMuted: "#7F8CA0",
  border: "#2A3647",
  divider: "#202B3A",
  pressed: "#202A38",
  input: "#182130",
  primary: "#60A5FA",
  primarySoft: "#172A46",
  agentBubble: "#182130",
  userBubble: "#49352E",
  userText: "#FCEDE6",
  danger: "#F87171",
  dangerSoft: "#3A1D24",
  success: "#4ADE80",
  overlay: "rgba(0, 0, 0, 0.68)",
  shadow: "#000000",
  skeleton: "#273244",
  skeletonLine: "#344155",
});

const ThemeContext = createContext(null);

export function ThemeProvider({ children }) {
  const systemColorScheme = useColorScheme();
  const [themePreference, setThemePreferenceState] = useState("system");
  const [isThemeReady, setIsThemeReady] = useState(false);

  useEffect(() => {
    let active = true;

    AsyncStorage.getItem(THEME_STORAGE_KEY)
      .then((savedPreference) => {
        if (active && VALID_PREFERENCES.has(savedPreference)) {
          setThemePreferenceState(savedPreference);
        }
      })
      .catch(() => {
        // Keep the system preference when local storage is unavailable.
      })
      .finally(() => {
        if (active) {
          setIsThemeReady(true);
        }
      });

    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    try {
      Appearance.setColorScheme(
        themePreference === "system" ? "auto" : themePreference
      );
    } catch {
      // The React tree still uses the selected theme on unsupported platforms.
    }
  }, [themePreference]);

  const setThemePreference = useCallback(async (nextPreference) => {
    if (!VALID_PREFERENCES.has(nextPreference)) {
      return;
    }

    setThemePreferenceState(nextPreference);
    try {
      await AsyncStorage.setItem(THEME_STORAGE_KEY, nextPreference);
    } catch {
      // The selected theme remains active for the current app session.
    }
  }, []);

  const resolvedTheme =
    themePreference === "system"
      ? systemColorScheme === "dark"
        ? "dark"
        : "light"
      : themePreference;
  const isDark = resolvedTheme === "dark";
  const colors = isDark ? DARK_COLORS : LIGHT_COLORS;

  const value = useMemo(
    () => ({
      colors,
      isDark,
      isThemeReady,
      resolvedTheme,
      themePreference,
      setThemePreference,
    }),
    [
      colors,
      isDark,
      isThemeReady,
      resolvedTheme,
      themePreference,
      setThemePreference,
    ]
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useAppTheme() {
  const context = useContext(ThemeContext);

  if (!context) {
    throw new Error("useAppTheme must be used inside ThemeProvider");
  }

  return context;
}
