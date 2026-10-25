import {
  createContext,
  useContext,
  useEffect,
  useState,
} from "react";
import { AppState, Platform } from "react-native";
import AsyncStorage from "@react-native-async-storage/async-storage";
import * as Linking from "expo-linking";
import * as WebBrowser from "expo-web-browser";

import {
  isSupabaseConfigured,
  supabase,
} from "../lib/supabase";


WebBrowser.maybeCompleteAuthSession();


const AuthContext = createContext(null);


function getParameter(parsedUrl, key) {
  const queryParameters = parsedUrl.searchParams;
  const hashParameters = new URLSearchParams(
    parsedUrl.hash.replace(/^#/, "")
  );

  return (
    queryParameters.get(key) ||
    hashParameters.get(key) ||
    null
  );
}


async function createSessionFromUrl(url) {
  const parsedUrl = new URL(url);
  const errorDescription = getParameter(
    parsedUrl,
    "error_description"
  );

  if (errorDescription) {
    throw new Error(
      decodeURIComponent(errorDescription.replace(/\+/g, " "))
    );
  }

  const code = getParameter(parsedUrl, "code");

  if (code) {
    const flowId = getParameter(parsedUrl, "sb_flow_id");
    const { data, error } =
      await supabase.auth.exchangeCodeForSession(
        code,
        flowId ? { flowId } : undefined
      );

    if (error) {
      throw error;
    }

    return data.session;
  }

  const accessToken = getParameter(
    parsedUrl,
    "access_token"
  );
  const refreshToken = getParameter(
    parsedUrl,
    "refresh_token"
  );

  if (!accessToken || !refreshToken) {
    return null;
  }

  const { data, error } = await supabase.auth.setSession({
    access_token: accessToken,
    refresh_token: refreshToken,
  });

  if (error) {
    throw error;
  }

  return data.session;
}


function getRedirectUrl() {
  if (Platform.OS === "web") {
    return `${window.location.origin}/`;
  }

  return Linking.createURL("/");
}


export function AuthProvider({ children }) {
  const [session, setSession] = useState(null);
  const [isLoading, setIsLoading] = useState(Boolean(supabase));
  const [authError, setAuthError] = useState("");

  useEffect(() => {
    if (!supabase) {
      return undefined;
    }

    let isMounted = true;

    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange(
      (_event, nextSession) => {
        if (isMounted) {
          setSession(nextSession);
        }
      }
    );

    async function initializeAuth() {
      try {
        if (Platform.OS === "web") {
          await createSessionFromUrl(window.location.href);

          if (
            window.location.search ||
            window.location.hash
          ) {
            window.history.replaceState(
              {},
              document.title,
              window.location.pathname
            );
          }
        } else {
          const initialUrl = await Linking.getInitialURL();
          if (
            initialUrl &&
            (initialUrl.includes("code=") || initialUrl.includes("access_token="))
          ) {
            await createSessionFromUrl(initialUrl);
          }
        }

        const { data, error } =
          await supabase.auth.getSession();

        if (error) {
          throw error;
        }

        if (isMounted) {
          setSession(data.session);
          setAuthError("");
        }
      } catch (error) {
        if (isMounted) {
          setSession(null);
          setAuthError(
            error.message || "Google sign-in failed"
          );
        }
      } finally {
        if (isMounted) {
          setIsLoading(false);
        }
      }
    }

    initializeAuth();

    const urlSubscription =
      Platform.OS !== "web"
        ? Linking.addEventListener("url", async ({ url }) => {
            if (
              url &&
              (url.includes("code=") || url.includes("access_token="))
            ) {
              try {
                const nextSession = await createSessionFromUrl(url);
                if (isMounted && nextSession) {
                  setSession(nextSession);
                  setAuthError("");
                }
              } catch (err) {
                if (isMounted) {
                  setAuthError(err.message || "Google sign-in failed");
                }
              }
            }
          })
        : null;
    

    

    initializeAuth();

    const appStateSubscription =
      Platform.OS !== "web"
        ? AppState.addEventListener("change", (state) => {
            if (state === "active") {
              supabase.auth.startAutoRefresh();
            } else {
              supabase.auth.stopAutoRefresh();
            }
          })
        : null;

    return () => {
      isMounted = false;
      subscription.unsubscribe();
      appStateSubscription?.remove();
      urlSubscription?.remove();
    };
  }, []);

  async function signInWithGoogle() {
    if (!supabase) {
      throw new Error(
        "Add your Supabase project values to .env first"
      );
    }

    setAuthError("");

    const redirectTo = getRedirectUrl();

    const { data, error } =
      await supabase.auth.signInWithOAuth({
        provider: "google",
        options: {
          redirectTo,
          skipBrowserRedirect: Platform.OS !== "web",
        },
      });

    if (error) {
      setAuthError(error.message);
      throw error;
    }

    if (Platform.OS === "web") {
      return;
    }

    const result = await WebBrowser.openAuthSessionAsync(
      data.url,
      redirectTo
    );

    if (result.type === "success") {
      const nextSession = await createSessionFromUrl(
        result.url
      );

      if (nextSession) {
        setSession(nextSession);
      }
    }
  }

  async function signOut() {
    setAuthError("");
    setSession(null);

    try {
      await AsyncStorage.removeItem("muse_active_conversation_id");
    } catch {
      // Ignore storage error
    }

    if (supabase) {
      try {
        await supabase.auth.signOut({ scope: "local" });
      } catch {
        // Ignore network errors during sign-out
      }
    }

  }

  return (
    <AuthContext.Provider
      value={{
        session,
        user: session?.user || null,
        isLoading,
        isConfigured: isSupabaseConfigured,
        authError,
        signInWithGoogle,
        signOut,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}


export function useAuth() {
  const context = useContext(AuthContext);

  if (!context) {
    throw new Error(
      "useAuth must be used inside AuthProvider"
    );
  }

  return context;
}
