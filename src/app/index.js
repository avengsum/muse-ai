import {
  ActivityIndicator,
  Pressable,
  SafeAreaView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import Svg, { Path } from "react-native-svg";
import { useEffect, useState } from "react";
import { router } from "expo-router";

import { useAuth } from "../context/AuthContext";
import { useAppTheme } from "../context/ThemeContext";

function GoogleIcon() {
  return (
    <Svg width={22} height={22} viewBox="0 0 24 24">
      <Path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4" />
      <Path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853" />
      <Path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.06H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.94l2.85-2.22.81-.63z" fill="#FBBC05" />
      <Path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84c.87-2.6 3.3-4.52 6.16-4.52z" fill="#EA4335" />
    </Svg>
  );
}

export default function SignInScreen() {
  const { colors } = useAppTheme();
  const [isSigningIn, setIsSigningIn] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  const {
    session,
    isConfigured,
    authError,
    signInWithGoogle,
  } = useAuth();
  useEffect(() => {
    if (session) {
      router.replace("/(tabs)/chat");
    }
  }, [session]);

  async function handleSignIn() {
    if (isSigningIn) {
      return;
    }

    setIsSigningIn(true);
    setErrorMessage("");

    try {
      await signInWithGoogle();
    } catch (error) {
      setErrorMessage(error.message || "Google sign-in failed");
    } finally {
      setIsSigningIn(false);
    }
  }

  return (
    <SafeAreaView style={[styles.container, { backgroundColor: colors.background }]}>
      <View style={styles.logoSection}>
        <View style={styles.emblemWrap}>
          <View style={styles.glowRing} />
          <View style={styles.logo}>
            <Text style={styles.logoIcon}>✦</Text>
          </View>
        </View>

        <View style={styles.nameRow}>
          <Text style={[styles.name, { color: colors.textStrong }]}>Muse</Text>
          <Text style={[styles.ai, { color: colors.primary }]}> AI</Text>
        </View>
      </View>

      <Pressable
        style={({ pressed }) => [
          styles.signInButton,
          { backgroundColor: colors.surface, borderColor: colors.border },
          pressed && { backgroundColor: colors.pressed },
          (!isConfigured || isSigningIn) && styles.disabledButton,
        ]}
        onPress={handleSignIn}
        disabled={!isConfigured || isSigningIn}
      >
        {isSigningIn ? (
          <ActivityIndicator size="small" color={colors.primary} />
        ) : (
          <>
            <View style={styles.googleIcon}>
              <GoogleIcon />
            </View>

            <Text style={[styles.buttonText, { color: colors.textStrong }]}>Sign in with Google</Text>
          </>
        )}
      </Pressable>

      {!isConfigured && (
        <Text style={[styles.setupText, { color: colors.textSecondary }]}>
          Add your Supabase URL and publishable key to .env
        </Text>
      )}

      {Boolean(errorMessage || authError) && (
        <Text style={[styles.errorText, { color: colors.danger }]}>
          {errorMessage || authError}
        </Text>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: "#FFFFFF",
    justifyContent: "space-between",
    alignItems: "center",
    paddingHorizontal: 24,
    paddingTop: 80,
    paddingBottom: 48,
    width: "100%",
    maxWidth: 400,
    alignSelf: "center",
  },

  logoSection: {
    flex: 1,
    justifyContent: "center",
    alignItems: "center",
  },

  emblemWrap: {
    width: 104,
    height: 104,
    alignItems: "center",
    justifyContent: "center",
    marginBottom: 18,
  },

  logo: {
    width: 84,
    height: 84,
    borderRadius: 42,
    backgroundColor: "#2563EB",
    justifyContent: "center",
    alignItems: "center",
    elevation: 8,
  },

  logoIcon: {
    color: "#FFFFFF",
    fontSize: 42,
  },

  nameRow: {
    flexDirection: "row",
  },

  name: {
    fontSize: 34,
    fontWeight: "800",
    color: "#0F172A",
  },

  ai: {
    fontSize: 34,
    fontWeight: "800",
    color: "#2563EB",
  },

  signInButton: {
    width: "100%",
    height: 54,
    borderWidth: 1,
    borderColor: "#E2E8F0",
    borderRadius: 16,
    flexDirection: "row",
    justifyContent: "center",
    alignItems: "center",
    backgroundColor: "#FFFFFF",
  },

  buttonPressed: {
    backgroundColor: "#F8FAFC",
    transform: [{ scale: 0.99 }],
  },

  glowRing: {
    position: "absolute",
    width: 104,
    height: 104,
    borderRadius: 52,
    backgroundColor: "rgba(37, 99, 235, 0.13)",
  },

  disabledButton: {
    opacity: 0.55,
  },

  googleIcon: {
    marginRight: 12,
  },

  buttonText: {
    color: "#0F172A",
    fontSize: 16,
    fontWeight: "700",
  },

  setupText: {
    marginTop: 12,
    color: "#64748B",
    fontSize: 12,
    textAlign: "center",
  },

  errorText: {
    marginTop: 10,
    color: "#DC2626",
    fontSize: 12,
    textAlign: "center",
  },
});
