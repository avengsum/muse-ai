import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";
import AsyncStorage from "@react-native-async-storage/async-storage";
import {
  getSettings,
  saveSettings,
} from "../services/api";

const ACTIVE_CONVERSATION_STORAGE_KEY = "muse_active_conversation_id";
const ConversationContext = createContext(null);

export function ConversationProvider({ children }) {
  const [conversationId, setConversationIdState] = useState(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [messageRefreshKey, setMessageRefreshKey] = useState(0);
  const [agentName, setAgentName] = useState("Cooper");
  const [accentColor, setAccentColor] = useState("#2563EB");
  const [notificationsEnabled, setNotificationsEnabled] = useState(true);

  useEffect(() => {
    let active = true;

    // Restore last active conversation across OAuth redirects / reloads
    AsyncStorage.getItem(ACTIVE_CONVERSATION_STORAGE_KEY)
      .then((savedId) => {
        if (active && savedId) {
          setConversationIdState((current) => current || savedId);
        }
      })
      .catch(() => {});

    getSettings()
      .then((settings) => {
        if (active) {
          setAgentName(settings.agent_name);
          setAccentColor(settings.accent_color);
          setNotificationsEnabled(settings.notifications_enabled);
        }
      })
      .catch(() => {});

    return () => {
      active = false;
    };
  }, []);

  const setConversationId = useCallback((nextId) => {
    setConversationIdState(nextId);
    if (nextId) {
      AsyncStorage.setItem(ACTIVE_CONVERSATION_STORAGE_KEY, String(nextId)).catch(
        () => {}
      );
    } else {
      AsyncStorage.removeItem(ACTIVE_CONVERSATION_STORAGE_KEY).catch(() => {});
    }
  }, []);

  function refreshConversations() {
    setRefreshKey((currentKey) => currentKey + 1);
  }

  function refreshMessages() {
    setMessageRefreshKey((currentKey) => currentKey + 1);
  }

  async function updateSettings(changes) {
    const settings = await saveSettings({
      agent_name: changes.agent_name ?? agentName,
      accent_color: changes.accent_color ?? accentColor,
      notifications_enabled:
        changes.notifications_enabled ?? notificationsEnabled,
    });
    setAgentName(settings.agent_name);
    setAccentColor(settings.accent_color);
    setNotificationsEnabled(settings.notifications_enabled);
    return settings;
  }

  return (
    <ConversationContext.Provider
      value={{
        conversationId,
        setConversationId,
        refreshKey,
        refreshConversations,
        messageRefreshKey,
        refreshMessages,
        agentName,
        accentColor,
        notificationsEnabled,
        updateSettings,
      }}
    >
      {children}
    </ConversationContext.Provider>
  );
}

export function useConversation() {
  const context = useContext(ConversationContext);

  if (!context) {
    throw new Error(
      "useConversation must be used inside ConversationProvider"
    );
  }

  return context;
}