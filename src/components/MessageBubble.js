import { createElement, useState } from "react";
import {
  ActivityIndicator,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { Image } from "expo-image";
import { Ionicons } from "@expo/vector-icons";
import * as WebBrowser from "expo-web-browser";
import * as Linking from "expo-linking";
import { WebView } from "react-native-webview";
import { startSwiggyOAuth } from "../services/api";
import { useAppTheme } from "../context/ThemeContext";

function formatTime(value) {
  const parts = String(value ? value : "09:00").split(":");
  const hour = Number(parts[0]);
  const minute = parts[1] ? parts[1] : "00";
  const suffix = hour >= 12 ? "PM" : "AM";
  const displayHour = hour % 12 ? hour % 12 : 12;
  return String(displayHour) + ":" + String(minute) + " " + suffix;
}

function formatSchedule(rule) {
  if (!rule) {
    return "Schedule pending";
  }

  if (rule.frequency === "weekly") {
    const weekday = String(rule.weekday ? rule.weekday : "monday");
    const capDay = weekday[0].toUpperCase() + weekday.slice(1);
    return "Every " + capDay + " at " + formatTime(rule.time);
  }

  if (rule.frequency === "once") {
    return "Once at " + formatTime(rule.time);
  }

  if (rule.frequency === "interval") {
    const mins = rule.interval_minutes ? rule.interval_minutes : 60;
    return "Every " + String(mins) + " minutes";
  }

  return "Every day at " + formatTime(rule.time);
}

function formatCurrency(value) {
  if (value === null) return "—";
  if (value === undefined) return "—";
  if (value === "") return "—";

  const number = Number(value);
  return Number.isFinite(number)
    ? "₹" + number.toLocaleString("en-IN", { maximumFractionDigits: 2 })
    : String(value);
}

function tokenizeInlineMarkdown(text) {
  const tokens = [];
  const str = String(text ? text : "");
  let i = 0;

  while (i < str.length) {
    if (str.startsWith("**", i)) {
      const end = str.indexOf("**", i + 2);
      if (end !== -1) {
        tokens.push({ type: "bold", content: str.slice(i + 2, end) });
        i = end + 2;
        continue;
      }
    }

    if (str[i] === "`") {
      const end = str.indexOf("`", i + 1);
      if (end !== -1) {
        tokens.push({ type: "code", content: str.slice(i + 1, end) });
        i = end + 1;
        continue;
      }
    }

    if (str[i] === "*") {
      const end = str.indexOf("*", i + 1);
      if (end !== -1 && end > i + 1) {
        tokens.push({ type: "italic", content: str.slice(i + 1, end) });
        i = end + 1;
        continue;
      }
    }

    let nextSpecial = str.length;
    const nextBold = str.indexOf("**", i + 1);
    const nextCode = str.indexOf("`", i + 1);
    const nextItalic = str.indexOf("*", i + 1);

    if (nextBold !== -1 && nextBold < nextSpecial) nextSpecial = nextBold;
    if (nextCode !== -1 && nextCode < nextSpecial) nextSpecial = nextCode;
    if (nextItalic !== -1 && nextItalic < nextSpecial) nextSpecial = nextItalic;

    tokens.push({ type: "text", content: str.slice(i, nextSpecial) });
    i = nextSpecial;
  }

  return tokens;
}

function renderInlineMarkdown(text, baseStyle, isUser) {
  if (!text) return null;
  const tokens = tokenizeInlineMarkdown(text);

  return tokens.map((token, idx) => {
    const key = "tok-" + String(idx);
    if (token.type === "bold") {
      return (
        <Text key={key} style={[baseStyle, styles.boldInline]}>
          {token.content}
        </Text>
      );
    }
    if (token.type === "code") {
      const codeStyle = isUser ? styles.codeInlineUser : styles.codeInlineAgent;
      return (
        <Text key={key} style={[baseStyle, codeStyle]}>
          {token.content}
        </Text>
      );
    }
    if (token.type === "italic") {
      return (
        <Text key={key} style={[baseStyle, styles.italicInline]}>
          {token.content}
        </Text>
      );
    }
    return <Text key={key}>{token.content}</Text>;
  });
}

function splitCodeBlocks(rawText) {
  const str = String(rawText ? rawText : "");
  const parts = [];
  let cursor = 0;

  while (cursor < str.length) {
    const startFence = str.indexOf("```", cursor);
    if (startFence === -1) {
      parts.push({ isCode: false, content: str.slice(cursor) });
      break;
    }

    if (startFence > cursor) {
      parts.push({ isCode: false, content: str.slice(cursor, startFence) });
    }

    const endFence = str.indexOf("```", startFence + 3);
    if (endFence === -1) {
      parts.push({ isCode: false, content: str.slice(startFence) });
      break;
    }

    parts.push({
      isCode: true,
      content: str.slice(startFence + 3, endFence),
    });
    cursor = endFence + 3;
  }

  return parts;
}

function FormattedMessage({ text, isUser, style }) {
  const { colors } = useAppTheme();
  if (!text) return null;
  const textStyle = [
    styles.messageText,
    isUser ? styles.userText : styles.agentText,
    { color: isUser ? colors.userText : colors.text },
  ];

  const blocks = splitCodeBlocks(text);

  return (
    <View style={style}>
      {blocks.map((block, bIdx) => {
        if (!block.content) return null;

        if (block.isCode) {
          const rawInner = block.content.replace(/^\r?\n/, "");
          const firstNewline = rawInner.indexOf("\n");
          let lang = "";
          let codeContent = rawInner;

          if (firstNewline !== -1) {
            const firstLine = rawInner.slice(0, firstNewline).trim();
            if (/^[a-zA-Z0-9_+-]+$/.test(firstLine)) {
              lang = firstLine;
              codeContent = rawInner.slice(firstNewline + 1);
            }
          }

          return (
            <View key={"code-" + String(bIdx)} style={styles.codeBlockContainer}>
              {Boolean(lang) && (
                <View style={styles.codeHeader}>
                  <Text style={styles.codeLangText}>{lang}</Text>
                </View>
              )}
              <ScrollView
                horizontal
                showsHorizontalScrollIndicator={false}
                contentContainerStyle={styles.codeScrollContent}
              >
                <Text style={styles.codeBlockText}>{codeContent.trim()}</Text>
              </ScrollView>
            </View>
          );
        }

        const lines = block.content.split("\n");
        return (
          <View key={"text-" + String(bIdx)}>
            {lines.map((line, lIdx) => {
              const lineKey = "ln-" + String(lIdx);
              const trimmed = line.trim();

              if (!trimmed) {
                return <View key={lineKey} style={{ height: 6 }} />;
              }

              if (
                trimmed === "---" ||
                trimmed === "***" ||
                trimmed === "___"
              ) {
                return <View key={lineKey} style={[styles.markdownHr, { backgroundColor: colors.border }]} />;
              }

              const headingMatch = trimmed.match(/^(#{1,4})\s+(.*)$/);
              if (headingMatch) {
                const level = headingMatch[1].length;
                const headingContent = headingMatch[2];
                const headingStyle =
                  level === 1
                    ? styles.mdH1
                    : level === 2
                    ? styles.mdH2
                    : styles.mdH3;
                return (
                  <Text
                    key={lineKey}
                    style={[
                      textStyle,
                      headingStyle,
                      { color: isUser ? colors.userText : colors.text },
                    ]}
                  >
                    {renderInlineMarkdown(headingContent, headingStyle, isUser)}
                  </Text>
                );
              }

              const bulletMatch = line.match(/^(\s*)([-*•])\s+(.*)$/);
              if (bulletMatch) {
                const indent = Math.min(bulletMatch[1].length * 6, 24);
                const itemContent = bulletMatch[3];
                return (
                  <View
                    key={lineKey}
                    style={[styles.bulletRow, { paddingLeft: indent }]}
                  >
                    <Text style={[textStyle, styles.bulletDot]}>•</Text>
                    <Text style={[textStyle, styles.bulletText]}>
                      {renderInlineMarkdown(itemContent, textStyle, isUser)}
                    </Text>
                  </View>
                );
              }

              const numMatch = line.match(/^(\s*)(\d+\.)\s+(.*)$/);
              if (numMatch) {
                const indent = Math.min(numMatch[1].length * 6, 24);
                return (
                  <View
                    key={lineKey}
                    style={[styles.bulletRow, { paddingLeft: indent }]}
                  >
                    <Text style={[textStyle, styles.numberPrefix]}>
                      {numMatch[2]}
                    </Text>
                    <Text style={[textStyle, styles.bulletText]}>
                      {renderInlineMarkdown(numMatch[3], textStyle, isUser)}
                    </Text>
                  </View>
                );
              }

              return (
                <Text key={lineKey} style={[textStyle, styles.paragraphLine]}>
                  {renderInlineMarkdown(line, textStyle, isUser)}
                </Text>
              );
            })}
          </View>
        );
      })}
    </View>
  );
}

function BrowserFrame({ url }) {
  if (Platform.OS === "web") {
    return createElement(
      "div",
      {
        style: {
          width: "100%",
          height: 210,
          overflow: "hidden",
          position: "relative",
          borderRadius: 12,
          backgroundColor: "#0F172A",
        },
      },
      createElement("iframe", {
        src: url,
        title: "Live browser",
        allow: "clipboard-read; clipboard-write",
        style: {
          width: "333.33%",
          height: 700,
          border: 0,
          transform: "scale(0.30)",
          transformOrigin: "0 0",
          backgroundColor: "#FFFFFF",
        },
      })
    );
  }

  const desktopZoomOutJS =
    "(function() {" +
    "var meta = document.querySelector('meta[name=\"viewport\"]');" +
    "if (!meta) { meta = document.createElement('meta'); meta.name = 'viewport'; document.head.appendChild(meta); }" +
    "meta.content = 'width=1080, initial-scale=0.28, maximum-scale=1.0, user-scalable=yes';" +
    "document.documentElement.style.zoom = '0.32';" +
    "})(); true;";

  return (
    <WebView
      source={{ uri: url }}
      style={styles.webView}
      injectedJavaScript={desktopZoomOutJS}
      scalesPageToFit
      sharedCookiesEnabled
      thirdPartyCookiesEnabled
    />
  );
}

function SandboxPreviewCard({ sandbox, isTurnComplete }) {
  const { colors } = useAppTheme();
  const [codeExpanded, setCodeExpanded] = useState(false);

  if (!sandbox) return null;

  const isRunning = sandbox.status === "running" && !isTurnComplete;
  const isFailed = sandbox.status === "failed";
  const charts = Array.isArray(sandbox.charts) ? sandbox.charts : [];
  const hasOutput = Boolean(sandbox.stdout || sandbox.stderr || sandbox.error);

  return (
    <View style={[styles.sandboxCard, { backgroundColor: colors.surface, borderColor: colors.border }]}>
      <View style={styles.sandboxHeader}>
        <View style={[styles.sandboxIcon, { backgroundColor: colors.surfaceTertiary }]}>
          <Ionicons name="terminal-outline" size={17} color={colors.text} />
        </View>
        <View style={styles.browserTitleGroup}>
          <Text style={[styles.browserTitle, { color: colors.text }]}>
            {sandbox.title || "E2B Python Sandbox"}
          </Text>
          <Text
            style={[
              styles.browserStatus,
              { color: isFailed ? colors.danger : colors.textSecondary },
            ]}
          >
            {isRunning
              ? "Running in cloud microVM..."
              : isFailed
              ? "Execution error"
              : "Completed • E2B Sandbox"}
          </Text>
        </View>
        {isRunning ? (
          <ActivityIndicator size="small" color={colors.primary} />
        ) : (
          <Pressable
            style={[styles.codeTogglePill, { backgroundColor: colors.surfaceTertiary }]}
            onPress={() => setCodeExpanded((prev) => !prev)}
          >
            <Text style={[styles.codeToggleText, { color: colors.textSecondary }]}>
              {codeExpanded ? "Hide Code" : "View Code"}
            </Text>
            <Ionicons
              name={codeExpanded ? "chevron-up" : "chevron-down"}
              size={13}
              color={colors.textSecondary}
            />
          </Pressable>
        )}
      </View>

      {codeExpanded && Boolean(sandbox.code) ? (
        <View style={styles.codeBlockContainer}>
          <View style={styles.codeHeader}>
            <Text style={styles.codeLangText}>PYTHON • E2B VM</Text>
          </View>
          <ScrollView
            horizontal
            showsHorizontalScrollIndicator={false}
            contentContainerStyle={styles.codeScrollContent}
          >
            <Text style={styles.codeBlockText}>{sandbox.code}</Text>
          </ScrollView>
        </View>
      ) : null}

      {(codeExpanded || isFailed) && hasOutput ? (
        <View style={styles.sandboxOutputBox}>
          <Text style={styles.sandboxOutputLabel}>CONSOLE OUTPUT</Text>
          {Boolean(sandbox.stdout) && (
            <Text style={styles.sandboxStdoutText}>{sandbox.stdout}</Text>
          )}
          {Boolean(sandbox.stderr || sandbox.error) && (
            <Text style={styles.sandboxErrorText}>
              {sandbox.error || sandbox.stderr}
            </Text>
          )}
        </View>
      ) : null}

      {charts.map((base64Png, idx) => (
        <View key={"chart-" + String(idx)} style={[styles.chartPreviewWrap, { backgroundColor: colors.surface, borderColor: colors.border }]}>
          <Image
            source={{ uri: `data:image/png;base64,${base64Png}` }}
            style={styles.chartImage}
            contentFit="contain"
          />
        </View>
      ))}

      {sandbox.preview_url ? (
        <View style={styles.browserPreview}>
          <BrowserFrame url={sandbox.preview_url} />
        </View>
      ) : null}
    </View>
  );
}

function UniversalToolApprovalCard({
  message,
  onConfirmToolAction,
  onCancelToolAction,
}) {
  const { colors } = useAppTheme();
  const approval = message.toolApproval;
  const status = message.toolApprovalStatus || "pending";
  const initialArgs =
    approval && typeof approval.arguments === "object" && approval.arguments
      ? approval.arguments
      : {};

  const [isEditing, setIsEditing] = useState(false);
  const [draftArgs, setDraftArgs] = useState(() => ({ ...initialArgs }));

  if (!approval) return null;

  const accentColor = approval.color || "#2563EB";
  const iconName = approval.icon || "construct-outline";
  const appName = approval.app_name || "Workspace";
  const actionLabel = approval.action_label || approval.tool_name || "Action";
  const canInteract = status === "pending";

  const entries = Object.entries(draftArgs).filter(
    ([key, val]) => val !== null && val !== undefined && !key.startsWith("_")
  );

  function handleFieldChange(key, textValue) {
    const originalVal = initialArgs[key];
    let parsedVal = textValue;
    if (typeof originalVal === "number") {
      const num = Number(textValue);
      parsedVal = Number.isFinite(num) ? num : textValue;
    } else if (typeof originalVal === "boolean") {
      parsedVal = textValue.trim().toLowerCase() === "true";
    }
    setDraftArgs((prev) => ({
      ...prev,
      [key]: parsedVal,
    }));
  }

  return (
    <View
      style={[
        styles.scheduleCard,
        { backgroundColor: colors.surface, borderColor: `${accentColor}70` },
      ]}
    >
      <View style={styles.scheduleHeading}>
        <View
          style={[
            styles.scheduleIcon,
            { backgroundColor: `${accentColor}18` },
          ]}
        >
          <Ionicons name={iconName} size={18} color={accentColor} />
        </View>
        <View style={{ flex: 1, marginLeft: 9 }}>
          <Text
            style={[
              styles.foodRestaurant,
              { color: accentColor, marginTop: 0 },
            ]}
          >
            {appName.toUpperCase()} • APPROVAL REQUIRED
          </Text>
          <Text style={[styles.scheduleTitle, { marginLeft: 0, marginTop: 2, color: colors.text }]}>
            {actionLabel}
          </Text>
        </View>
      </View>

      {entries.map(([key, value]) => {
        const displayKey = key.replace(/_/g, " ");
        const strVal =
          typeof value === "object"
            ? JSON.stringify(value, null, 2)
            : String(value);
        const isLongField =
          strVal.length > 60 ||
          /body|content|message|description|text|notes/i.test(key);

        return (
          <View
            key={key}
            style={[
              styles.detailRow,
              isEditing && { flexDirection: "column", marginBottom: 10 },
            ]}
          >
            <Text
              style={[
                styles.detailLabel,
                { width: isEditing ? "100%" : 88, textTransform: "capitalize", color: colors.textMuted },
              ]}
            >
              {displayKey}
            </Text>

            {isEditing ? (
              <TextInput
                style={[
                  styles.approvalInput,
                  isLongField && styles.approvalInputMultiline,
                  { backgroundColor: colors.input, borderColor: colors.border, color: colors.text },
                ]}
                value={strVal}
                onChangeText={(txt) => handleFieldChange(key, txt)}
                multiline={isLongField}
                editable={canInteract}
              />
            ) : (
              <Text
                style={[styles.detailValue, { textTransform: "none", color: colors.text }]}
                numberOfLines={isLongField ? 6 : 2}
              >
                {strVal}
              </Text>
            )}
          </View>
        );
      })}

      {message.toolApprovalError ? (
        <Text style={[styles.scheduleError, { color: colors.danger }]}>{message.toolApprovalError}</Text>
      ) : null}

      {status === "completed" ? (
        <View style={styles.savedRow}>
          <Ionicons name="checkmark-circle" size={17} color="#15803D" />
          <Text style={[styles.savedText, { color: colors.success }]}>Approved & Executed</Text>
        </View>
      ) : status === "cancelled" ? (
        <Text style={[styles.cancelledText, { color: colors.textSecondary }]}>Action cancelled</Text>
      ) : (
        <View style={styles.scheduleActions}>
          <Pressable
            style={[
              styles.confirmButton,
              { backgroundColor: accentColor, flex: 1.3 },
              !canInteract && styles.disabledButton,
            ]}
            disabled={!canInteract}
            onPress={() => {
              setIsEditing(false);
              if (onConfirmToolAction) {
                onConfirmToolAction(message.id, draftArgs);
              }
            }}
          >
            {status === "executing" ? (
              <ActivityIndicator size="small" color="#FFFFFF" />
            ) : (
              <Text style={styles.confirmText}>
                {isEditing ? "Save & Run" : "Approve & Run"}
              </Text>
            )}
          </Pressable>

          <Pressable
            style={[styles.lightButton, { backgroundColor: colors.surfaceTertiary }]}
            disabled={!canInteract}
            onPress={() => setIsEditing((prev) => !prev)}
          >
            <Text style={[styles.lightButtonText, { color: colors.textSecondary }]}>
              {isEditing ? "Done" : "Edit"}
            </Text>
          </Pressable>

          <Pressable
            style={[styles.lightButton, { backgroundColor: colors.surfaceTertiary }]}
            disabled={!canInteract}
            onPress={() => {
              if (onCancelToolAction) {
                onCancelToolAction(message.id);
              }
            }}
          >
            <Text style={[styles.lightButtonText, { color: colors.textSecondary }]}>Cancel</Text>
          </Pressable>
        </View>
      )}
    </View>
  );
}

export default function MessageBubble({
  message,
  onResumeBrowser,
  onConfirmSchedule,
  onEditSchedule,
  onCancelSchedule,
  onConfirmFoodOrder,
  onCancelFoodOrder,
  onConfirmToolAction,
  onCancelToolAction,
  onAutoResumeConnect,
}) {
  const { colors } = useAppTheme();
  const isUser = message.sender === "user";
  const browser = message.browser;
  const schedule = message.scheduleConfirmation;
  const scheduleStatus = message.scheduleStatus
    ? message.scheduleStatus
    : "pending";
  const canChangeSchedule = scheduleStatus === "pending";
  const food = message.foodConfirmation;
  const foodStatus = message.foodStatus ? message.foodStatus : "pending";
  const activity = Array.isArray(message.activity) ? message.activity : [];
  const scratchpad = message.scratchpad;
  const activeSpecialist = message.activeSpecialist;

  const [swiggyLoading, setSwiggyLoading] = useState(false);
  const [swiggySuccess, setSwiggySuccess] = useState(false);
  const [isConnecting, setIsConnecting] = useState(false);
  const [connectSuccess, setConnectSuccess] = useState(false);
  const [stepsExpanded, setStepsExpanded] = useState(false);

  async function openBrowser() {
    if (!browser || !browser.preview_url) {
      return;
    }

    if (Platform.OS === "web") {
      window.open(browser.preview_url, "_blank", "noopener,noreferrer");
      return;
    }

    await WebBrowser.openBrowserAsync(browser.preview_url);
  }

  async function openConnect() {
    const url =
      message.connectCta && message.connectCta.connectUrl
        ? message.connectCta.connectUrl
        : null;

    if (!url || isConnecting || connectSuccess) {
      return;
    }

    setIsConnecting(true);
    try {
      if (Platform.OS === "web") {
        const authWindow = window.open(
          url,
          "muse_oauth_popup",
          "width=540,height=680"
        );
        if (authWindow) {
          const timer = setInterval(() => {
            try {
              // When OAuth redirects back to our app's origin, close popup & auto-resume!
              if (
                authWindow.location &&
                authWindow.location.origin === window.location.origin &&
                authWindow.location.href !== "about:blank"
              ) {
                authWindow.close();
              }
            } catch {
              // Still on cross-origin Google/Composio page; wait
            }

            if (authWindow.closed) {
              clearInterval(timer);
              setIsConnecting(false);
              setConnectSuccess(true);
              if (onAutoResumeConnect) {
                onAutoResumeConnect(message, false);
              }
            }
          }, 600);
          return;
        }
      }

      const result = await WebBrowser.openAuthSessionAsync(
        url,
        message.connectCta.callbackUrl
      );

      if (result && result.type === "success") {
        setConnectSuccess(true);
        if (onAutoResumeConnect) {
          onAutoResumeConnect(message, false);
        }
      }
    } catch (error) {
      console.warn(error);
    } finally {
      if (Platform.OS !== "web") {
        setIsConnecting(false);
      }
    }
  }

  async function openSwiggyConnect() {
    if (swiggyLoading || swiggySuccess) {
      return;
    }

    setSwiggyLoading(true);
    try {
      const callbackUrl =
        message.swiggyCta && message.swiggyCta.callbackUrl
          ? message.swiggyCta.callbackUrl
          : Linking.createURL("/swiggy/callback");
      const authorization = await startSwiggyOAuth(callbackUrl);

      if (Platform.OS === "web") {
        const authWindow = window.open(
          authorization.authorization_url,
          "muse_swiggy_popup",
          "width=540,height=680"
        );
        if (authWindow) {
          const timer = setInterval(() => {
            try {
              if (
                authWindow.location &&
                authWindow.location.origin === window.location.origin &&
                authWindow.location.href !== "about:blank"
              ) {
                authWindow.close();
              }
            } catch {
              // Still on Swiggy OAuth domain; wait
            }

            if (authWindow.closed) {
              clearInterval(timer);
              setSwiggyLoading(false);
              setSwiggySuccess(true);
              if (onAutoResumeConnect) {
                onAutoResumeConnect(message, true);
              }
            }
          }, 600);
          return;
        }
      }

      const result = await WebBrowser.openAuthSessionAsync(
        authorization.authorization_url,
        authorization.callback_url
      );

      if (result && result.type === "success") {
        setSwiggySuccess(true);
        if (onAutoResumeConnect) {
          onAutoResumeConnect(message, true);
        }
      }
    } catch (error) {
      console.warn(error);
    } finally {
      if (Platform.OS !== "web") {
        setSwiggyLoading(false);
      }
    }
  }

  const hasPlan =
    !isUser &&
    scratchpad &&
    Array.isArray(scratchpad.plan) &&
    scratchpad.plan.length > 0;

  const hasAnyContent =
    isUser ||
    Boolean(message.text) ||
    activity.length > 0 ||
    hasPlan ||
    Boolean(browser) ||
    Boolean(message.sandbox) ||
    Boolean(message.connectCta) ||
    Boolean(message.swiggyCta) ||
    Boolean(food) ||
    Boolean(schedule) ||
    Boolean(message.toolApproval);

  if (!hasAnyContent) {
    return null;
  }

  return (
    <View style={[styles.messageRow, isUser ? styles.userRow : styles.agentRow]}>
      <View
        style={[
          styles.bubble,
          isUser ? styles.userBubble : styles.agentBubble,
          { backgroundColor: isUser ? colors.userBubble : colors.agentBubble },
        ]}
      >
        {!isUser && activeSpecialist ? (
          <View style={[styles.specialistBadge, { backgroundColor: colors.primarySoft }]}>
            <Ionicons name="sparkles" size={11} color={colors.primary} />
            <Text style={[styles.specialistBadgeText, { color: colors.primary }]}>{activeSpecialist}</Text>
          </View>
        ) : null}

        {hasPlan ? (
          <View style={[styles.scratchpadCard, { backgroundColor: colors.surface, borderColor: colors.border }]}>
            <View style={styles.scratchpadHeader}>
              <Ionicons name="list-outline" size={15} color={colors.primary} />
              <Text style={[styles.scratchpadTitle, { color: colors.text }]}>Execution Plan</Text>
              <Text style={[styles.scratchpadCount, { color: colors.primary }]}>
                Step{" "}
                {Math.min(
                  (scratchpad.currentStep ? scratchpad.currentStep : 0) + 1,
                  scratchpad.plan.length
                )}{" "}
                of {scratchpad.plan.length}
              </Text>
            </View>
            {scratchpad.plan.map((stepText, idx) => {
              const curIdx = scratchpad.currentStep ? scratchpad.currentStep : 0;
              const isDone = idx < curIdx;
              const isCurrent = idx === curIdx;
              return (
                <View key={"step-" + String(idx)} style={styles.planStepRow}>
                  <Ionicons
                    name={
                      isDone
                        ? "checkmark-circle"
                        : isCurrent
                        ? "radio-button-on"
                        : "ellipse-outline"
                    }
                    size={14}
                    color={isDone ? colors.success : isCurrent ? colors.primary : colors.textMuted}
                  />
                  <Text
                    style={[
                      styles.planStepText,
                      isDone && styles.planStepDone,
                      isCurrent && styles.planStepCurrent,
                      { color: isCurrent ? colors.text : colors.textSecondary },
                    ]}
                  >
                    {stepText}
                  </Text>
                </View>
              );
            })}
            {Boolean(scratchpad.notes) && (
              <View style={[styles.scratchpadNotesBox, { borderTopColor: colors.divider }]}>
                <Text style={[styles.scratchpadNotesText, { color: colors.textSecondary }]}>{scratchpad.notes}</Text>
              </View>
            )}
          </View>
        ) : null}

        {!isUser && activity.length > 0 ? (
          <Pressable
            style={[styles.activityCard, { backgroundColor: colors.surfaceSecondary, borderColor: colors.border }]}
            onPress={() => setStepsExpanded((prev) => !prev)}
          >
            <View style={styles.activityHeading}>
              <Ionicons name="pulse-outline" size={14} color={colors.primary} />
              <Text style={[styles.activityTitle, { color: colors.textSecondary }]}>
                Agent Steps ({activity.length})
              </Text>
              <Ionicons
                name={stepsExpanded ? "chevron-up" : "chevron-down"}
                size={14}
                color={colors.textSecondary}
              />
            </View>
            {stepsExpanded ? (
              activity.map((entry, index) => (
                <View key={"act-" + String(index)} style={styles.activityRow}>
                  <View
                    style={[
                      styles.activityDot,
                      index === activity.length - 1 && styles.activityDotActive,
                    ]}
                  />
                  <Text style={[styles.activityText, { color: colors.textSecondary }]}>{entry}</Text>
                </View>
              ))
            ) : (
              <View style={styles.activityRow}>
                <View style={[styles.activityDot, styles.activityDotActive]} />
                <Text style={[styles.activityText, { color: colors.textSecondary }]} numberOfLines={1}>
                  {activity[activity.length - 1]}
                </Text>
              </View>
            )}
          </Pressable>
        ) : null}

        {Boolean(message.text) && (
          <FormattedMessage
            text={message.text}
            isUser={isUser}
            style={
              !isUser && (activity.length > 0 || hasPlan)
                ? { marginTop: 8 }
                : null
            }
          />
        )}

        {browser ? (
          <View style={[styles.browserCard, { backgroundColor: colors.surface, borderColor: colors.border }]}>
            <View style={styles.browserHeader}>
              <View style={[styles.browserIcon, { backgroundColor: colors.primarySoft }]}>
                <Ionicons name="globe-outline" size={18} color={colors.primary} />
              </View>
              <View style={styles.browserTitleGroup}>
                <Text style={[styles.browserTitle, { color: colors.text }]}>Live browser</Text>
                <Text style={[styles.browserStatus, { color: colors.textSecondary }]} numberOfLines={1}>
                  {browser.status}
                  {browser.preview_url ? " • " + browser.preview_url : ""}
                </Text>
              </View>
              {browser.status === "running" || browser.status === "pending" ? (
                <ActivityIndicator size="small" color={colors.primary} />
              ) : null}
            </View>

            {browser.preview_url ? (
              <View style={styles.browserPreview}>
                <BrowserFrame url={browser.preview_url} />
              </View>
            ) : null}

            <View style={styles.browserActions}>
              {browser.preview_url ? (
                <Pressable style={styles.browserButton} onPress={openBrowser}>
                  <Ionicons name="open-outline" size={15} color="#FFFFFF" />
                  <Text style={styles.browserButtonText}>Open browser</Text>
                </Pressable>
              ) : null}

              {browser.status === "paused" && onResumeBrowser ? (
                <Pressable
                  style={[styles.resumeButton, { backgroundColor: colors.primarySoft }]}
                  onPress={() => onResumeBrowser(browser.id)}
                >
                  <Ionicons name="play" size={14} color="#2563EB" />
                  <Text style={[styles.resumeText, { color: colors.primary }]}>Resume</Text>
                </Pressable>
              ) : null}
            </View>
          </View>
        ) : null}

        {message.sandbox ? (
          <SandboxPreviewCard
            sandbox={message.sandbox}
            isTurnComplete={Boolean(message.text)}
          />
        ) : null}

        {message.connectCta ? (
          <View style={[styles.connectCard, { backgroundColor: colors.surface, borderColor: colors.border }]}>
            <View style={[styles.connectIcon, { backgroundColor: colors.primarySoft }]}>
              <Ionicons name="link-outline" size={18} color={colors.primary} />
            </View>
            <View style={styles.connectBody}>
              <Text style={[styles.connectTitle, { color: colors.text }]}>
                Connect {message.connectCta.toolName}
              </Text>
              <Text style={[styles.connectSubtitle, { color: colors.textSecondary }]}>
                {connectSuccess
                  ? "Connected! Resuming your request..."
                  : isConnecting
                  ? "Authorizing in browser..."
                  : "Authorize to continue automatically."}
              </Text>
            </View>
            <Pressable
              style={[
                styles.connectButton,
                (isConnecting || connectSuccess) && styles.disabledButton,
              ]}
              disabled={isConnecting || connectSuccess}
              onPress={openConnect}
            >
              {isConnecting ? (
                <ActivityIndicator size="small" color="#FFFFFF" />
              ) : connectSuccess ? (
                <Text style={styles.connectButtonText}>Connected ✓</Text>
              ) : (
                <Text style={styles.connectButtonText}>Connect</Text>
              )}
            </Pressable>
          </View>
        ) : null}

        {message.swiggyCta ? (
          <View style={[styles.swiggyConnectCard, { backgroundColor: colors.surface }] }>
            <View style={styles.swiggyIcon}>
              <Ionicons name="restaurant-outline" size={18} color="#F97316" />
            </View>
            <View style={styles.connectBody}>
              <Text style={[styles.connectTitle, { color: colors.text }]}>Connect Swiggy</Text>
              <Text style={[styles.connectSubtitle, { color: colors.textSecondary }]}>
                {swiggySuccess
                  ? "Connected! Resuming your order..."
                  : swiggyLoading
                  ? "Authorizing in browser..."
                  : "Authorize Swiggy to search restaurants and build your food cart."}
              </Text>
            </View>
            <Pressable
              style={[
                styles.swiggyButton,
                (swiggyLoading || swiggySuccess) && styles.disabledButton,
              ]}
              disabled={swiggyLoading || swiggySuccess}
              onPress={openSwiggyConnect}
            >
              {swiggyLoading ? (
                <ActivityIndicator size="small" color="#FFFFFF" />
              ) : swiggySuccess ? (
                <Text style={styles.connectButtonText}>Connected ✓</Text>
              ) : (
                <Text style={styles.connectButtonText}>Connect</Text>
              )}
            </Pressable>
          </View>
        ) : null}

        {food ? (
          <View style={[styles.foodCard, { backgroundColor: colors.surface, borderColor: colors.border }]}>
            <View style={styles.foodHeading}>
              <View style={styles.foodIcon}>
                <Ionicons name="fast-food-outline" size={18} color="#F97316" />
              </View>
              <View style={styles.foodHeadingBody}>
                <Text style={[styles.foodTitle, { color: colors.text }]}>Swiggy order review</Text>
                <Text style={styles.foodRestaurant}>
                  {food.cart && food.cart.restaurant_name
                    ? food.cart.restaurant_name
                    : "Restaurant"}
                </Text>
              </View>
            </View>

            {(food.cart && Array.isArray(food.cart.items)
              ? food.cart.items
              : []
            )
              .slice(0, 8)
              .map((item, index) => (
                <View
                  style={styles.foodItemRow}
                  key={"food-item-" + String(index)}
                >
                  <Text style={[styles.foodItemName, { color: colors.textSecondary }]}>
                    {item.quantity ? item.quantity : 1} ×{" "}
                    {item.name ? item.name : "Item"}
                    {item.variant ? " · " + item.variant : ""}
                  </Text>
                  {item.price !== undefined ? (
                    <Text style={[styles.foodItemPrice, { color: colors.textSecondary }]}>
                      {formatCurrency(item.price)}
                    </Text>
                  ) : null}
                </View>
              ))}

            {food.cart && food.cart.address ? (
              <View style={styles.foodDetailRow}>
                <Text style={[styles.foodDetailLabel, { color: colors.textMuted }]}>Deliver to</Text>
                <Text style={[styles.foodDetailValue, { color: colors.textSecondary }]}>{food.cart.address}</Text>
              </View>
            ) : null}
            <View style={styles.foodDetailRow}>
              <Text style={[styles.foodDetailLabel, { color: colors.textMuted }]}>Payment</Text>
              <Text style={[styles.foodDetailValue, { color: colors.textSecondary }]}>Cash on delivery</Text>
            </View>
            <View style={styles.foodTotalRow}>
              <Text style={[styles.foodTotalLabel, { color: colors.text }]}>Total</Text>
              <Text style={styles.foodTotalValue}>
                {formatCurrency(
                  food.total !== undefined
                    ? food.total
                    : food.cart
                    ? food.cart.total
                    : null
                )}
              </Text>
            </View>

            {food.summary ? (
              <Text style={[styles.foodSummary, { color: colors.textSecondary }]}>{food.summary}</Text>
            ) : null}
            {message.foodError ? (
              <Text style={styles.scheduleError}>{message.foodError}</Text>
            ) : null}

            {foodStatus === "placed" ? (
              <View style={styles.savedRow}>
                <Ionicons name="checkmark-circle" size={17} color="#15803D" />
                <Text style={styles.savedText}>
                  Order placed
                  {message.foodOrderId ? " · " + message.foodOrderId : ""}
                </Text>
              </View>
            ) : foodStatus === "cancelled" ? (
              <Text style={styles.cancelledText}>Cancelled</Text>
            ) : foodStatus === "pending_payment" ? (
              <View style={{ marginTop: 10 }}>
                <Text style={styles.foodSummary}>
                  Order #{food.order_id || message.foodOrderId} is awaiting UPI payment. Complete payment in your UPI app, then tap Verify.
                </Text>
                <View style={styles.scheduleActions}>
                  {Boolean(food.upi_intent_url) && (
                    <Pressable
                      style={[styles.confirmButton, { backgroundColor: "#F97316", flex: 1 }]}
                      onPress={() => Linking.openURL(food.upi_intent_url)}
                    >
                      <Text style={styles.confirmText}>Open UPI App</Text>
                    </Pressable>
                  )}
                  <Pressable
                    style={[styles.confirmButton, { flex: 1 }]}
                    onPress={() => {
                      if (onConfirmFoodOrder) onConfirmFoodOrder(message.id, "VERIFY_UPI");
                    }}
                  >
                    <Text style={styles.confirmText}>I Paid · Verify</Text>
                  </Pressable>
                </View>
              </View>
            ) : (
              <View style={styles.scheduleActions}>
                <Pressable
                  style={[
                    styles.confirmButton,
                    { backgroundColor: "#F97316", flex: 1 },
                    foodStatus !== "pending" && styles.disabledButton,
                  ]}
                  disabled={foodStatus !== "pending"}
                  onPress={() => {
                    if (onConfirmFoodOrder) onConfirmFoodOrder(message.id, "UPI");
                  }}
                >
                  {foodStatus === "placing" ? (
                    <ActivityIndicator size="small" color="#FFFFFF" />
                  ) : (
                    <Text style={styles.confirmText}>Pay via UPI</Text>
                  )}
                </Pressable>
                <Pressable
                  style={[
                    styles.confirmButton,
                    { flex: 1 },
                    foodStatus !== "pending" && styles.disabledButton,
                  ]}
                  disabled={foodStatus !== "pending"}
                  onPress={() => {
                    if (onConfirmFoodOrder) onConfirmFoodOrder(message.id, "COD");
                  }}
                >
                  <Text style={styles.confirmText}>Cash (COD)</Text>
                </Pressable>
                <Pressable
                  style={[styles.lightButton, { backgroundColor: colors.surfaceTertiary }]}
                  disabled={foodStatus !== "pending"}
                  onPress={() => {
                    if (onCancelFoodOrder) onCancelFoodOrder(message.id);
                  }}
                >
                  <Text style={[styles.lightButtonText, { color: colors.textSecondary }]}>Cancel</Text>
                </Pressable>
              </View>
            )}
          </View>
        ) : null}

        {schedule ? (
          <View style={[styles.scheduleCard, { backgroundColor: colors.surface, borderColor: colors.border }]}>
            <View style={styles.scheduleHeading}>
              <View style={[styles.scheduleIcon, { backgroundColor: colors.primarySoft }]}>
                <Ionicons name="time-outline" size={18} color={colors.primary} />
              </View>
              <Text style={[styles.scheduleTitle, { color: colors.text }]}>{schedule.title}</Text>
            </View>

            <View style={styles.detailRow}>
              <Text style={[styles.detailLabel, { color: colors.textMuted }]}>When</Text>
              <Text style={[styles.detailValue, { color: colors.text }]}>
                {formatSchedule(schedule.scheduleRule)}
              </Text>
            </View>
            <View style={styles.detailRow}>
              <Text style={[styles.detailLabel, { color: colors.textMuted }]}>Delivery</Text>
              <Text style={[styles.detailValue, { color: colors.text }]}>
                {schedule.delivery ? schedule.delivery : "chat"}
              </Text>
            </View>

            {schedule.summary ? (
              <Text style={[styles.scheduleSummary, { color: colors.textSecondary }]}>{schedule.summary}</Text>
            ) : null}

            {message.scheduleError ? (
              <Text style={styles.scheduleError}>{message.scheduleError}</Text>
            ) : null}

            {scheduleStatus === "confirmed" ? (
              <View style={styles.savedRow}>
                <Ionicons name="checkmark-circle" size={17} color="#15803D" />
                <Text style={styles.savedText}>Schedule created</Text>
              </View>
            ) : scheduleStatus === "cancelled" ? (
              <Text style={styles.cancelledText}>Cancelled</Text>
            ) : (
              <View style={styles.scheduleActions}>
                <Pressable
                  style={[
                    styles.confirmButton,
                    !canChangeSchedule && styles.disabledButton,
                  ]}
                  disabled={!canChangeSchedule}
                  onPress={() => {
                    if (onConfirmSchedule) onConfirmSchedule(message.id);
                  }}
                >
                  {scheduleStatus === "saving" ? (
                    <ActivityIndicator size="small" color="#FFFFFF" />
                  ) : (
                    <Text style={styles.confirmText}>Confirm</Text>
                  )}
                </Pressable>
                <Pressable
                  style={[styles.lightButton, { backgroundColor: colors.surfaceTertiary }]}
                  disabled={!canChangeSchedule}
                  onPress={() => {
                    if (onEditSchedule) onEditSchedule(message.id);
                  }}
                >
                  <Text style={[styles.lightButtonText, { color: colors.textSecondary }]}>Edit</Text>
                </Pressable>
                <Pressable
                  style={[styles.lightButton, { backgroundColor: colors.surfaceTertiary }]}
                  disabled={!canChangeSchedule}
                  onPress={() => {
                    if (onCancelSchedule) onCancelSchedule(message.id);
                  }}
                >
                  <Text style={[styles.lightButtonText, { color: colors.textSecondary }]}>Cancel</Text>
                </Pressable>
              </View>
            )}
          </View>
        ) : null}

        {message.toolApproval ? (
          <UniversalToolApprovalCard
            message={message}
            onConfirmToolAction={onConfirmToolAction}
            onCancelToolAction={onCancelToolAction}
          />
        ) : null}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  messageRow: { width: "100%", flexDirection: "row", marginBottom: 12 },
  userRow: { justifyContent: "flex-end" },
  agentRow: { justifyContent: "flex-start" },
  bubble: {
    maxWidth: "92%",
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderRadius: 20,
  },
  userBubble: { backgroundColor: "#E8C4B4", borderBottomRightRadius: 6 },
  agentBubble: { backgroundColor: "#EEF0F2", borderBottomLeftRadius: 6 },
  specialistBadge: {
    alignSelf: "flex-start",
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    paddingHorizontal: 8,
    paddingVertical: 3,
    marginBottom: 8,
    borderRadius: 8,
    backgroundColor: "#DBEAFE",
  },
  specialistBadgeText: {
    color: "#1D4ED8",
    fontSize: 10.5,
    fontWeight: "800",
    textTransform: "uppercase",
  },
  scratchpadCard: {
    marginBottom: 8,
    padding: 11,
    borderRadius: 12,
    backgroundColor: "#FFFFFF",
    borderWidth: 1,
    borderColor: "#BFDBFE",
  },
  scratchpadHeader: {
    flexDirection: "row",
    alignItems: "center",
    marginBottom: 7,
  },
  scratchpadTitle: {
    flex: 1,
    marginLeft: 6,
    color: "#1E293B",
    fontSize: 11.5,
    fontWeight: "800",
    textTransform: "uppercase",
  },
  scratchpadCount: {
    color: "#2563EB",
    fontSize: 11,
    fontWeight: "700",
  },
  planStepRow: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: 7,
    marginTop: 5,
  },
  planStepText: {
    flex: 1,
    color: "#475569",
    fontSize: 12,
    lineHeight: 16,
  },
  planStepDone: {
    color: "#64748B",
    textDecorationLine: "line-through",
  },
  planStepCurrent: {
    color: "#1E293B",
    fontWeight: "700",
  },
  scratchpadNotesBox: {
    marginTop: 8,
    paddingTop: 7,
    borderTopWidth: 1,
    borderTopColor: "#F1F5F9",
  },
  scratchpadNotesText: {
    color: "#475569",
    fontSize: 11.5,
    fontStyle: "italic",
    lineHeight: 16,
  },
  messageText: { fontSize: 15, lineHeight: 22 },
  userText: { color: "#3B2318", fontWeight: "500" },
  agentText: { color: "#1E2022" },
  paragraphLine: { marginBottom: 3 },
  boldInline: { fontWeight: "700" },
  italicInline: { fontStyle: "italic" },
  codeInlineAgent: {
    fontFamily: Platform.OS === "ios" ? "Menlo" : "monospace",
    fontSize: 13.5,
    backgroundColor: "#E2E8F0",
    color: "#0F172A",
    paddingHorizontal: 5,
    paddingVertical: 1,
    borderRadius: 4,
  },
  codeInlineUser: {
    fontFamily: Platform.OS === "ios" ? "Menlo" : "monospace",
    fontSize: 13.5,
    backgroundColor: "rgba(255,255,255,0.4)",
    color: "#3B2318",
    paddingHorizontal: 5,
    paddingVertical: 1,
    borderRadius: 4,
  },
  mdH1: {
    fontSize: 18,
    fontWeight: "800",
    color: "#0F172A",
    marginTop: 10,
    marginBottom: 4,
    lineHeight: 24,
  },
  mdH2: {
    fontSize: 16.5,
    fontWeight: "800",
    color: "#0F172A",
    marginTop: 8,
    marginBottom: 4,
    lineHeight: 22,
  },
  mdH3: {
    fontSize: 15.5,
    fontWeight: "700",
    color: "#1E293B",
    marginTop: 6,
    marginBottom: 3,
    lineHeight: 21,
  },
  markdownHr: {
    height: 1,
    backgroundColor: "#CBD5E1",
    marginVertical: 10,
  },
  bulletRow: {
    flexDirection: "row",
    alignItems: "flex-start",
    marginVertical: 2.5,
  },
  bulletDot: {
    width: 14,
    fontWeight: "800",
    color: "#2563EB",
  },
  numberPrefix: {
    minWidth: 20,
    fontWeight: "700",
    color: "#2563EB",
  },
  bulletText: {
    flex: 1,
  },
  codeBlockContainer: {
    marginVertical: 8,
    borderRadius: 12,
    overflow: "hidden",
    backgroundColor: "#0F172A",
    borderWidth: 1,
    borderColor: "#1E293B",
  },
  codeHeader: {
    paddingHorizontal: 12,
    paddingVertical: 5,
    backgroundColor: "#1E293B",
  },
  codeLangText: {
    color: "#94A3B8",
    fontSize: 11,
    fontWeight: "700",
    textTransform: "uppercase",
  },
  codeScrollContent: {
    padding: 12,
  },
  codeBlockText: {
    fontFamily: Platform.OS === "ios" ? "Menlo" : "monospace",
    fontSize: 12.5,
    lineHeight: 18,
    color: "#F8FAFC",
  },
  activityCard: {
    marginTop: 4,
    padding: 10,
    borderRadius: 12,
    backgroundColor: "#F8FAFC",
    borderWidth: 1,
    borderColor: "#E2E8F0",
  },
  activityHeading: {
    flexDirection: "row",
    alignItems: "center",
    marginBottom: 4,
  },
  activityTitle: {
    flex: 1,
    marginLeft: 6,
    color: "#334155",
    fontSize: 11,
    fontWeight: "800",
    textTransform: "uppercase",
  },
  activityRow: { flexDirection: "row", alignItems: "center", marginTop: 4 },
  activityDot: {
    width: 5,
    height: 5,
    borderRadius: 3,
    backgroundColor: "#94A3B8",
  },
  activityDotActive: {
    width: 6,
    height: 6,
    backgroundColor: "#2563EB",
  },
  activityText: {
    flex: 1,
    marginLeft: 7,
    color: "#64748B",
    fontSize: 11,
    lineHeight: 15,
  },
  browserCard: {
    minWidth: 280,
    marginTop: 10,
    padding: 10,
    borderWidth: 1,
    borderColor: "#BFDBFE",
    borderRadius: 14,
    backgroundColor: "#FFFFFF",
  },
  browserHeader: { flexDirection: "row", alignItems: "center" },
  browserIcon: {
    width: 34,
    height: 34,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 10,
    backgroundColor: "#EFF6FF",
  },
  browserTitleGroup: { flex: 1, marginLeft: 9 },
  browserTitle: { color: "#1E2022", fontSize: 13, fontWeight: "800" },
  browserStatus: {
    marginTop: 2,
    color: "#64748B",
    fontSize: 11,
  },
  browserPreview: {
    height: 210,
    marginTop: 10,
    overflow: "hidden",
    borderRadius: 12,
    borderWidth: 1,
    borderColor: "#E2E8F0",
    backgroundColor: "#0F172A",
  },
  webView: { height: 210, backgroundColor: "#FFFFFF" },
  browserActions: { flexDirection: "row", gap: 8 },
  browserButton: {
    height: 38,
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    marginTop: 10,
    borderRadius: 10,
    backgroundColor: "#2563EB",
  },
  browserButtonText: {
    marginLeft: 6,
    color: "#FFFFFF",
    fontSize: 12,
    fontWeight: "800",
  },
  sandboxCard: {
    minWidth: 280,
    marginTop: 10,
    padding: 11,
    borderWidth: 1,
    borderColor: "#CBD5E1",
    borderRadius: 14,
    backgroundColor: "#FFFFFF",
  },
  sandboxHeader: {
    flexDirection: "row",
    alignItems: "center",
  },
  sandboxIcon: {
    width: 34,
    height: 34,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 10,
    backgroundColor: "#F1F5F9",
  },
  codeTogglePill: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    paddingHorizontal: 9,
    paddingVertical: 5,
    borderRadius: 8,
    backgroundColor: "#F1F5F9",
  },
  codeToggleText: {
    color: "#334155",
    fontSize: 11,
    fontWeight: "700",
  },
  sandboxOutputBox: {
    marginTop: 6,
    padding: 10,
    borderRadius: 10,
    backgroundColor: "#0F172A",
  },
  sandboxOutputLabel: {
    marginBottom: 4,
    color: "#64748B",
    fontSize: 10,
    fontWeight: "800",
  },
  sandboxStdoutText: {
    fontFamily: Platform.OS === "ios" ? "Menlo" : "monospace",
    color: "#E2E8F0",
    fontSize: 12,
    lineHeight: 17,
  },
  sandboxErrorText: {
    fontFamily: Platform.OS === "ios" ? "Menlo" : "monospace",
    color: "#F87171",
    fontSize: 11.5,
    lineHeight: 16,
    marginTop: 4,
  },
  chartPreviewWrap: {
    marginTop: 10,
    borderRadius: 12,
    overflow: "hidden",
    borderWidth: 1,
    borderColor: "#E2E8F0",
    backgroundColor: "#FFFFFF",
  },
  chartImage: {
    width: "100%",
    height: 220,
  },
  connectCard: {
    minWidth: 270,
    flexDirection: "row",
    alignItems: "center",
    gap: 9,
    marginTop: 10,
    padding: 10,
    borderWidth: 1,
    borderColor: "#BFDBFE",
    borderRadius: 14,
    backgroundColor: "#FFFFFF",
  },
  connectIcon: {
    width: 34,
    height: 34,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 10,
    backgroundColor: "#EFF6FF",
  },
  connectBody: { flex: 1 },
  connectTitle: { color: "#1E293B", fontSize: 12, fontWeight: "800" },
  connectSubtitle: {
    marginTop: 2,
    color: "#64748B",
    fontSize: 10,
    lineHeight: 14,
  },
  connectButton: {
    height: 34,
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: 12,
    borderRadius: 9,
    backgroundColor: "#2563EB",
  },
  connectButtonText: { color: "#FFFFFF", fontSize: 11, fontWeight: "800" },
  swiggyConnectCard: {
    minWidth: 270,
    flexDirection: "row",
    alignItems: "center",
    gap: 9,
    marginTop: 10,
    padding: 10,
    borderWidth: 1,
    borderColor: "#FED7AA",
    borderRadius: 14,
    backgroundColor: "#FFF7ED",
  },
  swiggyIcon: {
    width: 34,
    height: 34,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 10,
    backgroundColor: "#FFEDD5",
  },
  swiggyButton: {
    height: 34,
    minWidth: 66,
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: 12,
    borderRadius: 9,
    backgroundColor: "#F97316",
  },
  foodCard: {
    minWidth: 280,
    marginTop: 10,
    padding: 12,
    borderWidth: 1,
    borderColor: "#FED7AA",
    borderRadius: 14,
    backgroundColor: "#FFFFFF",
  },
  foodHeading: { flexDirection: "row", alignItems: "center", marginBottom: 10 },
  foodIcon: {
    width: 32,
    height: 32,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 10,
    backgroundColor: "#FFF7ED",
  },
  foodHeadingBody: { flex: 1, marginLeft: 9 },
  foodTitle: { color: "#172033", fontSize: 14, fontWeight: "800" },
  foodRestaurant: {
    marginTop: 2,
    color: "#C2410C",
    fontSize: 11,
    fontWeight: "700",
  },
  foodItemRow: { flexDirection: "row", alignItems: "center", marginBottom: 6 },
  foodItemName: { flex: 1, color: "#334155", fontSize: 12, lineHeight: 17 },
  foodItemPrice: {
    marginLeft: 8,
    color: "#475569",
    fontSize: 12,
    fontWeight: "700",
  },
  foodDetailRow: { flexDirection: "row", marginTop: 6 },
  foodDetailLabel: {
    width: 70,
    color: "#64748B",
    fontSize: 11,
    fontWeight: "700",
  },
  foodDetailValue: {
    flex: 1,
    color: "#475569",
    fontSize: 11,
    lineHeight: 15,
  },
  foodTotalRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    marginTop: 10,
    paddingTop: 10,
    borderTopWidth: 1,
    borderTopColor: "#F1F5F9",
  },
  foodTotalLabel: { color: "#172033", fontSize: 13, fontWeight: "800" },
  foodTotalValue: { color: "#C2410C", fontSize: 14, fontWeight: "900" },
  foodSummary: {
    marginTop: 8,
    color: "#64748B",
    fontSize: 11,
    lineHeight: 16,
  },
  resumeButton: {
    height: 38,
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    marginTop: 10,
    borderRadius: 10,
    backgroundColor: "#EFF6FF",
  },
  resumeText: {
    marginLeft: 5,
    color: "#2563EB",
    fontSize: 12,
    fontWeight: "800",
  },
  scheduleCard: {
    minWidth: 270,
    marginTop: 10,
    padding: 12,
    borderWidth: 1,
    borderColor: "#D9E4F5",
    borderRadius: 14,
    backgroundColor: "#FFFFFF",
  },
  scheduleHeading: {
    flexDirection: "row",
    alignItems: "center",
    marginBottom: 10,
  },
  scheduleIcon: {
    width: 32,
    height: 32,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 10,
    backgroundColor: "#EFF6FF",
  },
  scheduleTitle: {
    flex: 1,
    marginLeft: 9,
    color: "#172033",
    fontSize: 14,
    fontWeight: "800",
  },
  detailRow: { flexDirection: "row", marginBottom: 6 },
  detailLabel: {
    width: 62,
    color: "#64748B",
    fontSize: 12,
    fontWeight: "700",
  },
  detailValue: {
    flex: 1,
    color: "#1E293B",
    fontSize: 12,
    fontWeight: "600",
    textTransform: "capitalize",
  },
  approvalInput: {
    marginTop: 4,
    paddingHorizontal: 10,
    paddingVertical: 8,
    borderWidth: 1,
    borderColor: "#CBD5E1",
    borderRadius: 8,
    backgroundColor: "#F8FAFC",
    color: "#0F172A",
    fontSize: 12.5,
  },
  approvalInputMultiline: {
    minHeight: 68,
    textAlignVertical: "top",
  },
  scheduleSummary: {
    marginTop: 4,
    color: "#64748B",
    fontSize: 12,
    lineHeight: 17,
  },
  scheduleError: { marginTop: 8, color: "#DC2626", fontSize: 12 },
  scheduleActions: { flexDirection: "row", gap: 8, marginTop: 12 },
  confirmButton: {
    minWidth: 82,
    height: 38,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 10,
    backgroundColor: "#2563EB",
  },
  disabledButton: { opacity: 0.55 },
  confirmText: { color: "#FFFFFF", fontSize: 12, fontWeight: "800" },
  lightButton: {
    height: 38,
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 10,
    backgroundColor: "#F1F5F9",
  },
  lightButtonText: { color: "#475569", fontSize: 12, fontWeight: "800" },
  savedRow: { flexDirection: "row", alignItems: "center", marginTop: 10 },
  savedText: {
    marginLeft: 6,
    color: "#15803D",
    fontSize: 12,
    fontWeight: "800",
  },
  cancelledText: {
    marginTop: 10,
    color: "#64748B",
    fontSize: 12,
    fontWeight: "700",
  },
});
