import { useEffect, useRef, useState } from "react";
import {
  Dimensions,
  Keyboard,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useConversation } from "../context/ConversationContext";
import { useAppTheme } from "../context/ThemeContext";

let ExpoSpeechRecognitionModule = null;
let rawUseSpeechRecognitionEvent = null;

try {
  const speechModule = require("expo-speech-recognition");
  ExpoSpeechRecognitionModule = speechModule.ExpoSpeechRecognitionModule;
  rawUseSpeechRecognitionEvent = speechModule.useSpeechRecognitionEvent;
} catch {
  // Native module is unavailable in standard Expo Go
}

function useSafeSpeechRecognitionEvent(eventName, callback) {
  if (
    ExpoSpeechRecognitionModule &&
    typeof rawUseSpeechRecognitionEvent === "function"
  ) {
    // eslint-disable-next-line react-hooks/rules-of-hooks
    rawUseSpeechRecognitionEvent(eventName, callback);
  }
}

const VOICE_ERROR_MESSAGES = {
  "audio-capture": "The microphone is unavailable. Check your device settings.",
  "language-not-supported": "Speech recognition does not support this language.",
  network: "Voice input needs a network connection on this device.",
  "not-allowed": "Microphone access is required for voice input.",
  "service-not-allowed": "Speech recognition is unavailable on this device.",
};

function joinTranscript(prefix, transcript) {
  return [prefix.trim(), transcript.trim()].filter(Boolean).join(" ");
}

export default function ChatInput({
  value,
  onChangeText,
  onSend,
  onStop,
  isSending,
  disabled,
  agentName: propAgentName,
}) {
  const { agentName: contextAgentName = "Cooper" } = useConversation();
  const { colors } = useAppTheme();
  const displayAgentName = propAgentName || contextAgentName || "Cooper";
  const [isListening, setIsListening] = useState(false);
  const [voiceError, setVoiceError] = useState("");
  const [keyboardOffset, setKeyboardOffset] = useState(0);
  const transcriptPrefixRef = useRef("");
  const wrapperRef = useRef(null);
  const offsetRef = useRef(0);
  const hasText = value.trim().length > 0;

  useSafeSpeechRecognitionEvent("start", () => {
    setIsListening(true);
    setVoiceError("");
  });

  useSafeSpeechRecognitionEvent("result", (event) => {
    const transcript = event.results?.[0]?.transcript || "";

    if (transcript) {
      onChangeText(joinTranscript(transcriptPrefixRef.current, transcript));
    }
  });

  useSafeSpeechRecognitionEvent("end", () => {
    setIsListening(false);
  });

  useSafeSpeechRecognitionEvent("error", (event) => {
    setIsListening(false);

    if (["aborted", "no-speech", "speech-timeout"].includes(event.error)) {
      return;
    }

    setVoiceError(
      VOICE_ERROR_MESSAGES[event.error] ||
        event.message ||
        "Voice input could not start. Please try again."
    );
  });

  useEffect(() => {
    return () => {
      try {
        ExpoSpeechRecognitionModule?.abort?.();
      } catch {
        // Ignore cleanup errors when native module is absent
      }
    };
  }, []);

  useEffect(() => {
    if (Platform.OS !== "android") {
      return undefined;
    }

    let timer = null;

    const showSub = Keyboard.addListener("keyboardDidShow", (event) => {
      const kbHeight = event.endCoordinates?.height || 0;
      const screenHeight = Dimensions.get("window").height;
      const rawScreenY = event.endCoordinates?.screenY || screenHeight;
      const kbTop = Math.min(rawScreenY, screenHeight - kbHeight);

      timer = setTimeout(() => {
        if (
          wrapperRef.current &&
          typeof wrapperRef.current.measureInWindow === "function"
        ) {
          wrapperRef.current.measureInWindow((_x, y, _width, height) => {
            if (!height) {
              offsetRef.current = 140;
              setKeyboardOffset(140);
              return;
            }
            const naturalBottom = y + height + offsetRef.current;
            const overlap = Math.max(0, naturalBottom - kbTop);
            const nextOffset = overlap > 0 ? overlap + 12 : 0;
            offsetRef.current = nextOffset;
            setKeyboardOffset(nextOffset);
          });
        } else {
          offsetRef.current = 140;
          setKeyboardOffset(140);
        }
      }, 40);
    });

    const hideSub = Keyboard.addListener("keyboardDidHide", () => {
      if (timer) {
        clearTimeout(timer);
      }
      offsetRef.current = 0;
      setKeyboardOffset(0);
    });

    return () => {
      if (timer) {
        clearTimeout(timer);
      }
      showSub.remove();
      hideSub.remove();
    };
  }, []);

  async function startListening() {
    if (disabled || isSending || isListening) {
      return;
    }

    setVoiceError("");

    if (
      !ExpoSpeechRecognitionModule ||
      typeof ExpoSpeechRecognitionModule.isRecognitionAvailable !== "function" ||
      !ExpoSpeechRecognitionModule.isRecognitionAvailable()
    ) {
      setVoiceError(
        "Voice input requires a native development build (not supported in Expo Go)."
      );
      return;
    }

    try {
      const permission =
        await ExpoSpeechRecognitionModule.requestPermissionsAsync();

      if (!permission.granted) {
        setVoiceError("Microphone access is required for voice input.");
        return;
      }

      transcriptPrefixRef.current = value.trim();
      ExpoSpeechRecognitionModule.start({
        lang: "en-IN",
        interimResults: true,
        continuous: false,
        maxAlternatives: 1,
        iosTaskHint: "dictation",
      });
    } catch (error) {
      setIsListening(false);
      setVoiceError(
        error?.message || "Voice input could not start. Please try again."
      );
    }
  }

  function stopListening() {
    try {
      ExpoSpeechRecognitionModule?.stop?.();
    } catch {
      setIsListening(false);
    }
  }

  return (
    <View
      ref={wrapperRef}
      style={[
        styles.wrapper,
        {
          backgroundColor: colors.background,
          marginBottom: keyboardOffset,
        },
      ]}
    >
      <View
        style={[
          styles.inputBar,
          { backgroundColor: colors.input, borderColor: colors.border },
          isListening && [
            styles.listeningInputBar,
            { backgroundColor: colors.dangerSoft },
          ],
        ]}
      >
        <TextInput
          style={[styles.input, { color: colors.text }]}
          value={value}
          onChangeText={onChangeText}
          placeholder={
            isSending
              ? `${displayAgentName} is working...`
              : isListening
                ? "Listening..."
                : `Ask ${displayAgentName} anything...`
          }
          placeholderTextColor={colors.textMuted}
          returnKeyType="send"
          onSubmitEditing={onSend}
          editable={!disabled && !isSending && !isListening}
        />

        {isSending ? (
          <Pressable
            style={({ pressed }) => [
              styles.circleButton,
              styles.stopButton,
              { backgroundColor: colors.textStrong },
              pressed && styles.stopButtonPressed,
            ]}
            onPress={onStop}
          >
            <Ionicons name="square" size={14} color="#FFFFFF" />
          </Pressable>
        ) : isListening ? (
          <Pressable
            accessibilityLabel="Stop voice input"
            accessibilityRole="button"
            style={({ pressed }) => [
              styles.circleButton,
              styles.listeningButton,
              pressed && styles.voiceButtonPressed,
            ]}
            onPress={stopListening}
          >
            <Ionicons name="stop" size={15} color="#FFFFFF" />
          </Pressable>
        ) : hasText ? (
          <Pressable
            accessibilityLabel="Send message"
            accessibilityRole="button"
            style={({ pressed }) => [
              styles.circleButton,
              styles.sendButton,
              { backgroundColor: colors.textStrong },
              pressed && styles.sendButtonPressed,
            ]}
            onPress={onSend}
            disabled={disabled}
          >
            <Ionicons name="arrow-up" size={20} color="#FFFFFF" />
          </Pressable>
        ) : (
          <Pressable
            accessibilityLabel="Start voice input"
            accessibilityRole="button"
            style={({ pressed }) => [
              styles.circleButton,
              styles.voiceButton,
              { backgroundColor: colors.surfaceTertiary },
              pressed && styles.voiceButtonPressed,
            ]}
            onPress={startListening}
            disabled={disabled}
          >
            <Ionicons name="mic" size={20} color={colors.textSecondary} />
          </Pressable>
        )}
      </View>

      {isListening ? (
        <Text style={[styles.listeningText, { color: colors.danger }]}>
          Listening — tap stop when finished
        </Text>
      ) : voiceError ? (
        <Text
          style={[styles.voiceError, { color: colors.danger }]}
          accessibilityRole="alert"
        >
          {voiceError}
        </Text>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrapper: {
    paddingHorizontal: 16,
    paddingTop: 6,
    paddingBottom: Platform.OS === "ios" ? 12 : 10,
    backgroundColor: "#FFFFFF",
  },

  inputBar: {
    minHeight: 52,
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: 8,
    paddingVertical: 6,
    borderWidth: 1,
    borderColor: "#ECEEF0",
    borderRadius: 26,
    backgroundColor: "#F3F4F6",
  },

  listeningInputBar: {
    borderColor: "#FCA5A5",
    backgroundColor: "#FFF7F7",
  },

  circleButton: {
    width: 38,
    height: 38,
    borderRadius: 19,
    justifyContent: "center",
    alignItems: "center",
  },

  sendButton: {
    backgroundColor: "#1E2022",
  },

  sendButtonPressed: {
    opacity: 0.8,
  },

  stopButton: {
    backgroundColor: "#1E2022",
  },

  stopButtonPressed: {
    opacity: 0.7,
  },

  voiceButton: {
    backgroundColor: "#E2E8F0",
  },

  listeningButton: {
    backgroundColor: "#EF4444",
  },

  voiceButtonPressed: {
    opacity: 0.75,
  },

  input: {
    flex: 1,
    paddingHorizontal: 10,
    paddingVertical: Platform.OS === "ios" ? 8 : 4,
    color: "#1E2022",
    fontSize: 14.5,
  },

  listeningText: {
    marginTop: 6,
    marginLeft: 12,
    color: "#DC2626",
    fontSize: 12,
    fontWeight: "600",
  },

  voiceError: {
    marginTop: 6,
    marginHorizontal: 12,
    color: "#DC2626",
    fontSize: 12,
    lineHeight: 17,
  },
});